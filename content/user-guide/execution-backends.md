---
title: "Execution Backends"
---


IOPS supports two execution backends for running benchmarks: local execution and SLURM cluster submission.

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
  estimated_time_seconds: 300  # For dry-run estimates
```

From command line:

```bash
# Set budget limit
iops config.yaml --max-core-hours 1000

# Estimate usage before running
iops config.yaml --dry-run --estimated-time 300
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

## Comparison

| Feature | Local | SLURM |
|---------|-------|-------|
| **Setup** | Simple | Requires cluster access |
| **Parallelism** | Limited | High |
| **Resource Management** | Manual | Automatic |
| **Monitoring** | Direct | Via scheduler |
| **Budget Tracking** | No | Yes |

## Next Steps

- Learn about [Configuration](configuration.md)
- Understand [Result Caching](caching.md)
- See [SLURM examples](../examples/slurm.md)
