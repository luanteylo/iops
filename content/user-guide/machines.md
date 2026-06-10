---
title: "Machine Overrides"
weight: 55
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

Since `sweep`, `expr`, and `adaptive` are mutually exclusive, IOPS resolves conflicts automatically after merging: whichever of the three the override provides wins, and the other two are removed from the base.

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

The same applies when switching to or from an `adaptive` definition (remember to also set `benchmark.search_method: "adaptive"` in the override).

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

### Validation Timing

IOPS validates configuration in two phases:

1. **Structural validation (before merge):** All required top-level sections (`benchmark`, `vars`, `command`, `scripts`, `output`) must be present in the base config and the `machines` section must be well-formed. This runs even without `--machine`.

2. **Semantic validation (after merge):** Types, references, constraints, etc. are validated on the fully merged configuration.

Because structural validation runs first, **the base config must be self-contained**: a required section (e.g., `output`) cannot live only inside a machine override. If needed, provide a minimal placeholder at the top level and let the machine override replace it:

```yaml
# Base: placeholder output (will be overridden per machine)
output:
  sink:
    type: csv

machines:
  cluster:
    output:
      sink:
        path: "/scratch/results.csv"
```

```bash
iops check config.yaml                    # Validates structure including machines
iops check config.yaml --machine cluster  # Validates merged config
```

Use `--resolve` to inspect the final merged YAML after overrides are applied, which helps debug which values a machine override produces:

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
        # Parser is inherited from base; only script_template changes
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

**Multiple SLURM clusters.** Override `workdir`, SLURM partitions, module systems, or custom command wrappers per cluster:

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
```

**Swept to fixed variables.** A variable swept in the base config can become fixed on a specific machine (sweep/expr conflict resolved automatically):

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
        expr: "lustre"          # Fixed; sweep removed automatically
```

**CI/CD environments.** Define a minimal machine (e.g., `ci`) overriding `repetitions: 1` and a single-value sweep for fast CI runs.

**Shared configs across a research group.** Each researcher gets a machine entry overriding their `workdir` and `#SBATCH --account` line.

---

## Tips

1. **Start with a working base config** before adding overrides
2. **Override only what differs**; the merge handles inheritance
3. **Use `iops check --resolve`** to inspect the fully merged YAML
4. **Use semantic names**: `grid5000_lyon` is clearer than `machine2`
5. **Use `IOPS_MACHINE` in scripts** for automation and CI/CD pipelines
6. **Include full key paths**: override `benchmark.slurm_options`, not just `slurm_options`

---

## See Also

- [YAML Schema Reference](yaml-schema#machines-optional) for `machines` section syntax
- [Command Line Interface](cli) for the `--machine` flag and `IOPS_MACHINE` usage
