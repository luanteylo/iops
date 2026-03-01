---
title: "Bayesian Optimization"
---

Bayesian optimization lets IOPS intelligently explore a parameter space to find configurations that maximize or minimize a target metric, using far fewer evaluations than exhaustive search. Instead of testing every combination, it builds a surrogate model from observed results and focuses on the most promising regions.

## Table of Contents

1. [Overview](#overview)
2. [Basic Configuration](#basic-configuration)
3. [How IOPS Implements Bayesian Optimization](#how-iops-implements-bayesian-optimization)
    - [The optimization loop](#the-optimization-loop)
    - [Parameter space encoding](#parameter-space-encoding)
    - [Nearest-neighbor mapping](#nearest-neighbor-mapping)
    - [Feedback and metric aggregation](#feedback-and-metric-aggregation)
4. [Choosing a Surrogate Model](#choosing-a-surrogate-model)
5. [Acquisition Functions](#acquisition-functions)
6. [Convergence and Early Stopping](#convergence-and-early-stopping)
    - [Default behavior](#default-behavior)
    - [Early stopping with xi boost](#early-stopping-with-xi-boost)
7. [Combining with Exhaustive Variables](#combining-with-exhaustive-variables)
8. [Fallback to Exhaustive](#fallback-to-exhaustive)
9. [Configuration Reference](#configuration-reference)

---

## Overview

Bayesian optimization (BO) is a sequential, model-based strategy for optimizing expensive black-box functions. In the context of benchmarking, each "function evaluation" is a full benchmark run, which may take minutes or hours. BO reduces the number of runs needed to find a good configuration by learning from previous results.

**When to use Bayesian optimization:**

- You have multiple parameters with many possible combinations
- Each benchmark run is expensive (long runtime, cluster allocation)
- You want to find the best configuration without testing everything

**When exhaustive or random search may be better:**

- Your parameter space is small enough to test everything
- You need complete coverage for statistical analysis
- You have no clear optimization target (exploratory study)

**Install note:** Bayesian optimization requires the `scikit-optimize` library. Install with:

```bash
pip install iops-benchmark[bayesian]
```

## Basic Configuration

A minimal Bayesian optimization config requires `search_method: "bayesian"`, an `objective_metric` (matching a parser metric), and at least one variable with multiple sweep values:

```yaml
benchmark:
  name: "Throughput Optimization"
  workdir: "./workdir"
  executor: "local"
  search_method: "bayesian"
  bayesian_config:
    objective_metric: "throughput"
    objective: "maximize"
    n_iterations: 20

vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4, 8]

  block_size:
    type: int
    sweep:
      mode: list
      values: [64, 128, 256, 512, 1024]

  transfer_size:
    type: int
    sweep:
      mode: range
      start: 1
      end: 16

command:
  template: "benchmark --nodes {{ nodes }} --bs {{ block_size }}k --xfer {{ transfer_size }}m"

scripts:
  - name: "bench"
    submit: "bash"
    script_template: |
      #!/bin/bash
      {{ command.template }}
    parser:
      file: "{{ execution_dir }}/output.txt"
      metrics:
        - name: throughput
      parser_script: |
        import re
        def parse(file_path):
            with open(file_path) as f:
                content = f.read()
            bw = float(re.search(r"Bandwidth: ([\d.]+)", content).group(1))
            return {"throughput": bw}

output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
```

This config has 4 x 5 x 16 = 320 possible combinations. With `n_iterations: 20`, IOPS tests only ~6% of the space while searching for the configuration that maximizes `throughput`.

## How IOPS Implements Bayesian Optimization

### The optimization loop

Each Bayesian iteration follows a four-step cycle:

```
┌─────────────────────────────────────────────────────────────┐
│  1. ASK     Optimizer suggests a point in continuous space   │
│       ↓                                                      │
│  2. MAP     Nearest-neighbor lookup finds the closest valid  │
│             configuration from the pre-built execution matrix│
│       ↓                                                      │
│  3. EXECUTE Run the benchmark (all repetitions)              │
│       ↓                                                      │
│  4. TELL    Report the observed metric back to the optimizer │
│             (using the actual evaluated point, not the       │
│             original suggestion)                             │
└─────────────────────────────────────────────────────────────┘
```

The first `n_initial_points` iterations (default: 5) use random sampling to build an initial dataset. After that, the surrogate model guides each suggestion.

IOPS builds the full execution matrix upfront (all valid parameter combinations after constraint filtering), then uses a lookup table to map optimizer suggestions to real configurations. This ensures every evaluated point is a valid, constraint-respecting combination.

### Parameter space encoding

The optimizer works in a continuous numerical space, but IOPS variables come in different forms. Each variable type is encoded differently:

**Integer and float ranges** (`sweep.mode: range`) map directly to `Integer` or `Real` dimensions in scikit-optimize. The optimizer can suggest any value in the continuous range, and nearest-neighbor mapping selects the closest valid discrete point.

```yaml
# Maps to Integer(low=1, high=16)
transfer_size:
  type: int
  sweep:
    mode: range
    start: 1
    end: 16
```

**Numeric lists** (`sweep.mode: list` with `type: int` or `type: float`) use ordinal encoding. Values are sorted, and the optimizer works with indices (0, 1, 2, ...) instead of the raw values. This preserves the natural ordering: the model can learn that index 3 tends to produce better results than index 1, which it cannot do with categorical encoding.

```yaml
# Sorted to [64, 128, 256, 512, 1024]
# Maps to Integer(low=0, high=4) where index 0 = 64, index 4 = 1024
block_size:
  type: int
  sweep:
    mode: list
    values: [256, 64, 1024, 128, 512]
```

**String lists** (`type: str`) use categorical encoding. There is no meaningful ordering between string values, so the optimizer treats them as unrelated categories.

```yaml
# Maps to Categorical(categories=["read", "write", "mixed"])
operation:
  type: str
  sweep:
    mode: list
    values: ["read", "write", "mixed"]
```

**Single-value variables** (one-element lists or ranges where start equals end) are excluded from the search space entirely. They are treated as fixed constants and included in every evaluation. There is nothing to optimize when only one value exists.

### Nearest-neighbor mapping

The optimizer suggests points in continuous space, but IOPS can only run configurations that exist in the pre-built execution matrix. After each suggestion, IOPS finds the nearest valid configuration using squared Euclidean distance in index space.

This means the point actually evaluated may differ from what the optimizer suggested. For example, if the optimizer suggests index 2.7 for `block_size` (which has values [64, 128, 256, 512, 1024]), the nearest valid index is 3, corresponding to 512.

When multiple valid points are equidistant (ties), IOPS selects the one with the lexicographically largest index vector. This provides deterministic tie-breaking that tends to favor higher parameter values.

The feedback step (TELL) always reports the point that was actually evaluated, not the original suggestion. This prevents the surrogate model from learning incorrect associations between parameters and outcomes.

### Feedback and metric aggregation

After a configuration finishes running, IOPS extracts the target metric from the parser results and reports it to the optimizer.

**Repetitions.** When `benchmark.repetitions > 1`, IOPS runs all repetitions before reporting to the optimizer. The best value across repetitions is used (maximum for `objective: "maximize"`, minimum for `objective: "minimize"`), not the mean. This favors peak performance, which is typically more representative for benchmarks where variability comes from system noise rather than fundamental differences.

**Objective sign flip.** scikit-optimize always minimizes. When `objective: "maximize"`, IOPS negates the metric value before passing it to the optimizer (and negates it back for display). This is transparent to the user.

## Choosing a Surrogate Model

The `base_estimator` option selects the surrogate model that approximates the relationship between parameters and the target metric. The default is `RF` (Random Forest).

| Model | Best for | Strengths | Weaknesses |
|-------|----------|-----------|------------|
| `RF` (Random Forest) | Mixed spaces, most cases | Low variance, handles categorical/ordinal well, consistent | Slightly less precise than GP on smooth functions |
| `GP` (Gaussian Process) | Purely continuous spaces | Excellent uncertainty estimates, smooth interpolation | Struggles with categorical variables, scales poorly with many observations |
| `ET` (Extra Trees) | Similar to RF | Slightly faster training | Higher variance than RF |
| `GBRT` (Gradient Boosted Trees) | Large datasets | Good accuracy with many observations | More sensitive to hyperparameters |

**Recommendation:** Start with `RF` (the default). It produces the most consistent results across different parameter space shapes. Switch to `GP` only if all your variables are continuous (integer or float ranges, no lists or strings) and the search space is smooth.

## Acquisition Functions

The acquisition function decides where to sample next, balancing exploration (trying unknown regions) against exploitation (refining known good regions).

| Function | Parameter | Behavior |
|----------|-----------|----------|
| `EI` (Expected Improvement) | `xi` (default: 0.01) | Balanced. Selects points where the expected improvement over the current best is highest. Good default for most cases. |
| `PI` (Probability of Improvement) | `xi` (default: 0.01) | Exploitative. Selects points most likely to improve over the current best, even by a small amount. Converges faster but may miss better optima. |
| `LCB` (Lower Confidence Bound) | `kappa` (default: 1.96) | Exploratory. Selects points where the model's lower confidence bound is lowest. Higher `kappa` values increase exploration. |

**Tuning `xi` and `kappa`:**

- `xi` controls the exploration/exploitation trade-off for `EI` and `PI`. The default (0.01) provides a good balance. Increase to 0.1 or higher if you want broader exploration. Decrease toward 0 for more exploitation.
- `kappa` controls exploration for `LCB`. The default (1.96) corresponds to a 95% confidence interval. Increase for more exploration, decrease for more exploitation.

For most benchmarking workloads, `EI` with the default `xi: 0.01` works well. If you find the optimizer converging too quickly to a local optimum, increase `xi` or switch to `LCB`.

## Convergence and Early Stopping

When the surrogate model believes it has found the optimum, it may repeatedly suggest the same (or similar) configurations that map to already-visited points. IOPS detects this and provides two strategies.

### Default behavior

By default (`early_stop_on_convergence: false`), when the optimizer's suggestions keep mapping to visited points (after 10 retries), IOPS randomly samples from the remaining unvisited configurations. This ensures the full iteration budget is spent, even if the surrogate model has converged. The random fallback often discovers configurations the model missed.

Optimization ends when either:
- All `n_iterations` are exhausted
- Every configuration in the search space has been visited

### Early stopping with xi boost

When `early_stop_on_convergence: true`, IOPS uses a more sophisticated strategy before stopping:

1. **Convergence detected:** The optimizer's suggestions keep mapping to visited points.
2. **Xi boost:** IOPS multiplies `xi` by `xi_boost_factor` (default: 5.0) to push the acquisition function toward unexplored regions. The boost is exponential: on the k-th convergence event, `xi` becomes `original_xi * xi_boost_factor^k`.
3. **Random sample:** A random unvisited configuration is evaluated to provide fresh data.
4. **Xi reset:** If the optimizer subsequently suggests a new (unvisited) point on its own, `xi` is restored to its original value and the convergence counter resets.
5. **Early stop:** After `convergence_patience` (default: 3) consecutive convergence events, the optimization terminates.

```yaml
bayesian_config:
  objective_metric: "throughput"
  objective: "maximize"
  n_iterations: 50
  early_stop_on_convergence: true
  convergence_patience: 3       # Stop after 3 convergence events
  xi_boost_factor: 5.0          # xi multiplied by 5.0 each time
```

With the defaults, the xi progression on repeated convergence would be: 0.01 (original), 0.05 (first boost), 0.25 (second boost), then early stop (third event exceeds patience).

Use early stopping when you want to save compute time and are confident that continued exploration is unlikely to improve results. For most cases, the default (no early stopping) produces better final results because the random fallback occasionally discovers configurations the model undervalues.

## Combining with Exhaustive Variables

The `exhaustive_vars` feature lets you test all values of specific variables at every search point. Variables listed in `exhaustive_vars` are removed from the optimizer's search space and instead tested exhaustively at each selected point.

```yaml
benchmark:
  search_method: "bayesian"
  bayesian_config:
    objective_metric: "bandwidth"
    objective: "maximize"
    n_iterations: 10
  exhaustive_vars: ["stripe_count"]

vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4, 8]

  block_size:
    type: int
    sweep:
      mode: list
      values: [64, 256, 1024]

  stripe_count:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4]
```

**Execution flow:**

1. The optimizer selects a point in the search space (e.g., `nodes=4, block_size=256`).
2. IOPS tests all `stripe_count` values for that point: `(4, 256, 1)`, `(4, 256, 2)`, `(4, 256, 4)`.
3. The best metric value across the exhaustive instances is reported back to the optimizer.
4. Total tests per iteration: 1 search point x 3 stripe counts = 3.
5. Total tests for the run: 10 iterations x 3 = 30 benchmark executions.

This is useful when one variable (like a filesystem tuning parameter) should always be fully characterized, while others (like scale) are worth optimizing.

See [Search Methods: Exhaustive Variables](../search-methods#exhaustive-variables) for more details.

## Fallback to Exhaustive

When `n_iterations` is greater than or equal to the total number of valid configurations in the search space, there is no benefit to using a surrogate model. By default (`fallback_to_exhaustive: true`), IOPS automatically switches to exhaustive search in this case:

```
INFO: Requested n_iterations=50 >= total_space=32. Using full exhaustive search
      instead of Bayesian optimization.
```

This avoids the overhead of building and querying a surrogate model when every configuration will be tested anyway. When `fallback_to_exhaustive: false`, IOPS clamps `n_iterations` to the space size and runs the optimizer normally.

## Configuration Reference

All fields below go under `benchmark.bayesian_config`:

| Field | Default | Description |
|-------|---------|-------------|
| `objective_metric` | *(required)* | Metric name to optimize. Must match a metric defined in `scripts[].parser.metrics`. |
| `objective` | `"minimize"` | Optimization direction: `"minimize"` or `"maximize"`. |
| `n_iterations` | `20` | Total number of configurations to evaluate. |
| `n_initial_points` | `5` | Number of random samples before guided search begins. Must be less than `n_iterations`. |
| `acquisition_func` | `"EI"` | Acquisition function: `"EI"` (Expected Improvement), `"PI"` (Probability of Improvement), or `"LCB"` (Lower Confidence Bound). |
| `base_estimator` | `"RF"` | Surrogate model: `"RF"` (Random Forest), `"GP"` (Gaussian Process), `"ET"` (Extra Trees), or `"GBRT"` (Gradient Boosted Trees). |
| `xi` | `0.01` | Exploration/exploitation trade-off for `EI` and `PI`. Higher values encourage exploration. |
| `kappa` | `1.96` | Exploration parameter for `LCB`. Higher values encourage exploration. |
| `fallback_to_exhaustive` | `true` | Switch to exhaustive search when `n_iterations` >= total search space size. |
| `early_stop_on_convergence` | `false` | Stop when the optimizer converges instead of falling back to random sampling. |
| `convergence_patience` | `3` | Number of consecutive convergence events before early stopping (only used when `early_stop_on_convergence` is true). |
| `xi_boost_factor` | `5.0` | Multiplier applied to `xi` on each convergence event to encourage exploration (only used when `early_stop_on_convergence` is true). |

See also:
- [Search Methods](../search-methods) for a comparison of all search strategies
- [Adaptive Variables](../adaptive-variables#adaptive-vs-bayesian-optimization) for when to use adaptive probing vs Bayesian optimization
- [Custom Reports](../reporting) for the `bayesian_evolution` plot type that visualizes optimization progress
