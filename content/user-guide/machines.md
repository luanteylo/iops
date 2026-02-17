---
title: "Machine Overrides"
weight: 15
---

Use a single configuration file across multiple systems with per-machine overrides.

---

## Table of Contents

1. [Overview](#overview)
2. [Merge Rules](#merge-rules)
3. [Configuration](#configuration)
4. [Example: Local Development + HPC Cluster](#example-local-development--hpc-cluster)
5. [Use Cases](#use-cases)
6. [Tips](#tips)

---

## Overview

The `machines` section lets you define per-machine overrides inside a single YAML file. Instead of maintaining separate configs for your laptop, HPC clusters, or cloud instances, write one base config and override only what differs per environment.

Select the target machine at runtime:

```bash
iops run config.yaml --machine cluster      # CLI flag
IOPS_MACHINE=cluster iops run config.yaml   # Environment variable
iops run config.yaml                        # No flag = base config only
```

The CLI flag takes priority over the environment variable.

---

## Merge Rules

When `--machine NAME` is specified, IOPS deep-merges the machine's overrides into the base config:

| Type | Behavior | Example |
|------|----------|---------|
| **Dicts** | Recursive deep merge | `benchmark`, `vars`, `output.sink` |
| **Named lists** (items with `name` key) | Merge by `name`, append new items | `scripts`, `constraints` |
| **Other lists** | Replace entirely | `sweep.values`, `exclude` |
| **Scalars** | Override wins | `benchmark.executor`, `output.sink.path` |

The distinction follows the Kubernetes convention: lists of **named objects** (each item has a `name` key) are merged by identity, while lists of scalars or anonymous objects are replaced wholesale.

**Per-field reference:**

| Config path | List type | Merge behavior |
|---|---|---|
| `vars.<var>.sweep.values` | Scalars | **Replace** |
| `scripts` | Named objects (`name`) | **Merge by name**, append new |
| `scripts[].parser.metrics` | Named objects (`name`) | **Merge by name**, append new |
| `constraints` | Named objects (`name`) | **Merge by name**, append new |
| `output.sink.exclude` | Strings | **Replace** |
| `output.sink.include` | Strings | **Replace** |
| `reporting.metrics.<m>.plots` | Anonymous objects | **Replace** |
| `reporting.default_plots` | Anonymous objects | **Replace** |

### sweep/expr/adaptive Mutual Exclusion

Since `sweep`, `expr`, and `adaptive` are mutually exclusive, IOPS handles conflicts automatically after merging:
- Override provides `expr` → base's `sweep` and `adaptive` are removed
- Override provides `sweep` → base's `expr` and `adaptive` are removed
- Override provides `adaptive` → base's `sweep` and `expr` are removed

```yaml
# Base: total_cores is swept
vars:
  total_cores:
    type: int
    sweep:
      mode: list
      values: [4, 8, 16]

# Machine override: total_cores becomes derived
machines:
  cluster:
    vars:
      total_cores:
        expr: "{{ nodes * ppn }}"
# Result: sweep is removed, only expr remains
```

This also works for switching to or from adaptive variables:

```yaml
# Base: problem_size is swept
vars:
  problem_size:
    type: int
    sweep:
      mode: list
      values: [1000, 2000, 4000]

# Machine override: problem_size becomes adaptive
machines:
  hpc:
    benchmark:
      search_method: "adaptive"
    vars:
      problem_size:
        adaptive:
          initial: 1000
          factor: 2
          stop_when: "exit_code != 0"
# Result: sweep is removed, only adaptive remains
```

---

## Configuration

Each machine entry can override any standard top-level section:

```yaml
machines:
  machine_name:
    benchmark: {}     # Optional
    vars: {}          # Optional
    command: {}       # Optional
    scripts: []       # Optional
    output: {}        # Optional
    constraints: []   # Optional
    reporting: {}     # Optional
```

Machine names are arbitrary identifiers (e.g., `laptop`, `cluster_a`, `grid5000_lyon`).

IOPS validates the `machines` section structure even without `--machine`, and validates the fully merged config when a machine is selected:

```bash
iops check config.yaml                  # Validates structure including machines
iops check config.yaml --machine cluster  # Validates merged config
```

Use `--resolve` to inspect the final merged YAML after overrides are applied. This is useful for debugging which values a machine override produces:

```bash
iops check config.yaml --machine cluster --resolve            # Print to stdout
iops check config.yaml --machine cluster --resolve merged.yaml  # Write to file
```

Generate a starter template with machine overrides using:

```bash
iops generate my_config.yaml --machines
```

---

## Example: Local Development + HPC Cluster

A common pattern: develop locally with small-scale parameters, then run full-scale on a cluster.

```yaml
benchmark:
  name: "IOR Benchmark"
  workdir: "./workdir"
  executor: "local"
  repetitions: 2

vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 2]             # Small scale for local

  ppn:
    type: int
    sweep:
      mode: list
      values: [4, 8]

  ntasks:
    type: int
    expr: "{{ nodes * ppn }}"

command:
  template: "ior -w -b 1024mb -o output.ior"

scripts:
  - name: "run"
    script_template: |
      #!/bin/bash
      mpirun -np {{ ntasks }} {{ command.template }}

    parser:
      file: "{{ execution_dir }}/output.txt"
      metrics:
        - name: throughput
      parser_script: |
        def parse(file_path):
            with open(file_path) as f:
                return {"throughput": float(f.read())}

output:
  sink:
    type: csv

machines:
  cluster:
    benchmark:
      workdir: "/scratch/user/benchmarks"
      executor: "slurm"
      repetitions: 5

    vars:
      nodes:
        sweep:
          values: [4, 8, 16, 32]   # Full-scale on cluster

      ppn:
        sweep:
          values: [16, 32, 64]

    scripts:
      - name: "run"
        # Parser is inherited from base — only script_template changes
        script_template: |
          #!/bin/bash
          #SBATCH --job-name=iops_{{ execution_id }}
          #SBATCH --nodes={{ nodes }}
          #SBATCH --ntasks-per-node={{ ppn }}
          #SBATCH --time=01:00:00
          #SBATCH --partition=batch

          module load mpi ior
          srun {{ command.template }}

    output:
      sink:
        path: "/scratch/user/benchmarks/results.csv"
```

```bash
iops run config.yaml                    # Local: 2×2×2 reps = 8 tests
iops run config.yaml --machine cluster  # Cluster: 4×3×5 reps = 60 tests
```

---

## Use Cases

**Multiple SLURM clusters** — Override `workdir`, SLURM partitions, module systems, or custom command wrappers per cluster:

```yaml
machines:
  cluster_a:
    benchmark:
      workdir: "/scratch/clusterA/user/bench"
      slurm_options:
        commands:
          submit: "clustera-submit"
    scripts:
      - name: "run"
        script_template: |
          #!/bin/bash
          #SBATCH --partition=compute
          #SBATCH --account=proj_a
          module load clustera-mpi
          {{ command.template }}

  cluster_b:
    benchmark:
      workdir: "/work/user/benchmarks"
    scripts:
      - name: "run"
        script_template: |
          #!/bin/bash
          #SBATCH --partition=standard
          #SBATCH --qos=normal
          module load intel openmpi
          {{ command.template }}
```

**Swept → fixed variables** — A variable swept in the base config can become fixed on a specific machine (sweep/expr conflict resolved automatically):

```yaml
# Base: sweep both filesystems locally
vars:
  filesystem:
    type: str
    sweep:
      mode: list
      values: ["lustre", "beegfs"]

machines:
  cluster_lustre:
    vars:
      filesystem:
        expr: "lustre"          # Fixed — sweep removed automatically
```

**CI/CD environments** — Define minimal configs for fast CI runs:

```yaml
machines:
  ci:
    benchmark:
      repetitions: 1
    vars:
      nodes:
        sweep:
          values: [1]           # Minimal testing
```

**Shared configs across a research group** — Each researcher overrides their account and workdir:

```yaml
machines:
  alice:
    benchmark:
      workdir: "/home/alice/scratch/bench"
    scripts:
      - name: "run"
        script_template: |
          #!/bin/bash
          #SBATCH --account=alice_account
          {{ command.template }}
```

---

## Tips

1. **Start with a working base config** — ensure it works in at least one environment before adding overrides
2. **Override only what differs** — don't repeat unchanged settings; the merge handles inheritance
3. **Use `iops check --resolve`** to inspect the fully merged YAML after overrides are applied
4. **Use semantic names** — `grid5000_lyon` is clearer than `machine2`
5. **Use `IOPS_MACHINE` in scripts** for automation and CI/CD pipelines
6. **Include full key paths** — override `benchmark.slurm_options`, not just `slurm_options`

---

## See Also

- [YAML Schema Reference](yaml-schema#machines-optional) — `machines` section syntax
- [Command Line Interface](cli) — `--machine` flag and `IOPS_MACHINE` usage
