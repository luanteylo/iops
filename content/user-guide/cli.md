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

IOPS uses a subcommand-based CLI similar to git and docker. Each subcommand has its own options and help.

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
| `iops cache <create\|rebuild\|list\|show\|stats>` | Cache management |
| `iops convert <file.xml>` | Convert JUBE XML to IOPS YAML |

## Subcommand Reference

### run - Execute Benchmark

```bash
iops run <config.yaml> [options]
```

**Options:**
- `--dry-run, -n` - Preview execution plan without running
- `--use-cache` - Skip tests with cached results
- `--cache-only` - Only use cached results; skip tests not in cache (requires `cache_file`)
- `--fail-fast` - Stop execution on first test failure
- `--parallel N` - Max concurrent test executions (overrides `benchmark.parallel` in config)
- `--machine NAME` - Apply machine-specific config overrides (or set `IOPS_MACHINE` env var)
- `--max-core-hours N` - Set core-hours budget limit (SLURM only)
- `--time-estimate SEC` - Estimated test duration in seconds
- `--log-file PATH` - Write logs to file
- `--log-level LEVEL` - Set log verbosity (DEBUG, INFO, WARNING, ERROR)
- `--no-log-terminal` - Disable terminal logging (log to file only)
- `-v, --verbose` - Enable verbose output

**Examples:**

```bash
iops run benchmark.yaml --dry-run
iops run benchmark.yaml --use-cache --log-level DEBUG
iops run benchmark.yaml --cache-only
iops run benchmark.yaml --parallel 4
iops run benchmark.yaml --max-core-hours 1000 --time-estimate 300
iops run benchmark.yaml --machine cluster   # or: export IOPS_MACHINE=cluster
```

### check - Validate Configuration

Validate a configuration file without executing:

```bash
iops check <config.yaml> [options]
```

**Options:**
- `--machine NAME` - Validate config with machine-specific overrides applied
- `--resolve [FILE]` - Output the fully resolved config as YAML. Prints to stdout when no file is given, or writes to `FILE`

**Examples:**

```bash
iops check benchmark.yaml
iops check benchmark.yaml --machine cluster --resolve
iops check benchmark.yaml --machine cluster --resolve /tmp/resolved.yaml
```

### generate - Create Config Template

```bash
iops generate [output.yaml] [options]
```

Creates a YAML configuration template. By default, generates a simple starter template for the IOR benchmark with local execution. If no path is provided, the output is saved to `iops_config.yaml`.

**Options:**
- `--slurm` - Generate template for SLURM executor (default: local)
- `--mdtest` - Generate template for mdtest benchmark (default: IOR)
- `--full` - Generate template with all options documented
- `--machines` - Include cross-executor machine overrides section (local + SLURM)
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
iops generate                                  # saves to iops_config.yaml
iops generate mdtest_slurm.yaml --mdtest --slurm
iops generate full_config.yaml --full
iops generate my_config.yaml --machines --examples
```

### report - Generate Report

Generate an interactive HTML report from results:

```bash
iops report <workdir/run_NNN> [options]
```

**Options:**
- `--report-config PATH` - Use custom report configuration
- `--export-plots` - Export plots as image files to `__iops_plots` folder (requires kaleido)
- `--plot-format FORMAT` - Image format for exported plots: `pdf` (default), `png`, `svg`, `jpg`, `webp`

**Examples:**

```bash
iops report ./workdir/run_001
iops report ./workdir/run_001 --report-config custom_report.yaml
iops report ./workdir/run_001 --export-plots --plot-format png
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

Filters are positional arguments in the format `VAR=VALUE`; only executions matching all filters are displayed. Numbers and booleans match loosely: `nodes=4` matches `4.0`, and `flag=true` matches `True` (case-insensitive).

**Options:**
- `--show-command` - Display the command column in output
- `--full` - Show full parameter values without truncation (default truncates at 30 chars)
- `--hide COL1,COL2` - Hide specific columns (comma-separated list)
- `--status STATUS` - Filter by execution status (SUCCEEDED, FAILED, ERROR, UNKNOWN, PENDING, SKIPPED)
- `--cached {yes,no}` - Filter by cache status (yes=only cached, no=only executed)
- `--watch, -w` - Enable watch mode for real-time monitoring (requires `rich` library)
- `--interval N` - Refresh interval in seconds for watch mode (default: 5, minimum: 1)
- `--metrics, -m` - Show metric columns with average values (watch mode only)
- `--filter-metric METRIC<OP>VALUE` - Filter by metric value, e.g., `bwMiB>1000` (watch mode only, can repeat)

**Examples:**

```bash
iops find ./workdir/run_001
iops find ./workdir/run_001 nodes=4 ppn=8
iops find ./workdir/run_001 --status FAILED --show-command
iops find ./workdir/run_001 --cached yes
iops find ./workdir/run_001 --watch --interval 2
iops find ./workdir/run_001 -w -m --filter-metric "bwMiB>1000" --filter-metric "latency<=0.5"
iops find study.tar.gz nodes=4 --status SUCCEEDED
```

See the [Exploring Executions guide](../exploring-executions) for filtering details, watch mode keyboard controls, and archive inspection.

### archive - Archive and Extract Workdirs

Create and extract IOPS archives for portability. Archives preserve all metadata, execution results, and directory structure, so benchmark data can move between systems. Running `iops archive` without a subcommand prints usage guidance.

#### archive create

Create a compressed archive from a run directory or workdir:

```bash
iops archive create <source> [filters...] [options]
```

The source can be:
- A **run directory** (containing `__iops_index.json`) - archives a single run
- A **workdir** (containing `run_*` subdirectories) - archives all runs together

IOPS automatically detects which type the source is.

**Options:**
- `-o, --output PATH` - Output archive path (default: `<source>.tar.gz`)
- `--compression {gz,bz2,xz,none}` - Compression format (default: gz)
- `--no-progress` - Disable progress bar
- `--partial` - Create partial archive with only filtered executions
- `--status STATUS` - Filter by execution status (SUCCEEDED, FAILED, etc.)
- `--cached {yes,no}` - Filter by cache status
- `--min-reps N` - Include executions with at least N completed repetitions (implies `--partial`)

**Filters:**

When using `--partial`, filter executions by parameter values using positional arguments:

```bash
iops archive create <source> --partial VAR1=VALUE1 VAR2=VALUE2
```

**Examples:**

```bash
iops archive create ./workdir/run_001 -o my_study.tar.gz
iops archive create ./workdir -o all_studies.tar.gz
iops archive create ./workdir/run_001 --compression xz -o study.tar.xz
iops archive create ./workdir/run_001 --partial --status SUCCEEDED nodes=4 -o filtered.tar.gz
iops archive create ./workdir/run_001 --partial --cached no -o fresh_results.tar.gz
iops archive create ./workdir/run_001 --min-reps 2 -o partial.tar.gz
```

#### archive extract

Extract an IOPS archive to a directory:

```bash
iops archive extract <archive> [options]
```

**Options:**
- `-o, --output PATH` - Output directory (default: a folder named after the archive)
- `--no-verify` - Skip integrity verification
- `--no-progress` - Disable progress bar

When `-o` is omitted, IOPS extracts into a folder named after the archive (for example, `study.tar.gz` extracts into `./study/`) instead of scattering files into the current directory.

By default, IOPS verifies extracted files against SHA256 checksums stored in the archive manifest. Progress bars are shown when the `rich` library is installed.

**Examples:**

```bash
iops archive extract study.tar.gz
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

### cache - Cache Management

Manage IOPS execution cache databases. Running `iops cache` without a subcommand prints usage guidance.

#### cache create

Build a cache database from a CSV file, mapping columns to parameters and metrics. Useful for importing results gathered outside IOPS (or from an older run) so they can be reused with `iops run --use-cache`:

```bash
iops cache create <csv_file> --params COL1,COL2 --metrics COL1,COL2 [options]
```

**Options:**
- `--params COL1,COL2` - Comma-separated CSV columns to treat as parameters (the cache key). Required.
- `--metrics COL1,COL2` - Comma-separated CSV columns to treat as metrics. Required.
- `--repetition-column COL` - CSV column holding the repetition number. If omitted, repetitions are auto-numbered (1, 2, 3, ...) per unique parameter set.
- `--delimiter CHAR` - CSV field delimiter (default: `,`).
- `--no-progress` - Disable the progress bar (shown while writing entries; requires the `watch` extra for `rich`).
- `-o, --output PATH` - Output cache database path (default: `<csv_stem>_cache.db`).

Each CSV row becomes one cached execution. Cell values are coerced to int, float, or bool where possible so they match how IOPS normalizes parameters at run time (for example, `8` and `"8"` hash to the same entry). Imported entries are stored with a `SUCCEEDED` status.

**Examples:**

```bash
# Import results, auto-numbering repetitions per parameter set
iops cache create results.csv --params nodes,ppn,block_size --metrics throughput,latency

# Use an existing column as the repetition number and choose the output path
iops cache create results.csv --params nodes,ppn --metrics throughput \
    --repetition-column rep -o study_cache.db

# Tab-separated input
iops cache create results.tsv --params nodes --metrics bw --delimiter $'\t'
```

The resulting database works with the other `cache` subcommands (`list`, `show`, `stats`) and with `iops run --use-cache` (the run's variables must hash to the same parameter set).

#### cache rebuild

Rebuild a cache database with modified variables:

```bash
iops cache rebuild <source> [options]
```

**Options:**
- `--exclude VAR1,VAR2` - Comma-separated list of variables to exclude from hash
- `--add VAR[:TYPE]=VALUE` - Add a variable to all entries. TYPE is int/float/str/bool (default: str). Can be repeated.
- `-o, --output PATH` - Output database path (default: `<source>_rebuilt.db`)

**Type Syntax:**

| Type | Example | Notes |
|------|---------|-------|
| `str` | `--add label=test` | Default if no type specified |
| `int` | `--add count:int=10` | |
| `float` | `--add rate:float=1.5` | |
| `bool` | `--add flag:bool=false` | Accepts: true/false, yes/no, 1/0 |

Specify types to match your YAML config.

**Examples:**

```bash
iops cache rebuild cache.db --exclude summary_file,output_path
iops cache rebuild cache.db --add cluster:str=skylake --add version:int=2 -o new_cache.db
iops cache rebuild cache.db --exclude output_path --add use_feature:bool=true -o new_cache.db
```

See the [Caching guide](../caching#rebuilding-the-cache) for detailed use cases.

### convert - Convert JUBE to IOPS

Convert a JUBE benchmark XML file to IOPS YAML format:

```bash
iops convert <file.xml> [options]
```

Requires the JUBE Python library (`pip install git+https://github.com/FZJ-JSC/JUBE.git`).

**Options:**
- `-o, --output PATH` - Output YAML path (default: `<input_stem>_iops.yaml`)
- `--benchmark NAME` - Select a specific benchmark if XML contains multiple
- `--executor {local,slurm}` - Target executor (default: local)
- `-n, --dry-run` - Print to stdout instead of writing a file

**Examples:**

```bash
iops convert benchmark.xml
iops convert benchmark.xml --executor slurm -o slurm_config.yaml
iops convert multi.xml --benchmark ior_bench --dry-run
```

See the [JUBE Conversion guide](../jube-conversion) for concept mapping, limitations, and post-conversion validation.

### --version - Show Version

```bash
iops --version
```

Displays the installed IOPS version.

### --help - Show Help

```bash
iops --help
```

Shows general help. Every subcommand (and nested subcommand) accepts `--help`, for example `iops run --help` or `iops archive create --help`.
