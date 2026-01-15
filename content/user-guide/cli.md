---
title: "Command Line Interface"
---

Complete reference for the IOPS command-line interface.

---

## Table of Contents

1. [Overview](#overview)
2. [Basic Usage](#basic-usage)
3. [Subcommand Reference](#subcommand-reference)

---

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
| `iops archive <create\|extract>` | Archive and extract workdirs |

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
- A tar archive (`.tar.gz`, `.tar.bz2`, `.tar.xz`, or `.tar`) created by `iops archive create`

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
- `--metrics, -m` - Show metric columns with average values (watch mode only)
- `--filter-metric METRIC<OP>VALUE` - Filter by metric value, e.g., `bwMiB>1000` (watch mode only, can repeat)

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

# Watch mode with metrics display
iops find ./workdir/run_001 --watch --metrics

# Filter by metric values (show only results with bwMiB > 1000)
iops find ./workdir/run_001 --watch --metrics --filter-metric "bwMiB>1000"

# Multiple metric filters
iops find ./workdir/run_001 --watch -m --filter-metric "bwMiB>1000" --filter-metric "latency<=0.5"

# Inspect executions in a tar archive (without extraction)
iops find study.tar.gz

# Filter executions in an archive
iops find study.tar.gz nodes=4 --status SUCCEEDED
```

### archive - Archive and Extract Workdirs

Create and extract IOPS archives for portability. Archives preserve all metadata, execution results, and directory structure, allowing you to move benchmark data between systems.

The `archive` command has two subcommands:

#### archive create

Create a compressed archive from a run directory or workdir:

```bash
iops archive create <source> [filters...] [options]
```

The source can be:
- A **run directory** (containing `__iops_index.json`) - archives a single run
- A **workdir** (containing `run_*` subdirectories) - archives all runs together

IOPS automatically detects whether the source is a run or workdir.

**Options:**
- `-o, --output PATH` - Output archive path (default: `<source>.tar.gz`)
- `--compression {gz,bz2,xz,none}` - Compression format (default: gz)
- `--no-progress` - Disable progress bar
- `--partial` - Create partial archive with only filtered executions
- `--status STATUS` - Filter by execution status (SUCCEEDED, FAILED, etc.)
- `--cached {yes,no}` - Filter by cache status
- `--min-reps N` - Include executions with at least N completed repetitions (implies `--partial`)

**Filters:**

When using `--partial`, you can filter executions by parameter values using positional arguments:

```bash
iops archive create <source> --partial VAR1=VALUE1 VAR2=VALUE2
```

**Examples:**

```bash
# Archive a single run (auto-detects as run)
iops archive create ./workdir/run_001

# Archive with custom output path
iops archive create ./workdir/run_001 -o my_study.tar.gz

# Archive entire workdir with all runs
iops archive create ./workdir -o all_studies.tar.gz

# Use different compression formats
iops archive create ./workdir/run_001 --compression xz -o study.tar.xz
iops archive create ./workdir/run_001 --compression bz2 -o study.tar.bz2
iops archive create ./workdir/run_001 --compression none -o study.tar

# Create partial archive with only completed tests
iops archive create ./workdir/run_001 --partial --status SUCCEEDED -o snapshot.tar.gz

# Partial archive filtered by parameters
iops archive create ./workdir/run_001 --partial nodes=4 ppn=8 -o subset.tar.gz

# Combine status and parameter filters
iops archive create ./workdir/run_001 --partial --status SUCCEEDED nodes=4 -o filtered.tar.gz

# Archive only non-cached (freshly executed) results
iops archive create ./workdir/run_001 --partial --cached no -o fresh_results.tar.gz

# Archive executions with at least 2 completed repetitions
iops archive create ./workdir/run_001 --min-reps 2 -o partial.tar.gz

# Combine min-reps with parameter filters
iops archive create ./workdir/run_001 --min-reps 1 nodes=4 -o filtered.tar.gz
```

#### archive extract

Extract an IOPS archive to a directory:

```bash
iops archive extract <archive> [options]
```

**Options:**
- `-o, --output PATH` - Output directory (default: current directory)
- `--no-verify` - Skip integrity verification
- `--no-progress` - Disable progress bar

By default, IOPS verifies the integrity of extracted files using SHA256 checksums stored in the archive manifest. Use `--no-verify` to skip this check.

Progress bars are shown by default when the `rich` library is installed. Use `--no-progress` to disable them.

**Examples:**

```bash
# Extract to current directory
iops archive extract study.tar.gz

# Extract to specific directory
iops archive extract study.tar.gz -o ./extracted

# Skip integrity verification
iops archive extract study.tar.gz -o ./extracted --no-verify
```

#### Archive Contents

Archives include:
- All execution directories and their contents (or filtered subset for partial archives)
- IOPS metadata files (`__iops_index.json`, `__iops_params.json`, etc.)
- Result files (CSV, Parquet, SQLite) - filtered for partial archives
- An archive manifest (`__iops_archive_manifest.json`) with:
  - IOPS version used to create the archive
  - Creation timestamp and source hostname
  - Archive type (run or workdir)
  - Run information (benchmark names, execution counts)
  - SHA256 checksums for integrity verification
  - For partial archives: filters applied and original execution count

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
iops archive --help
iops archive create --help
iops archive extract --help
```
