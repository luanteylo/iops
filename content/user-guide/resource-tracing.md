---
title: "Resource Tracing"
weight: 66
---

IOPS can optionally trace CPU and memory utilization during benchmark execution. This feature helps correlate parameter configurations with resource footprint, enabling heatmap analysis of how different parameters affect system resource usage.

**Warning: Performance Impact**

Resource tracing runs a background process that periodically reads `/proc/stat` and `/proc/meminfo` and writes to a CSV file. While designed to minimize interference (runs at low priority via `renice`), this may still affect benchmark results:

- **CPU overhead**: The sampler consumes a small amount of CPU time for reading proc files and computing deltas
- **I/O overhead**: Each sample appends a row to the trace CSV file
- **Memory**: The background process uses minimal memory (~1-2 MB)

For performance-critical measurements, run your benchmark **without tracing first** to establish a baseline, then enable tracing in a separate run to collect resource data.

## Quick Start

Enable resource tracing in your configuration:

```yaml
benchmark:
  name: "My Benchmark"
  trace_resources: true    # Enable tracing (default: false)
  trace_interval: 1.0      # Sample every 1 second (default)
```

## How It Works

When `trace_resources: true`, IOPS injects a resource sampler (`__iops_runtime_sampler.sh`) into each benchmark script. The sampler:

1. **Runs with low priority** (`renice -n 19`) to minimize interference
2. **Samples at configurable intervals** from `/proc/stat` and `/proc/meminfo`
3. **Writes per-node trace files** with hostname in filename (`__iops_trace_<hostname>.csv`)
4. **Uses a sentinel file** (`__iops_trace_running`) for graceful termination
5. **Stops automatically** when the exit handler removes the sentinel file

## Output Files

### Per-Execution Trace Files

Each execution produces one CSV file per node:

**Location:** `workdir/run_001/exec_0001/repetition_001/__iops_trace_<hostname>.csv`

**Format:**
```csv
timestamp,hostname,core,cpu_user_pct,cpu_system_pct,cpu_idle_pct,mem_total_kb,mem_available_kb
1705123456.123,node01,0,45.2,5.1,49.7,128000000,64000000
1705123456.123,node01,1,42.1,4.8,53.1,128000000,64000000
1705123457.123,node01,0,47.8,5.3,46.9,128000000,63000000
```

**Fields:**
| Field | Description |
|-------|-------------|
| `timestamp` | Unix timestamp with milliseconds |
| `hostname` | Node hostname |
| `core` | CPU core number (0-indexed) |
| `cpu_user_pct` | User CPU utilization (%) |
| `cpu_system_pct` | System CPU utilization (%) |
| `cpu_idle_pct` | Idle CPU (%) |
| `mem_total_kb` | Total memory in KB |
| `mem_available_kb` | Available memory in KB |

### Run-Level Summary

After all executions complete, IOPS aggregates traces into a summary CSV:

**Location:** `workdir/run_001/__iops_resource_summary.csv`

**Format:**
```csv
execution_id,repetition,nodes,ppn,block_size,...,mem_peak_gb,mem_avg_gb,cpu_avg_pct,cpu_max_pct,cpu_imbalance_pct,nodes_traced,samples_collected,trace_duration_s
exec_0001,1,4,8,1024,64.2,58.1,78.5,95.2,12.3,4,120,120.5
exec_0001,2,4,8,1024,63.8,57.9,77.9,94.8,11.8,4,118,118.2
```

This file includes:
- `execution_id` and `repetition`
- **All user variables** (for correlation analysis)
- **Aggregated resource metrics**

### Aggregated Metrics

Metrics are computed from all trace samples across all nodes. A **sample** is one row in the trace CSV - a single measurement at a specific timestamp for a specific core on a specific node.

The following intermediate values are computed per sample:

- `mem_used` = `mem_total_kb - mem_available_kb` (memory used)
- `cpu_total` = `cpu_user_pct + cpu_system_pct` (CPU utilization)

| Metric | Description | Formula |
|--------|-------------|---------|
| `mem_peak_gb` | Maximum memory used across all samples | `max(mem_used) / 1024²` |
| `mem_avg_gb` | Average memory across all samples | `sum(mem_used) / count(samples) / 1024²` |
| `mem_peak_per_node_gb` | Highest per-node peak memory | `max(max(mem_used) per node) / 1024²` |
| `cpu_avg_pct` | Average CPU utilization | `sum(cpu_total) / count(samples)` |
| `cpu_max_pct` | Peak CPU utilization | `max(cpu_total)` |
| `cpu_imbalance_pct` | Load balancing indicator | `max(max(cpu_total) per core) - min(max(cpu_total) per core)` |
| `nodes_traced` | Number of nodes with trace data | `count(distinct hostname)` |
| `samples_collected` | Total samples across all nodes | `count(rows)` |
| `trace_duration_s` | Time span of trace data | `max(timestamp) - min(timestamp)` |


## Configuration Reference

```yaml
benchmark:
  # Enable resource tracing (default: false)
  trace_resources: true

  # Sampling interval in seconds (default: 1.0)
  # Lower = finer granularity but more data
  trace_interval: 0.5
```

## Multi-Node Support

For SLURM multi-node jobs, IOPS automatically launches samplers on all allocated nodes:

1. **Detection**: The sampler detects multi-node jobs via `SLURM_NNODES > 1`
2. **Launch**: Uses `srun --overlap --ntasks-per-node=1` to start one sampler per node
3. **Coordination**: All samplers share the same sentinel file on the shared filesystem
4. **Termination**: When the exit handler removes the sentinel file, all node samplers stop

Each node produces its own trace file (`__iops_trace_node01.csv`, `__iops_trace_node02.csv`, etc.), and the aggregation automatically combines data from all nodes.

## Fault Tolerance

Resource tracing is designed to never break your benchmark:

- All sampler commands use `|| true` to suppress errors
- Missing or malformed trace files are skipped during aggregation
- If no trace files exist, the summary is simply not created

## I/O Considerations

Trace files are written to the execution directory. For benchmarks testing storage performance:

- Place workdir on a separate filesystem from the test target
- Or accept the minimal I/O overhead (one CSV append per sample interval)

The sampler uses buffered writes and runs at lowest scheduling priority to minimize impact.
