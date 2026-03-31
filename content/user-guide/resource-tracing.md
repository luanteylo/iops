---
title: "Resource Sampling"
weight: 66
---

IOPS can optionally sample CPU, memory, and GPU utilization during benchmark execution. This feature helps correlate parameter configurations with resource footprint, enabling heatmap analysis of how different parameters affect system resource usage.

**Warning: Performance Impact**

Resource sampling runs background processes that periodically collect system metrics and write to CSV files. While designed to minimize interference (runs at low priority via `renice`), this may still affect benchmark results:

- **CPU overhead**: The sampler consumes a small amount of CPU time for reading proc files and computing deltas
- **GPU overhead**: The GPU sampler invokes `nvidia-smi` at each sampling interval
- **I/O overhead**: Each sample appends a row to the trace CSV file
- **Memory**: The background processes use minimal memory (~1-2 MB each)

For performance-critical measurements, run your benchmark **without sampling first** to establish a baseline, then enable sampling in a separate run to collect resource data.

## Quick Start

Enable resource sampling in your configuration:

```yaml
benchmark:
  name: "My Benchmark"
  probes:
    resource_sampling: true    # CPU/memory sampling (default: false)
    gpu_sampling: true         # GPU sampling (default: false)
    sampling_interval: 1.0     # Sample every 1 second (default)
```

## How It Works

### CPU/Memory Sampling

When `probes.resource_sampling: true`, IOPS injects a resource sampler (`__iops_runtime_sampler.sh`) into each benchmark script. The sampler:

1. **Runs with low priority** (`renice -n 19`) to minimize interference
2. **Samples at configurable intervals** from `/proc/stat` and `/proc/meminfo`
3. **Writes per-node sample files** with hostname in filename (`__iops_trace_<hostname>.csv`)
4. **Uses a sentinel file** (`__iops_trace_running`) for graceful termination
5. **Stops automatically** when the exit handler removes the sentinel file

### GPU Sampling

When `probes.gpu_sampling: true`, IOPS injects a GPU sampler (`__iops_runtime_gpu_sampler.sh`) that collects GPU metrics. The sampler:

1. **Detects GPU vendor** at runtime (currently supports NVIDIA via `nvidia-smi`, designed for future AMD/Intel support)
2. **Queries all GPUs** in a single call per sample interval
3. **Writes per-node GPU sample files** (`__iops_gpu_trace_<hostname>.csv`)
4. **Gracefully skips** if no supported GPU is detected (no errors, no empty files)
5. **Uses its own sentinel file** (`__iops_gpu_trace_running`) independent of the CPU sampler

Both samplers share the `sampling_interval` setting, run at low priority, and support SLURM multi-node jobs.

## Output Files

### Per-Execution CPU/Memory Sample Files

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

### Per-Execution GPU Sample Files

When `gpu_sampling` is enabled and a supported GPU is detected, each execution produces one GPU sample CSV per node:

**Location:** `workdir/run_001/exec_0001/repetition_001/__iops_gpu_trace_<hostname>.csv`

**Format:**
```csv
timestamp,hostname,gpu_index,gpu_name,utilization_gpu_pct,utilization_mem_pct,memory_used_mib,memory_total_mib,temperature_c,power_draw_w,clock_sm_mhz,clock_mem_mhz
1705123456.5,node01,0,NVIDIA A100-SXM4-80GB,85,40,30000,81920,62,250.50,1410,1215
1705123457.5,node01,0,NVIDIA A100-SXM4-80GB,92,45,32000,81920,64,275.30,1410,1215
1705123456.5,node01,1,NVIDIA A100-SXM4-80GB,78,35,28000,81920,60,240.10,1410,1215
```

**Fields:**
| Field | Description |
|-------|-------------|
| `timestamp` | Unix timestamp with milliseconds |
| `hostname` | Node hostname |
| `gpu_index` | GPU device index (0-indexed) |
| `gpu_name` | GPU model name |
| `utilization_gpu_pct` | GPU compute utilization (%) |
| `utilization_mem_pct` | GPU memory controller utilization (%) |
| `memory_used_mib` | GPU memory used (MiB) |
| `memory_total_mib` | GPU memory total (MiB) |
| `temperature_c` | GPU temperature (Celsius) |
| `power_draw_w` | Current power draw (Watts) |
| `clock_sm_mhz` | Streaming multiprocessor clock (MHz) |
| `clock_mem_mhz` | Memory clock (MHz) |

### Run-Level Summary

After all executions complete, IOPS aggregates samples into a summary CSV:

**Location:** `workdir/run_001/__iops_resource_summary.csv`

This file contains one row per execution+repetition, with all user variables and aggregated metrics from both CPU/memory and GPU samples (when enabled). This enables correlation analysis between parameter configurations and resource footprint.

### CPU/Memory Aggregated Metrics

Metrics are computed from all samples across all nodes. A **sample** is one row in the CSV, representing a single measurement at a specific timestamp for a specific core on a specific node.

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

### GPU Aggregated Metrics

When `gpu_sampling` is enabled, GPU metrics are added to the summary CSV. Metrics are computed **per GPU first**, then aggregated across GPUs. This prevents idle GPUs from dragging down the averages on multi-GPU machines where only a subset of GPUs is active.

#### Per-GPU Columns

Each GPU gets its own set of columns in the summary CSV, named by device index:

| Column pattern | Example | Description |
|----------------|---------|-------------|
| `gpuN_avg_utilization_pct` | `gpu0_avg_utilization_pct` | Average utilization for GPU N |
| `gpuN_avg_power_w` | `gpu0_avg_power_w` | Average power draw for GPU N |
| `gpuN_energy_j` | `gpu0_energy_j` | Energy consumed by GPU N (Joules) |
| `gpuN_avg_temperature_c` | `gpu0_avg_temperature_c` | Average temperature for GPU N |
| `gpuN_mem_peak_mib` | `gpu0_mem_peak_mib` | Peak memory used by GPU N |

These per-GPU columns let you identify which GPUs were active and compare their individual resource profiles.

#### Aggregate Columns

Aggregate metrics use the **maximum of per-GPU averages** so that idle GPUs do not dilute the stats. For example, if GPU 0 averages 90% utilization and GPU 1 is idle at 0%, `gpu_avg_utilization_pct` reports 90%, not 45%.

| Metric | Description | Aggregation |
|--------|-------------|-------------|
| `gpu_count` | Number of distinct GPUs sampled | `count(distinct hostname:gpu_index)` |
| `gpu_avg_utilization_pct` | Best per-GPU average utilization | `max(per-GPU avg utilization)` |
| `gpu_max_utilization_pct` | Peak instantaneous utilization | `max(all samples)` |
| `gpu_avg_mem_utilization_pct` | Best per-GPU average memory utilization | `max(per-GPU avg mem utilization)` |
| `gpu_mem_peak_mib` | Peak GPU memory used | `max(all per-GPU peaks)` |
| `gpu_avg_temperature_c` | Highest per-GPU average temperature | `max(per-GPU avg temperature)` |
| `gpu_max_temperature_c` | Peak instantaneous temperature | `max(all samples)` |
| `gpu_avg_power_w` | Highest per-GPU average power | `max(per-GPU avg power)` |
| `gpu_max_power_w` | Peak instantaneous power | `max(all samples)` |
| `gpu_energy_j` | Total energy consumed (Joules) | `sum(per-GPU energy)` |
| `gpu_trace_duration_s` | Time span of GPU sample data | `max(timestamp) - min(timestamp)` |
| `gpu_samples_collected` | Total GPU samples | `count(rows)` |

#### Energy Calculation

The `gpu_energy_j` metric provides total GPU energy consumption in Joules. Energy is computed per GPU by integrating instantaneous power draw over time using the trapezoidal rule, then summed across all GPUs:

```
E = sum over all GPUs of: integral(P(t) dt)
```

For each GPU, consecutive power samples are integrated: `E_interval = (P_i + P_{i+1}) / 2 * (t_{i+1} - t_i)`. This gives accurate results even with varying power draw. Per-GPU energy is available via `gpu0_energy_j`, `gpu1_energy_j`, etc. To convert to kilowatt-hours: `kWh = gpu_energy_j / 3600000`.

## Configuration Reference

```yaml
benchmark:
  probes:
    # Enable CPU/memory sampling (default: false)
    resource_sampling: true

    # Enable GPU sampling (default: false)
    # Currently supports NVIDIA GPUs (via nvidia-smi)
    # Gracefully skips if no supported GPU is detected
    gpu_sampling: true

    # Sampling interval in seconds (default: 1.0)
    # Shared by both resource_sampling and gpu_sampling
    # Lower = finer granularity but more data
    sampling_interval: 0.5
```

## Multi-Node Support

For SLURM multi-node jobs, IOPS automatically launches samplers on all allocated nodes:

1. **Detection**: The sampler detects multi-node jobs via `SLURM_NNODES > 1`
2. **Launch**: Uses `srun --overlap --ntasks-per-node=1` to start one sampler per node
3. **Coordination**: All samplers share the same sentinel file on the shared filesystem
4. **Termination**: When the exit handler removes the sentinel file, all node samplers stop

Each node produces its own sample files (`__iops_trace_node01.csv`, `__iops_gpu_trace_node01.csv`, etc.), and the aggregation automatically combines data from all nodes.

Both the CPU/memory sampler and the GPU sampler support multi-node operation independently.

## Fault Tolerance

Resource sampling is designed to never break your benchmark:

- All sampler commands use `|| true` to suppress errors
- Missing or malformed sample files are skipped during aggregation
- If no sample files exist, the summary is simply not created
- The GPU sampler gracefully skips if no supported GPU vendor is detected (no errors, no empty files)

## I/O Considerations

Sample files are written to the execution directory. For benchmarks testing storage performance:

- Place workdir on a separate filesystem from the test target
- Or accept the minimal I/O overhead (one CSV append per sample interval)

The sampler uses buffered writes and runs at lowest scheduling priority to minimize impact.
