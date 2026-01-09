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
# Add the IOPS Spack repository
spack repo add https://gitlab.inria.fr/lgouveia/iops-spack.git
```

### Option 1: Standalone Mode

Uses pip to install dependencies from PyPI.

```bash
spack install iops-benchmark+standalone
```

### Option 2: Full Spack-Managed Dependencies

Spack builds and manages all dependencies.

```bash
spack install iops-benchmark
```

### Loading and Verifying

```bash
# Load the module
spack load iops-benchmark

# Verify installation
iops --version
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

