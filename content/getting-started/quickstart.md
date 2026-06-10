---
title: "Quick Start"
---

Run your first benchmark with IOPS in a few minutes.

---

## Table of Contents

1. [Step 1: Create a Configuration](#step-1-create-a-configuration)
2. [Step 2: Preview Your Benchmark](#step-2-preview-your-benchmark)
3. [Step 3: Run the Benchmark](#step-3-run-the-benchmark)
4. [Step 4: Explore Executions](#step-4-explore-executions)
5. [Step 5: Analyze Results](#step-5-analyze-results)
6. [Understanding the Output](#understanding-the-output)

---

## Step 1: Create a Configuration

Generate a YAML configuration template:

```bash
iops generate my_config.yaml

# Fully-documented template with all options
iops generate my_config.yaml --full
```

## Step 2: Preview Your Benchmark

```bash
# Dry-run to see what will be executed
iops run my_config.yaml --dry-run
iops run my_config.yaml -n

# Check configuration validity
iops check my_config.yaml
```

The dry-run shows how many test instances will be generated, the parameter combinations, and estimated resource usage (for SLURM).

## Step 3: Run the Benchmark

```bash
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

Use the `find` command to explore and filter executions, inspect execution folders, or locate failed tests:

```bash
# List all executions with their parameters
iops find /path/to/workdir/run_001

# Filter executions by variable values
iops find /path/to/workdir/run_001 size=1000

# Show details for a specific execution
iops find /path/to/workdir/run_001/exec_023
```

## Step 5: Analyze Results

After the benchmark completes, generate an HTML report with interactive plots, statistical analysis, parameter correlations, and performance summaries:

```bash
iops report /path/to/workdir/run_001
```

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

The `__iops_*` files annotated in the tree above let the `find` command locate and filter executions by their parameters. See [Metadata Files]({{< relref "/user-guide/metadata-files" >}}) for their structure and how to disable them.

