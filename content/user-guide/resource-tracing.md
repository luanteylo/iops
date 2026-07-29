---
title: "Resource Sampling"
weight: 75
---

IOPS can optionally sample CPU, memory, GPU, and I/O activity during benchmark execution, so you can correlate parameter configurations with resource footprint (e.g., heatmap analysis of how parameters affect resource usage).

**Warning: Performance Impact**

Resource sampling runs background processes that periodically collect system metrics and write to CSV files. Although the samplers run at low priority (via `renice`), they may still affect benchmark results: a small amount of CPU time for reading proc files, an `nvidia-smi` invocation per GPU sample, one CSV append per sample interval, and ~1-2 MB of memory per process. For performance-critical measurements, run your benchmark **without sampling first** to establish a baseline, then enable sampling in a separate run to collect resource data.

## Quick Start

Enable resource sampling in your configuration:

```yaml
benchmark:
  name: "My Benchmark"
  probes:
    resource_sampling: true    # CPU/memory sampling (default: false)
    gpu_sampling: true         # GPU sampling (default: false)
    io_sampling: true          # I/O sampling (default: false)
    io_paths:                  # Restrict I/O sampling to these paths (default: all storage)
      - "{{ execution_dir }}"
    sampling_interval: 1.0     # Sample every 1 second (default)
```

## How It Works

### CPU/Memory Sampling

When `probes.resource_sampling: true`, IOPS injects a resource sampler (`__iops_runtime_sampler.sh`) into each benchmark script. The sampler runs with low priority (`renice -n 19`), reads `/proc/stat` and `/proc/meminfo` at the configured interval, and writes per-node, per-attempt sample files (`__iops_trace_<hostname>_<attempt_id>.csv`). A per-attempt sentinel file (`__iops_trace_running.<attempt_id>`) controls graceful termination: the sampler stops when the exit handler removes its sentinel.

### GPU Sampling

When `probes.gpu_sampling: true`, IOPS injects a GPU sampler (`__iops_runtime_gpu_sampler.sh`) that detects the GPU vendor at runtime (currently NVIDIA via `nvidia-smi`, designed for future AMD/Intel support), queries all GPUs in a single call per interval, and writes per-node, per-attempt GPU sample files (`__iops_gpu_trace_<hostname>_<attempt_id>.csv`). It gracefully skips if no supported GPU is detected (no errors, no empty files) and uses its own per-attempt sentinel file (`__iops_gpu_trace_running.<attempt_id>`), independent of the CPU sampler.

### I/O Sampling

When `probes.io_sampling: true`, IOPS injects an I/O sampler (`__iops_runtime_io_sampler.sh`) that reads two independent counter sources each interval and writes per-node, per-attempt sample files (`__iops_io_trace_<hostname>_<attempt_id>.csv`), with its own sentinel (`__iops_io_trace_running.<attempt_id>`).

Two sources are needed because neither one alone describes both a local disk and a network filesystem:

| Source | Read from | Covers | Reports nothing for |
|--------|-----------|--------|---------------------|
| `block` | `/proc/diskstats` | Local disks, NVMe | NFS, whose traffic never reaches a client block device |
| `nfs` | `/proc/self/mountstats` | NFS mounts, per mount | Local disks |

Each row is tagged with its source, so a study comparing storage backends can tell them apart rather than seeing one arm report zero.

#### Scoping to the storage you care about

By default every block device and NFS mount on the node is counted. A node usually has storage the benchmark never touches, so a job writing to `/tmp` on a machine that also mounts NFS would report both. `io_paths` restricts the counters to the filesystems actually holding the paths you name:

```yaml
benchmark:
  probes:
    io_sampling: true
    io_paths:
      - "{{ execution_dir }}"      # where this execution writes
      - "/scratch/shared/input"    # where it reads from
```

Paths are Jinja2 templates rendered per execution, so they can reference `{{ execution_dir }}` or any swept variable, exactly like `command.template`. Each path is resolved **on the compute node**, since mount tables differ across an allocation, and a path the benchmark has not created yet resolves through its nearest existing ancestor.

Resolution maps a path to a counter:

| The path lives on | Resolved to | Precision |
|-------------------|-------------|-----------|
| A local filesystem | The whole block device behind it (a partition resolves to its parent disk, an LVM or md volume to the disks underneath) | Device-level |
| An NFS mount | That mount's client counters | Mount-level, exact |
| tmpfs, ramfs, or anything with no backing device | Nothing countable | Reported, not counted |

**Device-level is not path-level.** Scoping to `/tmp` restricts the counters to the disk holding `/tmp`. If `/` lives on that same disk, its traffic is still included. NFS scoping is exact because the kernel keeps counters per mount; block scoping is only as precise as the device layout. To measure a local filesystem cleanly, give it its own device.

A path that resolves to nothing countable, such as anything on tmpfs, is not silently ignored: the run logs a warning naming the path and its filesystem type, and every node records what each path resolved to in `__iops_io_targets_<hostname>_<attempt_id>.json` next to the trace.

Two more things to know before drawing conclusions from the numbers:

- **The counters are node-level, not process-level.** They include anything else running on the node that touches the same storage. On a dedicated compute node in a batch job that is what you want; on a shared machine it is noise.
- **NFS byte counts are what crossed the wire.** The probe reads the server-read and server-written counters, not the normal-read counters, so reads the page cache satisfied locally are excluded. Comparing an NFS arm against a local-disk arm is therefore comparing like with like: both count traffic that reached storage.

Block devices are counted once. Partitions (`sda1`) are excluded because their traffic is already in the parent device, and virtual devices (`dm-*`, `md*`, `loop*`) are excluded because they would double count the disks underneath them.

Other filesystems (Lustre, GPFS) are not yet read. They plug in as additional counter sources in the same way the GPU sampler is designed to gain AMD and Intel support.

All three samplers share the `sampling_interval` setting and support multi-node jobs on SLURM, OAR and PBS.

## Output Files

### Per-Execution CPU/Memory Sample Files

Each execution produces one CSV file per node:

**Location:** `workdir/run_001/exec_0001/repetition_001/__iops_trace_<hostname>_<attempt_id>.csv`

`attempt_id` is the scheduler job id (`SLURM_JOB_ID`, `OAR_JOB_ID` or `PBS_JOBID`), falling back to the shell PID when running outside a scheduler. Every node of a job uses the same value. Including it in the filename prevents a second attempt (e.g. when SLURM requeues the job after a node failure) from truncating the first attempt's trace, and prevents one attempt's exit handler from stopping another attempt's sampler. Post-mortem aggregation picks up every matching file, so if an attempt aborts and leaves a short partial trace on disk, you may want to delete that file before running the report.

**Format:**
```csv
timestamp,hostname,core,cpu_user_pct,cpu_system_pct,cpu_idle_pct,mem_total_kb,mem_available_kb
1705123456.123,node01,0,45.2,5.1,49.7,128000000,64000000
1705123456.123,node01,1,42.1,4.8,53.1,128000000,64000000
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

**Location:** `workdir/run_001/exec_0001/repetition_001/__iops_gpu_trace_<hostname>_<attempt_id>.csv`

**Format:**
```csv
timestamp,hostname,gpu_index,gpu_name,utilization_gpu_pct,utilization_mem_pct,memory_used_mib,memory_total_mib,temperature_c,power_draw_w,clock_sm_mhz,clock_mem_mhz
1705123456.5,node01,0,NVIDIA A100-SXM4-80GB,85,40,30000,81920,62,250.50,1410,1215
1705123457.5,node01,0,NVIDIA A100-SXM4-80GB,92,45,32000,81920,64,275.30,1410,1215
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

### Per-Execution I/O Sample Files

When `io_sampling` is enabled, each execution produces one I/O sample CSV per node:

**Location:** `workdir/run_001/exec_0001/repetition_001/__iops_io_trace_<hostname>_<attempt_id>.csv`

**Format:**
```csv
timestamp,hostname,source,device,path,interval_s,read_bytes,write_bytes,read_ops,write_ops
1705123457.1,node01,block,nvme0n1,/scratch/run,1.002,0,536870912,0,4096
1705123457.1,node01,nfs,server:/export,/data/input,1.002,104857600,0,800,0
```

**Fields:**
| Field | Description |
|-------|-------------|
| `timestamp` | Unix timestamp with milliseconds |
| `hostname` | Node hostname |
| `source` | Counter source: `block` or `nfs` |
| `device` | Block device name (`nvme0n1`) or NFS mount source (`server:/export`) |
| `path` | The configured `io_paths` entry this row was resolved from, empty when no paths were configured |
| `interval_s` | Seconds this row covers, measured rather than assumed |
| `read_bytes` | Bytes read during the interval |
| `write_bytes` | Bytes written during the interval |
| `read_ops` | Read operations during the interval |
| `write_ops` | Write operations during the interval |

Values are per-interval deltas, not cumulative counters. The first sample of a run establishes the baseline and emits no row. A counter that goes backwards (a reset or a wrap) is clamped to zero rather than emitting a spurious burst. `interval_s` is recorded because `sleep` drifts under load, so rates computed from it are more accurate than rates assuming the configured interval.

### Per-Execution I/O Targets Files

When `io_paths` is set, each node records what the configured paths resolved to:

**Location:** `workdir/run_001/exec_0001/repetition_001/__iops_io_targets_<hostname>_<attempt_id>.json`

```json
{
  "hostname": "node01",
  "paths": [
    {"path": "/scratch/run", "kind": "block", "target": "nvme0n1", "mount": "/scratch", "fstype": "ext4"},
    {"path": "/dev/shm/cache", "kind": "none", "target": "", "mount": "/dev/shm", "fstype": "tmpfs"}
  ]
}
```

`kind` is `block`, `nfs`, or `none` when the filesystem has no counters to read. One file per node, because the same path can resolve differently across an allocation. This is the first thing to check when an I/O metric reads zero.

### Run-Level Summary

After all executions complete, IOPS aggregates samples into a summary CSV:

**Location:** `workdir/run_001/__iops_resource_summary.csv`

This file contains one row per execution+repetition, with all user variables and aggregated metrics from the CPU/memory, GPU, and I/O samplers (whichever are enabled), enabling correlation analysis between parameter configurations and resource footprint.

Columns are the union across all executions. An execution short enough that its sampler collected no usable samples reports only the counter columns, and the remaining cells are left empty.

### CPU/Memory Aggregated Metrics

Metrics are computed from all samples across all nodes. A **sample** is one row in the CSV: a single measurement at a specific timestamp for a specific core on a specific node.

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

When traces span multiple nodes (multi-node runs, or a rescheduled job that left a partial trace on a previous host), the hostname is added as a prefix so same-indexed GPUs on different hosts do not collide: `node01_gpu0_*`, `node01_gpu1_*`, `node02_gpu0_*`, and so on. Single-node runs keep the plain `gpuN_*` naming.

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

The `gpu_energy_j` metric provides total GPU energy consumption in Joules. Energy is computed per GPU by integrating instantaneous power draw over time using the trapezoidal rule (`E_interval = (P_i + P_{i+1}) / 2 * (t_{i+1} - t_i)` for consecutive samples), then summed across all GPUs. This gives accurate results even with varying power draw. Per-GPU energy is available via `gpu0_energy_j`, `gpu1_energy_j`, etc. To convert to kilowatt-hours: `kWh = gpu_energy_j / 3600000`.

### I/O Aggregated Metrics

When `io_sampling` is enabled, I/O metrics are added to the summary CSV. Byte totals sum the per-interval deltas across every device, source, and node. Volumes use 1024-based units, matching the memory metrics.

`duration` below is the elapsed time a single node covered, summed over its samples. Using the first and last timestamps instead would drop the window between the baseline and the first emitted row.

| Metric | Description | Formula |
|--------|-------------|---------|
| `io_read_gb` | Total read across all sources | `sum(read_bytes) / 1024³` |
| `io_write_gb` | Total written across all sources | `sum(write_bytes) / 1024³` |
| `io_disk_read_gb` | Read from block devices | `sum(read_bytes where source = block) / 1024³` |
| `io_disk_write_gb` | Written to block devices | `sum(write_bytes where source = block) / 1024³` |
| `io_nfs_read_gb` | Read from NFS mounts | `sum(read_bytes where source = nfs) / 1024³` |
| `io_nfs_write_gb` | Written to NFS mounts | `sum(write_bytes where source = nfs) / 1024³` |
| `io_read_mbs_avg` | Aggregate read throughput | `sum(read_bytes) / 1024² / duration` |
| `io_write_mbs_avg` | Aggregate write throughput | `sum(write_bytes) / 1024² / duration` |
| `io_read_mbs_peak_per_node` | Busiest single read sample on any node | `max(sum(read_bytes) per node-instant / interval_s) / 1024²` |
| `io_write_mbs_peak_per_node` | Busiest single write sample on any node | `max(sum(write_bytes) per node-instant / interval_s) / 1024²` |
| `io_read_iops_avg` | Average read operations per second | `sum(read_ops) / duration` |
| `io_write_iops_avg` | Average write operations per second | `sum(write_ops) / duration` |
| `io_nodes_traced` | Number of nodes with I/O sample data | `count(distinct hostname)` |
| `io_samples_collected` | Sampling instants across all nodes | `count(distinct hostname + timestamp)` |
| `io_trace_duration_s` | Elapsed time covered | `max(sum(interval_s) per node)` |

The averages are aggregate: they sum every node's traffic over the elapsed window, which is the number a storage study wants. The peaks are per node, because samples on different nodes are not clock-aligned and adding them at a supposedly shared instant would be fiction.

The disk and NFS columns are always emitted, holding zero when that source saw no traffic, so a run comparing the two backends produces a complete table either way.

Short executions undersample. If a test finishes in less time than a few sampling intervals, the totals cover only the intervals that were observed and will read low. Lower `sampling_interval` for short tests, or treat the volumes as a lower bound.

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

    # Enable I/O sampling (default: false)
    # Reads block device counters (/proc/diskstats) and NFS client
    # counters (/proc/self/mountstats), reporting each source separately
    io_sampling: true

    # Restrict I/O sampling to the storage behind these paths
    # (default: every block device and NFS mount on the node).
    # Jinja2 templates, rendered per execution, resolved on the compute node.
    io_paths:
      - "{{ execution_dir }}"
      - "/scratch/input"

    # Sampling interval in seconds (default: 1.0)
    # Shared by resource_sampling, gpu_sampling and io_sampling
    # Lower = finer granularity but more data
    sampling_interval: 0.5
```

## Multi-Node Support

For multi-node jobs, IOPS automatically launches samplers on all allocated nodes. A shared node launcher (`__iops_node_launcher.sh`) resolves the job's node list and starts one sampler per node:

| Scheduler | Node list | Launch method |
|-----------|-----------|---------------|
| SLURM | `scontrol show hostnames $SLURM_JOB_NODELIST` | `srun --overlap --ntasks-per-node=1` (one call covers the allocation) |
| OAR | `$OAR_NODEFILE` | `oarsh` per remote node |
| PBS | `$PBS_NODEFILE` | `ssh` per remote node |
| None detected | local hostname | background process on the local node |

All samplers share the same sentinel file on the shared filesystem; when the exit handler removes it, all node samplers stop.

Each node produces its own sample files (`__iops_trace_node01_<attempt_id>.csv`, `__iops_gpu_trace_node01_<attempt_id>.csv`, etc.), and the aggregation combines data from all nodes. The CPU/memory sampler and the GPU sampler support multi-node operation independently.

Two requirements for remote sampling to produce data:

1. The execution directory must be on a filesystem shared by all nodes, since remote samplers write their traces there. When it is node-local the benchmark still runs, only the remote traces stay behind on their nodes.
2. Passwordless remote access must work between compute nodes (`oarsh` or `ssh` in batch mode), which is the default on most clusters.

Check `nodes_traced` in `__iops_resource_summary.csv` to confirm how many nodes were actually sampled. A value of 1 on a multi-node run means only the head node reported.

## Fault Tolerance

Resource sampling is designed to never break your benchmark:

- All sampler commands use `|| true` to suppress errors
- Missing or malformed sample files are skipped during aggregation
- If no sample files exist, the summary is simply not created
- The GPU sampler gracefully skips if no supported GPU vendor is detected (no errors, no empty files)
- The I/O sampler gracefully skips when neither counter source is readable (for example on a non-Linux host), and when every configured path resolves to storage with no counters

## I/O Considerations

Sample files are written to the execution directory. For benchmarks testing storage performance, place workdir on a separate filesystem from the test target, or accept the minimal I/O overhead (one CSV append per sample interval). The sampler uses buffered writes and runs at lowest scheduling priority to minimize impact.
