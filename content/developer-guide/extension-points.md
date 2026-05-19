---
title: "Extension Points"
weight: 20
---

IOPS is designed so that its most common customization surfaces follow a
consistent pattern: define a class that inherits from an abstract base,
register it with a decorator, and IOPS picks it up by name from the config.
This page walks through each extension point with a minimal code skeleton.

## Planners

**What it is.** A planner decides the order in which parameter combinations
are tested. IOPS ships with four: `exhaustive`, `random`, `bayesian`, and
`adaptive`.

**Where the interface lives.** `iops/execution/planner.py`, class `BasePlanner`.

**Abstract methods to implement.**

```python
from iops.execution.planner import BasePlanner
from iops.execution.matrix import ExecutionInstance
from typing import Optional

@BasePlanner.register("myrandom")
class MyPlanner(BasePlanner):

    def next_test(self) -> Optional[ExecutionInstance]:
        """Return the next test, or None when the plan is exhausted."""
        ...

    def record_completed_test(self, test: ExecutionInstance) -> None:
        """Called after each test completes. No-op for non-adaptive planners."""
        ...
```

After registering, set `benchmark.search_method: myrandom` in your YAML and
IOPS will instantiate your planner via `BasePlanner.build(cfg)`.

`BasePlanner.__init__` receives the full `GenericBenchmarkConfig`. Call
`super().__init__(cfg)` to initialize the random seed and logger. For access
to the full execution matrix, look at how `ExhaustivePlanner` calls
`self._build_execution_matrix()` (defined on `BasePlanner`).

See the [Execution Loop]({{< relref "execution-loop" >}}) page for the detailed planner/runner interaction.

---

## Executors

**What it is.** An executor submits a prepared script and waits for
it to finish. IOPS ships with `local` (subprocess) and `slurm` (sbatch).

**Where the interface lives.** `iops/execution/executors.py`, class `BaseExecutor`.

**Abstract methods to implement.**

```python
from iops.execution.executors import BaseExecutor
from iops.execution.matrix import ExecutionInstance

@BaseExecutor.register("myenv")
class MyExecutor(BaseExecutor):

    def submit(self, test: ExecutionInstance) -> None:
        """Launch the job. Must set test.metadata["__jobid"] and
        test.metadata["__submission_time"]."""
        ...

    def wait_and_collect(self, test: ExecutionInstance) -> None:
        """Block until done, then populate status, timing, and metrics."""
        ...
```

Set `benchmark.executor: myenv` in your YAML. `BaseExecutor.build(cfg)` handles
the registry lookup.

Call `self._init_execution_metadata(test)` at the start of `submit()`: this
helper (on `BaseExecutor`) pre-populates the standard keys (`__jobid`,
`__executor_status`, `__submission_time`, `__job_start`, `__end`) with `None`
so downstream code can rely on them being present. Look at `LocalExecutor`
and `SlurmExecutor` in `iops/execution/executors.py` for working examples.

---

## Output sinks

**What it is.** A sink is where each test result row is written after
execution. The three built-in types are `csv`, `parquet`, and `sqlite`.

**Where the interface lives.** `iops/results/writer.py` (the write functions)
and `iops/config/models.py` (`OutputSinkConfig`).

Unlike planners and executors, output sinks do not use a registry. Adding a
new sink type requires:

1. Add the new type string to the `Literal` in `OutputSinkConfig.type`
   (`iops/config/models.py`).
2. Add a `_write_<type>()` function in `iops/results/writer.py` following the
   same signature as `_write_csv` and `_write_parquet`.
3. Add a matching `if typ == "<type>":` branch in `save_test_execution()`.
4. Update `validate_yaml_config()` in `iops/config/loader.py` if any new
   fields are required.

`build_output_row(test)` in `writer.py` produces the flat dictionary that all
sinks receive. You do not need to change that function for a new sink type.

---

## Parser scripts

**What it is.** A parser script is user-supplied Python that extracts metric
values from a benchmark output file. It is not a registered extension; it is
inline YAML.

**Where the interface lives.** `iops/execution/parser.py`,
`parse_metrics_from_execution()`.

A parser script defines a single function:

```python
def parse(file_path: str) -> dict:
    """Return a dict mapping metric names to numeric values."""
    ...
```

The script runs with execution context injected as globals: `vars`, `env`,
`os_env`, `execution_id`, `execution_dir`, `workdir`, `repetition`,
`repetitions`, `metrics`.

For full documentation and examples, see [Writing Parsers]({{< relref "/user-guide/writing-parsers" >}}).

---

## Probes

**What it is.** A probe is a bash script injected into the user's execution
script to collect data from compute nodes at runtime. IOPS ships with three
probes: the system snapshot, the resource sampler, and the GPU sampler.

**Where the code lives.** Probe templates are string constants in
`iops/execution/planner.py`. Injection is done by
`BasePlanner._inject_iops_scripts()`. There is no separate `probes/` package;
all probe logic lives in `planner.py`.

The probe architecture is built on a centralized bash exit handler. Every
probe registers a cleanup function with `_iops_register_exit`:

```bash
# In your probe script template:
_iops_my_probe() {
    # collect data into ${execution_dir}/__iops_mydata.json
}
_iops_register_exit "_iops_my_probe"
```

To add a probe:

1. Define a new bash template string constant in `planner.py` (follow the
   pattern of `SYSTEM_PROBE_TEMPLATE`).
2. Add a new field to `ProbesConfig` in `iops/config/models.py` and update
   `iops/config/loader.py` to parse it.
3. In `BasePlanner._inject_iops_scripts()`, write the template to a file in
   `exec_dir` and inject a `source` line into the user script when the new
   probe is enabled.
4. If the probe writes a file that the executor should read back, add
   collection logic in `BaseExecutor.wait_and_collect()` (see how
   `_collect_system_info()` handles `__iops_sysinfo.json`).

See the [Probe System]({{< relref "probe-system" >}}) page for the full exit handler architecture.

---

## Constraints

**What it is.** A constraint is a Python expression evaluated against each
parameter combination before execution. Violated combinations are skipped,
warned about, or turned into hard errors depending on `violation_policy`.

**Where the interface lives.** `iops/execution/constraints.py`,
`evaluate_constraint()`. Configuration model: `ConstraintConfig` in
`iops/config/models.py`.

Constraints are not a registry-based extension; they are pure data (a `rule`
string and a `violation_policy`). The evaluator runs them during matrix
construction in `iops/execution/matrix.py`.

To add support for new functions or variables inside constraint rules, extend
the `allowed_funcs` dict inside `evaluate_constraint()`. Currently available:
`min`, `max`, `abs`, `round`, `floor`, `ceil`, `int`, `float`, and all
user-defined variables plus `os_env`.
