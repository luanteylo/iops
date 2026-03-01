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

Uses a surrogate model to intelligently explore the parameter space, focusing on promising regions. Default parameters are empirically tuned: with 20 iterations (~7% of search space), Bayesian optimization achieves ~90% of optimal vs ~79% for random search.

```yaml
benchmark:
  search_method: "bayesian"
  bayesian_config:
    objective_metric: "throughput"  # Required: must match parser metric
    objective: "maximize"           # or "minimize" (default: "minimize")
    n_initial_points: 5             # Random samples before guided search
    n_iterations: 20                # Total evaluations
    acquisition_func: "EI"          # Expected Improvement (default)
    base_estimator: "RF"            # Random Forest (default, most consistent)
    xi: 0.01                        # Exploration trade-off (default)
    fallback_to_exhaustive: true    # Use exhaustive if n_iterations >= total space
    early_stop_on_convergence: false # Stop when optimizer converges
    convergence_patience: 3         # Convergences before early stop
    xi_boost_factor: 5.0            # xi multiplier when stuck
```

### Configuration Options

- **objective_metric** (required): Metric to optimize (must match a parser-defined metric)
- **objective**: `maximize` or `minimize` (default: `minimize`)
- **n_initial_points**: Random samples before optimization starts (default: 5)
- **n_iterations**: Total number of evaluations (default: 20)
- **acquisition_func**: Acquisition function (default: `EI`)
  - `EI`: Expected Improvement (balanced exploration/exploitation)
  - `PI`: Probability of Improvement (more exploitative)
  - `LCB`: Lower Confidence Bound (more exploratory)
- **base_estimator**: Surrogate model type (default: `RF`)
  - `RF`: Random Forest (most consistent results, handles categorical well)
  - `ET`: Extra Trees (similar to RF, slightly higher variance)
  - `GP`: Gaussian Process (best for continuous spaces)
  - `GBRT`: Gradient Boosted Regression Trees
- **xi**: Exploration trade-off for EI/PI (default: 0.01, good balance)
- **kappa**: Exploration parameter for LCB (default: 1.96)
- **fallback_to_exhaustive** (bool, default: true): Use exhaustive search if n_iterations >= total space
- **early_stop_on_convergence** (bool, default: false): Stop when optimizer converges instead of falling back to random sampling. When enabled, uses `convergence_patience` and `xi_boost_factor` to escape local optima before stopping.
- **convergence_patience** (int, default: 3): Number of consecutive convergence events before early stopping. When convergence is detected, `xi` is boosted to encourage exploration.
- **xi_boost_factor** (float, default: 5.0): Multiplier for `xi` when convergence is detected. Helps escape local optima by encouraging more exploration.

See [Bayesian Optimization](../bayesian-optimization) for a complete guide covering parameter encoding, surrogate model selection, and convergence behavior.



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


## Adaptive Probing

Automatically finds threshold values by starting at an initial value and stepping (doubling, adding, or custom expression) until a stop condition is met. Useful for finding limits like maximum problem sizes, memory capacity, or performance cliffs.

```yaml
benchmark:
  search_method: "adaptive"

vars:
  problem_size:
    type: int
    adaptive:
      initial: 1000
      factor: 2                          # Double each iteration
      stop_when: "exit_code != 0"        # Stop when benchmark fails
      max_iterations: 15                 # Safety limit
```

### Key Features

- **One adaptive variable per config**: All other variables use `sweep` or `expr`
- **Independent probes**: When swept variables are present, each combination gets its own probe
- **Multiple repetitions**: All reps complete before evaluating the stop condition
- **Three step modes**: `factor` (multiplicative), `increment` (additive), `step_expr` (custom Jinja2)
- **Configurable stop conditions**: Based on exit code, parsed metrics, execution time, or status

See [Adaptive Variables](../adaptive-variables) for a complete guide.


## Comparison

| Method | Coverage | Speed | Best For | Deterministic |
|--------|----------|-------|----------|---------------|
| **Exhaustive** | Complete | Slow for large spaces | Small spaces, full coverage | Yes |
| **Bayesian** | Focused (~90% optimal with 7% coverage) | Fast for optimization | Finding optima, expensive tests | No |
| **Random** | Statistical (~79% optimal with 7% coverage) | Fast | Exploration, large spaces | With seed |
| **Adaptive** | Threshold search | Variable | Finding limits, capacity testing | Yes |

*Performance figures for exhaustive/bayesian/random based on empirical testing with 20 iterations across 10 seeds.*

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



