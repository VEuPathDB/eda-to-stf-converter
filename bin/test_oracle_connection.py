#!/usr/bin/env python3
"""Test Oracle database connection."""

import os
import sys

import yaml
import oracledb


def main():
    # Enable thick mode for Oracle Native Network Encryption support
    oracledb.init_oracle_client()

    config_path = sys.argv[1] if len(sys.argv) > 1 else "conf/config.yaml"

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: Config file not found: {config_path}")
        sys.exit(1)

    db_config = config.get("database", {})
    password = os.environ.get("DB_PASSWORD")

    if not password:
        print("Error: DB_PASSWORD environment variable not set")
        sys.exit(1)

    dsn = f"{db_config['host']}:{db_config.get('port', 1521)}/{db_config['name']}"

    print(f"Connecting to Oracle: {db_config['user']}@{dsn}")

    try:
        with oracledb.connect(
            user=db_config["user"],
            password=password,
            dsn=dsn
        ) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 'Connection successful' FROM DUAL")
                result = cursor.fetchone()
                print(result[0])

                cursor.execute("SELECT banner FROM v$version WHERE ROWNUM = 1")
                version = cursor.fetchone()
                if version:
                    print(f"Oracle version: {version[0]}")

    except oracledb.Error as e:
        print(f"Oracle connection error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
