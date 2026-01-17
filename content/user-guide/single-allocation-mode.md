---
title: "Single-Allocation Mode"
---

Single-allocation mode runs all tests within a single SLURM allocation instead of submitting separate jobs for each test. This guide explains how to configure and troubleshoot this mode.

---

## Table of Contents

1. [Overview](#overview)
2. [When to Use](#when-to-use)
3. [Basic Configuration](#basic-configuration)
4. [How It Works](#how-it-works)
5. [Running MPI Programs](#running-mpi-programs)
   - [With PMI Support](#with-pmi-support)
   - [Without PMI Support](#without-pmi-support)
6. [Variable Resources Per Test](#variable-resources-per-test)
7. [Troubleshooting](#troubleshooting)
8. [Complete Example](#complete-example)

---

## Overview

By default, IOPS submits a separate SLURM job for each test (`per-test` mode). Single-allocation mode changes this behavior:

| Mode | How it works |
|------|--------------|
| `per-test` (default) | Each test = separate `sbatch` job |
| `single` | One allocation, all tests run via `srun` |

---

## When to Use

Single-allocation mode is useful when:

- **Job limits**: Your HPC system limits jobs per user
- **Queue wait times**: Avoid waiting in queue for each test
- **Many small tests**: Hundreds of short tests run more efficiently
- **Scheduler load**: Reduce load on the SLURM scheduler

---

## Basic Configuration

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

The `allocation_script` contains your SBATCH directives. IOPS automatically adds:
- Shebang (`#!/bin/bash`)
- `--job-name=iops_allocation`
- `--output` and `--error` paths
- `sleep infinity` at the end to keep the allocation alive

The `sleep infinity` command prevents the allocation job from exiting immediately after starting. IOPS runs tests via `srun` into this sleeping allocation, and cancels it when all tests complete.

---

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│  1. IOPS creates __iops_allocation.sh from your directives  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  2. IOPS submits via sbatch, waits for allocation to start  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  3. For each test, IOPS runs:                               │
│     srun --jobid=<alloc_id> --overlap                       │
│          --nodes=1 --ntasks=1 bash script.sh                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  4. Your script runs on ONE node, launches MPI from there   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  5. When all tests complete, IOPS cancels the allocation    │
└─────────────────────────────────────────────────────────────┘
```

**Key point**: Your script runs on a single node. If you need multiple nodes for MPI, your script must handle that (see below).

---

## Running MPI Programs

IOPS provides two approaches for running MPI programs in single-allocation mode:

1. **Automatic MPI configuration** (Recommended): Use the `mpi:` block for simplified MPI launching
2. **Manual MPI configuration**: Handle MPI launching yourself in the script template

### Automatic MPI Configuration (Recommended)

The `mpi:` configuration block automatically handles:
- SLURM_NODEID check (only node 0 runs mpirun)
- NODELIST construction from SLURM_JOB_NODELIST
- mpirun flags (--oversubscribe, --mca plm rsh, etc.)
- Environment variable passing

**Before (manual, error-prone):**

```yaml
script_template: |
  #!/bin/bash
  module load openmpi
  if [ "$SLURM_NODEID" = "0" ]; then
    NODELIST=$(scontrol show hostnames $SLURM_JOB_NODELIST | head -n {{ nodes }} | sed 's/$/:{{ ppn }}/' | tr '\n' ',' | sed 's/,$//')
    mpirun --host $NODELIST -np {{ nodes * ppn }} --mca plm rsh --oversubscribe \
      -x LD_LIBRARY_PATH="$LD_LIBRARY_PATH" -x PATH="$PATH" \
      {{ command.template }}
  fi
```

**After (clean, automatic):**

```yaml
scripts:
  - name: "benchmark"
    mpi:
      nodes: "{{ nodes }}"
      ppn: "{{ ppn }}"
      pass_env: [LD_LIBRARY_PATH, PATH]
    script_template: |
      #!/bin/bash
      module load openmpi
      {{ command.template }}
```

#### MPI Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `launcher` | string | `"mpirun"` | MPI launcher - `"mpirun"` or `"srun"` |
| `nodes` | string/int | `"all"` | Number of nodes - `"{{ var }}"`, integer, or `"all"` |
| `ppn` | string/int | (required) | Processes per node - `"{{ var }}"` or integer |
| `extra_options` | list | `[]` | Additional launcher flags |

**Environment variable handling**: All environment variables from the script are **automatically** passed to MPI processes. Any variables you `export` in your script (including PATH, LD_LIBRARY_PATH, LD_PRELOAD, or custom variables like TOTO_*) are available on all remote nodes without needing to list them explicitly.

#### Nodes Resolution

| Value | Behavior |
|-------|----------|
| `"{{ var }}"` | Use variable, `head -n $value` |
| `4` (number) | Fixed, `head -n 4` |
| `"all"` | Full allocation, no `head` |
| *(omitted)* | Default to `"all"` |

#### Example with Extra Options

```yaml
scripts:
  - name: "benchmark"
    mpi:
      nodes: "{{ nodes }}"
      ppn: "{{ ppn }}"
      extra_options:
        - "--mca btl tcp,self"
        - "--mca mpi_show_mca_params all"
    script_template: |
      #!/bin/bash
      module load openmpi
      export OMP_NUM_THREADS=4  # Automatically passed to all MPI processes
      {{ command.template }}
```

#### Using srun Launcher

For systems with PMI support, use the `srun` launcher:

```yaml
scripts:
  - name: "benchmark"
    mpi:
      launcher: "srun"
      nodes: "{{ nodes }}"
      ppn: "{{ ppn }}"
    script_template: |
      #!/bin/bash
      module load openmpi
      {{ command.template }}
```

### Manual MPI Configuration

If you need full control over MPI launching, you can write the launch logic yourself.

#### With PMI Support

If your MPI installation has SLURM PMI support, use `srun` directly in your script:

```yaml
script_template: |
  #!/bin/bash
  module load openmpi

  srun --nodes={{ nodes }} \
       --ntasks={{ nodes * ppn }} \
       {{ command.template }}
```

**How to check for PMI support**: Run a simple MPI program with srun. If you see errors like "OPAL ERROR: Not initialized in file pmix" or "OMPI was not built with SLURM's PMI support", you don't have PMI support.

#### Without PMI Support

Most HPC systems have OpenMPI compiled **without** SLURM PMI support. In this case, use `mpirun` with explicit host selection:

```yaml
script_template: |
  #!/bin/bash
  module load openmpi

  # mpirun uses SLURM environment automatically
  mpirun -np {{ nodes * ppn }} {{ command.template }}
```

If this doesn't work (wrong number of nodes, wrong process distribution), see [Variable Resources Per Test](#variable-resources-per-test).

---

## Variable Resources Per Test

When sweeping over different node counts, you need to explicitly control which nodes mpirun uses.

### The Problem

Your allocation has 8 nodes, but tests use 1, 2, 4, or 8 nodes:

```yaml
benchmark:
  executor: "slurm"
  slurm_options:
    allocation:
      mode: "single"
      allocation_script: |
        #SBATCH --nodes=8           # Max nodes needed
        #SBATCH --time=04:00:00
        #SBATCH --exclusive

vars:
  nodes:
    type: int
    sweep: { mode: list, values: [1, 2, 4, 8] }

  ppn:  # processes per node
    type: int
    sweep: { mode: list, values: [4, 8, 16] }

command:
  template: "mpi_benchmark --size {{ nodes * ppn }}"
```

Without explicit control, mpirun might use all 8 nodes for every test.

### The Solution

Build a host list with slot counts and pass it to mpirun:

```yaml
script_template: |
  #!/bin/bash
  module load openmpi

  # Build host list: node1:slots,node2:slots,...
  # IMPORTANT: Inside srun, SLURM_JOB_NODELIST only shows the current step's node.
  # Query the full allocation's node list from the job record:
  ALLOC_NODES=$(scontrol show job $SLURM_JOB_ID | grep -oP 'NodeList=\K[^\s]+')
  NODELIST=$(scontrol show hostnames $ALLOC_NODES \
             | head -n {{ nodes }} \
             | sed 's/$/:{{ ppn }}/' \
             | tr '\n' ',')
  NODELIST=${NODELIST%,}  # Remove trailing comma

  # --mca plm rsh: Use SSH to launch processes on remote nodes
  # (bypasses SLURM's process launcher which requires PMI support)
  # --oversubscribe: Bypass SLURM's slot tracking (see note below)
  mpirun --host $NODELIST \
         -np {{ nodes * ppn }} \
         --map-by ppr:{{ ppn }}:node \
         --mca plm rsh \
         --oversubscribe \
         {{ command.template }}
```

**Why `--oversubscribe`?** When using `--exclusive` in your allocation, SLURM marks all node resources as "in use" by the allocation job. OpenMPI may still query SLURM for available slots and incorrectly report "not enough slots". The `--oversubscribe` flag tells mpirun to skip this check and trust your `--host` specification.

**Is it safe?** Yes, in single-allocation mode with `--exclusive`. You're not actually oversubscribing - you have exclusive access to the nodes. The flag simply bypasses the incorrect slot detection. As long as your configuration doesn't request more processes than available cores, there's no performance impact.

The host list format is `hostname:slots,hostname:slots,...`

```bash
# Example: 4 nodes, 8 processes per node
bora001:8,bora002:8,bora003:8,bora004:8
```

Without the `:slots` suffix, mpirun assumes 1 slot per host.

### Key mpirun Flags

| Flag | Purpose |
|------|---------|
| `--host $NODELIST` | Specify which nodes to use |
| `-np N` | Total number of processes |
| `--map-by ppr:N:node` | N processes per node |
| `--mca plm rsh` | Use SSH for launching (bypass SLURM) |
| `-x VAR=value` | Pass environment variable to processes |


### SLURM Variables in Scripts

| Variable | Description |
|----------|-------------|
| `SLURM_JOB_ID` | Allocation job ID |
| `SLURM_JOB_NODELIST` | **All nodes in allocation** |
| `SLURM_NODELIST` | Current step only (1 node) |
| `SLURM_JOB_NUM_NODES` | Total nodes in allocation |

**Important**: Always use `SLURM_JOB_NODELIST` to get the full node list. Since your script runs on a single node, `SLURM_NODELIST` only contains that one node.

### Passing Environment Variables to MPI

Use mpirun's `-x` flag, **not** the `env` command:

```yaml
# CORRECT
mpirun -x MY_VAR=value -x LD_PRELOAD=/path/to/lib.so {{ command.template }}

# WRONG - mpirun interprets 'env' as the program to launch
mpirun env MY_VAR=value {{ command.template }}
```

---

## Troubleshooting

### Error: "Not enough slots available"

```
There are not enough slots available in the system to satisfy the N
slots that were requested by the application
```

**Causes and fixes**:

1. **Missing slot counts in host list**
   ```bash
   # Wrong: defaults to 1 slot per host
   NODELIST=bora001,bora002

   # Correct: specify slots per host
   NODELIST=bora001:8,bora002:8
   ```

2. **Using SLURM_NODELIST instead of SLURM_JOB_NODELIST**
   ```bash
   # Wrong: only contains the single node running the script
   scontrol show hostnames $SLURM_NODELIST

   # Correct: contains all allocation nodes
   scontrol show hostnames $SLURM_JOB_NODELIST
   ```

### Error: "OPAL ERROR: Not initialized in file pmix"

Your OpenMPI doesn't have SLURM PMI support. Don't use `srun` to launch MPI programs directly. Use `mpirun` with `--mca plm rsh` instead.

### Error: "env" or unexpected program name in error

You're using `env VAR=value` with mpirun. Use `-x VAR=value` instead:

```yaml
# Wrong
mpirun env LD_PRELOAD=/path/lib.so ./program

# Correct
mpirun -x LD_PRELOAD=/path/lib.so ./program
```


### MPI processes don't start on remote nodes

Check that:
1. SSH works between compute nodes (passwordless)
2. You're using `--mca plm rsh` with mpirun
3. The module environment is set up in your script (modules don't inherit)

---

## Complete Example

Here's a complete working configuration for an IOR benchmark with variable node counts using the automatic MPI configuration:

```yaml
benchmark:
  name: "IOR Scaling Test"
  workdir: "/scratch/user/benchmark"
  executor: "slurm"
  repetitions: 3

  slurm_options:
    allocation:
      mode: "single"
      allocation_script: |
        #SBATCH --nodes=8
        #SBATCH --time=02:00:00
        #SBATCH --exclusive
        #SBATCH --partition=batch

vars:
  nodes:
    type: int
    sweep: { mode: list, values: [1, 2, 4, 8] }

  ppn:  # processes per node
    type: int
    expr: "8"

  block_size_mb:
    type: int
    sweep: { mode: list, values: [256, 512, 1024] }

command:
  template: >
    ior -w -r -b {{ block_size_mb }}m -t 1m
    -o /scratch/user/testfile

scripts:
  - name: "ior"
    mpi:
      nodes: "{{ nodes }}"
      ppn: "{{ ppn }}"
      pass_env: [LD_LIBRARY_PATH, PATH]
    script_template: |
      #!/bin/bash

      # Load modules (required - doesn't inherit from allocation)
      module purge
      module load openmpi/4.1 ior/3.3

      echo "Running IOR benchmark"
      echo "Total processes: {{ nodes * ppn }}"

      {{ command.template }}

    parser:
      file: "{{ execution_dir }}/stdout"
      metrics:
        - name: write_bw
        - name: read_bw
      parser_script: |
        import re
        def parse(file_path):
            with open(file_path) as f:
                content = f.read()
            write = re.search(r'write\s+[\d.]+\s+[\d.]+\s+([\d.]+)', content)
            read = re.search(r'read\s+[\d.]+\s+[\d.]+\s+([\d.]+)', content)
            return {
                'write_bw': float(write.group(1)) if write else None,
                'read_bw': float(read.group(1)) if read else None
            }

output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
```

### Manual Alternative

If you need more control, here's the same example with manual MPI configuration:

```yaml
scripts:
  - name: "ior"
    script_template: |
      #!/bin/bash

      # Load modules (required - doesn't inherit from allocation)
      module purge
      module load openmpi/4.1 ior/3.3

      # Only run MPI from node 0
      if [ "$SLURM_NODEID" = "0" ]; then
        # Build host list from FULL allocation
        NODELIST=$(scontrol show hostnames $SLURM_JOB_NODELIST \
                   | head -n {{ nodes }} \
                   | sed 's/$/:{{ ppn }}/' \
                   | tr '\n' ',')
        NODELIST=${NODELIST%,}

        echo "Running on nodes: $NODELIST"
        echo "Total processes: {{ nodes * ppn }}"

        # Run MPI program
        mpirun --host $NODELIST \
               -np {{ nodes * ppn }} \
               --map-by ppr:{{ ppn }}:node \
               --mca plm rsh \
               --oversubscribe \
               -x LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
               -x PATH="$PATH" \
               {{ command.template }}
      fi

    parser:
      # ... same as above
```
