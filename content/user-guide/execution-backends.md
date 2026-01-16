---
title: "Execution Backends"
---

IOPS supports two execution backends for running benchmarks: local execution and SLURM cluster submission.

---

## Table of Contents

1. [Local Executor](#local-executor)
2. [SLURM Executor](#slurm-executor)
   - [Budget Control](#budget-control)
   - [Job Monitoring](#job-monitoring)
   - [Custom SLURM Commands](#custom-slurm-commands)
   - [Single-Allocation Mode](#single-allocation-mode)

---

## Local Executor

Runs benchmarks directly on your local machine using subprocesses.

```yaml
benchmark:
  executor: "local"
```

### Use Cases

- Development and testing
- Small experiments
- Single-node benchmarks
- Quick iterations

### Example Configuration

```yaml
benchmark:
  name: "Local Test"
  workdir: "./workdir"
  executor: "local"

scripts:
  - name: "benchmark"
    submit: "bash"
    script_template: |
      #!/bin/bash
      set -euo pipefail
      {{ command.template }}
```

## SLURM Executor

Submits jobs to a SLURM cluster with automatic resource management and monitoring.

```yaml
benchmark:
  executor: "slurm"
  max_core_hours: 1000
  cores_expr: "{{ nodes * processes_per_node }}"
```

### Use Cases

- Large-scale experiments
- Multi-node benchmarks
- HPC environments
- Resource-intensive workloads

### Example Configuration

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
    submit: "sbatch --parsable"
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

Prevent exceeding compute allocations with core-hours tracking:

```yaml
benchmark:
  max_core_hours: 1000  # Stop after 1000 core-hours
  cores_expr: "{{ nodes * processes_per_node }}"
```

From command line:

```bash
# Set budget limit
iops run config.yaml --max-core-hours 1000

# Estimate usage before running
iops run config.yaml --dry-run --time-estimate 300
iops run config.yaml -n --time-estimate 300
```

### Job Monitoring

IOPS automatically:

- Submits jobs via `sbatch`
- Monitors status with `squeue`
- Handles job failures gracefully
- Tracks resource usage

### Custom SLURM Commands

For systems with command wrappers or custom SLURM installations, you can customize the command templates used for job management. Commands are templates that support `{job_id}` placeholder for runtime substitution:

```yaml
benchmark:
  executor: "slurm"
  executor_options:
    commands:
      submit: "sbatch"                                      # Default submit command
      status: "squeue -j {job_id} --noheader --format=%T"  # Job status query template
      info: "scontrol show job {job_id}"                   # Job information template
      cancel: "scancel {job_id}"                           # Job cancellation template
    poll_interval: 30                                       # Status polling interval (seconds)
```

**Example with wrapper and custom flags**:

```yaml
benchmark:
  executor: "slurm"
  executor_options:
    commands:
      submit: "lrms-wrapper sbatch"
      status: "lrms-wrapper -r {job_id} --custom-format"   # Custom flags: -r instead of -j
      info: "lrms-wrapper info {job_id}"
      cancel: "lrms-wrapper kill {job_id}"
    poll_interval: 10                                       # Check status every 10 seconds
```

This allows IOPS to work with various SLURM configurations and wrapper systems commonly found in HPC environments. The `{job_id}` placeholder is replaced with the actual job ID at runtime, giving you complete control over command structure and flags.

**Notes**:
- The `submit` command specified in `executor_options` is a default. Individual scripts can override it via `scripts[].submit`.
- The `{job_id}` placeholder is required for status, info, and cancel commands.
- The `poll_interval` controls how often (in seconds) IOPS checks job status during execution. Default is 30 seconds.

### Single-Allocation Mode

By default, IOPS submits a separate SLURM job for each test (`per-test` mode). For scenarios where this creates too much scheduler overhead, you can run all tests within a single SLURM allocation:

```yaml
benchmark:
  executor: "slurm"
  executor_options:
    allocation:
      mode: "single"              # Run all tests in one allocation
      nodes: 8                    # Total nodes for the allocation
      time: "02:00:00"            # Total time limit
      partition: "batch"          # Optional
      account: "myaccount"        # Optional
```

#### When to Use Single-Allocation Mode

- **Job limits**: HPC systems that limit the number of jobs per user
- **Queue wait times**: Avoid waiting in queue for each individual test
- **Many small tests**: Running hundreds of short tests more efficiently
- **Scheduler load**: Reduce load on the SLURM scheduler

#### How It Works

1. IOPS collects all tests from the planner (respecting cache)
2. Generates a wrapper script (`__iops_allocation_wrapper.sh`) containing all tests
3. Submits ONE `sbatch` job for the entire allocation
4. Tests run sequentially within the allocation
5. Exit codes are tracked and results are collected after completion

#### Full Configuration

```yaml
benchmark:
  executor: "slurm"
  executor_options:
    poll_interval: 30
    allocation:
      mode: "single"                    # "single" or "per-test" (default)
      nodes: 8                          # Required: nodes for allocation
      ntasks_per_node: 4                # Optional: tasks per node
      time: "02:00:00"                  # Required: time limit (HH:MM:SS or D-HH:MM:SS)
      partition: "batch"                # Optional: SLURM partition
      account: "myaccount"              # Optional: SLURM account
      extra_sbatch: |                   # Optional: additional directives
        #SBATCH --exclusive
        #SBATCH --constraint=ib
      srun_options: "--nodes={{ nodes }} --ntasks-per-node={{ ppn }}"  # Optional
```

#### srun_options

The `srun_options` field is a Jinja2 template that controls how each test is launched within the allocation:

- **If provided**: Each test runs with `srun <options> bash script.sh`
- **If omitted**: Each test runs with `bash script.sh` (suitable when tests manage their own `srun`)

The template has access to all variables from your configuration:

```yaml
# Example: Each test gets its own subset of nodes
srun_options: "--nodes={{ nodes }} --ntasks={{ nodes * ppn }}"
```

#### Important Notes

- **Script SBATCH directives are ignored**: In single-allocation mode, the allocation wrapper controls all resources. Any `#SBATCH` directives in your `script_template` are ignored.
- **Sequential execution**: Tests run one after another within the allocation, not in parallel.
- **Stdout/stderr capture**: Each test's output is still redirected to its own `execution_dir/stdout` and `execution_dir/stderr`.
- **Caching works normally**: Cached tests are skipped and not included in the allocation.
- **Folder structure unchanged**: The same `exec_XXXX/repetition_YYY` structure is used.

