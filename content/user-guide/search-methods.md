---
title: "Search Methods"
---


IOPS supports multiple search strategies for exploring your parameter space. Each method has different trade-offs between thoroughness, efficiency, and use cases.

## Exhaustive Search

Tests all possible parameter combinations. Thorough but can be expensive for large parameter spaces.

```yaml
benchmark:
  search_method: "exhaustive"
```

### When to Use

- Small to medium parameter spaces
- Need complete coverage of all combinations
- Want deterministic, reproducible results
- Generating comprehensive datasets

### Example

```yaml
vars:
  threads: { type: int, sweep: { mode: list, values: [1, 2, 4, 8] } }
  buffer: { type: int, sweep: { mode: list, values: [4, 16, 64] } }
# Total tests: 4 × 3 = 12 combinations
```

## Bayesian Optimization

Uses Gaussian Process regression to intelligently explore the parameter space, focusing on promising regions.

```yaml
benchmark:
  search_method: "bayesian"
  bayesian_config:
    objective_metric: "throughput"  # Required: must match parser metric
    objective: "maximize"  # or "minimize" (default: "minimize")
    n_initial_points: 5
    n_iterations: 20
    acquisition_func: "EI"  # Expected Improvement
    base_estimator: "RF"    # Random Forest (default)
```

### When to Use

- Large parameter spaces
- Expensive evaluations (time or cost)
- Optimizing for a specific metric
- Want to find optima quickly
- Smooth objective functions

### Configuration Options

- **objective_metric** (required): Metric to optimize (must match a parser-defined metric)
- **objective**: `maximize` or `minimize` (default: `minimize`)
- **n_initial_points**: Random samples before optimization starts (default: 5)
- **n_iterations**: Total number of evaluations (default: 20)
- **acquisition_func**: Acquisition function (default: `EI`)
  - `EI`: Expected Improvement (balanced)
  - `PI`: Probability of Improvement (more exploitative)
  - `LCB`: Lower Confidence Bound (more exploratory)
- **base_estimator**: Surrogate model type (default: `RF`)
  - `RF`: Random Forest (robust, handles categorical well)
  - `GP`: Gaussian Process (best for continuous)
  - `ET`: Extra Trees
  - `GBRT`: Gradient Boosted Regression Trees
- **xi**: Exploration trade-off for EI/PI (default: 0.01)
- **kappa**: Exploration parameter for LCB (default: 1.96)

### Example

```yaml
benchmark:
  search_method: "bayesian"
  bayesian_config:
    objective_metric: "bandwidth_mbps"  # Required
    objective: "maximize"
    n_initial_points: 10
    n_iterations: 50

vars:
  block_size: { type: int, sweep: { mode: list, values: [4, 8, 16, 32, 64] } }
  transfer_size: { type: int, sweep: { mode: list, values: [1, 2, 4, 8] } }
# Instead of 5 × 4 = 20 tests, runs 50 intelligently selected tests
```

## Random Sampling

Randomly samples from the parameter space. Useful for statistical analysis and exploration.

```yaml
benchmark:
  search_method: "random"
  random_config:
    n_samples: 20  # Sample exactly 20 configurations
    # OR
    # percentage: 0.1  # Sample 10% of parameter space
    fallback_to_exhaustive: true
```

### When to Use

- Very large parameter spaces
- Quick exploration and reconnaissance
- Statistical sampling for analysis
- Budget-constrained experiments
- Initial understanding before focused optimization

### Configuration Options

- **n_samples** (int): Explicit number of configurations to sample
  - Mutually exclusive with `percentage`
- **percentage** (float): Proportion of parameter space (0.0-1.0)
  - Mutually exclusive with `n_samples`
- **fallback_to_exhaustive** (bool, default: true): Use exhaustive if sample size >= total space

### Example

```yaml
benchmark:
  search_method: "random"
  random_config:
    n_samples: 30
  random_seed: 42  # For reproducibility

vars:
  processes: { type: int, sweep: { mode: list, values: [1,2,4,8,16,32] } }
  volume: { type: int, sweep: { mode: list, values: [1,2,4,8,16] } }
# Total space: 6 × 5 = 30 configurations
# Samples: 30 random configurations
# With repetitions: 30 × 3 = 90 tests
```

## Comparison

| Method | Coverage | Speed | Best For | Deterministic |
|--------|----------|-------|----------|---------------|
| **Exhaustive** | Complete | Slow for large spaces | Small spaces, full coverage | Yes |
| **Bayesian** | Focused | Fast for optimization | Finding optima, expensive tests | No |
| **Random** | Statistical | Fast | Exploration, large spaces | With seed |

## Exhaustive Variables

The `exhaustive_vars` feature allows you to combine intelligent search with exhaustive testing for specific variables. This is useful when you want to analyze the full impact of certain variables while efficiently exploring others.

```yaml
benchmark:
  search_method: "bayesian"  # or "random"
  exhaustive_vars: ["ost_num"]  # Test all values at each search point
```

### How It Works

When using Bayesian or random search with `exhaustive_vars`:

1. The search method selects points in the **search space** (non-exhaustive variables)
2. For each selected point, IOPS tests **all values** of exhaustive variables
3. Results include the full cross-product

### Example

```yaml
benchmark:
  search_method: "bayesian"
  bayesian_config:
    objective_metric: "bandwidth_mbps"  # Required
    objective: "maximize"
    n_initial_points: 3
    n_iterations: 8
  exhaustive_vars: ["ost_num"]  # Always test all OST values

vars:
  nodes: { type: int, sweep: { mode: list, values: [1, 2, 4, 8] } }
  ppn: { type: int, sweep: { mode: list, values: [4, 8, 16] } }
  ost_num: { type: int, sweep: { mode: list, values: [1, 2, 4, 8, 16] } }
```

**Execution flow:**
- Bayesian selects point: `(nodes=4, ppn=16)`
- IOPS tests all ost_num values:
  - `(nodes=4, ppn=16, ost_num=1)`
  - `(nodes=4, ppn=16, ost_num=2)`
  - `(nodes=4, ppn=16, ost_num=4)`
  - `(nodes=4, ppn=16, ost_num=8)`
  - `(nodes=4, ppn=16, ost_num=16)`
- Total: 8 search points × 5 ost_num values = 40 tests
- Compare to: Full factorial would be 4 × 3 × 5 = 60 tests

### When to Use

- **Analyze variable impact**: Understand how one variable (e.g., OST count) affects performance across different configurations
- **Hybrid exploration**: Use intelligent search for expensive variables, exhaustive testing for cheap ones
- **Systematic analysis**: Ensure complete coverage of specific variables while reducing total test count

### Notes

- With `search_method: "exhaustive"`, `exhaustive_vars` has no effect (already tests all combinations)
- Exhaustive variables must have a `sweep` definition
- Can specify multiple exhaustive variables: `exhaustive_vars: ["ost_num", "stripe_size"]`

## Multi-Round Workflows

Search methods work with multi-round optimization:

```yaml
benchmark:
  search_method: "random"
  random_config:
    n_samples: 10

rounds:
  - name: "explore_processes"
    sweep_vars: ["processes"]
    search:
      metric: "throughput"
      objective: "max"

  - name: "explore_volume"
    sweep_vars: ["volume"]
    search:
      metric: "throughput"
      objective: "max"
```

Each round independently applies the search method to its parameter space.

## Reproducibility

Ensure reproducible sampling with `random_seed`:

```yaml
benchmark:
  search_method: "random"  # or "bayesian"
  random_seed: 12345
```

Same seed = same samples across runs.

## Next Steps

- Understand the [YAML Format](yaml-format.md)
- Learn about [Execution Backends](execution-backends.md)
- Explore [Multi-Round Optimization](../reference/yaml-schema.md#section-rounds-optional)
