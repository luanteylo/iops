---
title: "Configuration Guide"
---


This guide explains how to configure IOPS for your benchmarking needs.

## Configuration File Structure

IOPS uses YAML files to define benchmark experiments. The configuration file has several key sections:

1. **benchmark**: Global settings like working directory, executor type, and search method
2. **vars**: Variable definitions (parameters to sweep)
3. **command**: The benchmark command template
4. **scripts**: Execution scripts and result parsers
5. **output**: Where and how to store results
6. **rounds**: (Optional) Multi-round optimization workflows

## Generating a Configuration Template

The easiest way to start is to generate a template:

```bash
iops generate my_config.yaml
```

This creates a fully-commented template with all available options.

## Benchmark Section

The `benchmark` section defines global configuration:

```yaml
benchmark:
  name: "My Benchmark Study"
  description: "Performance testing with varying parameters"
  workdir: "./workdir"
  executor: "local"  # or "slurm"
  search_method: "exhaustive"  # or "bayesian" or "random"
  repetitions: 3
  cache_file: "/path/to/cache.db"  # Optional: for result caching
```

### Key Fields

- **name**: Human-readable benchmark name
- **workdir**: Base directory for all outputs
- **executor**: Where to run jobs (`local` or `slurm`)
- **search_method**: How to explore parameter space
- **repetitions**: Number of times to repeat each test
- **cache_file**: Optional cache file for skipping redundant tests
- **track_executions**: Optional (default: true) - write metadata files for `iops find` command

## Variables Section

Define parameters to vary:

### Swept Variables

```yaml
vars:
  threads:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4, 8, 16]

  buffer_size:
    type: int
    sweep:
      mode: range
      start: 4
      end: 64
      step: 4
```

### Derived Variables

```yaml
vars:
  total_size:
    type: int
    expr: "buffer_size * threads"

  output_file:
    type: str
    expr: "{{ execution_dir }}/results.dat"
```

## Command Section

Define the benchmark command using Jinja2 templating:

```yaml
command:
  template: >
    my_benchmark
    --threads {{ threads }}
    --buffer {{ buffer_size }}mb
    --output {{ output_file }}

  metadata:
    operation: "write"
    pattern: "sequential"

  env:
    OMP_NUM_THREADS: "{{ threads }}"
```

Jinja2 templates support powerful features including conditionals, loops, and filters. For comprehensive templating documentation including syntax requirements, see the [Jinja2 Templating section](../reference/yaml-schema.md#jinja2-templating) in the YAML Schema Reference.

## Scripts Section

Define how to execute the benchmark and parse results:

```yaml
scripts:
  - name: "benchmark"
    submit: "bash"  # or "sbatch" for SLURM

    script_template: |
      #!/bin/bash
      set -euo pipefail

      echo "Running test {{ execution_id }}, repetition {{ repetition }}"
      {{ command.template }}

    parser:
      file: "{{ execution_dir }}/output.json"
      metrics:
        - name: throughput
        - name: latency
      parser_script: |
        import json
        def parse(file_path: str):
            with open(file_path) as f:
                data = json.load(f)
            return {
                "throughput": float(data["throughput"]),
                "latency": float(data["latency"])
            }
```

## Output Section

Configure result storage:

```yaml
output:
  sink:
    type: csv  # or "parquet" or "sqlite"
    path: "{{ workdir }}/results.csv"
    mode: append
    exclude:
      - "benchmark.description"
```

## Validation

Always validate your configuration before running:

```bash
# Check configuration validity
iops check my_config.yaml

# Preview what will be executed
iops run my_config.yaml --dry-run
iops run my_config.yaml -n
```

## Next Steps

- Learn about the [YAML Format](yaml-format.md) in detail
- Explore [Search Methods](search-methods.md)
- Configure [Execution Backends](execution-backends.md)
- Enable [Result Caching](caching.md)
