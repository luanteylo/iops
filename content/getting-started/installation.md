---
title: "Installation"
---

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Installation (from PyPI)](#quick-installation-from-pypi)
3. [Installation from Source](#installation-from-source)
4. [Offline Installation (Wheelhouse)](#offline-installation-wheelhouse)
5. [Installation with Spack (for HPC environments)](#installation-with-spack-for-hpc-environments)
6. [Verifying Your Installation](#verifying-your-installation)

---

## Prerequisites

Before installing IOPS, ensure you have:

- **Python 3.10 or later**
- For benchmark execution: Required tools in PATH (e.g., `ior`, `mpirun` for I/O benchmarks)
- For SLURM clusters: Access to a SLURM scheduler

### Virtual environment (recommended)

Install IOPS into an isolated environment (`venv` or Conda, both work the same) so its dependencies do not conflict with other Python tools on the machine.

```bash
# Option 1: venv (standard library)
python3 -m venv ~/.venvs/iops
source ~/.venvs/iops/bin/activate

# Option 2: Conda / Mamba
conda create -n iops python=3.10
conda activate iops
```

With the environment active, use any of the installation methods below.

## Quick Installation (from PyPI)

```bash
pip install iops-benchmark
```

## Installation from Source

```bash
# Clone the repository
git clone https://gitlab.inria.fr/lgouveia/iops.git
cd iops

# Install the package with dependencies
pip install .

# Verify installation
iops --version
```

## Offline Installation (Wheelhouse)

For clusters without internet access, create a wheelhouse (a directory of pre-downloaded wheel files) on a machine with internet, then transfer it to the cluster.

### Step 1: Create the Wheelhouse (on a machine with internet)

```bash
mkdir iops-wheelhouse

# Download IOPS and all dependencies as wheels
pip download iops-benchmark -d iops-wheelhouse
```

### Step 2: Transfer to the Cluster

```bash
scp -r iops-wheelhouse user@cluster:/path/to/destination/
```

### Step 3: Install on the Cluster

```bash
# Install from the wheelhouse (no internet required)
pip install --no-index --find-links=/path/to/iops-wheelhouse iops-benchmark
```

### Notes

- Ensure the machine creating the wheelhouse has the same OS and Python version as the cluster
- For different architectures (e.g., x86_64 vs ARM), create the wheelhouse on a matching system or use `--platform` flag with `pip download`

## Installation with Spack (for HPC environments)

[Spack](https://spack.io/) is a package manager designed for HPC systems that integrates well with cluster module systems.

**Warning: Spack installs can take a long time**

In full Spack-managed mode, Spack compiles everything from source, including Python itself and scientific libraries such as NumPy, SciPy, and their BLAS backends. The first build can take from 30 minutes to several hours depending on the cluster, the compiler, and the dependency cache. Prefer standalone mode (PyPI wheels) to get IOPS quickly; reserve full mode for reproducible environments that require Spack-built dependencies.

### Adding the IOPS Spack Repository

```bash
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

## Verifying Your Installation

```bash
# Check version
iops --version

# Generate a configuration template
iops generate test_config.yaml

# Check the configuration
iops check test_config.yaml
```
