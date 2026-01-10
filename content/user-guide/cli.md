---
title: "Command Line Interface"
---


Complete reference for the IOPS command-line interface.

## Overview

IOPS uses a subcommand-based CLI structure similar to git, docker, and other modern tools. Each subcommand has its own set of options and help documentation.

## Basic Usage

```bash
iops <subcommand> [arguments] [options]
```

| Command | Purpose |
|---------|---------|
| `iops run <config.yaml>` | Execute benchmark |
| `iops check <config.yaml>` | Validate configuration |
| `iops generate [path]` | Create config template |
| `iops report <path>` | Generate HTML report |
| `iops find <path> [filters...]` | Explore executions |

## Subcommand Reference

### run - Execute Benchmark

Execute a benchmark configuration:

```bash
iops run <config.yaml> [options]
```

Runs the benchmark defined in the configuration file.

**Options:**
- `--dry-run, -n` - Preview execution plan without running
- `--use-cache` - Skip tests with cached results
- `--max-core-hours N` - Set core-hours budget limit (SLURM only)
- `--time-estimate SEC` - Estimated test duration in seconds
- `--log-file PATH` - Write logs to file
- `--log-level LEVEL` - Set log verbosity (DEBUG, INFO, WARNING, ERROR)
- `--no-log-terminal` - Disable terminal logging (log to file only)
- `-v, --verbose` - Enable verbose output

**Examples:**

```bash
# Basic execution
iops run benchmark.yaml

# Dry-run to preview
iops run benchmark.yaml --dry-run
iops run benchmark.yaml -n

# With caching and verbose logging
iops run benchmark.yaml --use-cache --log-level DEBUG

# With budget limit and time estimate
iops run benchmark.yaml --max-core-hours 1000 --time-estimate 300
```

### check - Validate Configuration

Validate a configuration file without executing:

```bash
iops check <config.yaml>
```

Checks the YAML syntax and validates all configuration settings.

**Examples:**

```bash
# Validate configuration
iops check benchmark.yaml
```

### generate - Create Config Template

Generate a configuration template:

```bash
iops generate [output.yaml] [options]
```

Creates a YAML configuration template. By default, generates a simple starter template for the IOR benchmark with local execution. If no path is provided, the output is saved to `iops_config.yaml`.

**Options:**
- `--slurm` - Generate template for SLURM executor (default: local)
- `--mdtest` - Generate template for mdtest benchmark (default: IOR)
- `--full` - Generate comprehensive template with all options documented
- `--examples` - Copy example configurations and scripts to output directory

**Templates:**

| Benchmark | Executor | Flag Combination |
|-----------|----------|------------------|
| IOR | Local | (default) |
| IOR | SLURM | `--slurm` |
| mdtest | Local | `--mdtest` |
| mdtest | SLURM | `--mdtest --slurm` |

**Examples:**

```bash
# Generate simple IOR + local template (saves to iops_config.yaml)
iops generate

# Generate at specific path
iops generate my_config.yaml

# Generate IOR + SLURM template
iops generate slurm_config.yaml --slurm

# Generate mdtest + local template
iops generate mdtest_config.yaml --mdtest

# Generate mdtest + SLURM template
iops generate mdtest_slurm.yaml --mdtest --slurm

# Generate comprehensive template with all options
iops generate full_config.yaml --full

# Generate template and copy example files
iops generate my_config.yaml --examples
```

### analyze - Generate Report

Generate an interactive HTML report from results:

```bash
iops report <workdir/run_NNN> [options]
```

Creates visualization reports with plots and statistical analysis.

**Options:**
- `--report-config PATH` - Use custom report configuration

**Examples:**

```bash
# Generate report
iops report ./workdir/run_001

# With custom report config
iops report ./workdir/run_001 --report-config custom_report.yaml
```

### find - Explore Executions

Find and display execution folders with their parameters:

```bash
iops find <path> [filters...] [options]
```

The path can be:
- A run root directory (containing `__iops_index.json`)
- A workdir containing multiple `run_XXX` folders
- A specific execution folder (containing `__iops_params.json`)

**Filters:**

Filters are specified as positional arguments in the format `VAR=VALUE`:

```bash
iops find <path> VAR1=VALUE1 VAR2=VALUE2
```

Only executions matching all specified filters will be displayed.

**Options:**
- `--show-command` - Display the command column in output
- `--full` - Show full parameter values without truncation (default truncates at 30 chars)
- `--hide COL1,COL2` - Hide specific columns (comma-separated list)
- `--status STATUS` - Filter by execution status (SUCCEEDED, FAILED, ERROR, UNKNOWN, PENDING, SKIPPED)
- `--cached {yes,no}` - Filter by cache status (yes=only cached, no=only executed)
- `--watch, -w` - Enable watch mode for real-time monitoring (requires `rich` library)
- `--interval N` - Refresh interval in seconds for watch mode (default: 5)

**Examples:**

```bash
# List all executions in a run
iops find ./workdir/run_001

# List all runs in a workdir
iops find ./workdir

# Show details for specific execution
iops find ./workdir/run_001/exec_0042

# Filter by single variable
iops find ./workdir/run_001 nodes=4

# Filter by multiple variables
iops find ./workdir/run_001 nodes=4 ppn=8

# Show command column
iops find ./workdir/run_001 --show-command

# Show full parameter values without truncation
iops find ./workdir/run_001 --full

# Hide specific columns
iops find ./workdir/run_001 --hide nodes,ppn

# Filter by execution status
iops find ./workdir/run_001 --status FAILED

# Combine filters and options
iops find ./workdir/run_001 nodes=4 --status SUCCEEDED --show-command

# Complex filter
iops find ./workdir block_size=1024 threads=8

# Watch mode - monitor execution progress in real-time
iops find ./workdir/run_001 --watch

# Watch mode with custom refresh interval (2 seconds)
iops find ./workdir/run_001 --watch --interval 2

# Watch mode with filters
iops find ./workdir/run_001 nodes=4 --watch

# Show only cached results (from --use-cache runs)
iops find ./workdir/run_001 --cached yes

# Show only freshly executed results (not from cache)
iops find ./workdir/run_001 --cached no
```

### --version - Show Version

```bash
iops --version
```

Displays the installed IOPS version.

### --help - Show Help

```bash
iops --help
```

Shows general help information.

For subcommand-specific help:

```bash
iops run --help
iops check --help
iops generate --help
iops report --help
iops find --help
```
