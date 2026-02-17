---
title: "Adaptive Variables"
---

Adaptive variables let IOPS automatically probe for threshold values by starting at an initial value and progressing until a stop condition is met. This is useful for finding limits such as maximum problem sizes, memory capacities, or performance cliffs without manually defining the search space.

## Table of Contents

1. [Overview](#overview)
2. [Basic Configuration](#basic-configuration)
3. [Step Methods](#step-methods)
4. [Stop Conditions](#stop-conditions)
5. [Direction](#direction)
6. [Safety Limits](#safety-limits)
7. [Probe Results](#probe-results)
8. [Multiple Repetitions](#multiple-repetitions)
9. [Combining with Swept Variables](#combining-with-swept-variables)
    - [How probes advance](#how-probes-advance)
    - [Multiple swept variables](#multiple-swept-variables)
10. [Complete Example](#complete-example)
11. [Constraints](#constraints)
    - [Why only one adaptive variable?](#why-only-one-adaptive-variable)
12. [Configuration Reference](#configuration-reference)

---

## Overview

Unlike swept variables (which test a fixed list of values) or derived variables (which are computed from other variables), an adaptive variable is driven by a feedback loop:

1. Start at an `initial` value
2. Run the benchmark
3. Evaluate a `stop_when` condition against the result
4. If the condition is not met, advance the value (multiply, add, or compute) and repeat
5. If the condition is met, record the last successful value and stop

When the config also has swept variables, each swept combination gets its own independent probe. For example, with `nodes=[1, 2, 4]` and an adaptive `problem_size`, IOPS runs three independent probes, one per node count.

## Basic Configuration

```yaml
benchmark:
  search_method: "adaptive"    # Required for adaptive variables

vars:
  problem_size:
    type: int
    adaptive:
      initial: 1000            # Starting value
      factor: 2                # Next = previous * 2
      stop_when: "exit_code != 0"  # Stop when benchmark fails
```

Only [one adaptive variable](#why-only-one-adaptive-variable) is allowed per config. All other variables must use `sweep` or `expr`.

## Step Methods

Exactly one of `factor`, `increment`, or `step_expr` must be specified to define how the adaptive value progresses.

### Multiplicative (`factor`)

Each step multiplies the previous value by the factor.

```yaml
adaptive:
  initial: 1000
  factor: 2                    # Sequence: 1000, 2000, 4000, 8000, ...
  stop_when: "exit_code != 0"
```

For ascending direction, `factor` must be > 1. For descending direction, `factor` must be < 1.

### Additive (`increment`)

Each step adds the increment to the previous value.

```yaml
adaptive:
  initial: 100
  increment: 50                # Sequence: 100, 150, 200, 250, ...
  stop_when: "exit_code != 0"
```

For ascending direction, `increment` must be positive. For descending direction, `increment` must be negative.

### Custom expression (`step_expr`)

A Jinja2 expression that computes the next value from `previous` and `iteration`.

```yaml
adaptive:
  initial: 100
  step_expr: "{{ previous * 2 + 100 }}"  # Sequence: 100, 300, 700, 1500, ...
  stop_when: "exit_code != 0"
```

`step_expr` does not require numeric variable types (it can work with `str` types), while `factor` and `increment` require `int` or `float`.

## Stop Conditions

The `stop_when` field is a Python expression evaluated after each execution completes. When it evaluates to `True`, the probe stops.

### Available context

| Variable | Type | Description |
|----------|------|-------------|
| `exit_code` | int or None | Process return code (`__returncode`) |
| `status` | str | Executor status (`SUCCEEDED`, `FAILED`, etc.) |
| `metrics` | dict | Parsed metrics from the benchmark output |
| `execution_time` | float or None | Elapsed time in seconds (when timestamps are available) |
| `previous` | any | The adaptive value that was just tested (named `previous` for consistency with `step_expr`, where it means "use the previous value to compute the next") |
| `iteration` | int | 0-based iteration counter |

### Examples

**Stop on non-zero exit code** (the most common pattern):
```yaml
stop_when: "exit_code != 0"
```

**Stop when a metric degrades below a threshold:**
```yaml
stop_when: "metrics.get('throughput', 0) < 100"
```

**Stop when execution takes too long:**
```yaml
stop_when: "execution_time is not None and execution_time > 300"
```

## Direction

The `direction` field controls the expected progression order. It defaults to `"ascending"`.

```yaml
# Ascending (default): values increase over iterations
adaptive:
  initial: 1000
  factor: 2                    # 1000, 2000, 4000, ...
  direction: "ascending"

# Descending: values decrease over iterations
adaptive:
  initial: 1024
  factor: 0.5                  # 1024, 512, 256, ...
  direction: "descending"
```

Direction is used for validation only (ensuring `factor`/`increment` produce values in the expected order). It does not alter the step computation itself.

## Safety Limits

Use `max_iterations` to cap the number of values tested. When the limit is reached, the probe stops even if the stop condition was never triggered.

```yaml
adaptive:
  initial: 1000
  factor: 2
  stop_when: "exit_code != 0"
  max_iterations: 10           # Test at most 10 values
```

When `max_iterations` is omitted, the internal limit defaults to 100.

## Probe Results

After all probes finish, IOPS records:

- **found_value**: The last adaptive value where `stop_when` was `False` (the benchmark succeeded)
- **failed_value**: The first adaptive value where `stop_when` was `True` (the benchmark failed or degraded)
- **iterations**: Total number of values tested
- **stop_reason**: `"condition_met"`, `"max_iterations"`, or `"constraint_violation"`

Results are stored in the run metadata file (`__iops_run_metadata.json`) under the `adaptive_results` key and are displayed in the run summary logs.

### Example output

```
Adaptive probing results for 'problem_size':
  nodes=1: found=4000, failed=8000, iterations=4, stop_reason=condition_met
  nodes=2: found=8000, failed=16000, iterations=5, stop_reason=condition_met
  nodes=4: found=16000, iterations=10, stop_reason=max_iterations
```

## Multiple Repetitions

When `benchmark.repetitions > 1`, the planner runs all repetitions for each adaptive value before evaluating `stop_when`. If any repetition triggers the stop condition, the probe stops at that value. This provides robustness against flaky results.

```yaml
benchmark:
  search_method: "adaptive"
  repetitions: 3               # Run each value 3 times before deciding

vars:
  problem_size:
    type: int
    adaptive:
      initial: 1000
      factor: 2
      stop_when: "exit_code != 0"
```

## Combining with Swept Variables

When adaptive and swept variables coexist, IOPS creates one **independent probe** per unique combination of swept variable values. The adaptive variable is excluded from the normal Cartesian product matrix; instead, the planner builds the matrix from the swept variables only and assigns one probe per combination.

```yaml
vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4]

  problem_size:
    type: int
    adaptive:
      initial: 1000
      factor: 2
      stop_when: "exit_code != 0"
```

This creates 3 probes. Each probe independently doubles `problem_size` until the benchmark fails for that specific `nodes` value. The result is a per-node-count maximum problem size.

### How probes advance

Each probe tracks its own state and advances independently. When a new adaptive value is generated for one probe, only that specific swept combination is tested (not all combinations). Probes are served in round-robin order: IOPS emits all repetitions for the current value of one probe, then moves to the next probe, and cycles back.

**Example** with `nodes=[1, 2, 4]`, `problem_size` adaptive (initial=1000, factor=2):

```
Probe 0 (nodes=1): problem_size=1000 ok
Probe 1 (nodes=2): problem_size=1000 ok
Probe 2 (nodes=4): problem_size=1000 ok
Probe 0 (nodes=1): problem_size=2000 ok
Probe 1 (nodes=2): problem_size=2000 ok
Probe 2 (nodes=4): problem_size=2000 ok
Probe 0 (nodes=1): problem_size=4000 FAIL  -> probe 0 finished (found=2000, failed=4000)
Probe 1 (nodes=2): problem_size=4000 ok
Probe 2 (nodes=4): problem_size=4000 ok
Probe 1 (nodes=2): problem_size=8000 FAIL  -> probe 1 finished (found=4000, failed=8000)
Probe 2 (nodes=4): problem_size=8000 ok
Probe 2 (nodes=4): problem_size=16000 FAIL -> probe 2 finished (found=8000, failed=16000)
```

Key points:
- When probe 0 finishes at `problem_size=4000`, probes 1 and 2 keep going on their own
- Each probe can reach a different threshold (nodes=1 fails earlier, nodes=4 fails later)
- The total number of tests varies per probe: probe 0 ran 3 tests, probe 1 ran 4, probe 2 ran 5

### Multiple swept variables

When there are multiple swept variables, the number of probes equals the size of the Cartesian product of all swept variables:

```yaml
vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4]

  io_pattern:
    type: str
    sweep:
      mode: list
      values: ["sequential", "random"]

  problem_size:
    type: int
    adaptive:
      initial: 1000
      factor: 2
      stop_when: "exit_code != 0"
```

This creates 3 x 2 = 6 independent probes: `(nodes=1, io_pattern=sequential)`, `(nodes=1, io_pattern=random)`, `(nodes=2, io_pattern=sequential)`, and so on. Each finds its own threshold for `problem_size`.

## Complete Example

This example finds the maximum problem size before an out-of-memory failure for each node count:

```yaml
benchmark:
  name: "Memory Limit Finder"
  workdir: "./workdir"
  executor: "local"
  search_method: "adaptive"
  repetitions: 1

vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4, 8]

  problem_size:
    type: int
    adaptive:
      initial: 1000
      factor: 2
      stop_when: "exit_code != 0"
      max_iterations: 15

  total_elements:
    type: int
    expr: "problem_size * nodes"

command:
  template: "benchmark --size {{ problem_size }} --nodes {{ nodes }}"

scripts:
  - name: "bench"
    submit: "bash"
    script_template: |
      #!/bin/bash
      {{ command.template }}
      echo '{"peak_mem_mb": 1024}' > {{ execution_dir }}/result.json

    parser:
      file: "{{ execution_dir }}/result.json"
      metrics:
        - name: peak_mem_mb
      parser_script: |
        import json
        def parse(file_path):
            with open(file_path) as f:
                return json.load(f)

output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
```

## Constraints

- Only one adaptive variable per config
- Adaptive variables cannot appear in `exhaustive_vars` or `cache_exclude_vars`
- `benchmark.search_method` must be `"adaptive"` when an adaptive variable is defined
- `factor` and `increment` require numeric types (`int` or `float`)
- `step_expr` works with any type
- Conditional variables (`when`) cannot reference the adaptive variable, because `when` conditions are evaluated during matrix generation before the adaptive value is known. Use only swept variables in `when` expressions.

### Why only one adaptive variable?

This is a deliberate design choice to keep the search well-defined and the results interpretable:

- **Ambiguous search strategy.** With one adaptive variable the progression is clear: step forward in one dimension until you hit a wall. With two adaptive variables (say `problem_size` and `buffer_size`), how should they advance? Both at once? One at a time? Alternate? Each strategy produces different results, and there is no obviously correct default.
- **Stop condition attribution.** The `stop_when` expression tells you "something failed," but with two adaptive variables moving simultaneously you cannot tell which one caused the failure. With one adaptive variable the cause is unambiguous.
- **Exponential probe space.** With one adaptive variable and N swept combos you get N independent 1D probes. With two adaptive variables each probe becomes a 2D search, which is closer to what Bayesian optimization already handles (with a surrogate model to guide it).
- **Clean result structure.** The output is a simple `found_value` / `failed_value` pair per probe. With two adaptive variables you would need a 2D boundary, which is harder to represent and act on.

If you need to explore thresholds for two variables, sweep one and probe the other:

```yaml
vars:
  buffer_size:
    type: int
    sweep:
      mode: list
      values: [64, 128, 256, 512]    # sweep this one

  problem_size:
    type: int
    adaptive:
      initial: 1000
      factor: 2
      stop_when: "exit_code != 0"    # probe this one per buffer_size
```

This gives you the threshold `problem_size` for each `buffer_size` value, which is usually more actionable than probing both dimensions blindly. Alternatively, run two separate adaptive configs (one per variable) for fully independent threshold searches.

## Configuration Reference

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `initial` | Yes | | Starting value |
| `factor` | One of three | | Multiplicative step (next = previous * factor) |
| `increment` | One of three | | Additive step (next = previous + increment) |
| `step_expr` | One of three | | Jinja2 expression for custom progression |
| `stop_when` | Yes | | Python expression evaluated after each execution |
| `max_iterations` | No | 100 (internal) | Maximum number of values to test |
| `direction` | No | `"ascending"` | Expected progression: `"ascending"` or `"descending"` |
