---
title: "Measuring the runtime overhead of an I/O interception library"
date: 2026-05-30
tags: ["overhead-analysis", "resource-tracing", "slurm", "ld-preload"]
author: "Luan Teylo, INRIA"
---

> This study is part of our paper **"TOTO: Transparent I/O Tuning for HPC Applications"**, accepted at **ICS 2026** (International Conference on Supercomputing, Belfast, July 2026). The overhead measurements below were produced with IOPS.

When you intercept I/O system calls to analyze application behavior, how much overhead do you actually add? That's the question we needed to answer for [TOTO](https://gitlab.inria.fr/hpc_io/toto) (Transparent and Online Tool for I/O), a library that hooks into I/O calls via `LD_PRELOAD` to provide runtime analysis of parallel file system access patterns.

Before deploying TOTO in production, we needed to quantify its overhead across different workloads. Sounds simple, but there were a few complications:

1. **Baseline comparison**: Every test must run both *with* and *without* TOTO
2. **Multi-dimensional space**: Overhead varies with process count, I/O size, access pattern, and TOTO's analysis frequency
3. **[Conditional parameters]({{< ref "/user-guide/matrix-generation#conditional-variables" >}})**: TOTO-specific settings only make sense when TOTO is enabled
4. **[Resource monitoring]({{< ref "/user-guide/resource-tracing" >}})**: We need CPU and memory data, not just execution time

This turned out to be a perfect use case for IOPS. Here's how we tackled it.

---

## The Key Tricks

### Conditional Variables

TOTO has an `analysis_period` parameter that controls how often it gathers I/O statistics. But this parameter is meaningless when TOTO is disabled, so we'd just be creating redundant test combinations.

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

Execution time alone doesn't tell the whole story. We wanted CPU and memory utilization data to understand *where* the overhead comes from. IOPS can [sample these during execution]({{< ref "/user-guide/resource-tracing" >}}):

```yaml
benchmark:
  probes:
    resource_sampling: true   # Enable tracing
    sampling_interval: 0.05   # Sample every 50ms
```

This generates per-node trace files with timestamped samples, plus a summary CSV with mean/max/std statistics. We can then compare resource footprints between baseline and instrumented runs directly.

### Conditional Execution with Jinja2

Using Jinja2 conditionals in the script template, we can enable TOTO only when `with_toto` is true:

```bash
mpirun ... {% if with_toto %} env LD_PRELOAD=/path/to/toto.so {% endif %} {{ command.template }}
```

---

## Results

To isolate the cost of the interception and analysis machinery, we ran TOTO with its stripe-count tuning **disabled**: every component stays active (calls are intercepted, statistics are kept, the analysis thread still communicates), but TOTO cannot improve performance, so only its negative impact shows up. We picked the largest-scale experiments on each platform (256 processes on PlaFRIM, 8192 on Irene), repeated each configuration 5 times, and swept request size (1, 8, 32 MiB), spatiality (contiguous, random), file strategy (shared-file, file-per-process), and the analysis period (250–2000 ms).

### Bandwidth overhead on PlaFRIM

The heatmap below reports the bandwidth slowdown of TOTO versus the baseline, per access pattern and analysis period. Overhead is **low in general (median 1%) and never exceeds 8%**, staying below 5% for most cases. The worst case is **random access to a shared file**, where the slowdown reaches up to 8% for short analysis periods (250–500 ms): shorter periods mean more frequent analysis communication, the random pattern triggers more `seek` calls, and the shared file forces the master rank to combine per-process statistics. (Negative values are an artifact of run-to-run variability.)

![TOTO overhead on PlaFRIM](../../images/blog/toto_overhead_heatmap_plafrim.png)

### At scale, overhead disappears into the noise (Irene)

On Irene, with 8192 processes, run-to-run variability dominates: the medians even suggest TOTO is *faster* in some cases. None of these differences are statistically significant (Mann-Whitney U test, 5% confidence), so we conclude the overhead is negligible at scale.

![TOTO overhead on Irene](../../images/blog/toto_overhead_irene.png)

### Where the cost comes from: CPU vs. the analysis period

Resource tracing tells us *why*. Peak memory per node sits on the diagonal (no measurable overhead), but **average CPU usage is driven by the analysis period**: at 250 ms the analysis thread communicates so often that CPU usage climbs from 5–8% to ~30%, while at 1000–2000 ms it falls back near the baseline. The analysis period is therefore a trade-off between adaptation speed and CPU cost, and a value of 500 ms or above keeps both performance and resource overhead low.

![TOTO resource overhead on PlaFRIM](../../images/blog/toto_overhead_resources_plafrim.png)

---

## Full Configuration

Here's the complete YAML configuration used in this study:

```yaml
benchmark:
  name: "toto+base+all"
  description: "TOTO Study: All tests with toto + baseline (without toto)"
  workdir: "/home/user/workdir"
  cache_file: "/home/user/workdir/cache.db"
  repetitions: 6
  search_method: "exhaustive"
  executor: "slurm"
  random_seed: 42
  cache_exclude_vars: ["summary_file"]
  cores_expr: "{{ nodes * 36 }}"

  probes:
    system_snapshot: true
    execution_index: true
    resource_sampling: true
    sampling_interval: 0.05

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
      values: [32]

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

  metadata:
    operation: "write"

scripts:
  - name: "ior"
    script_template: |
      #!/bin/bash
      #SBATCH --job-name=iops_{{ execution_id }}
      #SBATCH --ntasks={{ total_procs }}
      #SBATCH --nodes={{ nodes }}
      #SBATCH --ntasks-per-node={{ procs_per_node }}
      #SBATCH --time=00:01:00
      #SBATCH --chdir={{ execution_dir }}
      #SBATCH -o batch%j.out
      #SBATCH -e batch%j.err
      #SBATCH --exclusive
      #SBATCH --constraint bora

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

      mpirun --mca btl ^uct --mca fs ^lustre --mca osc ^ucx --mca pml ^ucx \
        --mca btl_openib_allow_ib 1 \
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
```

---

## Related Documentation

- [Full Interactive Report]({{< ref "/reports" >}}) - Explore the complete results from this study
- [Resource Tracing]({{< ref "/user-guide/resource-tracing" >}}) - CPU and memory monitoring
- [Conditional Variables]({{< ref "/user-guide/matrix-generation#conditional-variables" >}}) - How `when` clauses work
- [YAML Schema Reference]({{< ref "/user-guide/yaml-schema" >}}) - Complete configuration reference
- [Execution Backends]({{< ref "/user-guide/execution-backends" >}}) - SLURM and local execution
