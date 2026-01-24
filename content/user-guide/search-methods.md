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
    early_stop_on_convergence: bool #   Stop when optimizer converges (default: false)
    fallback_to_exhaustive: true  # Use exhaustive if n_iterations >= total space
```

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
- **fallback_to_exhaustive** (bool, default: true): Use exhaustive search if n_iterations >= total space
- **early_stop_on_convergence** (bool, default: false): Stop when optimizer converges instead of falling back to random sampling




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


### Configuration Options

- **n_samples** (int): Explicit number of configurations to sample
  - Mutually exclusive with `percentage`
- **percentage** (float): Proportion of parameter space (0.0-1.0)
  - Mutually exclusive with `n_samples`
- **fallback_to_exhaustive** (bool, default: true): Use exhaustive if sample size >= total space


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


### Notes

- With `search_method: "exhaustive"`, `exhaustive_vars` has no effect (already tests all combinations)
- Exhaustive variables must have a `sweep` definition
- Can specify multiple exhaustive variables: `exhaustive_vars: ["ost_num", "stripe_size"]`



