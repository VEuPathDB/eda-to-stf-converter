"""dump-info.yaml records which converter build produced a dump, and from where."""

from __future__ import annotations

import subprocess
from datetime import datetime

import yaml

from eda_to_stf import provenance
from eda_to_stf.stf import StfWriter

DB_CONFIG = {
    "type": "oracle",
    "host": "localhost",
    "port": 1541,
    "name": "eda068n.example.org",
    "user": "someone",
    "password": "s3cret",
}


def write_and_load(tmp_path):
    path = StfWriter(tmp_path).write_dump_info("STUDY-1", DB_CONFIG)
    assert path == tmp_path / "dump-info.yaml"
    return yaml.safe_load(path.read_text())


def test_dump_info_has_every_key(tmp_path, monkeypatch):
    monkeypatch.setattr(
        provenance, "converter_commit", lambda: provenance.Commit("a" * 40, False)
    )

    info = write_and_load(tmp_path)

    assert list(info) == [
        "converter_commit",
        "converter_dirty",
        "converter_version",
        "study_stable_id",
        "dumped_at",
        "database",
    ]
    assert info["converter_commit"] == "a" * 40
    assert info["converter_dirty"] is False
    assert info["converter_version"] == provenance.converter_version()
    assert info["study_stable_id"] == "STUDY-1"
    assert datetime.fromisoformat(info["dumped_at"]).utcoffset().total_seconds() == 0
    assert info["database"] == {
        "type": "oracle",
        "host": "localhost",
        "port": 1541,
        "name": "eda068n.example.org",
    }


def test_no_credentials_in_dump_info(tmp_path):
    StfWriter(tmp_path).write_dump_info("STUDY-1", DB_CONFIG)
    text = (tmp_path / "dump-info.yaml").read_text()

    assert "someone" not in text
    assert "s3cret" not in text
    assert "password" not in text.lower()


def test_env_var_overrides_git(monkeypatch):
    monkeypatch.setenv("EDA_TO_STF_COMMIT", "b" * 40)

    def fail(*args, **kwargs):
        raise AssertionError("git must not run when EDA_TO_STF_COMMIT is set")

    monkeypatch.setattr(subprocess, "run", fail)

    assert provenance.converter_commit() == provenance.Commit("b" * 40, None)


def test_git_lookup_in_package_dir(monkeypatch):
    monkeypatch.delenv("EDA_TO_STF_COMMIT", raising=False)

    commit = provenance.converter_commit()

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=provenance.PACKAGE_DIR,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert commit.sha == head
    assert isinstance(commit.dirty, bool)


def test_no_git_and_no_env_var_is_unknown(monkeypatch, capsys):
    monkeypatch.delenv("EDA_TO_STF_COMMIT", raising=False)

    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)

    assert provenance.converter_commit() == provenance.Commit("unknown", None)
    assert "unknown" in capsys.readouterr().err


def test_package_not_in_a_git_checkout_is_unknown(monkeypatch, tmp_path):
    monkeypatch.delenv("EDA_TO_STF_COMMIT", raising=False)
    monkeypatch.setattr(provenance, "PACKAGE_DIR", tmp_path)

    assert provenance.converter_commit() == provenance.Commit("unknown", None)
