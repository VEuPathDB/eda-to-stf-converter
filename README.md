# EDA to STF Converter

Convert data from relational databases (PostgreSQL, Oracle) to STF transfer format.

## Installation

```bash
# Install base package
pip install -e .

# Install with PostgreSQL support
pip install -e ".[postgres]"

# Install with Oracle support
pip install -e ".[oracle]"

# Install development dependencies
pip install -e ".[dev]"
```

## Configuration

1. Copy the example configuration:
   ```bash
   cp conf/config.example.yaml conf/config.yaml
   ```

2. Edit `conf/config.yaml` with your database settings.

3. Set the database password via environment variable:
   ```bash
   export DB_PASSWORD="your_password"
   ```

## Usage

```bash
eda-to-stf --config conf/config.yaml
```

## Dump provenance

Each study's output directory gets a `dump-info.yaml` beside `study.yaml`:

| key | value |
|---|---|
| `converter_commit` | `EDA_TO_STF_COMMIT` if set, else `git rev-parse HEAD` of the checkout holding the installed package, else `unknown` (with a warning) |
| `converter_dirty` | `true` if that checkout had uncommitted changes to tracked files; `null` when the commit came from `EDA_TO_STF_COMMIT` or is `unknown` |
| `converter_version` | package version |
| `study_stable_id` | the study dumped |
| `dumped_at` | UTC, ISO 8601 |
| `database` | `type`, `host`, `port`, `name` from the config; never the user or password |

It is a separate file because study-wrangler passes every top-level `study.yaml` key
on to the study, and reads only the entity files `study.yaml` lists.

## Docker

Build the image:
```bash
docker build --build-arg EDA_TO_STF_COMMIT=$(git rev-parse HEAD) -t eda-to-stf .
```

The image has no `.git`, so without the build arg every dump records
`converter_commit: unknown` (see [Dump provenance](#dump-provenance)).

Run with a config file:
```bash
docker run -v $(pwd)/conf/config.yaml:/app/conf/config.yaml \
           -v $(pwd)/output:/app/output \
           -e DB_PASSWORD="your_password" \
           eda-to-stf
```

## Development

Run tests:
```bash
pytest
```

Format code:
```bash
black src/ tests/
ruff check src/ tests/
```

## Project Structure

```
eda-to-stf-converter/
├── bin/              # Executable scripts
├── conf/             # Configuration files
├── src/
│   └── eda_to_stf/   # Main package
├── tests/            # Test files
├── pyproject.toml    # Project configuration
└── README.md
```
