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

```python
def run(self):
    while True:
        # 1. Check budget
        if budget_exceeded:
            break

        # 2. Get next test from planner
        test = self.planner.next_test()
        if test is None:
            break  # No more tests

        # 3. Check cache
        if self.cache and self.use_cache_reads:
            cached_result = self.cache.get_cached_result(test.vars, test.repetition)
            if cached_result:
                # Use cached result, skip execution
                test.metadata.update(cached_result)
                test.metadata['__cached'] = True

        # 4. Execute if not cached
        if not used_cache:
            self._write_status_file(test, status="RUNNING")
            self.executor.submit(test)
            self.executor.wait_and_collect(test)

            # Store in cache if succeeded
            if succeeded:
                self.cache.store_result(...)

        # 5. Write status and results
        self._write_status_file(test)
        save_test_execution(test)

        # 6. Notify planner of completion
        self.planner.record_completed_test(test)
```

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

The planner builds an execution matrix from config:

```python
def _build_execution_matrix(self):
    # Build parameter combinations
    kept_instances, skipped_instances = build_execution_matrix(self.cfg)

    # Store skipped for reference
    self.skipped_matrix = skipped_instances

    # Shuffle for random execution order
    self.execution_matrix = self.random_sample(kept_instances)

    # Initialize folders upfront if configured
    if cfg.benchmark.create_folders_upfront:
        self._initialize_all_folders(kept_instances, skipped_instances)
```

### Repetition Interleaving

The ExhaustivePlanner uses random interleaving to avoid running all repetitions of one test before moving to the next:

```python
def next_test(self):
    # Randomly pick from active tests (those with remaining repetitions)
    idx = self.random.choice(self._active_indices)
    test = self.execution_matrix[idx]

    # Track which repetition this is
    rep_idx = self._next_rep_by_idx[idx]
    self._next_rep_by_idx[idx] += 1

    # Remove from active pool when all reps done
    if self._next_rep_by_idx[idx] >= self._total_reps_by_idx[idx]:
        self._active_indices.remove(idx)

    # Prepare artifacts for this repetition
    self._prepare_execution_artifacts(test, repetition=rep_idx + 1)

    return test
```

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

Runs benchmarks via subprocess:

```python
def submit(self, test):
    self._init_execution_metadata(test)

    now = timestamp
    test.metadata["__submission_time"] = now
    test.metadata["__job_start"] = now  # No queue for local
    result = subprocess.run(
        ["bash", str(test.script_file)],
        cwd=test.execution_dir,
        capture_output=True,
    )
    test.metadata["__end"] = timestamp

    # Write stdout/stderr to files
    stdout_path.write_text(result.stdout)
    stderr_path.write_text(result.stderr)

    # Set status based on return code
    if result.returncode != 0:
        test.metadata["__executor_status"] = self.STATUS_FAILED
    else:
        test.metadata["__executor_status"] = self.STATUS_SUCCEEDED

def wait_and_collect(self, test):
    # Parse metrics if succeeded
    if test.metadata["__executor_status"] == self.STATUS_SUCCEEDED:
        metrics = parse_metrics_from_execution(test)
        test.metadata["metrics"] = metrics

    # Collect system info from probe
    self._store_system_info(test)
```

### SlurmExecutor

Submits to SLURM and polls for completion:

```python
def submit(self, test):
    self._init_execution_metadata(test)

    # Submit via sbatch
    result = subprocess.run(submit_cmd, capture_output=True)
    job_id = parse_job_id(result.stdout)

    test.metadata["__jobid"] = job_id
    test.metadata["__submission_time"] = timestamp

    # Track for cleanup on interrupt
    if self.runner:
        self.runner.submitted_job_ids.add(job_id)

def wait_and_collect(self, test):
    job_id = test.metadata["__jobid"]

    # Poll until job leaves queue
    while True:
        state = get_job_state(job_id)
        if state == "RUNNING" and not test.metadata.get("__job_start"):
            test.metadata["__job_start"] = timestamp  # Job started running
        if state not in SLURM_ACTIVE_STATES:
            break
        time.sleep(poll_interval)

    test.metadata["__end"] = timestamp

    # Determine final status
    if state in SLURM_FAIL_STATES:
        test.metadata["__executor_status"] = self.STATUS_FAILED
    else:
        test.metadata["__executor_status"] = self.STATUS_SUCCEEDED

    # Parse metrics and collect sysinfo
    if succeeded:
        metrics = parse_metrics_from_execution(test)
        test.metadata["metrics"] = metrics

    self._store_system_info(test)
```

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

Results are cached by:
- Parameter values (excluding `cache_exclude_vars`)
- Repetition number

```python
cache_key = hash(
    frozenset({k: v for k, v in params.items() if k not in exclude_vars}.items()),
    repetition
)
```

## Budget Tracking

The runner tracks core-hour usage:

```python
# After each test
if not used_cache:
    cores = evaluate(cores_expr, test.vars)  # e.g., "nodes * ppn"
    duration_hours = test.metadata["__sysinfo"]["duration_seconds"] / 3600
    core_hours = cores * duration_hours

    self.accumulated_core_hours += core_hours

    if self.accumulated_core_hours >= self.max_core_hours:
        self.budget_exceeded = True
        break
```

## Status File Writing

The runner writes status files for monitoring:

```python
def _write_status_file(self, test, status=None):
    if not execution_index:  # From probes config
        return

    # Determine status
    if status is None:
        status = test.metadata.get("__executor_status", "UNKNOWN")

    # Get duration from sysinfo
    sysinfo = test.metadata.get("__sysinfo")
    duration = sysinfo.get("duration_seconds") if sysinfo else None

    status_data = {
        "status": status,
        "error": test.metadata.get("__error"),
        "end_time": test.metadata.get("__end"),
        "cached": test.metadata.get("__cached", False),
        "duration_seconds": duration,
    }

    # Write to repetition folder
    status_file = test.execution_dir / "__iops_status.json"
    status_file.write_text(json.dumps(status_data))
```

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
