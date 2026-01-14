---
title: "Quick Start"
---


This guide will walk you through running your first benchmark with IOPS in just a few minutes.

## Step 1: Create a Configuration

Generate a YAML configuration template:

```bash
iops generate my_config.yaml
```

For a fully-documented template with all options:

```bash
iops generate my_config.yaml --full
```

## Step 2: Preview Your Benchmark

Before running, it's good practice to preview what will be executed:

```bash
# Dry-run to see what will be executed
iops run my_config.yaml --dry-run
iops run my_config.yaml -n

# Check configuration validity
iops check my_config.yaml
```

The dry-run will show you:

- How many test instances will be generated
- What parameter combinations will be tested
- Estimated resource usage (for SLURM)

## Step 3: Run the Benchmark

Run your benchmark with the basic command:

```bash
# Basic execution
iops run my_config.yaml
```

### Common Options

```bash
# With caching (skip already-executed tests)
iops run my_config.yaml --use-cache

# With budget limit (SLURM only)
iops run my_config.yaml --max-core-hours 1000

# With verbose output
iops run my_config.yaml --verbose
iops run my_config.yaml -v

# With debug logging
iops run my_config.yaml --log-level DEBUG

# Write logs to file
iops run my_config.yaml --log-file benchmark.log

# Disable terminal logging (log to file only)
iops run my_config.yaml --no-log-terminal
```

## Step 4: Explore Executions

You can explore and filter your benchmark executions using the `find` command:

```bash
# List all executions with their parameters
iops find /path/to/workdir/run_001

# Filter executions by variable values
iops find /path/to/workdir/run_001 size=1000

# Show details for a specific execution
iops find /path/to/workdir/run_001/exec_023
```

This is useful for:
- Finding specific parameter combinations
- Inspecting execution folders
- Locating failed tests
- Exploring large parameter sweeps

## Step 5: Analyze Results

After your benchmark completes, generate an interactive HTML report:

```bash
# Generate HTML report with interactive plots
iops report /path/to/workdir/run_001
```

The report includes:

- Interactive plots of your metrics
- Statistical analysis
- Parameter correlations
- Performance summaries

## Understanding the Output

IOPS creates a structured working directory:

```
workdir/
├── run_001/                        # Unique run directory
│   ├── __iops_index.json           # Index of all executions
│   ├── __iops_run_metadata.json    # Run metadata for reports
│   ├── exec_0001/                  # Individual execution instance
│   │   ├── __iops_params.json      # Parameters for this execution
│   │   ├── __iops_status.json      # Execution status
│   │   ├── repetition_001/         # Repetition folder
│   │   │   ├── run_benchmark.sh    # Generated execution script
│   │   │   ├── stdout              # Standard output
│   │   │   ├── stderr              # Standard error
│   │   │   ├── __iops_exit_handler.sh    # Exit trap coordinator
│   │   │   ├── __iops_atexit_sysinfo.sh  # System info script
│   │   │   └── __iops_sysinfo.json       # System info (generated at exit)
│   │   └── repetition_002/
│   ├── exec_0002/
│   │   └── ...
│   ├── results.csv                 # Aggregated results
│   └── report.html                 # Analysis report
└── iops.log                        # Execution log
```

### IOPS Metadata Files

IOPS creates metadata files with the `__iops_` prefix to enable execution tracking and exploration:

- `__iops_index.json` - Index of all executions in the run root
- `__iops_run_metadata.json` - Run metadata used for HTML reports
- `__iops_params.json` - Parameter values for each execution folder
- `__iops_status.json` - Execution status (SUCCEEDED, FAILED, ERROR)
- `__iops_sysinfo.json` - System information (if system probe is enabled)

These files enable the `find` command to quickly locate and filter executions by their parameters.

