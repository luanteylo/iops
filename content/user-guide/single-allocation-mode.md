---
title: "Single-Allocation Mode"
---

> **Experimental Feature**
>
> Single-allocation mode is experimental. It may contain bugs or undergo breaking changes in future releases. Please report any issues you encounter.

Single-allocation mode runs all tests within a single SLURM allocation instead of submitting separate jobs for each test. This guide explains how to configure this mode.

---

## Table of Contents

1. [Overview](#overview)
2. [When to Use](#when-to-use)
3. [Basic Configuration](#basic-configuration)
4. [How It Works](#how-it-works)
5. [Running MPI Programs](#running-mpi-programs)


---

## Overview

By default, IOPS submits a separate SLURM job for each test (`per-test` mode). Single-allocation mode changes this behavior:

| Mode | How it works |
|------|--------------|
| `per-test` (default) | Each test = separate `sbatch` job |
| `single` | One allocation, all tests run sequentially in bash |

---

## When to Use

Single-allocation mode is useful when:

- **Job limits**: Your HPC system limits jobs per user
- **Queue wait times**: Avoid waiting in queue for each test
- **Many small tests**: Hundreds of short tests run more efficiently
- **Scheduler load**: Reduce load on the SLURM scheduler

> **Warning: Resource efficiency considerations**
>
> Single-allocation mode requires allocating resources for your **largest test**. When sweeping over variable resource counts (e.g., `nodes: [1, 2, 4, 8]`), smaller tests leave resources idle:
>
> - Allocate 8 nodes, run a 2-node test → 6 nodes idle
> - This increases core-hours consumed while resources sit unused
>
> **Best suited for:** Tests that all use the same (or similar) amount of resources.
>
> **Consider per-test mode** (`mode: "per-test"`) when tests have highly variable resource requirements and queue wait times are acceptable.

---

## Basic Configuration

```yaml
benchmark:
  executor: "slurm"
  slurm_options:
    allocation:
      mode: "single"
      test_timeout: 300  # Per-test timeout in seconds (default: 3600)
      allocation_script: |
        #SBATCH --nodes=8
        #SBATCH --time=02:00:00
        #SBATCH --partition=batch
        #SBATCH --account=myaccount
        #SBATCH --exclusive
```



The `allocation_script` contains your SBATCH directives and setup commands. IOPS generates a complete execution script (`__iops_kickoff.sh`) that includes:
- Shebang (`#!/bin/bash`)
- Your SBATCH directives
- `--job-name=iops_single_alloc` and output/error paths
- Your setup commands (module loads, environment variables)
- A `run_test()` dispatcher function that runs each test with timeout
- Sequential calls to `run_test` for each test

The job completes automatically when all tests finish.

---

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│  1. IOPS generates __iops_kickoff.sh with all tests         │
│     - Your SBATCH directives and setup commands             │
│     - run_test() function with timeout handling             │
│     - Sequential run_test calls for each test               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  2. IOPS submits __iops_kickoff.sh via sbatch               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  3. Tests run sequentially inside the allocation:           │
│     run_test "exec_0001/rep_001" "script.sh" ...            │
│     run_test "exec_0001/rep_002" "script.sh" ...            │
│     ...                                                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  4. Each test writes status to __iops_status.json:          │
│     RUNNING → SUCCEEDED / FAILED / TIMEOUT                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  5. IOPS runner monitors status files and collects results  │
└─────────────────────────────────────────────────────────────┘
```

## Running MPI Programs

In single-allocation mode, your script runs directly on the first allocated node. For MPI programs, you need to launch processes to other nodes using `srun` or `mpirun`.

### With PMI Support (Recommended)

If your MPI installation has SLURM PMI support, use `srun` directly in your script:

```yaml
script_template: |
  #!/bin/bash
  module load openmpi

  srun --nodes={{ nodes }} \
       --ntasks={{ nodes * ppn }} \
       {{ command.template }}
```

**How to check for PMI support**:
1. Run `srun --mpi=list` to see SLURM's supported PMI versions
2. Run `ompi_info | grep pmi` to see OpenMPI's PMI support
3. **Both must match**: If SLURM has `pmi2` but OpenMPI has `pmix3x`, they may not be compatible. Test with `srun --mpi=pmi2 --ntasks=2 hostname` inside an allocation.

#### Without PMI Support

Most HPC systems have OpenMPI compiled **without** SLURM PMI support. In this case, use `mpirun` instead.

**The problem:** Unlike `srun`, `mpirun` doesn't automatically limit processes to a subset of your allocation. If you allocate 8 nodes but a test only needs 2, `mpirun -np 8` will spread processes across all 8 nodes instead of concentrating them on 2.

**The solution:** Build an explicit host list to control which nodes mpirun uses:

```yaml
script_template: |
  #!/bin/bash
  module load openmpi

  # Get all nodes in the allocation
  ALLOC_NODES=$(scontrol show job $SLURM_JOB_ID | grep -oP 'NodeList=\K[^\s]+')

  # Build host list: node1:slots,node2:slots,...
  NODELIST=$(scontrol show hostnames $ALLOC_NODES \
             | head -n {{ nodes }} \
             | sed 's/$/:{{ ppn }}/' \
             | tr '\n' ',')
  NODELIST=${NODELIST%,}  # Remove trailing comma

  # Launch with explicit host list
  mpirun --host $NODELIST \
         -np {{ nodes * ppn }} \
         --map-by ppr:{{ ppn }}:node \
         --mca plm rsh \
         --oversubscribe \
         {{ command.template }}
```

**Key flags explained:**

| Flag | Purpose |
|------|---------|
| `--host $NODELIST` | Specify which nodes to use (format: `node1:slots,node2:slots`) |
| `-np N` | Total number of processes |
| `--map-by ppr:N:node` | Place N processes per node |
| `--mca plm rsh` | Use SSH to launch on remote nodes (bypasses SLURM) |
| `--oversubscribe` | Bypass slot detection (safe with `--exclusive`) |

