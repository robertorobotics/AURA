# Nextis Assembler v2

CAD-driven assembly automation platform. Upload a STEP file, the system plans the assembly, the robot builds it autonomously.

## Setup

Requires Python 3.11+ and conda (for pythonocc-core).

```bash
# Create conda environment
conda create -n nextis python=3.11
conda activate nextis

# Install pythonocc-core (STEP/IGES parser, conda only)
conda install -c conda-forge pythonocc-core

# Install the package in development mode
pip install -e ".[dev]"
```

## Development

```bash
# Format and lint
ruff check nextis/ tests/
ruff format nextis/ tests/

# Run tests
pytest
```

## Project Structure

See [CLAUDE.md](CLAUDE.md) for full architecture documentation and [docs/extraction-guide.md](docs/extraction-guide.md) for migration details.
