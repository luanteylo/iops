---
title: "Bayesian Optimization Example"
---


This example demonstrates using Bayesian optimization to efficiently explore parameter space.

See `docs/examples/example_bayesian.yaml` for the complete configuration.

## Key Features

- Uses Gaussian Process optimization
- Intelligently selects promising parameter combinations
- Requires fewer evaluations than exhaustive search

## Configuration

```yaml
benchmark:
  search_method: "bayesian"
  bayesian_config:
    target_metric: "throughput"
    objective: "maximize"
    n_initial_points: 5
    n_iterations: 20
```

## When to Use

- Large parameter spaces
- Expensive evaluations
- Optimizing for a specific metric
- Want to find optima quickly
