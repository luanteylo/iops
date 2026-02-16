# IOPS Adaptive Variable — Development Tasks

**Feature**: Dynamic search exploration via a new `adaptive` variable type.
**Branch**: `feature/adaptive-variable`

---

## Task 1 — Data Model: `AdaptiveConfig` and `VarConfig` update

**Assignee**:
**Files**: `iops/config/models.py`

Add a new `AdaptiveConfig` dataclass and extend `VarConfig` to support the `adaptive` field alongside `sweep` and `expr`.

### What to do

- [ ] Create the `AdaptiveConfig` dataclass with fields:
  - `initial: Any` — starting value (required)
  - `factor: Optional[float]` — multiplicative step (`next = previous * factor`)
  - `increment: Optional[float]` — additive step (`next = previous + increment`)
  - `step_expr: Optional[str]` — Jinja2 expression for custom progression (has access to `previous`, `iteration`)
  - `stop_when: str` — expression evaluated after each execution (required, see below)
  - `max_iterations: Optional[int]` — safety limit, default `None` (no limit)
  - `direction: str` — `"ascending"` (default) or `"descending"`, controls progression order
- [ ] Add `adaptive: Optional[AdaptiveConfig] = None` to `VarConfig` (line ~258)
- [ ] Add `"adaptive"` to `ALLOWED_VAR_KEYS` in `loader.py` (line ~77)

### `stop_when` expression context

The `stop_when` expression is evaluated after each execution. It has access to:

| Variable         | Type   | Description                                 |
|------------------|--------|---------------------------------------------|
| `exit_code`      | int    | Process return code (`__returncode`)         |
| `status`         | str    | Executor status (`SUCCEEDED`, `FAILED`, ...) |
| `metrics`        | dict   | Parsed metrics dict (if parsing succeeded)   |
| `execution_time` | float  | Wall clock time in seconds                   |
| `previous`       | Any    | Current parameter value that was tested      |
| `iteration`      | int    | Current iteration number (0-based)           |

**Examples**:
```yaml
stop_when: "exit_code != 0"                    # stop on failure
stop_when: "status == 'FAILED'"                # stop on failure (alternative)
stop_when: "metrics['throughput'] < 100"        # stop when metric drops
stop_when: "metrics['error_rate'] > 0.05"       # stop when error rate exceeds 5%
stop_when: "execution_time > 3600"              # stop if execution takes > 1h
```

### Notes

- Exactly one of `factor`, `increment`, or `step_expr` must be provided (mutual exclusivity).
- `step_expr` is a Jinja2 expression that renders to the next value. Available context: `previous`, `iteration`.

---

## Task 2 — Config Validation for Adaptive Variables

**Assignee**:
**Files**: `iops/config/loader.py`

Extend the config loader to parse, validate, and enforce rules for the new `adaptive` configuration.

### What to do

- [ ] Add `ALLOWED_ADAPTIVE_KEYS = {"initial", "factor", "increment", "step_expr", "stop_when", "max_iterations", "direction"}` alongside the other `ALLOWED_*_KEYS` sets (~line 54-113)
- [ ] In `_parse_to_config()` (~line 939-976, vars parsing block): parse the `adaptive` dict into an `AdaptiveConfig` object, similar to how `sweep` is parsed into `SweepConfig`
- [ ] In `validate_generic_config()` (~line 1597-1671): change the `sweep XOR expr` check to `sweep XOR expr XOR adaptive` — exactly one of the three must be set
- [ ] Add adaptive-specific validation rules:
  - `initial` is required
  - `stop_when` is required
  - Exactly one of `factor`, `increment`, `step_expr` must be set
  - `factor` must not be 0; if `direction` is `ascending`, `factor > 1` or `increment > 0`
  - `direction` must be `"ascending"` or `"descending"` (if provided)
  - `max_iterations` must be a positive integer (if provided)
  - `stop_when` and `step_expr` must be valid Jinja2 (use existing `_validate_jinja_template()`)
  - Variable `type` must be numeric (`int` or `float`) when using `factor` or `increment`
- [ ] Validate that an adaptive variable is **not** referenced in `exhaustive_vars` or `cache_exclude_vars`

### Notes

- Follow the existing validation pattern — all checks go in `loader.py`, nowhere else.
- Error messages should be clear: `"var 'problem_size' has 'adaptive' but also has 'sweep'; only one is allowed"`.

---

## Task 3 — Extract Instance Creation Helper from `matrix.py`

**Assignee**:
**Files**: `iops/execution/matrix.py`

The current `build_execution_matrix()` creates `ExecutionInstance` objects inline during Cartesian product iteration. The adaptive planner needs to create single instances on-the-fly. Extract the instance construction into a reusable function.

### What to do

- [ ] Extract a new function from the instance creation block inside `build_execution_matrix()`:
  ```python
  def create_execution_instance(
      cfg: GenericBenchmarkConfig,
      base_vars: Dict[str, Any],
      execution_id: int,
      search_var_names: List[str],
      exhaustive_var_names: List[str],
  ) -> ExecutionInstance:
      """Create a single ExecutionInstance from a set of base variable values."""
  ```
- [ ] Refactor `build_execution_matrix()` to call `create_execution_instance()` internally (no behavior change)
- [ ] Verify all existing tests still pass after the refactor

### Notes

- This is a pure refactoring task — no new functionality, no behavior change.
- The new function will be imported by the `AdaptivePlanner` in Task 4.

---

## Task 4 — Implement `AdaptivePlanner`

**Assignee**:
**Files**: `iops/execution/planner.py`

Implement the core adaptive search planner. This is the main logic of the feature.

### What to do

- [ ] Create `AdaptivePlanner` class registered as `"adaptive"` using the existing registry pattern
- [ ] Constructor: identify adaptive variables and swept variables from config. Build the Cartesian product of **non-adaptive swept variables only** (the "static matrix"). For each combination, maintain an independent probe state.
- [ ] Implement `next_test()`:
  1. Pick the next static combination (or continue current one)
  2. For the current static combination, get the current adaptive variable value from the probe state
  3. Call `create_execution_instance()` (from Task 3) to build the `ExecutionInstance` with merged variables (static combo + current adaptive value)
  4. Return the instance (handle repetitions as normal)
- [ ] Implement `record_completed_test()`:
  1. Build the `stop_when` evaluation context from the completed test:
     - `exit_code` from `test.metadata["__returncode"]`
     - `status` from `test.metadata["__executor_status"]`
     - `metrics` from `test.metadata.get("metrics", {})`
     - `execution_time` from `test.metadata` timestamps
     - `previous` = current adaptive value
     - `iteration` = current iteration index
  2. Evaluate `stop_when` expression. If `True`: mark this probe as finished, record `found_value` (last value where condition was NOT met) and `failed_value` (current value)
  3. If `False` and `max_iterations` not reached: compute next adaptive value using `factor`/`increment`/`step_expr`, advance the probe
  4. If `max_iterations` reached: mark probe finished with `stop_reason: "max_iterations"`
- [ ] Handle the case where **all repetitions** for an adaptive value must complete before evaluating `stop_when`. Aggregate across repetitions (e.g., stop if **any** repetition triggers the condition, or if **all** do — start with "any").
- [ ] Store probe results per static combination:
  ```python
  @dataclass
  class ProbeResult:
      found_value: Any        # last successful value
      failed_value: Any       # first value that triggered stop (or None)
      iterations: int         # number of probes performed
      stop_reason: str        # "condition_met" | "max_iterations" | "all_succeeded"
  ```

### Interaction with swept variables

When the config has both adaptive and swept variables:
```yaml
vars:
  nodes:
    type: int
    sweep: {mode: list, values: [1, 2, 4]}
  problem_size:
    type: int
    adaptive: {initial: 1000, factor: 2, stop_when: "exit_code != 0"}
```
The planner runs a **nested probe**: for each `nodes` value (1, 2, 4), it probes `problem_size` independently. The found threshold may differ per `nodes` value.

### Notes

- Only **one adaptive variable** is supported per config (validate this in Task 2).
- The planner must handle the `direction` field: `ascending` means values grow, `descending` means values shrink.
- `step_expr` uses Jinja2: render with `{"previous": current_value, "iteration": i}` context.

---

## Task 5 — Auto-select `AdaptivePlanner` in Runner

**Assignee**:
**Files**: `iops/execution/runner.py`, `iops/config/loader.py`

When the config contains an adaptive variable, the planner should automatically be `AdaptivePlanner`, regardless of `search_method`.

### What to do

- [ ] In `IOPSRunner.__init__()` (~line 38-93): before building the planner, check if any variable in `cfg.vars` has `adaptive` set. If so, override `cfg.benchmark.search_method` to `"adaptive"` (or build the planner directly).
- [ ] Alternative approach: handle this in `validate_generic_config()` — if adaptive vars exist and `search_method` is not `"adaptive"`, emit a warning and auto-correct, or raise an error if `search_method` is `"bayesian"` (incompatible).
- [ ] Add `"adaptive"` to the list of valid `search_method` values in loader validation (~line where `search_method` is checked).

### Notes

- Decide on approach: auto-override silently, warn, or error. Recommended: warn and auto-override. Example: `"Config contains adaptive variable 'problem_size'; overriding search_method to 'adaptive'"`.

---

## Task 6 — Store Exit Code in Metadata

**Assignee**:
**Files**: `iops/execution/executors.py`

The `stop_when` expression needs access to `exit_code`. Currently, `LocalExecutor` stores `__returncode` (~line 496) but this should be consistently available across all executors.

### What to do

- [ ] Verify `LocalExecutor` stores `test.metadata["__returncode"]` (already done, line 496)
- [ ] For `SlurmExecutor`: extract the exit code from SLURM job accounting (`sacct`) and store it as `test.metadata["__returncode"]`. Currently, SLURM only stores status strings. Check the `_map_slurm_state()` method (~line 957) — the exit code is available from `sacct -o ExitCode`.
- [ ] Ensure `__returncode` defaults to `None` if unavailable (not `KeyError`)
- [ ] Document the `__returncode` metadata field in the executor base class docstring

### Notes

- For SLURM, the return code format from `sacct` is `exitcode:signal` (e.g., `0:0`, `1:0`, `9:9`). Parse the first number.
- If `sacct` data is unavailable, set `__returncode = None` and let `stop_when` handle it gracefully.

---

## Task 7 — Adaptive Results Reporting

**Assignee**:
**Files**: `iops/execution/runner.py`, `iops/results/writer.py`

After all probes complete, report the adaptive search results.

### What to do

- [ ] At the end of the run, collect `ProbeResult` objects from the `AdaptivePlanner`
- [ ] Write a summary to the run log:
  ```
  Adaptive probing results for 'problem_size':
    nodes=1: found=8000, failed=16000, iterations=5, stop_reason=condition_met
    nodes=2: found=16000, failed=32000, iterations=6, stop_reason=condition_met
    nodes=4: found=32000, iterations=20, stop_reason=max_iterations
  ```
- [ ] Include probe results in `__iops_run_metadata.json` under a new `"adaptive_results"` key:
  ```json
  {
    "adaptive_results": {
      "problem_size": {
        "nodes=1": {"found_value": 8000, "failed_value": 16000, "iterations": 5, "stop_reason": "condition_met"},
        "nodes=2": {"found_value": 16000, "failed_value": 32000, "iterations": 6, "stop_reason": "condition_met"}
      }
    }
  }
  ```
- [ ] Each individual execution still gets written to the output sink (CSV/Parquet/SQLite) as normal — adaptive probing doesn't change per-execution result storage

### Notes

- The `found_value` is the **last value where `stop_when` was `False`** (i.e., the last "good" value).
- If the probe never triggers `stop_when`, `failed_value` is `None` and `stop_reason` is `"all_succeeded"` or `"max_iterations"`.

---

## Task 8 — Caching Support for Adaptive Probing

**Assignee**:
**Files**: `iops/execution/runner.py`

Ensure the existing cache mechanism works correctly with adaptive probing.

### What to do

- [ ] Verify that cached results still trigger `stop_when` evaluation. When a probe value hits cache, the `record_completed_test()` path must still be called with the cached metadata (including `__returncode`, `metrics`, `__executor_status`).
- [ ] Check that `__returncode` is stored/restored by the cache (file: `iops/execution/cache.py`). If not, add it to the cached metadata.
- [ ] Ensure the probe sequence is deterministic: same `initial` + `factor`/`increment` + cache results produce the same found/failed values.
- [ ] Add a test: run an adaptive probe, run it again with `--use-cache`, verify same results and that all executions were cache hits.

### Notes

- The runner already calls `record_completed_test()` for cached results (~line 1525 area). Just verify the metadata is complete enough for `stop_when` evaluation.

---

## Task 9 — Unit Tests

**Assignee**:
**Files**: `tests/test_adaptive.py` (new file)

### What to do

- [ ] **Config parsing**: valid adaptive config parses correctly into `AdaptiveConfig`
- [ ] **Validation — mutual exclusivity**: var with both `sweep` and `adaptive` raises error; var with both `expr` and `adaptive` raises error
- [ ] **Validation — step exclusivity**: `factor` + `increment` together raises error; none of the three raises error
- [ ] **Validation — required fields**: missing `initial` or `stop_when` raises error
- [ ] **AdaptivePlanner — basic probe**: mock executor, verify probe sequence 1000 -> 2000 -> 4000, stop on simulated failure
- [ ] **AdaptivePlanner — increment mode**: initial=100, increment=50 produces 100, 150, 200, ...
- [ ] **AdaptivePlanner — step_expr**: `"{{ previous * 2 + 100 }}"` produces correct sequence
- [ ] **AdaptivePlanner — max_iterations**: probe stops after N iterations even if stop_when never triggers
- [ ] **AdaptivePlanner — metric-based stop**: `stop_when: "metrics['throughput'] < 100"` stops when metric drops
- [ ] **AdaptivePlanner — with swept vars**: verify independent probing per swept combination
- [ ] **AdaptivePlanner — descending direction**: probe goes from high to low
- [ ] **Probe results**: verify `found_value`, `failed_value`, `iterations`, `stop_reason` correctness
- [ ] **Integration test**: end-to-end with `LocalExecutor` (use a trivial script that fails above a threshold)

---

## Task 10 — Documentation

**Assignee**:
**Files**: `CHANGELOG.md`, Hugo website, `CLAUDE.md`

### What to do

- [ ] Add `adaptive` variable type to `CLAUDE.md` — YAML schema section, `VarConfig` fields
- [ ] Add changelog entry under the next version section
- [ ] Create Hugo docs page explaining the adaptive variable with examples:
  - Finding maximum problem size before OOM
  - Finding performance degradation threshold using metric-based stop
  - Weak scaling with probing until failure
- [ ] Update the `iops generate` interactive wizard if it supports variable type selection

---

## Dependency Graph

```
Task 1 (models) ─────┐
                      ├──> Task 4 (planner) ──> Task 5 (runner integration)
Task 2 (validation) ──┤                              │
                      │                               ├──> Task 7 (reporting)
Task 3 (refactor) ────┘                               │
                                                      ├──> Task 8 (caching)
Task 6 (exit code) ───────────────────────────────────┘

Task 9 (tests) ──── depends on Tasks 1-6
Task 10 (docs) ──── depends on Tasks 1-7
```

Tasks 1, 2, 3, and 6 can start in parallel. Task 4 requires 1+2+3. Tasks 5, 7, 8 require Task 4. Tests and docs come last.
