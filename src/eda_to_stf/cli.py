"""Command-line interface for EDA to STF converter."""

import argparse
import sys
from pathlib import Path

import yaml

from .converter import convert_study
from .db import EdaDatabase


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Convert EDA study data to STF transfer format"
    )
    parser.add_argument(
        "study_id",
        help="Study stable_id to convert"
    )
    parser.add_argument(
        "-o", "--output",
        default="./output",
        help="Output directory for STF files (default: ./output)"
    )
    parser.add_argument(
        "-c", "--config",
        default="conf/config.yaml",
        help="Path to configuration file (default: conf/config.yaml)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output"
    )

    args = parser.parse_args()

    # Load config
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    db_config = config.get("database", {})

    # Create output directory path
    output_dir = Path(args.output) / args.study_id

    if args.verbose:
        print(f"EDA to STF Converter")
        print(f"Study: {args.study_id}")
        print(f"Output: {output_dir}")
        print(f"Database: {db_config.get('type', 'oracle')}://{db_config.get('host')}:{db_config.get('port')}")
        print()

    try:
        with EdaDatabase(db_config) as db:
            convert_study(
                db=db,
                study_stable_id=args.study_id,
                output_dir=output_dir,
                verbose=args.verbose
            )

        print(f"Success! STF files written to: {output_dir}")

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
