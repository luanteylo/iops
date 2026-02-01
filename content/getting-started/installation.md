---
title: "Installation"
---

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Installation (from PyPI)](#quick-installation-from-pypi)
3. [Installation with Spack (for HPC environments)](#installation-with-spack-for-hpc-environments)
4. [Offline Installation (Wheelhouse)](#offline-installation-wheelhouse)
5. [Installation from Source](#installation-from-source)
6. [Verifying Your Installation](#verifying-your-installation)

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

## Offline Installation (Wheelhouse)

For clusters without internet access, you can create a wheelhouse (a directory of pre-downloaded wheel files) on a machine with internet, then transfer it to the cluster.

### Step 1: Create the Wheelhouse (on a machine with internet)

```bash
# Create a directory for the wheels
mkdir iops-wheelhouse

# Download IOPS and all dependencies as wheels
pip download iops-benchmark -d iops-wheelhouse
```

### Step 2: Transfer to the Cluster

Copy the wheelhouse directory to the cluster using your preferred method:

```bash
# Example using scp
scp -r iops-wheelhouse user@cluster:/path/to/destination/

# Example using rsync
rsync -av iops-wheelhouse user@cluster:/path/to/destination/
```

### Step 3: Install on the Cluster

```bash
# Install from the wheelhouse (no internet required)
pip install --no-index --find-links=/path/to/iops-wheelhouse iops-benchmark
```

### Notes

- Ensure the machine creating the wheelhouse has the same OS and Python version as the cluster
- For different architectures (e.g., x86_64 vs ARM), create the wheelhouse on a matching system or use `--platform` flag with `pip download`

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

