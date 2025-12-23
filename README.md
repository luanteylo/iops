# IOPS

**A generic benchmark orchestration framework for automated parametric experiments.**

IOPS automates the generation, execution, and analysis of benchmark experiments. Instead of writing custom scripts for each benchmark study, you define a YAML configuration describing what to vary, what to run, and what to measure—IOPS handles the rest.

## What is IOPS?

IOPS is a framework that transforms benchmark experiments from manual scripting into automated, reproducible workflows.

**Without IOPS**: Write bash scripts → Parse outputs → Aggregate data → Generate plots → Repeat for each parameter change

**With IOPS**: Write one YAML config → Run `iops config.yaml` → Get interactive HTML reports

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

### Quick Installation (from PyPI - Coming Soon)

Once published to PyPI, you'll be able to install IOPS with a single command:

```bash
pip install iops-benchmark
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

### Using a Virtual Environment (Recommended)

Using a virtual environment keeps IOPS dependencies isolated from your system Python:

**Option 1: Python venv**

```bash
# Create virtual environment
python3 -m venv iops_env

# Activate it
source iops_env/bin/activate  # On Linux/Mac

# Install IOPS (from source)
pip install .

# Or for development
pip install -e .

# Verify installation
iops --version
```

**Option 2: Conda**

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

## Quick Start

### 1. Create a Configuration

Generate a comprehensive YAML template with all options documented:

```bash
iops --generate_setup my_config.yaml
```

This creates a fully-commented template showing all available configuration options. Customize it for your needs.

Or start from an example:

```bash
cp docs/examples/example_simple.yaml my_config.yaml
```

### 2. Preview Your Benchmark

```bash
# Dry-run to see what will be executed
iops my_config.yaml --dry-run

# Check configuration validity
iops my_config.yaml --check_setup
```

### 3. Run the Benchmark

```bash
# Basic execution
iops my_config.yaml

# With caching (skip already-executed tests)
iops my_config.yaml --use_cache

# With budget limit (SLURM only)
iops my_config.yaml --max-core-hours 1000

# With verbose logging
iops my_config.yaml --log_level DEBUG
```

### 4. Generate Analysis Report

```bash
# Generate HTML report with interactive plots
iops analyze /path/to/workdir/run_001
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
  search_method: "exhaustive"
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
      values: [4, 16, 64]

command:
  template: "my_benchmark --threads {{ threads }} --buffer {{ buffer_size }}"

scripts:
  - name: "benchmark"
    parser:
      file: "{{ execution_dir }}/output.json"
      metrics:
        - name: throughput
      parser_script: scripts/parse_results.py

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
  sqlite_db: "/path/to/cache.db"
```

Then use `--use_cache` to skip tests with identical parameters:

```bash
iops config.yaml --use_cache
```

### Multi-Round Execution

Run experiments in stages with the `rounds` feature:

```yaml
rounds:
  - name: "explore"
    sweep_vars: ["nodes"]
    repetitions: 1

  - name: "validate"
    sweep_vars: ["nodes", "processes_per_node"]
    repetitions: 5
```

Best results from each round propagate to the next.

### Budget Control

Prevent exceeding compute allocations:

```bash
# Set budget limit from command line
iops config.yaml --max-core-hours 1000

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

## Examples

Check `docs/examples/` for working configuration examples:

- `example_simple.yaml` - Basic local execution
- `example_bayesian.yaml` - Bayesian optimization
- `example_plafrim.yaml` - SLURM cluster deployment
- `example_plafrim_bayesian.yaml` - Cluster with Bayesian search

## Command Reference

```bash
# Run benchmark
iops <config.yaml> [options]

# Common options:
  --dry-run              Preview without executing
  --use_cache            Skip cached tests
  --max-core-hours N     Budget limit (SLURM)
  --log_level LEVEL      Verbosity (DEBUG, INFO, WARNING)
  --no-log-terminal      Disable terminal logging (log to file only)
  --check_setup          Validate configuration

# Generate analysis report
iops analyze <workdir/run_NNN>

# Generate configuration template
iops --generate_setup [output.yaml]

# Show version
iops --version
```

## License

This project is developed at Inria. See LICENSE file for details.

