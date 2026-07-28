---
title: "Adaptive Variables"
weight: 45
---

Adaptive variables let IOPS probe for threshold values by starting at an initial value and progressing until a stop condition is met. Use them to find limits such as maximum problem sizes, memory capacities, or performance cliffs without manually defining the search space.

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
10. [Staircase Search with an Escalating Variable](#staircase-search-with-an-escalating-variable)
    - [How the staircase walks](#how-the-staircase-walks)
    - [Reading the frontier](#reading-the-frontier)
    - [When not to use it](#when-not-to-use-it)
11. [Complete Example](#complete-example)
12. [Constraints](#constraints)
    - [Why only one adaptive variable?](#why-only-one-adaptive-variable)
    - [Adaptive vs Bayesian optimization](#adaptive-vs-bayesian-optimization)
13. [Configuration Reference](#configuration-reference)

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

Each step multiplies the previous value by the factor: with `initial: 1000` and `factor: 2`, the sequence is 1000, 2000, 4000, 8000, ... For ascending direction, `factor` must be > 1; for descending, `factor` must be < 1.

### Additive (`increment`)

Each step adds the increment to the previous value: with `initial: 100` and `increment: 50`, the sequence is 100, 150, 200, 250, ... For ascending direction, `increment` must be positive; for descending, negative.

### Custom expression (`step_expr`)

A Jinja2 expression that computes the next value from `previous` and `iteration`:

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
| `metrics` | dict | Parsed metrics as a dict (e.g., `metrics.get('bwMiB', 0)`) |
| *metric names* | any | Each parsed metric is also available directly by name (e.g., `totalTime`, `bwMiB`) |
| `execution_time` | float or None | Wall-clock elapsed time in seconds (from executor timestamps) |
| `previous` | any | The adaptive value that was just tested (same name as in `step_expr`) |
| `iteration` | int | 0-based iteration counter |

Parsed metrics are available both directly by name and through the `metrics` dict:

```yaml
stop_when: "totalTime > 2"                    # direct access
stop_when: "metrics.get('totalTime', 0) > 2"  # dict access (safer if metric might be missing)
```

Metric names cannot conflict with the built-in context variables listed above; IOPS validates this at config load time. Note that `execution_time` (wall-clock time from executor timestamps, including queue wait and setup) differs from timing metrics your parser returns (like IOR's `totalTime`, which measures only the benchmark operation).

### Examples

```yaml
# Stop on non-zero exit code (the most common pattern)
stop_when: "exit_code != 0"

# Stop when a metric degrades below a threshold
stop_when: "gflops < 50"

# Combine conditions with and/or:
# stop if benchmark crashes OR takes longer than 2 minutes
stop_when: "exit_code != 0 or (execution_time is not None and execution_time > 120)"

# Stop when benchmark succeeds but performance degrades
stop_when: "exit_code == 0 and gflops < 50"
```

## Direction

The `direction` field declares the expected progression order: `"ascending"` (default, values increase) or `"descending"` (values decrease, e.g., `initial: 1024` with `factor: 0.5` gives 1024, 512, 256, ...). Direction is used for validation only (ensuring `factor`/`increment` produce values in the expected order); it does not alter the step computation itself.

## Safety Limits

Use `max_iterations` to cap the number of values tested:

```yaml
adaptive:
  initial: 1000
  factor: 2
  stop_when: "exit_code != 0"
  max_iterations: 10           # Test at most 10 values
```

When the limit is reached, the probe stops even if the stop condition was never triggered. When `max_iterations` is omitted, the probe runs without a limit and only stops on the `stop_when` condition.

## Probe Results

After all probes finish, IOPS records:

- **last_value_before_stop**: The last adaptive value where `stop_when` was `False`, meaning the probe continued past it
- **stop_value**: The value that triggered `stop_when`
- **iterations**: Total number of values tested
- **stop_reason**: `"condition_met"`, `"max_iterations"`, `"constraint_violation"`, or `"step_error"`

A `step_error` means the next value could not be computed, most often a `step_expr` that indexes a list with fewer values than the probe asked for. That probe stops and the rest of the run continues; the error naming the variable, iteration, and previous value is written to the log. When `max_iterations` is set and the expression does not reference `previous`, IOPS catches this at config load time instead, so `iops check` reports it before any test runs.

Results are stored in the run metadata file (`__iops_run_metadata.json`) under the `adaptive_results` key and are displayed in the run summary logs:

```
Adaptive probing results for 'problem_size':
  nodes=1: stop_value=8000, last_value_before_stop=4000, iterations=4, stop_reason=condition_met
  nodes=2: stop_value=16000, last_value_before_stop=8000, iterations=5, stop_reason=condition_met
  nodes=4: last_value_before_stop=16000, iterations=10, stop_reason=max_iterations
```

These names describe the probe's progression rather than success or failure, because `stop_when` decides what stopping means. With the usual `"exit_code != 0"`, the probe stops on the first failure, so `stop_value` is the first failing value and `last_value_before_stop` is the largest working one. With an inverted condition such as `"exit_code == 0"` (keep stepping while it fails, stop at the first success), `stop_value` is the value that succeeded.

**Note:** before 3.5.9 these were named `found_value` and `failed_value`, which assumed that stopping meant failure and so read backwards for an inverted `stop_when`. Both names are still written to the metadata file and still work as attributes on the probe result; see [Deprecations](../../about/deprecations).

## Multiple Repetitions

When `benchmark.repetitions > 1` (e.g., `repetitions: 3`), the planner runs all repetitions for each adaptive value before evaluating `stop_when`. If any repetition triggers the stop condition, the probe stops at that value. This provides robustness against flaky results.

## Combining with Swept Variables

When adaptive and swept variables coexist, IOPS creates one **independent probe** per unique combination of swept variable values. The adaptive variable is excluded from the normal Cartesian product matrix; the planner builds the matrix from the swept variables only and assigns one probe per combination. With `nodes=[1, 2, 4]` and an adaptive `problem_size`, this creates 3 probes; each independently doubles `problem_size` until the benchmark fails for that specific `nodes` value, yielding a per-node-count maximum problem size.

### How probes advance

Each probe tracks its own state and advances independently. When a new adaptive value is generated for one probe, only that specific swept combination is tested. Probes are served in round-robin order: IOPS emits all repetitions for the current value of one probe, then moves to the next probe, and cycles back.

**Example** with `nodes=[1, 2, 4]`, `problem_size` adaptive (initial=1000, factor=2):

```
Probe 0 (nodes=1): problem_size=1000 ok
Probe 1 (nodes=2): problem_size=1000 ok
Probe 2 (nodes=4): problem_size=1000 ok
Probe 0 (nodes=1): problem_size=2000 ok
Probe 1 (nodes=2): problem_size=2000 ok
Probe 2 (nodes=4): problem_size=2000 ok
Probe 0 (nodes=1): problem_size=4000 FAIL  -> probe 0 finished (stop_value=4000, last_value_before_stop=2000)
Probe 1 (nodes=2): problem_size=4000 ok
Probe 2 (nodes=4): problem_size=4000 ok
Probe 1 (nodes=2): problem_size=8000 FAIL  -> probe 1 finished (stop_value=8000, last_value_before_stop=4000)
Probe 2 (nodes=4): problem_size=8000 ok
Probe 2 (nodes=4): problem_size=16000 FAIL -> probe 2 finished (stop_value=16000, last_value_before_stop=8000)
```

When probe 0 finishes, probes 1 and 2 keep going on their own. Each probe can reach a different threshold and run a different number of tests (here 3, 4, and 5).

### Multiple swept variables

With multiple swept variables, the number of probes equals the size of the Cartesian product of all swept variables. For example, `nodes=[1, 2, 4]` and `ppn=[8, 16]` with an adaptive `matrix_size` creates 3 x 2 = 6 independent probes: `(nodes=1, ppn=8)`, `(nodes=1, ppn=16)`, `(nodes=2, ppn=8)`, and so on. Each finds its own threshold for `matrix_size`.

## Staircase Search with an Escalating Variable

A plain adaptive probe finishes as soon as `stop_when` triggers. Often that is not the end of the story: the run failed because some resource ran out, and giving that resource more would let the search continue. An **escalating variable** expresses exactly that.

```yaml
vars:
  problem_size:
    type: int
    adaptive:                        # the workload axis
      initial: 1000
      increment: 1000
      stop_when: "exit_code != 0"
      max_iterations: 20

  number_of_blocks:
    type: int
    escalate:                        # the resource axis
      values: [1, 4, 16]
```

When the probe would stop, the escalating variable advances to its next value and **the same adaptive value is retested** rather than the probe finishing. The probe ends only when the escalation values run out.

`escalate` is a variable kind like `sweep`, `expr`, and `adaptive`, and cannot be combined with them on the same variable. At most one escalating variable is allowed, and it requires an adaptive variable to extend. The escalation is driven by the adaptive variable's own `stop_when`, so there is only one condition to reason about.

### How the staircase walks

With the config above, against a benchmark where each problem size needs more blocks than the last:

| Run | Result | Action |
|-----|--------|--------|
| `problem_size=1000, number_of_blocks=1` | works | advance `problem_size` |
| `problem_size=2000, number_of_blocks=1` | fails | escalate, retest 2000 |
| `problem_size=2000, number_of_blocks=4` | works | advance `problem_size` |
| `problem_size=3000, number_of_blocks=4` | fails | escalate, retest 3000 |
| `problem_size=3000, number_of_blocks=16` | works | advance `problem_size` |
| `problem_size=4000, number_of_blocks=16` | fails | escalation exhausted, finish |

Only one axis moves per step, which is what keeps the search well defined. The cost is `P + B - 1` runs for `P` workload values and `B` escalation values. Sweeping the resource axis instead, so each workload value restarts the search from the smallest resource, costs up to `P x B`.

Each swept variable combination gets its own independent staircase, exactly as it gets its own probe without escalation.

### Reading the frontier

A staircase produces a frontier rather than a single threshold, reported per escalation value:

```
Adaptive probing results for 'problem_size' (escalating 'number_of_blocks'):
  (no swept vars):
    number_of_blocks=1: reached problem_size=1000
    number_of_blocks=4: reached problem_size=2000
    number_of_blocks=16: reached problem_size=3000
    stop_reason=escalation_exhausted, stopped at problem_size=4000
```

This reads along either axis: the smallest `number_of_blocks` each `problem_size` needs, or the largest `problem_size` each `number_of_blocks` can handle. They are the same three rows.

The frontier is also written to `__iops_run_metadata.json` under `adaptive_results`, as a `frontier` list alongside the usual fields, with `escalate_var` naming the escalating variable. An escalation value that never succeeded reports `null`, so a level is never credited with a value it did not actually run.

`stop_reason` is `escalation_exhausted` when the search ran out of escalation values. The other reasons apply unchanged: `max_iterations` if the workload axis hit its cap first, and `constraint_violation` or `step_error` as usual.

### When not to use it

The staircase never goes back to an earlier escalation value. It assumes that a value which fails at one adaptive value also fails at every later one. That holds for capacity limits, where more of the resource never hurts.

It does not hold if the escalating variable can fail at the top end too, for example if a high process count fails on communication overhead where a lower one succeeded. In that case the search walks past working configurations without noticing. Sweep the resource axis instead, so every combination is tested.

## Complete Example

This example finds the largest matrix that a DGEMM (dense matrix multiplication) kernel can process before exceeding a time limit, for each node count:

```yaml
benchmark:
  name: "DGEMM Scaling Limit Finder"
  workdir: "./workdir"
  executor: "slurm"
  search_method: "adaptive"
  repetitions: 1

vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4, 8]

  ppn:
    type: int
    sweep:
      mode: list
      values: [16]

  ntasks:
    type: int
    expr: "{{ nodes * ppn }}"

  matrix_size:
    type: int
    adaptive:
      initial: 1000
      factor: 2
      stop_when: "execution_time is not None and execution_time > 120"
      max_iterations: 12

  memory_per_task_mb:
    type: int
    expr: "{{ (matrix_size * matrix_size * 8 * 3) // (ntasks * 1024 * 1024) }}"

command:
  template: "dgemm_benchmark --size {{ matrix_size }} --np {{ ntasks }}"

scripts:
  - name: "dgemm"
    script_template: |
      #!/bin/bash
      #SBATCH --job-name=iops_{{ execution_id }}
      #SBATCH --nodes={{ nodes }}
      #SBATCH --ntasks={{ ntasks }}
      #SBATCH --ntasks-per-node={{ ppn }}
      #SBATCH --time=00:15:00
      #SBATCH --exclusive

      module load mpi blas
      mpirun {{ command.template }}

    parser:
      file: "{{ execution_dir }}/dgemm_result.json"
      metrics:
        - name: gflops
      parser_script: |
        import json
        def parse(file_path):
            with open(file_path) as f:
                data = json.load(f)
            return {"gflops": data["gflops"]}

output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
```

With 4 node counts and 1 ppn value, IOPS creates 4 probes. Each doubles `matrix_size` (1000, 2000, 4000, 8000, ...) until the computation takes longer than 2 minutes. More nodes handle larger matrices because the work is distributed across more processes.

## Constraints

- Only one adaptive variable per config
- Adaptive variables cannot appear in `exhaustive_vars` or `cache_exclude_vars`
- `benchmark.search_method` must be `"adaptive"` when an adaptive variable is defined (adaptive cannot be combined with `"bayesian"`, `"random"`, or `"exhaustive"` search methods)
- Adaptive probing cannot be used with SLURM [single-allocation mode](../single-allocation-mode) (`allocation.mode: "single"`), which pre-generates all tests upfront and leaves no feedback loop
- `factor` and `increment` require numeric types (`int` or `float`); `step_expr` works with any type
- Conditional variables (`when`) cannot reference the adaptive variable, because `when` conditions are evaluated during matrix generation before the adaptive value is known. Use only swept variables in `when` expressions.
- At most one escalating variable per config, and it requires an adaptive variable to extend. Escalating variables are subject to the same rules as adaptive ones: excluded from `exhaustive_vars`, `cache_exclude_vars`, and `when` expressions.

### Why only one adaptive variable?

A deliberate design choice that keeps the search well-defined and the results interpretable:

- **Search strategy.** One adaptive variable steps forward in one dimension until it hits a wall; with two moving independently, there is no obviously correct way to advance them.
- **Stop condition attribution.** With two adaptive variables moving at once, you cannot tell which one caused `stop_when` to trigger.
- **Result structure.** One adaptive variable yields a simple `last_value_before_stop` / `stop_value` pair per probe; two would require a 2D boundary, which is closer to what Bayesian optimization handles with a surrogate model.

If the two variables are **coupled**, meaning one should advance precisely when the other stalls, use an [escalating variable](#staircase-search-with-an-escalating-variable). That case is well defined because only one axis moves per step, which is what the objections above are really about.

If they are genuinely independent, sweep one and probe the other:

```yaml
vars:
  block_factor:
    type: int
    sweep: { mode: list, values: [32, 64, 128, 256] }   # sweep this one
  matrix_size:
    type: int
    adaptive:
      initial: 1000
      factor: 2
      stop_when: "exit_code != 0"    # probe this one per block_factor
```

This gives the threshold `matrix_size` for each `block_factor` value, testing every combination. Alternatively, run two separate adaptive configs (one per variable) for fully independent threshold searches.

### Adaptive vs Bayesian optimization

Adaptive probing and Bayesian optimization are separate search methods and cannot be used together in the same config:

- **Adaptive** probes a single dimension to find a threshold (e.g., "what is the largest matrix size before running out of memory?")
- **Bayesian** explores a multi-dimensional space to find an optimal combination (e.g., "which nodes/ppn/block_factor combo maximizes GFLOPS?")

A common two-step workflow is to run adaptive first to discover limits, then use those limits as sweep ranges for a Bayesian run:

```yaml
# Step 1: adaptive config discovers max matrix_size per node count
# Result: nodes=4 -> 8000, nodes=8 -> 16000, nodes=16 -> 32000

# Step 2: Bayesian run with sweep values informed by adaptive results
benchmark:
  search_method: "bayesian"
  bayesian_config: { objective_metric: "gflops", objective: "maximize", n_iterations: 30 }

vars:
  nodes: { type: int, sweep: { mode: list, values: [4, 8, 16] } }
  matrix_size: { type: int, sweep: { mode: list, values: [1000, 2000, 4000, 8000, 16000] } }
```

## Configuration Reference

### `adaptive`

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `initial` | Yes | | Starting value |
| `factor` | One of three | | Multiplicative step (next = previous * factor) |
| `increment` | One of three | | Additive step (next = previous + increment) |
| `step_expr` | One of three | | Jinja2 expression for custom progression |
| `stop_when` | Yes | | Python expression evaluated after each execution |
| `max_iterations` | No | No limit | Maximum number of values to test |
| `direction` | No | `"ascending"` | Expected progression: `"ascending"` or `"descending"` |

### `escalate`

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `values` | Yes | | Ordered values to escalate through when the adaptive probe would stop |
