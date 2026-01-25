---
title: "TOTO Overhead Analysis"
weight: 10
---

*Evaluating the runtime overhead of a transparent I/O interception library*

---

## The Challenge

**TOTO** (Transparent and Online Tool for I/O) is a library that intercepts I/O system calls via `LD_PRELOAD` to provide runtime analysis and optimization of parallel file system access patterns. Before deploying such a library in production, researchers need to quantify its overhead across different workloads.

The challenge involves several complexities:

1. **Baseline comparison**: Every test configuration must run both *with* and *without* TOTO to measure overhead
2. **Multi-dimensional parameter space**: Overhead may vary with process count, I/O request size, access pattern, and TOTO's internal analysis period
3. **Conditional parameters**: TOTO-specific parameters (like `analysis_period`) only apply when TOTO is enabled
4. **LD_PRELOAD complications**: Setting `LD_PRELOAD` in scripts can break SLURM commands (`scontrol`, `squeue`) and module loading
5. **Resource monitoring**: Need CPU and memory utilization data to understand where overhead comes from

---

## The Solution with IOPS

IOPS addresses each challenge with specific features:

| Challenge | IOPS Feature |
|-----------|--------------|
| Baseline comparison | `with_toto` boolean variable in sweep |
| Conditional parameters | `when` clause on `analysis_period` |
| LD_PRELOAD issues | `pass_env` with Jinja conditionals (single-allocation mode) |
| Resource monitoring | `trace_resources: true` with configurable sampling |
| Multi-dimensional sweep | Exhaustive search with constraints |

### Key Technique: Conditional Variables

The `analysis_period` parameter controls how often TOTO gathers and analyzes I/O statistics. This parameter is **only relevant when TOTO is enabled**. Without conditional variables, you'd have redundant test combinations.

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

**Without `when`**: 2 (with_toto) x 5 (analysis_period) = 10 combinations per parameter set
**With `when`**: 5 (with TOTO) + 1 (baseline) = 6 combinations per parameter set

This eliminates redundant tests where `analysis_period` varies but TOTO isn't even running.

### Key Technique: Resource Tracing

IOPS can sample CPU and memory utilization during benchmark execution:

```yaml
benchmark:
  trace_resources: true    # Enable tracing
  trace_interval: 0.05     # Sample every 50ms (aggressive for overhead studies)
```

This generates:
- Per-node trace files: `__iops_trace_<hostname>.csv` with timestamped CPU/memory samples
- Aggregated summary: `__iops_resource_summary.csv` with mean/max/std statistics per execution

The summary CSV enables direct comparison of resource footprint between baseline and instrumented runs.

---

## Configuration Examples

IOPS supports two SLURM execution modes. Here are complete configurations for both approaches.

### Per-Test Mode (Traditional)

Each test submits a separate SLURM job. Simpler but slower when running many tests due to queue wait times.

```yaml
benchmark:
  name: "toto+base+all"
  description: "TOTO Study: All tests with toto + baseline (without toto)"
  workdir: "/home/user/workdir"
  repetitions: 6
  search_method: "exhaustive"
  executor: "slurm"

  # Resource tracing for overhead measurement
  trace_resources: true
  trace_interval: 0.05

  collect_system_info: true
  track_executions: true

vars:
  # Boolean to toggle TOTO on/off
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

  # Conditional: only swept when with_toto is true
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

  # Derived variables
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
      # TOTO environment variables
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

### Single-Allocation Mode (Recommended for Many Tests)

All tests run within one SLURM allocation. Faster and avoids queue wait times, but requires careful handling of `LD_PRELOAD`.

The key difference: environment variables are passed via `mpi.pass_env` instead of shell exports. This avoids `LD_PRELOAD` breaking `scontrol` and `module` commands.

```yaml
benchmark:
  name: "toto+base+all"
  description: "TOTO Study: All tests with toto + baseline (without toto)"
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

  # Resource tracing for overhead measurement
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
    # MPI configuration with conditional environment variables
    # Empty values are automatically skipped (no -x flag generated)
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

    # Script is clean - no exports needed!
    # Environment variables are passed directly via mpirun -x flags
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

## Why Single-Allocation Mode for LD_PRELOAD?

In per-test mode, the script runs as a SLURM job script. Any `export LD_PRELOAD=...` statement affects subsequent commands, including `scontrol` and `module load`. This breaks SLURM's internal tools.

In single-allocation mode with `mpi.pass_env`:
1. The script runs *before* any exports happen
2. `module load` commands work normally
3. Environment variables are passed *only* to the mpirun command via `-x` flags
4. Jinja conditionals ensure variables are only passed when needed

---

## Results Visualization

The resource tracing data enables detailed overhead analysis. Here are example visualizations from a real study:

### CPU Overhead by Process Count and Analysis Period

Shows how TOTO's CPU overhead scales with the number of MPI processes and the analysis period:

![CPU Overhead Heatmap](../../images/showcase/cpu_overhead_heatmap.png)

### Memory Overhead

Memory footprint comparison between baseline and instrumented runs:

![Memory Overhead Heatmap](../../images/showcase/memory_overhead_heatmap.png)

### Combined Overhead View

Simultaneous view of CPU and memory overhead across configurations:

![Combined Overhead Heatmap](../../images/showcase/overhead_heatmap_combined.png)

### Overhead Summary by Process Count

Aggregate overhead statistics showing the relationship between parallelism and instrumentation cost:

![Overhead Summary](../../images/showcase/overhead_summary_by_procs.png)

### Resource Scaling by Analysis Period

How TOTO's resource consumption changes with different analysis periods:

![Resource Scaling](../../images/showcase/resource_scaling_by_period.png)

---

## Running the Study

```bash
# Validate configuration
iops check toto_tests.yaml

# Preview execution plan (dry run)
iops run toto_tests.yaml --dry-run

# Execute the study
iops run toto_tests.yaml

# Generate report after completion
iops report /path/to/workdir/run_001
```

---

## Key Takeaways

1. **Conditional variables** eliminate redundant test combinations when parameters only apply under certain conditions

2. **Resource tracing** provides the data needed to quantify runtime overhead beyond just execution time

3. **Single-allocation mode with `pass_env`** cleanly handles `LD_PRELOAD` without breaking SLURM commands

4. **Constraints** prevent invalid parameter combinations (e.g., more nodes than processes)

5. **Jinja conditionals** in `pass_env` values enable clean A/B testing with environment variable injection

---

## Related Documentation

- [Single-Allocation Mode](/user-guide/single-allocation-mode) - Detailed guide to MPI configuration and troubleshooting
- [Resource Tracing](/user-guide/resource-tracing) - CPU and memory monitoring configuration
- [Conditional Variables](/user-guide/matrix-generation#conditional-variables) - How `when` clauses work
- [YAML Schema Reference](/user-guide/yaml-schema) - Complete configuration reference
