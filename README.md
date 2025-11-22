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

## Docker

Build the image:
```bash
docker build -t eda-to-stf .
```

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
