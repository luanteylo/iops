---
title: "TOTO Overhead Analysis"
subtitle: "Measuring the runtime overhead of an I/O interception library"
date: 2024-11-20
tags: ["overhead-analysis", "resource-tracing", "slurm", "ld-preload"]
draft: true
---

When you intercept I/O system calls to analyze application behavior, how much overhead do you actually add? That's the question we needed to answer for TOTO (Transparent and Online Tool for I/O), a library that hooks into I/O calls via `LD_PRELOAD` to provide runtime analysis of parallel file system access patterns.

Before deploying TOTO in production, we needed to quantify its overhead across different workloads. Sounds simple, but there were a few complications:

1. **Baseline comparison**: Every test must run both *with* and *without* TOTO
2. **Multi-dimensional space**: Overhead varies with process count, I/O size, access pattern, and TOTO's analysis frequency
3. **Conditional parameters**: TOTO-specific settings only make sense when TOTO is enabled
4. **LD_PRELOAD headaches**: Setting `LD_PRELOAD` in scripts can break SLURM commands
5. **Resource monitoring**: We need CPU and memory data, not just execution time

This turned out to be a perfect use case for IOPS. Here's how we tackled it.

---

## The Key Tricks

### Conditional Variables

TOTO has an `analysis_period` parameter that controls how often it gathers I/O statistics. But this parameter is meaningless when TOTO is disabled—we'd just be creating redundant test combinations.

IOPS has a `when` clause for exactly this situation:

```yaml
vars:
  with_toto:
    type: bool
    sweep:
      mode: list
      values: [0, 1]  # false, true

  analysis_period:
    type: int
    sweep:
      mode: list
      values: [100, 250, 500, 1000, 2000]
    when: "with_toto"    # Only sweep when TOTO is enabled
    default: 0           # Use 0 when TOTO is disabled
```

Without `when`, we'd have 2 × 5 = 10 combinations. With `when`, we get 5 (with TOTO) + 1 (baseline) = 6 combinations. The savings add up quickly when you have multiple conditional parameters.

### Resource Tracing

Execution time alone doesn't tell the whole story. We wanted CPU and memory utilization data to understand *where* the overhead comes from. IOPS can sample these during execution:

```yaml
benchmark:
  trace_resources: true    # Enable tracing
  trace_interval: 0.05     # Sample every 50ms
```

This generates per-node trace files with timestamped samples, plus a summary CSV with mean/max/std statistics. We can then compare resource footprints between baseline and instrumented runs directly.

### The LD_PRELOAD Problem

Here's something that bit us: when you `export LD_PRELOAD=...` in a SLURM job script, it affects everything that runs after—including `scontrol`, `squeue`, and `module load`. Those commands break spectacularly.

The solution is IOPS's single-allocation mode with `pass_env`. Instead of exporting variables in the script, we pass them directly to mpirun via `-x` flags:

```yaml
scripts:
  - name: "ior"
    mpi:
      pass_env:
        LD_PRELOAD: "{{ '/path/to/toto.so' if with_toto else '' }}"
        TOTO_ANALYSIS_PERIOD: "{{ analysis_period if with_toto else '' }}"
```

Empty values are automatically skipped (no `-x` flag generated). The script stays clean, `module load` works normally, and environment variables only affect the actual benchmark command.

---

## Two Ways to Run It

IOPS supports two SLURM modes. Here are complete configurations for both.

### Per-Test Mode (Simple)

Each test submits a separate SLURM job. Straightforward, but slower when running many tests due to queue wait times.

```yaml
benchmark:
  name: "toto+base+all"
  description: "TOTO overhead study: all tests with and without TOTO"
  workdir: "/home/user/workdir"
  repetitions: 6
  search_method: "exhaustive"
  executor: "slurm"

  trace_resources: true
  trace_interval: 0.05
  collect_system_info: true
  track_executions: true

vars:
  with_toto:
    type: bool
    sweep:
      mode: list
      values: [0, 1]

  nodes:
    type: int
    sweep:
      mode: list
      values: [16]

  total_procs:
    type: int
    sweep:
      mode: list
      values: [16, 64, 256]

  requests_mb:
    type: int
    sweep:
      mode: list
      values: [1, 8, 32]

  volume_size_gb:
    type: int
    sweep:
      mode: list
      values: [16]

  analysis_period:
    type: int
    sweep:
      mode: list
      values: [250, 500, 1000, 2000]
    when: "with_toto"
    default: 0

  spatiality:
    type: str
    sweep:
      mode: list
      values: ['cont', 'random']

  filestrategy:
    type: str
    sweep:
      mode: list
      values: ['shared-file', 'file-per-proc']

  procs_per_node:
    type: int
    expr: "{{ total_procs // nodes }}"

  block_size_mb:
    type: int
    expr: "(volume_size_gb * 1024) // (nodes * procs_per_node)"

  summary_file:
    type: str
    expr: "{{ execution_dir }}/summary_{{ execution_id }}_{{ repetition }}.json"

constraints:
  - name: "block_transfer_alignment"
    rule: "block_size_mb % requests_mb == 0"
    violation_policy: "skip"

command:
  template: >
    ior -w -b {{ block_size_mb }}mb
    -t {{ requests_mb }}mb
    {% if spatiality == 'random' %} -z {% endif %}
    {% if filestrategy == 'file-per-proc' %} -F {% endif %}
    -O summaryFile={{ summary_file }} -O summaryFormat=JSON
    -o /beegfs/user/ior/output.ior

scripts:
  - name: "ior"
    submit: "sbatch"
    script_template: |
      #!/bin/bash
      #SBATCH --job-name=iops_{{ execution_id }}
      #SBATCH --ntasks={{ total_procs }}
      #SBATCH --nodes={{ nodes }}
      #SBATCH --ntasks-per-node={{ procs_per_node }}
      #SBATCH --time=00:05:00
      #SBATCH --chdir={{ execution_dir }}
      #SBATCH --exclusive

      {% if with_toto %}
      export TOTO_PFS_PATHS=/beegfs
      export TOTO_LOG_LEVEL='ERROR'
      export TOTO_LOG_TO_STDOUT=0
      export TOTO_BEEGFS_STRIPING_PREFIX=/beegfs/user
      export TOTO_BEEGFS_STRIPING_SUFIX=ior
      export TOTO_LOGS_FOLDER={{ execution_dir }}
      export TOTO_ANALYSIS_PERIOD={{ analysis_period }}
      {% endif %}

      module purge
      module load mpi/openmpi/4.0.1
      module load compiler/gcc/12.2.0

      mpirun --mca btl ^uct --mca fs ^lustre \
        {% if with_toto %} env LD_PRELOAD=/home/user/toto/toto.so {% endif %} \
        {{ command.template }}

    parser:
      file: "{{ summary_file }}"
      metrics:
        - name: bwMiB
        - name: totalTime
      parser_script: |
        import json
        def parse(file_path: str):
            with open(file_path, "r") as f:
                data = json.load(f)
            tests = data.get("tests", [])
            if not tests:
                raise ValueError("No tests found in IOR JSON")
            results = tests[0].get("Results", [])
            if not results:
                raise ValueError("No Results found in IOR JSON")
            write_res = next(
                (r for r in results if str(r.get("access", "")).lower() == "write"),
                results[0],
            )
            return write_res

output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"

reporting:
  enabled: true
```

### Single-Allocation Mode (Recommended)

All tests run within one SLURM allocation. Faster, avoids queue wait times, and cleanly handles `LD_PRELOAD` via `pass_env`.

```yaml
benchmark:
  name: "toto+base+all"
  description: "TOTO overhead study: all tests with and without TOTO"
  workdir: "/home/user/workdir"
  repetitions: 6
  search_method: "exhaustive"

  executor: "slurm"
  slurm_options:
    allocation:
      mode: "single"
      allocation_script: |
        #SBATCH --nodes=16
        #SBATCH --time=04:00:00
        #SBATCH --exclusive
        #SBATCH --constraint=bora

  trace_resources: true
  trace_interval: 0.05
  collect_system_info: true
  track_executions: true

vars:
  with_toto:
    type: bool
    sweep:
      mode: list
      values: [0, 1]

  nodes:
    type: int
    sweep:
      mode: list
      values: [8, 16]

  total_procs:
    type: int
    sweep:
      mode: list
      values: [16, 64, 256]

  requests_mb:
    type: int
    sweep:
      mode: list
      values: [1, 8, 32]

  volume_size_gb:
    type: int
    sweep:
      mode: list
      values: [16]

  analysis_period:
    type: int
    sweep:
      mode: list
      values: [100, 250, 500, 1000, 2000]
    when: "with_toto"
    default: 0

  spatiality:
    type: str
    sweep:
      mode: list
      values: ['cont', 'random']

  filestrategy:
    type: str
    sweep:
      mode: list
      values: ['shared-file', 'file-per-proc']

  procs_per_node:
    type: int
    expr: "{{ total_procs // nodes }}"

  block_size_mb:
    type: int
    expr: "(volume_size_gb * 1024) // (nodes * procs_per_node)"

  summary_file:
    type: str
    expr: "{{ execution_dir }}/summary_{{ execution_id }}_{{ repetition }}.json"

constraints:
  - name: "block_transfer_alignment"
    rule: "block_size_mb % requests_mb == 0"
    violation_policy: "skip"

  - name: "valid_procs_distribution"
    rule: "total_procs >= nodes"
    violation_policy: "skip"
    description: "Must have at least 1 process per node"

command:
  template: >
    ior -w -b {{ block_size_mb }}mb
    -t {{ requests_mb }}mb
    {% if spatiality == 'random' %} -z {% endif %}
    {% if filestrategy == 'file-per-proc' %} -F {% endif %}
    -O summaryFile={{ summary_file }} -O summaryFormat=JSON
    -o /beegfs/user/ior/output.ior

scripts:
  - name: "ior"
    mpi:
      nodes: "{{ nodes }}"
      ppn: "{{ procs_per_node }}"
      pass_env:
        LD_PRELOAD: "{{ '/home/user/toto/toto.so' if with_toto else '' }}"
        TOTO_PFS_PATHS: "{{ '/beegfs' if with_toto else '' }}"
        TOTO_LOG_LEVEL: "{{ 'ERROR' if with_toto else '' }}"
        TOTO_LOG_TO_STDOUT: "{{ '0' if with_toto else '' }}"
        TOTO_BEEGFS_STRIPING_PREFIX: "{{ '/beegfs/user' if with_toto else '' }}"
        TOTO_BEEGFS_STRIPING_SUFIX: "{{ 'ior' if with_toto else '' }}"
        TOTO_LOGS_FOLDER: "{{ execution_dir if with_toto else '' }}"
        TOTO_ANALYSIS_PERIOD: "{{ analysis_period if with_toto else '' }}"
      extra_options:
        - "-mca btl ^uct"
        - "--mca fs ^lustre"
        - "--mca osc ^ucx"
        - "--mca pml ^ucx"
        - "--mca btl_openib_allow_ib 1"

    script_template: |
      #!/bin/bash

      module purge
      module load mpi/openmpi/4.0.1
      module load compiler/gcc/12.2.0

      echo "=== SLURM Allocation Details ==="
      echo "SLURM_JOB_ID:        $SLURM_JOB_ID"
      echo "SLURM_JOB_NODELIST:  $SLURM_JOB_NODELIST"
      echo "Hostname:            $(hostname)"
      echo ""
      echo "=== Test Parameters ==="
      echo "Requested nodes:     {{ nodes }}"
      echo "Procs per node:      {{ procs_per_node }}"
      echo "Total procs:         {{ nodes * procs_per_node }}"
      echo "With TOTO:           {{ with_toto }}"
      echo ""

      {{ command.template }}

    parser:
      file: "{{ summary_file }}"
      metrics:
        - name: bwMiB
        - name: totalTime
      parser_script: |
        import json
        def parse(file_path: str):
            with open(file_path, "r") as f:
                data = json.load(f)
            tests = data.get("tests", [])
            if not tests:
                raise ValueError("No tests found in IOR JSON")
            results = tests[0].get("Results", [])
            if not results:
                raise ValueError("No Results found in IOR JSON")
            write_res = next(
                (r for r in results if str(r.get("access", "")).lower() == "write"),
                results[0],
            )
            return write_res

output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"

reporting:
  enabled: true
```

---

## Some Results

The resource tracing data lets us visualize overhead in different ways. Here are some plots from a real study:

### CPU Overhead

How TOTO's CPU overhead scales with process count and analysis period:

![CPU Overhead Heatmap](../../images/blog/cpu_overhead_heatmap.png)

### Memory Overhead

Memory footprint comparison between baseline and instrumented runs:

![Memory Overhead Heatmap](../../images/blog/memory_overhead_heatmap.png)

### Combined View

CPU and memory overhead side by side:

![Combined Overhead Heatmap](../../images/blog/overhead_heatmap_combined.png)

### Overhead by Process Count

The relationship between parallelism and instrumentation cost:

![Overhead Summary](../../images/blog/overhead_summary_by_procs.png)

### Resource Scaling by Analysis Period

How TOTO's resource consumption changes with different analysis frequencies:

![Resource Scaling](../../images/blog/resource_scaling_by_period.png)

---

## Running the Study

```bash
# Validate configuration
iops check toto_tests.yaml

# Preview execution plan
iops run toto_tests.yaml --dry-run

# Execute
iops run toto_tests.yaml

# Generate report
iops report /path/to/workdir/run_001
```

---

## What We Learned

A few things that made this study work well:

1. **Conditional variables** saved us from running redundant tests where TOTO-specific parameters varied but TOTO wasn't even enabled

2. **Resource tracing** gave us the CPU and memory data we needed—execution time alone wouldn't have told the full story

3. **Single-allocation mode with `pass_env`** was the cleanest way to handle `LD_PRELOAD` without breaking SLURM commands

4. **Constraints** caught invalid parameter combinations early (like requesting more nodes than processes)

5. **Jinja conditionals in `pass_env`** made A/B testing with environment variables straightforward

---

## Related Documentation

- [Single-Allocation Mode](/user-guide/single-allocation-mode) - MPI configuration details
- [Resource Tracing](/user-guide/resource-tracing) - CPU and memory monitoring
- [Conditional Variables](/user-guide/matrix-generation#conditional-variables) - How `when` clauses work
- [YAML Schema Reference](/user-guide/yaml-schema) - Complete configuration reference
