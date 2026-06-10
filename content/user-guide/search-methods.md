---
title: "Search Methods"
---


IOPS supports multiple search strategies for exploring your parameter space, each with different trade-offs between thoroughness and efficiency.

## Exhaustive Search

Tests all possible parameter combinations. Thorough but expensive for large parameter spaces.

```yaml
benchmark:
  search_method: "exhaustive"
```

## Bayesian Optimization

Uses a surrogate model to explore the parameter space, focusing on promising regions. Default parameters are empirically tuned: with 20 iterations (~7% of search space), Bayesian optimization achieves ~90% of optimal vs ~79% for random search.

```yaml
benchmark:
  search_method: "bayesian"
  bayesian_config:
    objective_metric: "throughput"  # Required: must match parser metric
    objective: "maximize"           # or "minimize" (default: "minimize")
    n_initial_points: 5             # Random samples before guided search (default: 5)
    n_iterations: 20                # Total evaluations (default: 20)
    acquisition_func: "EI"          # "EI", "PI", or "LCB" (default: "EI")
    base_estimator: "RF"            # "RF", "ET", "GP", or "GBRT" (default: "RF")
    xi: 0.01                        # Exploration trade-off for EI/PI (default: 0.01)
    kappa: 1.96                     # Exploration parameter for LCB (default: 1.96)
    fallback_to_exhaustive: true    # Use exhaustive if n_iterations >= total space (default: true)
    early_stop_on_convergence: false # Stop when optimizer converges (default: false)
    convergence_patience: 3         # Convergence events before early stop (default: 3)
    xi_boost_factor: 5.0            # xi multiplier on each convergence event (default: 5.0)
```

See [Bayesian Optimization](../bayesian-optimization) for the full guide: each option in detail, parameter encoding, surrogate model selection, and convergence behavior.

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

- **n_samples** (int): Explicit number of configurations to sample. Mutually exclusive with `percentage`.
- **percentage** (float): Fraction of the parameter space, between 0 and 1 (e.g., `0.1` for 10%). Values above `1.0` are a configuration error. Mutually exclusive with `n_samples`.
- **fallback_to_exhaustive** (bool, default: true): Use exhaustive if sample size >= total space

## Adaptive Probing

Finds threshold values by starting at an initial value and stepping (multiplying, adding, or a custom expression) until a stop condition is met. Useful for finding limits like maximum problem sizes or memory capacity. Only one adaptive variable is allowed per config; when swept variables are present, each combination gets its own independent probe.

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

See [Adaptive Variables](../adaptive-variables) for the full guide: step methods, stop conditions, probe behavior, and the configuration reference.

## Comparison

| Method | Coverage | Speed | Best For | Deterministic |
|--------|----------|-------|----------|---------------|
| **Exhaustive** | Complete | Slow for large spaces | Small spaces, full coverage | Yes |
| **Bayesian** | Focused (~90% optimal with 7% coverage) | Fast for optimization | Finding optima, expensive tests | No |
| **Random** | Statistical (~79% optimal with 7% coverage) | Fast | Exploration, large spaces | With seed |
| **Adaptive** | Threshold search | Variable | Finding limits, capacity testing | Yes |

*Performance figures for exhaustive/bayesian/random based on empirical testing with 20 iterations across 10 seeds.*

> **Note:** With SLURM single-allocation mode (`slurm_options.allocation.mode: "single"`), only `exhaustive` and `random` are supported. `bayesian` and `adaptive` are rejected at config validation because single-allocation mode pre-generates all tests upfront, leaving no feedback loop. See [Single-Allocation Mode](../single-allocation-mode).

## Exhaustive Variables

The `exhaustive_vars` option combines Bayesian or random search with exhaustive testing for specific variables: the search method selects points among the non-exhaustive variables, and IOPS tests all values of the exhaustive variables at each selected point.

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

**Execution flow:** Bayesian selects a point such as `(nodes=4, ppn=16)`, then IOPS tests it with every `ost_num` value (1, 2, 4, 8, 16). Total: 8 search points × 5 ost_num values = 40 tests.

### Notes

- With `search_method: "exhaustive"`, `exhaustive_vars` has no effect (already tests all combinations)
- Exhaustive variables must have a `sweep` definition
- Multiple exhaustive variables are allowed: `exhaustive_vars: ["ost_num", "stripe_size"]`
