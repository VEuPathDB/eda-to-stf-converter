# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Run Commands

```bash
# Build Docker image
docker build -t eda-to-stf .

# Run converter (Docker, requires --network host for Oracle)
docker run --rm --network host \
  -v $(pwd)/conf/config.yaml:/app/conf/config.yaml \
  -v $(pwd)/output:/app/output \
  -e DB_PASSWORD="password" \
  eda-to-stf "STUDY_STABLE_ID" -v

# Test Oracle connection
docker run --rm --network host \
  -v $(pwd)/conf/config.yaml:/app/conf/config.yaml \
  -e DB_PASSWORD="password" \
  --entrypoint python \
  eda-to-stf /app/bin/test_oracle_connection.py

# Run tests
pytest

# Format code
black src/ tests/
ruff check src/ tests/
```

## Architecture

The converter transforms VEuPathDB EDA (Exploratory Data Analysis) schema data into STF (Study Transfer Format) files.

### Core Modules

- **`db.py`** - SQLAlchemy-based database layer supporting Oracle and PostgreSQL. Contains dataclasses (`Study`, `Entity`, `Variable`) and `EdaDatabase` class for querying EDA schema tables.

- **`stf.py`** - STF file generation. `StfWriter` produces `study.yaml`, `entity-{name}.yaml`, and `entity-{name}.tsv` files following the STF specification.

- **`converter.py`** - Orchestrates the conversion: fetches study metadata, iterates entities in hierarchical order, and writes STF output.

- **`cli.py`** - Command-line entry point (`eda-to-stf` command).

### EDA Schema Tables

The converter queries these Oracle/PostgreSQL tables:
- `eda.study` - Study metadata (stable_id, internal_abbrev)
- `eda.entitytypegraph` - Entity definitions and hierarchy
- `eda.attributegraph_{study}_{entity}` - Variable metadata per entity
- `eda.attributevalue_{study}_{entity}` - Actual data values (tall format, pivoted to wide)
- `eda.ancestors_{study}_{entity}` - Parent ID mappings for child entities

### Data Flow

1. CLI receives study `stable_id` and config path
2. `EdaDatabase` connects and fetches study + entities
3. Entities sorted by hierarchy (parents before children)
4. For each entity: fetch variables from `attributegraph`, fetch data from `attributevalue` joined with `ancestors`, write YAML and TSV
5. Write `study.yaml` listing all entities

### Oracle Thick Mode

Oracle connections require "thick mode" for Native Network Encryption. The Docker image includes Oracle Instant Client 23.5. The `oracledb.init_oracle_client()` call enables thick mode.

## Configuration

Database password must be set via `DB_PASSWORD` environment variable (not in config file). Config file specifies `type: oracle` or `type: postgres` with connection details.
