# IOPS - Integrated Orchestration for Parametric Studies

**A generic benchmark orchestration framework for automated parametric experiments.**

IOPS automates the generation, execution, and analysis of benchmark experiments. Instead of writing custom scripts for each benchmark study, you define a YAML configuration describing what to vary, what to run, and what to measure—IOPS handles the rest.

## What is IOPS?

IOPS is a framework that transforms benchmark experiments from manual scripting into automated, reproducible workflows.

**Without IOPS**: Write bash scripts → Parse outputs → Aggregate data → Generate plots → Repeat for each parameter change

**With IOPS**: Write one YAML config → Run `iops run config.yaml` → Get interactive HTML reports

Originally designed for I/O performance studies (see [our 2022 paper](https://inria.hal.science/hal-03753813/)), IOPS has evolved into a generic framework for any parametric benchmark workflow.

## Key Features

- **Parameter Sweeping**: Automatically generate and execute tests for all parameter combinations
- **Multiple Search Strategies**: Exhaustive, Bayesian optimization, or random sampling
- **Execution Backends**: Run locally or submit to SLURM clusters
- **Smart Caching**: Skip redundant tests with parameter-aware result caching
- **Budget Control**: Set core-hour limits to avoid exceeding compute allocations
- **Automatic Reports**: Generate interactive HTML reports with plots and statistical analysis
- **Flexible Output**: Export results to CSV, Parquet, or SQLite

## Installation

### Prerequisites

- Python 3.10 or later
- For benchmark execution: Required tools in PATH (e.g., `ior`, `mpirun` for I/O benchmarks)
- For SLURM clusters: Access to a SLURM scheduler

### Quick Installation (from PyPI)

Install IOPS directly from PyPI:

```bash
pip install iops-benchmark
```

### Installation with Spack (for HPC environments)

[Spack](https://spack.io/) is a package manager designed for HPC systems. To install IOPS with Spack:

```bash
# Add the IOPS Spack repository
spack repo add https://gitlab.inria.fr/lgouveia/iops-spack.git

# Option 1: Standalone mode - uses pip for dependencies
spack install iops-benchmark+standalone

# Option 2: Full Spack-managed dependencies
spack install iops-benchmark

# Load the module
spack load iops-benchmark

# Verify installation
iops --version
```

### Basic Installation (from source)

```bash
# Clone the repository
git clone https://gitlab.inria.fr/lgouveia/iops.git
cd iops

# Install the package with dependencies
pip install .

# Verify installation
iops --version
```

## Quick Start

### 1. Create a Configuration

Generate a YAML configuration template:

```bash
iops generate my_config.yaml
```

For a fully-documented template with all options:

```bash
iops generate my_config.yaml --full
```



### 2. Preview Your Benchmark

```bash
# Dry-run to see what will be executed
iops run my_config.yaml --dry-run

# Check configuration validity
iops check my_config.yaml
```

### 3. Run the Benchmark

```bash
# Basic execution
iops run my_config.yaml

# With caching (skip already-executed tests)
iops run my_config.yaml --use-cache

# With budget limit (SLURM only)
iops run my_config.yaml --max-core-hours 1000

# With verbose logging
iops run my_config.yaml --log-level DEBUG
```

### 4. Explore Executions

```bash
# List all executions with their parameters
iops find /path/to/workdir/run_001

# Filter executions by variable values
iops find /path/to/workdir/run_001 nodes=4 ppn=8

# Show details for specific execution
iops find /path/to/workdir/run_001/exec_042
```

### 5. Generate Analysis Report

```bash
# Generate HTML report with interactive plots
iops report /path/to/workdir/run_001
```

## How It Works

IOPS follows a simple workflow:

1. **Configuration**: Define variables to sweep, commands to run, and metrics to measure in a YAML file
2. **Planning**: IOPS generates execution instances for parameter combinations
3. **Execution**: Runs tests locally or submits SLURM jobs
4. **Parsing**: Extracts metrics from output files using your parser script
5. **Storage**: Saves results to CSV, SQLite, or Parquet
6. **Analysis**: Generates HTML reports with interactive plots and statistics

### Core Concepts

**Variables**: Parameters you want to vary

```yaml
vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [4, 8, 16, 32]
```

**Commands**: What to execute (supports Jinja2 templating)

```yaml
command:
  template: "ior -w -b {{ block_size }}mb -o {{ output_file }}"
```

**Metrics**: What to measure

```yaml
metrics:
  - name: bandwidth_mbps
  - name: latency_ms
```

**Search Methods**:
- `exhaustive`: Test all combinations (thorough, complete)
- `bayesian`: Gaussian Process optimization (efficient, finds optima faster)
- `random`: Random sampling (useful for statistical analysis)

### Example Configuration

```yaml
benchmark:
  name: "My Benchmark Study"
  workdir: "./workdir"
  executor: "local"  # or "slurm" for clusters
  repetitions: 3

vars:
  threads:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4, 8]

  buffer_size:
    type: int
    sweep:
      mode: list
      values: [64, 256, 1024]

command:
  template: "my_benchmark --threads {{ threads }} --buffer {{ buffer_size }}"

scripts:
  - name: "benchmark"
    submit: "bash"
    script_template: |
      #!/bin/bash
      # Built-in variables: execution_id, execution_dir, repetition
      echo "Running execution {{ execution_id }}, repetition {{ repetition }}"
      {{ command.template }} > output.txt

    parser:
      # execution_dir is automatically set to each execution's folder
      file: "{{ execution_dir }}/output.txt"
      metrics:
        - name: throughput
      parser_script: |
        import re

        def parse(file_path: str):
            with open(file_path) as f:
                content = f.read()
            match = re.search(r"throughput:\s*([\d.]+)", content)
            return {"throughput": float(match.group(1)) if match else 0}

output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
```

## SLURM Integration

IOPS provides native SLURM cluster support with automatic job submission, monitoring, and budget tracking:

```yaml
benchmark:
  executor: "slurm"
  max_core_hours: 1000
  cores_expr: "{{ nodes * processes_per_node }}"

scripts:
  - name: "benchmark"
    submit: "sbatch"
    script_template: |
      #!/bin/bash
      #SBATCH --nodes={{ nodes }}
      #SBATCH --ntasks-per-node={{ processes_per_node }}
      #SBATCH --time=01:00:00

      module load mpi/openmpi
      {{ command.template }}
```

Features:
- Automatic job submission and status monitoring
- Core-hours budget tracking and enforcement
- Multi-node resource allocation
- Graceful handling of job failures

## Advanced Features

### Result Caching

IOPS caches execution results to avoid redundant tests. Enable caching by specifying a SQLite database in your config:

```yaml
benchmark:
  cache_file: "/path/to/cache.db"
```

Then use `--use-cache` to skip tests with identical parameters:

```bash
iops run config.yaml --use-cache
```

### Budget Control

Prevent exceeding compute allocations:

```bash
# Set budget limit from command line
iops run config.yaml --max-core-hours 1000

# Or in YAML config
benchmark:
  max_core_hours: 500
  cores_expr: "{{ nodes * ppn }}"
```

## Documentation

For comprehensive documentation, examples, and tutorials, visit:

**[https://lgouveia.gitlabpages.inria.fr/iops/](https://lgouveia.gitlabpages.inria.fr/iops/)**

The documentation includes:
- Complete YAML configuration reference
- User guides for all features
- Working examples for various scenarios
- Best practices and optimization tips


## Command Reference

IOPS uses a subcommand-based CLI similar to git and docker:

```bash
# Run benchmark
iops run <config.yaml> [options]
  --dry-run              Preview without executing
  --use-cache            Skip cached tests
  --max-core-hours N     Budget limit (SLURM)
  --log-level LEVEL      Verbosity (DEBUG, INFO, WARNING)
  --no-log-terminal      Disable terminal logging (log to file only)

# Validate configuration
iops check <config.yaml>

# Find and explore executions
iops find <path> [filters...]
iops find <path> nodes=4 ppn=8    # Filter by parameters
iops find <path> --show-command   # Show command column

# Generate analysis report
iops report <workdir/run_NNN> [--report-config report.yaml]

# Generate configuration template
iops generate [output.yaml]

# Show version
iops --version

# Show help
iops --help
iops run --help      # Subcommand-specific help
```

## License

This project is developed at Inria. See LICENSE file for details.

