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

## Installation with Spack (for HPC environments)

[Spack](https://spack.io/) is a package manager designed for HPC systems. It handles complex dependency chains and integrates well with module systems commonly found on clusters.

### Adding the IOPS Spack Repository

```bash
# Add the IOPS Spack repository directly
spack repo add https://gitlab.inria.fr/lgouveia/iops-spack.git
```

### Installing IOPS

```bash
# Install IOPS and all dependencies
spack install iops-benchmark

# Load the module
spack load iops-benchmark

# Verify installation
iops --version
```

### Tips for HPC Systems

On HPC systems with older compilers, you may need to load a newer GCC module before installing:

```bash
module load gcc/12.2.0  # adjust version as needed
spack compiler find
spack install iops-benchmark
```

To speed up installation, you can configure Spack to use system packages (Python, OpenSSL, etc.) by editing `~/.spack/packages.yaml`. See the [Spack documentation](https://spack.readthedocs.io/en/latest/getting_started.html#system-packages) for details.

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
iops generate test_config.yaml

# Check the configuration
iops check test_config.yaml
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
