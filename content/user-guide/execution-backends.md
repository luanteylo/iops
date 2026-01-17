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

This allows IOPS to work with various SLURM configurations and wrapper systems commonly found in HPC environments. The `{job_id}` placeholder is replaced with the actual job ID at runtime, giving you complete control over command structure and flags.

**Notes**:
- The `{job_id}` placeholder is required for status, info, and cancel commands.
- The `poll_interval` controls how often (in seconds) IOPS checks job status during execution. Default is 30 seconds.

### Single-Allocation Mode

By default, IOPS submits a separate SLURM job for each test (`per-test` mode). For scenarios where this creates too much scheduler overhead, you can run all tests within a single SLURM allocation.

```yaml
benchmark:
  executor: "slurm"
  slurm_options:
    allocation:
      mode: "single"
      allocation_script: |
        #SBATCH --nodes=8
        #SBATCH --time=02:00:00
        #SBATCH --partition=batch
        #SBATCH --account=myaccount
        #SBATCH --exclusive
```

#### When to Use

- **Job limits**: HPC systems that limit the number of jobs per user
- **Queue wait times**: Avoid waiting in queue for each individual test
- **Many small tests**: Running hundreds of short tests more efficiently
- **Scheduler load**: Reduce load on the SLURM scheduler

#### MPI Configuration

For MPI programs in single-allocation mode, use the `mpi:` block to automatically handle nodelist construction, mpirun flags, and environment variable passing:

```yaml
scripts:
  - name: "benchmark"
    mpi:
      nodes: "{{ nodes }}"
      ppn: "{{ ppn }}"
      pass_env:                     # Optional: defaults to [PATH, LD_LIBRARY_PATH]
        - LD_PRELOAD                # Add custom vars your script exports
        - MY_APP_CONFIG
    script_template: |
      #!/bin/bash
      module load openmpi
      export LD_PRELOAD=/path/to/lib.so
      {{ command.template }}
```

For detailed configuration, MPI setup, troubleshooting, and complete examples, see the dedicated **[Single-Allocation Mode Guide]({{< relref "single-allocation-mode" >}})**.

