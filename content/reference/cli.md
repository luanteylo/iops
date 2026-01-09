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

## Available Subcommands

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
iops generate [output.yaml]
```

Creates a comprehensive YAML template with all options documented. If no path is provided, the command is interactive.

**Examples:**

```bash
# Interactive generation
iops generate

# Generate at specific path
iops generate my_config.yaml
```

### analyze - Generate Report

Generate an interactive HTML report from results:

```bash
iops analyze <workdir/run_NNN> [options]
```

Creates visualization reports with plots and statistical analysis.

**Options:**
- `--report-config PATH` - Use custom report configuration

**Examples:**

```bash
# Generate report
iops analyze ./workdir/run_001

# With custom report config
iops analyze ./workdir/run_001 --report-config custom_report.yaml
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
- `--status STATUS` - Filter by execution status (SUCCEEDED, FAILED, ERROR, UNKNOWN, PENDING)

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
iops analyze --help
iops find --help
```

## Command Summary

| Command | Purpose |
|---------|---------|
| `iops run <config.yaml>` | Execute benchmark |
| `iops check <config.yaml>` | Validate configuration |
| `iops generate [path]` | Create config template |
| `iops analyze <path>` | Generate HTML report |
| `iops find <path> [filters...]` | Explore executions |
| `iops --version` | Show version |
| `iops --help` | Show help |

## Context-Sensitive Help

Each subcommand provides its own help documentation:

```bash
iops run --help      # Shows run-specific options
iops check --help    # Shows check-specific options
iops generate --help # Shows generate-specific options
iops analyze --help  # Shows analyze-specific options
iops find --help     # Shows find-specific options
```

This is more convenient than the old flag-based system where all options were shown together.

## Benefits of Subcommand Structure

The new subcommand-based CLI offers several advantages:

1. **Clearer Intent** - `iops run config.yaml` is more explicit than `iops config.yaml`
2. **Context-Sensitive Help** - Each subcommand shows only relevant options
3. **Familiar Pattern** - Matches git, docker, kubectl, and other modern tools
4. **Better Organization** - Related options are grouped under their subcommand
5. **Easier Discovery** - Users can explore available commands with `iops --help`

## Migration from Old Syntax

If you're updating from an older version of IOPS, here's how the commands have changed:

| Old Syntax | New Syntax |
|------------|------------|
| `iops config.yaml` | `iops run config.yaml` |
| `iops config.yaml --dry-run` | `iops run config.yaml --dry-run` |
| `iops config.yaml --check` | `iops check config.yaml` |
| `iops --generate` | `iops generate` |
| `iops --generate output.yaml` | `iops generate output.yaml` |
| `iops --analyze /path` | `iops analyze /path` |
| `iops --find /path` | `iops find /path` |
| `iops --find /path --filter nodes=4` | `iops find /path nodes=4` |
