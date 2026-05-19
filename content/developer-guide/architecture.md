---
title: "Architecture"
weight: 10
---

IOPS is a YAML-driven benchmark orchestration framework. This page gives you
the mental model you need to navigate the codebase in about five minutes.

## Data flow

```
YAML config file
      |
      v
iops/config/loader.py        <-- validates, resolves Jinja2, returns GenericBenchmarkConfig
      |
      v
iops/execution/matrix.py     <-- builds ExecutionInstance list from parameter combinations
      |
      v
iops/execution/planner.py    <-- orders and supplies instances (exhaustive / random / bayesian / adaptive)
      |
      v
iops/execution/runner.py     <-- orchestration loop: cache check, execute, write results
      |
      v
iops/execution/executors.py  <-- submit(test) + wait_and_collect(test)  [local | slurm]
      |
      v
iops/execution/parser.py     <-- runs user parse() function, extracts metrics
      |
      v
iops/results/writer.py       <-- appends one row per repetition to CSV / Parquet / SQLite
      |
      v
iops/reporting/              <-- iops report generates interactive HTML from the result file
```

For the full detail on what happens inside the runner loop, see the
[Execution Loop]({{< relref "execution-loop" >}}) page.

## Package map

| Package | Responsibility | Key file |
|---------|----------------|----------|
| `iops/config` | YAML schema definitions and loading/validation pipeline | `models.py` (dataclasses), `loader.py` (validation and Jinja2 resolution) |
| `iops/execution` | Everything that runs a test: matrix, planners, executors, cache, parser, constraints | `runner.py` (orchestration), `planner.py` (search strategies), `executors.py` (local/SLURM) |
| `iops/results` | Reading and writing execution results and metadata | `writer.py` (CSV/Parquet/SQLite append), `find.py` (execution listing), `watch.py` (live monitoring) |
| `iops/reporting` | HTML report generation from a completed run directory | `report_generator.py` |
| `iops/cache` | SQLite-backed result cache keyed on parameter hash | `execution_cache.py` |
| `iops/archive` | Portable `.tar.gz` archives of run directories with manifests and checksums | `core.py` |
| `iops/convert` | One-way conversion of JUBE XML configs to IOPS YAML | `jube_converter.py` |
| `iops/setup` | Interactive config template generator (`iops generate`) | `wizard.py` |
| `iops/main.py` | CLI entry point: argparse subcommands, dispatch to modules above | (single file) |
| `iops/logger.py` | `HasLogger` mixin used by planner, executor, runner, and cache | (single file) |

## Central data structure: `ExecutionInstance`

`ExecutionInstance` (defined in `iops/execution/matrix.py`) is the object that
flows through the entire pipeline. It carries the resolved variable values, the
rendered command, paths to the generated script and execution directory, the
parser configuration, and a `metadata` dict that executors and the runner
populate with timing, status, and metrics.

## Centralized validation

All YAML validation lives in `iops/config/loader.py`. No other module
re-validates things already checked there. The three entry points are
`validate_yaml_config()` (pre-flight on raw YAML, used by `iops check`),
`validate_generic_config()` (post-parse on the `GenericBenchmarkConfig`
object), and `load_generic_config()` which calls both and returns the
validated config.

## Registry pattern

Planners and executors both use a decorator-based registry so that new
implementations can be added without modifying dispatch logic:

```python
@BasePlanner.register("exhaustive")
class ExhaustivePlanner(BasePlanner): ...

# Instantiated by name from config
planner = BasePlanner.build(cfg)
```

The same pattern applies to `BaseExecutor` in `iops/execution/executors.py`.
See [Extension Points]({{< relref "extension-points" >}}) for how to add your own planner or executor.
