---
title: "Command Line Interface"
---


Complete reference for the IOPS command-line interface.

## Basic Usage

```bash
iops <config.yaml> [options]
```

## Commands

### Run Benchmark

```bash
iops config.yaml
```

Executes the benchmark defined in the configuration file.

### Generate Configuration Template

```bash
iops --generate [output.yaml]
```

Generates a comprehensive YAML template with all options documented.

### Analyze Results

```bash
iops --analyze <workdir/run_NNN>
```

Generates an interactive HTML report from completed benchmark results.

### Find Executions

```bash
iops --find <path>
```

Finds and displays execution folders in a workdir with their parameters. The path can be:
- A run root directory (containing `__iops_index.json`)
- A workdir containing multiple `run_XXX` folders
- A specific execution folder (containing `__iops_params.json`)

**Filter by parameters:**

```bash
iops --find <path> --filter VAR=VALUE [VAR2=VALUE2 ...]
```

Filter executions by variable values. Only executions matching all specified filters will be displayed.

**Examples:**

```bash
# List all executions in a run
iops --find ./workdir/run_001

# List all runs in a workdir
iops --find ./workdir

# Show details for specific execution
iops --find ./workdir/run_001/exec_0042

# Filter by variable values
iops --find ./workdir/run_001 --filter nodes=4 ppn=8
iops --find ./workdir --filter block_size=1024
```

### Show Version

```bash
iops --version
```

Displays the installed IOPS version.

## Common Options

### Mode Options

```bash
# Generate configuration template
iops --generate [output.yaml]

# Check configuration validity
iops config.yaml --check

# Analyze results
iops --analyze <workdir/run_NNN>

# Find and filter executions
iops --find <path>
iops --find <path> --filter VAR=VALUE
```

### Execution Options

```bash
# Dry-run (preview without executing)
iops config.yaml --dry-run
iops config.yaml -n

# Use cached results
iops config.yaml --use-cache

# Set core-hours budget (SLURM)
iops config.yaml --max-core-hours 1000

# Provide time estimates (seconds)
iops config.yaml --time-estimate 120
```

### Logging Options

```bash
# Set log level
iops config.yaml --log-level DEBUG

# Enable verbose output
iops config.yaml --verbose
iops config.yaml -v

# Write logs to file
iops config.yaml --log-file benchmark.log

# Disable terminal logging (log to file only)
iops config.yaml --no-log-terminal
```

### Reporting Options

```bash
# Use custom report configuration
iops --analyze <workdir/run_NNN> --report-config custom_report.yaml
```

## Complete Options Reference

```
Usage: iops [OPTIONS] [CONFIG_PATH]

Arguments:
  config_path              Path to YAML configuration file

Mode Options:
  --generate [PATH]        Generate configuration template
  --check                  Validate configuration
  --analyze PATH           Generate analysis report from results
  --find PATH              Find execution folders in workdir
  --filter VAR=VALUE       Filter executions by variable values (use with --find)

Execution Options:
  -n, --dry-run           Preview without executing
  --use-cache             Skip cached tests
  --max-core-hours N      Budget limit (SLURM)
  --time-estimate SEC     Estimated test duration (seconds)

Logging Options:
  --log-file PATH         Write logs to file
  --log-level LEVEL       Log verbosity (DEBUG, INFO, WARNING, ERROR)
  --no-log-terminal       Disable terminal logging
  -v, --verbose           Enable verbose output

Reporting Options:
  --report-config PATH    Custom report configuration file

General Options:
  --version               Show version
  --help                  Show help message
```

## Examples

```bash
# Basic execution
iops benchmark.yaml

# With caching and verbose logging
iops benchmark.yaml --use-cache --log-level DEBUG

# With verbose output and log file
iops benchmark.yaml -v --log-file benchmark.log

# Dry-run with budget estimation
iops benchmark.yaml --dry-run --time-estimate 300 --max-core-hours 1000
iops benchmark.yaml -n --time-estimate 300

# Validate configuration
iops benchmark.yaml --check

# Generate report with custom configuration
iops --analyze workdir/run_001 --report-config custom_report.yaml

# Find and explore executions
iops --find workdir/run_001
iops --find workdir/run_001 --filter nodes=4
iops --find workdir/run_001 --filter nodes=4 ppn=8
iops --find workdir/run_001/exec_0023
```
