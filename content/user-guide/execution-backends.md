---
title: "Execution Backends"
---

IOPS supports two execution backends for running benchmarks: local execution and SLURM cluster submission.

---

## Table of Contents

1. [Local Executor](#local-executor)
2. [Parallel Execution](#parallel-execution)
3. [SLURM Executor](#slurm-executor)
   - [Budget Control](#budget-control) → [dedicated guide](../budget-control)
   - [Job Monitoring](#job-monitoring)
   - [Custom SLURM Commands](#custom-slurm-commands)
   - [Single-Allocation Mode](#single-allocation-mode) → [dedicated guide](../single-allocation-mode)

---

## Local Executor

Runs benchmarks directly on your local machine using subprocesses. Suited for development, small experiments, single-node benchmarks, and quick iterations.

```yaml
benchmark:
  name: "Local Test"
  workdir: "./workdir"
  executor: "local"

scripts:
  - name: "benchmark"
    script_template: |
      #!/bin/bash
      set -euo pipefail
      {{ command.template }}
```

## Parallel Execution

By default, IOPS runs tests sequentially (one at a time). Run multiple tests concurrently by setting the `parallel` option:

```yaml
benchmark:
  parallel: 4  # Run up to 4 tests at the same time
```

Or from the command line: `iops run config.yaml --parallel 4`

The CLI flag overrides the YAML value.

Parallel execution works with both `local` and `slurm` executors. With the local executor, multiple subprocesses run simultaneously. With SLURM, multiple jobs are submitted and polled concurrently, reducing total wall-clock time when queue wait is short.

### Planner Compatibility

Not all search methods support full parallelism. IOPS automatically caps the effective degree based on the planner:

| Search Method | Max Parallelism | Reason |
|---|---|---|
| `exhaustive` | Unlimited | All tests are independent |
| `random` | Unlimited | All tests are independent |
| `bayesian` | 1 (sequential) | Optimizer needs results from each test to suggest the next |
| `adaptive` | Number of probes | Each probe (one per swept-variable combination) is independent, but tests within a probe are sequential |

When the requested degree exceeds what the planner supports, IOPS logs a warning and uses the planner's maximum.

### Limitations

- **Single-allocation mode** (`slurm_options.allocation.mode: "single"`) runs all tests in one SLURM job script and is incompatible with parallel execution. The `parallel` setting is ignored with a warning.
- **Budget tracking** remains accurate under parallel execution. Core-hours are accumulated atomically as tests complete.
- **Result ordering** in the output file may differ from sequential runs since tests complete in non-deterministic order.

---

## SLURM Executor

Submits jobs to a SLURM cluster with automatic resource management and monitoring. Suited for large-scale, multi-node, and resource-intensive experiments.

```yaml
benchmark:
  name: "SLURM Benchmark"
  workdir: "/scratch/$USER/benchmark"
  executor: "slurm"
  max_core_hours: 500
  cores_expr: "{{ nodes * ppn }}"

vars:
  nodes:
    type: int
    sweep: { mode: list, values: [2, 4, 8] }

  ppn:  # processes per node
    type: int
    expr: "16"

scripts:
  - name: "mpi_benchmark"
    script_template: |
      #!/bin/bash
      #SBATCH --job-name=bench_{{ execution_id }}
      #SBATCH --nodes={{ nodes }}
      #SBATCH --ntasks-per-node={{ ppn }}
      #SBATCH --time=01:00:00
      #SBATCH --output={{ execution_dir }}/stdout
      #SBATCH --error={{ execution_dir }}/stderr

      module load openmpi
      {{ command.template }}
```

### Budget Control

Track core-hours consumption and stop execution when a budget limit is reached:

```yaml
benchmark:
  max_core_hours: 1000  # Stop after 1000 core-hours
  cores_expr: "{{ nodes * processes_per_node }}"
```

Or from command line: `iops run config.yaml --max-core-hours 1000`

For detailed configuration, accuracy considerations, and cache interaction, see the **[Budget Control](../budget-control)** guide.

### Job Monitoring

IOPS automatically submits jobs via `sbatch`, monitors status with `squeue`, handles job failures gracefully, and tracks resource usage.

### Custom SLURM Commands

For systems with command wrappers or custom SLURM installations, you can customize the command templates used for job management. Commands are templates that support a `{job_id}` placeholder, replaced with the actual job ID at runtime:

```yaml
benchmark:
  executor: "slurm"
  slurm_options:
    commands:
      submit: "sbatch"                                      # Submit command
      status: "squeue -j {job_id} --noheader --format=%T"  # Job status query template
      info: "scontrol show job {job_id}"                   # Job information template
      cancel: "scancel {job_id}"                           # Job cancellation template
    poll_interval: 30                                       # Status polling interval (seconds)
```

**Example with wrapper and custom flags**:

```yaml
benchmark:
  executor: "slurm"
  slurm_options:
    commands:
      submit: "lrms-wrapper sbatch"
      status: "lrms-wrapper -r {job_id} --custom-format"   # Custom flags: -r instead of -j
      info: "lrms-wrapper info {job_id}"
      cancel: "lrms-wrapper kill {job_id}"
    poll_interval: 10                                       # Check status every 10 seconds
```

**Notes**:
- The `{job_id}` placeholder is required for status, info, and cancel commands.
- The `poll_interval` controls how often (in seconds) IOPS checks job status during execution. Default is 30 seconds.

### Single-Allocation Mode

By default, IOPS submits a separate SLURM job for each test (`per-test` mode). When this creates too much scheduler overhead (job limits, long queue waits, many small tests), set `slurm_options.allocation.mode: "single"` to run all tests within one SLURM allocation.

See the **[Single-Allocation Mode](../single-allocation-mode)** guide for configuration, search method restrictions, MPI setup, and complete examples.
