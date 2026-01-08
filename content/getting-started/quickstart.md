---
title: "Quick Start"
---


This guide will walk you through running your first benchmark with IOPS in just a few minutes.

## Step 1: Create a Configuration

Generate a comprehensive YAML template with all options documented:

```bash
iops --generate my_config.yaml
```

This creates a fully-commented template showing all available configuration options. You can customize it for your needs.

Alternatively, start from an example:

```bash
cp docs/examples/example_simple.yaml my_config.yaml
```

## Step 2: Preview Your Benchmark

Before running, it's good practice to preview what will be executed:

```bash
# Dry-run to see what will be executed
iops my_config.yaml --dry-run
iops my_config.yaml -n

# Check configuration validity
iops my_config.yaml --check
```

The dry-run will show you:

- How many test instances will be generated
- What parameter combinations will be tested
- Estimated resource usage (for SLURM)

## Step 3: Run the Benchmark

Run your benchmark with the basic command:

```bash
# Basic execution
iops my_config.yaml
```

### Common Options

```bash
# With caching (skip already-executed tests)
iops my_config.yaml --use-cache

# With budget limit (SLURM only)
iops my_config.yaml --max-core-hours 1000

# With verbose output
iops my_config.yaml --verbose
iops my_config.yaml -v

# With debug logging
iops my_config.yaml --log-level DEBUG

# Write logs to file
iops my_config.yaml --log-file benchmark.log

# Disable terminal logging (log to file only)
iops my_config.yaml --no-log-terminal
```

## Step 4: Explore Executions

You can explore and filter your benchmark executions using the `--find` command:

```bash
# List all executions with their parameters
iops --find /path/to/workdir/run_001

# Filter executions by variable values
iops --find /path/to/workdir/run_001 --filter size=1000

# Show details for a specific execution
iops --find /path/to/workdir/run_001/exec_023
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
iops --analyze /path/to/workdir/run_001
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
├── run_001/                    # Unique run directory
│   ├── __iops_index.json       # Index of all executions with parameters
│   ├── exec_001/               # Individual execution instance
│   │   ├── __iops_params.json  # Parameters for this execution
│   │   ├── repetition_1/       # Repetition folder
│   │   │   ├── script.sh       # Generated execution script
│   │   │   ├── stdout.txt      # Standard output
│   │   │   └── stderr.txt      # Standard error
│   │   └── repetition_2/
│   ├── exec_002/
│   │   ├── __iops_params.json
│   │   └── repetition_1/
│   ├── results.csv             # Aggregated results
│   ├── results.db              # SQLite database (if enabled)
│   └── report.html             # Analysis report
└── iops.log                    # Execution log
```

### IOPS Metadata Files

IOPS creates metadata files with the `__iops_` prefix to enable execution tracking and exploration:

- `__iops_index.json` - Index of all executions in the run root
- `__iops_params.json` - Parameter values for each execution folder
- `__iops_sysinfo.json` - System information (if system probe is enabled)

These files enable the `--find` command to quickly locate and filter executions by their parameters.

## Simple Example

Here's a minimal working example:

```yaml title="simple_benchmark.yaml"
benchmark:
  name: "Simple Example"
  workdir: "./workdir"
  executor: "local"
  search_method: "exhaustive"
  repetitions: 1

vars:
  size:
    type: int
    sweep:
      mode: list
      values: [100, 1000, 10000]

command:
  template: "echo 'Processing size: {{ size }}' && sleep 1"

scripts:
  - name: "test"
    parser:
      file: "{{ execution_dir }}/stdout.txt"
      metrics:
        - name: size
      parser_script: |
        import sys
        import re
        with open(sys.argv[1]) as f:
            content = f.read()
            match = re.search(r'size: (\d+)', content)
            if match:
                print(f"size,{match.group(1)}")

output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
```

Run it:

```bash
iops simple_benchmark.yaml
```

## Next Steps

- Learn about [Core Concepts](concepts.md)
- Explore the [User Guide](../user-guide/configuration.md)
- Check out more [Examples](../examples/index.md)
- Understand the [YAML Format](../user-guide/yaml-format.md)
