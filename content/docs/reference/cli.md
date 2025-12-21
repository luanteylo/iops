# Command Line Interface

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
iops --generate_setup [output.yaml]
```

Generates a comprehensive YAML template with all options documented.

### Analyze Results

```bash
iops analyze <workdir/run_NNN>
```

Generates an interactive HTML report from completed benchmark results.

### Show Version

```bash
iops --version
```

Displays the installed IOPS version.

## Common Options

### Validation

```bash
# Check configuration validity
iops config.yaml --check_setup

# Dry-run (preview without executing)
iops config.yaml --dry-run
```

### Caching

```bash
# Use cached results
iops config.yaml --use_cache
```

### Logging

```bash
# Set log level
iops config.yaml --log_level DEBUG

# Disable terminal logging (log to file only)
iops config.yaml --no-log-terminal
```

### Budget Control (SLURM)

```bash
# Set core-hours budget
iops config.yaml --max-core-hours 1000

# Provide time estimates
iops config.yaml --estimated-time 120
```

## Complete Options Reference

```
Options:
  config_path              Path to YAML configuration file

  --generate_setup [PATH]  Generate configuration template
  --check_setup            Validate configuration
  --dry-run                Preview without executing
  --use_cache              Skip cached tests
  --max-core-hours N       Budget limit (SLURM)
  --estimated-time SEC     Estimated test duration (seconds)
  --log_level LEVEL        Log verbosity (DEBUG, INFO, WARNING, ERROR)
  --no-log-terminal        Disable terminal logging
  --version                Show version
  --help                   Show help message
```

## Examples

```bash
# Basic execution
iops benchmark.yaml

# With caching and verbose logging
iops benchmark.yaml --use_cache --log_level DEBUG

# Dry-run with budget estimation
iops benchmark.yaml --dry-run --estimated-time 300 --max-core-hours 1000

# Validate and check setup
iops benchmark.yaml --check_setup
```
