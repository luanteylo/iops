---
title: "Quick Start"
---


This guide will walk you through running your first benchmark with IOPS in just a few minutes.

## Step 1: Create a Configuration

Generate a comprehensive YAML template with all options documented:

```bash
iops --generate_setup my_config.yaml
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

# Check configuration validity
iops my_config.yaml --check_setup
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
iops my_config.yaml --use_cache

# With budget limit (SLURM only)
iops my_config.yaml --max-core-hours 1000

# With verbose logging
iops my_config.yaml --log_level DEBUG

# Disable terminal logging (log to file only)
iops my_config.yaml --no-log-terminal
```

## Step 4: Analyze Results

After your benchmark completes, generate an interactive HTML report:

```bash
# Generate HTML report with interactive plots
iops analyze /path/to/workdir/run_001
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
│   ├── instances/              # Individual test instances
│   │   ├── instance_001/
│   │   │   ├── script.sh       # Generated execution script
│   │   │   ├── stdout.txt      # Standard output
│   │   │   └── stderr.txt      # Standard error
│   │   └── instance_002/
│   ├── results.csv             # Aggregated results
│   ├── results.db              # SQLite database (if enabled)
│   └── report.html             # Analysis report
└── iops.log                    # Execution log
```

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
