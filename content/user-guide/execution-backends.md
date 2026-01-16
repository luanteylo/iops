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
      mode: "single"
      allocation_script: |
        #SBATCH --nodes=8
        #SBATCH --time=02:00:00
        #SBATCH --partition=batch
        #SBATCH --account=myaccount
        #SBATCH --exclusive
```

#### When to Use Single-Allocation Mode

- **Job limits**: HPC systems that limit the number of jobs per user
- **Queue wait times**: Avoid waiting in queue for each individual test
- **Many small tests**: Running hundreds of short tests more efficiently
- **Scheduler load**: Reduce load on the SLURM scheduler

#### How It Works

1. IOPS writes your `allocation_script` to `__iops_allocation.sh`, injecting:
   - Shebang (`#!/bin/bash`) if not provided
   - `--job-name=iops_allocation`
   - `--output` and `--error` paths to `workdir/logs/`
   - A sleep command to keep the allocation alive
2. IOPS submits the allocation via `sbatch` and waits for it to start
3. Tests run via `srun --jobid=<alloc_id> --overlap bash script.sh`
4. When all tests complete, IOPS cancels the allocation

#### Script Requirements

Your `script_template` must be compatible with running via `srun`:

**1. No SBATCH directives needed**

```yaml
# In single-allocation mode, SBATCH directives in scripts are IGNORED
# The allocation_script controls all resources
script_template: |
  #!/bin/bash
  module load mpi
  mpirun {{ command.template }}
```

**2. MPI programs work automatically**

SLURM sets environment variables (`SLURM_JOB_ID`, `SLURM_NODELIST`, etc.) that `mpirun`/`mpiexec` detect:

```yaml
script_template: |
  #!/bin/bash
  module load openmpi
  # mpirun automatically uses SLURM's allocation
  mpirun -np {{ ntasks }} ./my_benchmark
```

**3. Load modules in the script**

Modules must be loaded in the script since `srun` starts a fresh shell:

```yaml
script_template: |
  #!/bin/bash
  module purge
  module load gcc/12.2 openmpi/4.1 ior/3.3

  mpirun {{ command.template }}
```

**4. SLURM environment variables are available**

Scripts have access to all SLURM variables from the allocation:

| Variable | Description |
|----------|-------------|
| `SLURM_JOB_ID` | Allocation job ID |
| `SLURM_NODELIST` | List of allocated nodes |
| `SLURM_JOB_NUM_NODES` | Number of nodes |
| `SLURM_NTASKS` | Total tasks (if set in allocation) |

#### Configuration Reference

```yaml
benchmark:
  executor: "slurm"
  executor_options:
    poll_interval: 30                   # Status polling interval (seconds)
    allocation:
      mode: "single"                    # "single" or "per-test" (default)
      allocation_script: |              # Required when mode="single"
        #SBATCH --nodes=8
        #SBATCH --time=02:00:00
        #SBATCH --partition=batch
        #SBATCH --account=myaccount
        #SBATCH --exclusive
        #SBATCH --constraint=ib
```

#### Important Notes

- **Script SBATCH directives are ignored**: The `allocation_script` controls all resources
- **Sequential execution**: Tests run one after another, not in parallel
- **Stdout/stderr capture**: Each test's output goes to its own `execution_dir/stdout` and `stderr`
- **Caching works normally**: Cached tests are skipped
- **Folder structure unchanged**: Same `exec_XXXX/repetition_YYY` structure

