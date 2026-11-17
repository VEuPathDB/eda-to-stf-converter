"""Which converter build produced a dump."""

from __future__ import annotations

import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import NamedTuple

COMMIT_ENV_VAR = "EDA_TO_STF_COMMIT"
DISTRIBUTION = "eda-to-stf-converter"
PACKAGE_DIR = Path(__file__).resolve().parent
UNKNOWN = "unknown"


class Commit(NamedTuple):
    sha: str
    dirty: bool | None


def converter_version() -> str:
    try:
        return metadata.version(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return UNKNOWN


def converter_commit() -> Commit:
    """Commit from the env var, else the git checkout holding this package.

    The env var carries no dirty state, so `dirty` is None for it and for unknown.
    """
    sha = os.environ.get(COMMIT_ENV_VAR)
    if sha:
        return Commit(sha, None)

    try:
        # Confirms the enclosing repo tracks this package, not some unrelated parent.
        _git("ls-files", "--error-unmatch", "__init__.py")
        sha = _git("rev-parse", "HEAD")
        dirty = _git("status", "--porcelain", "--untracked-files=no") != ""
    except (OSError, subprocess.CalledProcessError):
        print(
            f"warning: converter commit {UNKNOWN}: set {COMMIT_ENV_VAR} "
            "or run from a git checkout",
            file=sys.stderr,
        )
        return Commit(UNKNOWN, None)

    return Commit(sha, dirty)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=PACKAGE_DIR,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
