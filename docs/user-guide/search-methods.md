# Search Methods

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
    target_metric: "throughput"
    objective: "maximize"  # or "minimize"
    n_initial_points: 5
    n_iterations: 20
    acquisition_func: "EI"  # Expected Improvement
```

### When to Use

- Large parameter spaces
- Expensive evaluations (time or cost)
- Optimizing for a specific metric
- Want to find optima quickly
- Smooth objective functions

### Configuration Options

- **target_metric**: Metric to optimize (from parser output)
- **objective**: `maximize` or `minimize`
- **n_initial_points**: Random samples before optimization starts
- **n_iterations**: Total number of evaluations
- **acquisition_func**: Acquisition function
  - `EI`: Expected Improvement (default, balanced)
  - `PI`: Probability of Improvement (more exploitative)
  - `LCB`: Lower Confidence Bound (more exploratory)

### Example

```yaml
benchmark:
  search_method: "bayesian"
  bayesian_config:
    target_metric: "bandwidth_mbps"
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
