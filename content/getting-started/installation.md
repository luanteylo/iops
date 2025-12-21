---
title: "Installation"
---


## Prerequisites

Before installing IOPS, ensure you have:

- **Python 3.10 or later**
- For benchmark execution: Required tools in PATH (e.g., `ior`, `mpirun` for I/O benchmarks)
- For SLURM clusters: Access to a SLURM scheduler

## Quick Installation (from PyPI)

Install IOPS directly from PyPI:

```bash
pip install iops-benchmark
```

## Installation from Source

### Basic Installation

Clone the repository and install the package:

```bash
# Clone the repository
git clone https://gitlab.inria.fr/lgouveia/iops.git
cd iops

# Install the package with dependencies
pip install .

# Verify installation
iops --version
```

### Development Installation

For development work, install in editable mode:

```bash
# Clone the repository
git clone https://gitlab.inria.fr/lgouveia/iops.git
cd iops

# Install in editable mode
pip install -e .

# Verify installation
iops --version
```

## Using a Virtual Environment (Recommended)

Using a virtual environment keeps IOPS dependencies isolated from your system Python.

### Option 1: Python venv

```bash
# Create virtual environment
python3 -m venv iops_env

# Activate it
source iops_env/bin/activate  # On Linux/Mac
# or on Windows:
# iops_env\Scripts\activate

# Install IOPS (from source)
pip install .

# Or for development
pip install -e .

# Verify installation
iops --version
```

### Option 2: Conda

```bash
# Create conda environment
conda create -n iops python=3.10
conda activate iops

# Install IOPS (from source)
pip install .

# Or for development
pip install -e .

# Verify installation
iops --version
```

## Verifying Your Installation

After installation, verify that IOPS is correctly installed:

```bash
# Check version
iops --version

# Generate a configuration template
iops --generate_setup test_config.yaml

# Check the configuration
iops test_config.yaml --check_setup
```

## Dependencies

IOPS automatically installs the following dependencies:

- `pyyaml` - YAML parsing
- `ruamel.yaml` - Enhanced YAML support
- `psutil` - System utilities
- `sqlmodel` - SQLite ORM
- `smt` - Surrogate modeling toolkit
- `scikit-optimize` - Bayesian optimization
- `pandas` - Data manipulation
- `jinja2` - Template engine
- `plotly` - Interactive plots
- `pyarrow` & `fastparquet` - Parquet file support

## Next Steps

Now that IOPS is installed, proceed to the [Quick Start](quickstart.md) guide to run your first benchmark.
