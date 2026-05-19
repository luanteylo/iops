---
title: "Execution Loop"
weight: 30
---

This page documents the IOPS execution loop architecture, including how the Runner, Planner, and Executor components work together to orchestrate benchmark execution.

## Overview

The execution loop follows a **pull-based** design where the Runner requests tests from the Planner and delegates execution to the Executor:

```
┌─────────────────────────────────────────────────────────────────┐
│                         IOPSRunner                              │
│                                                                 │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐     │
│  │   Planner   │─────►│   Runner    │─────►│  Executor   │     │
│  │             │      │   Loop      │      │             │     │
│  │ next_test() │      │             │      │ submit()    │     │
│  │             │◄─────│             │◄─────│ wait_and_   │     │
│  │ record_     │      │             │      │ collect()   │     │
│  │ completed() │      │             │      │             │     │
│  └─────────────┘      └─────────────┘      └─────────────┘     │
│         │                    │                    │             │
│         ▼                    ▼                    ▼             │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐     │
│  │   Matrix    │      │   Cache     │      │   Parser    │     │
│  │  Builder    │      │             │      │             │     │
│  └─────────────┘      └─────────────┘      └─────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

## Component Roles

| Component | Responsibility |
|-----------|----------------|
| **Runner** | Orchestrates the execution loop, manages cache, tracks budget, writes results |
| **Planner** | Generates test configurations, manages execution order, prepares artifacts |
| **Executor** | Submits jobs, waits for completion, collects output and metrics |
| **Matrix Builder** | Generates parameter combinations from config, applies constraints |
| **Cache** | Stores/retrieves results to skip redundant executions |
| **Parser** | Extracts metrics from benchmark output files |

## The Execution Loop

### Main Loop (`IOPSRunner.run()`)

Each iteration of the loop performs these steps for one test:

1. **Budget check.** If `accumulated_core_hours` has crossed `max_core_hours`, stop.
2. **Pull next test.** Call `self.planner.next_test()`. A `None` return means the plan is exhausted.
3. **Cache lookup.** If a cache is configured and `--use-cache` is set, look up the test by its parameter hash. A hit populates `test.metadata` from the cached row.
4. **Execute on miss.** Call `self.executor.submit(test)`, then `self.executor.wait_and_collect(test)`. The executor updates `test.metadata` in place with status, timing, and metrics.
5. **Persist.** Save the result row via `save_test_execution(test)` and write the per-execution status file.
6. **Notify planner.** Call `self.planner.record_completed_test(test)` so adaptive and Bayesian planners can update their state.

The real implementation also handles parallel execution (`_run_parallel`), kickoff mode, fail-fast, and signal handling. See `IOPSRunner.run()` and `_process_completed()` in `iops/execution/runner.py`.

### Sequence Diagram

```
Runner              Planner             Executor            Cache
  │                    │                    │                 │
  │  next_test()       │                    │                 │
  │───────────────────►│                    │                 │
  │                    │                    │                 │
  │  ExecutionInstance │                    │                 │
  │◄───────────────────│                    │                 │
  │                    │                    │                 │
  │  get_cached_result()                    │                 │
  │──────────────────────────────────────────────────────────►│
  │                    │                    │                 │
  │  (cache miss)      │                    │                 │
  │◄──────────────────────────────────────────────────────────│
  │                    │                    │                 │
  │  submit(test)      │                    │                 │
  │────────────────────────────────────────►│                 │
  │                    │                    │                 │
  │  wait_and_collect(test)                 │                 │
  │────────────────────────────────────────►│                 │
  │                    │                    │                 │
  │  test.metadata updated                  │                 │
  │◄────────────────────────────────────────│                 │
  │                    │                    │                 │
  │  store_result()    │                    │                 │
  │──────────────────────────────────────────────────────────►│
  │                    │                    │                 │
  │  record_completed_test()                │                 │
  │───────────────────►│                    │                 │
  │                    │                    │                 │
```

## Planner Architecture

### Base Planner

All planners inherit from `BasePlanner` and implement:

```python
class BasePlanner(ABC):
    @abstractmethod
    def next_test(self) -> Optional[ExecutionInstance]:
        """Return next test to execute, or None when done."""
        pass

    @abstractmethod
    def record_completed_test(self, test: ExecutionInstance) -> None:
        """Called after each test completes (for adaptive planners)."""
        pass

    def _prepare_execution_artifacts(self, test, repetition):
        """Create folders and scripts for execution."""
        pass
```

### Registry Pattern

Planners register themselves using a decorator:

```python
@BasePlanner.register("exhaustive")
class ExhaustivePlanner(BasePlanner):
    ...

@BasePlanner.register("random")
class RandomSamplingPlanner(BasePlanner):
    ...

@BasePlanner.register("bayesian")
class BayesianPlanner(BasePlanner):
    ...

# Dynamic instantiation from config
planner = BasePlanner.build(cfg)  # Uses cfg.benchmark.search_method
```

### Planner Types

| Planner | Strategy | `record_completed_test()` |
|---------|----------|---------------------------|
| **Exhaustive** | Tests all parameter combinations | No-op |
| **Random** | Random subset of parameter space | No-op |
| **Bayesian** | Optimization-guided search | Updates surrogate model |

### Execution Matrix

`BasePlanner._build_execution_matrix()` delegates to
`build_execution_matrix()` in `iops/execution/matrix.py`, which expands the
parameter sweeps into `ExecutionInstance` objects, evaluates derived
variables and constraints, and returns two lists: kept and skipped
instances. The planner shuffles the kept list (seeded by
`benchmark.random_seed`) and optionally creates all execution folders
upfront when `create_folders_upfront` is set.

### Repetition Interleaving

The `ExhaustivePlanner` does not run all repetitions of one test back to
back. Instead, on each `next_test()` call it picks a random test from the
set of tests that still have repetitions left, returns the next repetition
of that test, and removes it from the active pool once all repetitions are
done. This spreads transient system noise across the matrix instead of
concentrating it on one parameter combination. See `ExhaustivePlanner` in
`iops/execution/planner.py`.

## Executor Architecture

### Base Executor

All executors inherit from `BaseExecutor` and implement:

```python
class BaseExecutor(ABC):
    # Status constants
    STATUS_SUCCEEDED = "SUCCEEDED"
    STATUS_FAILED = "FAILED"
    STATUS_RUNNING = "RUNNING"
    STATUS_PENDING = "PENDING"
    STATUS_ERROR = "ERROR"

    @abstractmethod
    def submit(self, test: ExecutionInstance):
        """Submit/execute the job. Sets test.metadata["__jobid"]."""
        pass

    @abstractmethod
    def wait_and_collect(self, test: ExecutionInstance):
        """Wait for completion, parse metrics, collect sysinfo."""
        pass
```

### Registry Pattern

```python
@BaseExecutor.register("local")
class LocalExecutor(BaseExecutor):
    ...

@BaseExecutor.register("slurm")
class SlurmExecutor(BaseExecutor):
    ...

# Dynamic instantiation
executor = BaseExecutor.build(cfg)  # Uses cfg.benchmark.executor
```

### LocalExecutor

`submit()` runs the script synchronously with `subprocess.run(["bash", test.script_file])`, captures stdout/stderr to files in the execution directory, and sets `__executor_status` to `SUCCEEDED` or `FAILED` based on the return code. Because there is no queue, `__submission_time` and `__job_start` are both set to the same instant.

`wait_and_collect()` calls `parse_metrics_from_execution(test)` to run the user's parser script on succeeded tests, then collects sysinfo from the probe output.

### SlurmExecutor

`submit()` calls `sbatch` via subprocess, parses the returned job ID from stdout, and stores it in `test.metadata["__jobid"]`. The job ID is also added to `runner.submitted_job_ids` so the runner can cancel pending jobs on interrupt.

`wait_and_collect()` polls `sacct`/`squeue` until the job leaves an active state. The first time it sees the job in `RUNNING`, it records `__job_start` (so queue time can be separated from execution time). Final status is mapped from the SLURM state to `SUCCEEDED` or `FAILED`. Then it parses metrics and collects sysinfo the same way as `LocalExecutor`.

## ExecutionInstance

The central data structure passed through the loop:

```python
@dataclass
class ExecutionInstance:
    # Identity
    execution_id: int           # Unique ID within run
    repetition: int             # Current repetition (1-based)
    repetitions: int            # Total repetitions

    # Parameters
    vars: Dict[str, Any]        # Resolved variable values
    command: str                # Rendered command template

    # Paths
    script_file: Path           # Path to generated script
    execution_dir: Path         # Working directory
    post_script_file: Path      # Optional post-processing script

    # Parser config
    parser: ParserConfig        # Metrics extraction config

    # Metadata (populated during execution)
    metadata: Dict[str, Any]    # Status, timing, metrics, sysinfo
```

### Metadata Keys

| Key | Set By | Description |
|-----|--------|-------------|
| `__jobid` | Executor | Job identifier (e.g., SLURM job ID) |
| `__submission_time` | Executor | Time when job was submitted |
| `__job_start` | Executor | Time when job started running (after queue wait) |
| `__end` | Executor | Execution end timestamp |
| `__executor_status` | Executor | Final status (SUCCEEDED, FAILED, etc.) |
| `__error` | Executor | Error message if failed |
| `__returncode` | Executor | Script exit code |
| `__stdout_path` | Executor | Path to stdout file |
| `__stderr_path` | Executor | Path to stderr file |
| `__sysinfo` | Executor | System info from probe |
| `__cached` | Runner | True if result came from cache |
| `metrics` | Executor/Parser | Extracted metric values |

## Cache Integration

### Cache Flow

```
┌────────────────────────────────────────────────────────────┐
│                      Runner Loop                            │
│                                                             │
│   ┌─────────────────┐                                       │
│   │ get_cached_     │──── HIT ────► Use cached metrics      │
│   │ result()        │              Skip execution           │
│   └────────┬────────┘                                       │
│            │                                                │
│          MISS                                               │
│            │                                                │
│            ▼                                                │
│   ┌─────────────────┐                                       │
│   │ Execute test    │                                       │
│   └────────┬────────┘                                       │
│            │                                                │
│            ▼                                                │
│   ┌─────────────────┐                                       │
│   │ store_result()  │──── SUCCEEDED ────► Cache for later   │
│   └─────────────────┘                                       │
└────────────────────────────────────────────────────────────┘
```

### Cache Key

The cache key is derived from the parameter values (with any variables in
`cache_exclude_vars` removed) plus the repetition number. The exact hashing
is in `ExecutionCache` in `iops/cache/`.

## Budget Tracking

After each non-cached test, the runner computes `core_hours = cores * duration_hours`, where `cores` is evaluated from `benchmark.cores_expr` (e.g., `"nodes * ppn"`) against the test's variables, and `duration_hours` comes from `test.metadata["__sysinfo"]["duration_seconds"]`. The accumulated value is checked against `max_core_hours`, and when exceeded the loop stops on the next iteration. See `IOPSRunner._compute_core_hours()` and `_budget_exceeded_check()` in `iops/execution/runner.py`.

## Status File Writing

`IOPSRunner._write_status_file()` writes `__iops_status.json` into the
execution directory after each test, capturing status, error, end time,
cache flag, and duration. The file is gated on `probes.execution_index`
being enabled. This is the file consumed by `iops find` and `iops find
--watch`. See [Data Sources]({{< relref "data-sources" >}}) for the field-level mapping.

## Source Code References

| File | Purpose |
|------|---------|
| `iops/execution/runner.py` | IOPSRunner class, main execution loop |
| `iops/execution/planner.py` | BasePlanner, ExhaustivePlanner, BayesianPlanner |
| `iops/execution/executors.py` | BaseExecutor, LocalExecutor, SlurmExecutor |
| `iops/execution/matrix.py` | build_execution_matrix(), ExecutionInstance |
| `iops/execution/cache.py` | ExecutionCache class |
| `iops/execution/parser.py` | parse_metrics_from_execution() |
| `iops/results/writer.py` | save_test_execution() |

### Key Entry Points

| Function/Method | Location | Purpose |
|-----------------|----------|---------|
| `IOPSRunner.run()` | runner.py | Main execution loop |
| `IOPSRunner.run_dry()` | runner.py | Dry-run mode (no execution) |
| `BasePlanner.next_test()` | planner.py | Get next test to execute |
| `BasePlanner._prepare_execution_artifacts()` | planner.py | Create folders and scripts |
| `BaseExecutor.submit()` | executors.py | Submit/execute job |
| `BaseExecutor.wait_and_collect()` | executors.py | Wait and collect results |
| `build_execution_matrix()` | matrix.py | Generate parameter combinations |
