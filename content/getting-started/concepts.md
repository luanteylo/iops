---
title: "Core Concepts"
---


Understanding these core concepts will help you make the most of IOPS.

## Variables

Variables are the parameters you want to vary in your experiments. Each variable has a type and a sweep definition.

```yaml
vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [4, 8, 16, 32]

  block_size:
    type: int
    sweep:
      mode: range
      start: 4
      stop: 64
      step: 4
```

### Variable Types

- `int`: Integer values
- `float`: Floating-point values
- `str`: String values
- `bool`: Boolean values (true/false)

### Sweep Modes

- **`list`**: Explicit list of values
- **`range`**: Numeric range with start, stop, and step
- **`logspace`**: Logarithmically spaced values

## Commands

Commands define what to execute for each test instance. IOPS uses Jinja2 templating to inject variable values.

```yaml
command:
  template: "ior -w -b {{ block_size }}mb -t {{ transfer_size }}mb -o {{ output_file }}"
```

### Template Variables

You can use any defined variable in your command template, plus special built-in variables:

- `{{ execution_dir }}`: Path to the instance execution directory
- `{{ workdir }}`: Path to the working directory
- `{{ instance_id }}`: Unique instance identifier

## Metrics

Metrics are the values you want to measure and analyze. They're extracted from your benchmark output using parser scripts.

```yaml
metrics:
  - name: bandwidth_mbps
  - name: latency_ms
  - name: iops
```

## Search Methods

IOPS supports three search strategies for exploring your parameter space:

### Exhaustive Search

Tests all possible parameter combinations. Thorough but can be expensive for large parameter spaces.

```yaml
benchmark:
  search_method: "exhaustive"
```

**Best for**: Small to medium parameter spaces, when you need complete coverage.

### Bayesian Optimization

Uses Gaussian Process regression to intelligently explore the parameter space, focusing on promising regions.

```yaml
benchmark:
  search_method: "bayesian"
  max_iterations: 50
```

**Best for**: Large parameter spaces, optimization problems, finding optima quickly.

### Random Sampling

Randomly samples from the parameter space. Useful for statistical analysis and exploration.

```yaml
benchmark:
  search_method: "random"
  max_iterations: 100
```

**Best for**: Very large parameter spaces, when you need statistical sampling.

## Execution Backends

IOPS supports two execution backends:

### Local Executor

Runs benchmarks directly on your local machine.

```yaml
benchmark:
  executor: "local"
```

**Best for**: Development, small experiments, single-node benchmarks.

### SLURM Executor

Submits jobs to a SLURM cluster with automatic resource management.

```yaml
benchmark:
  executor: "slurm"
  max_core_hours: 1000
  cores_expr: "{{ nodes * ppn }}"
```

**Best for**: Large-scale experiments, multi-node benchmarks, HPC environments.

## Caching

IOPS can cache execution results to avoid redundant tests. When enabled, IOPS compares parameter combinations and skips tests that have already been executed.

```yaml
benchmark:
  cache_file: "/path/to/cache.db"
```

Enable caching with the `--use-cache` flag:

```bash
iops config.yaml --use-cache
```

## Rounds

Rounds allow you to run experiments in stages, using results from earlier rounds to inform later ones.

```yaml
rounds:
  - name: "explore"
    sweep_vars: ["nodes"]
    repetitions: 1

  - name: "validate"
    sweep_vars: ["nodes", "processes_per_node"]
    repetitions: 5
```

**Best for**: Multi-stage experiments, progressive refinement.

## Output Formats

IOPS can export results to multiple formats:

- **CSV**: Simple, human-readable
- **SQLite**: Queryable database
- **Parquet**: Efficient columnar format

```yaml
output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
```

## Next Steps

- Learn about [Configuration](../user-guide/configuration.md)
- Understand the [YAML Format](../user-guide/yaml-format.md)
- Explore [Search Methods](../user-guide/search-methods.md) in detail
