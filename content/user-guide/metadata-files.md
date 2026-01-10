---
title: "Metadata Files"
weight: 65
---

IOPS generates metadata files with the `__iops_` prefix to track executions, enable fast lookups, and support report generation. This page documents all metadata files, their purpose, when they are written, and how to control their generation.

## I/O Overhead Considerations

Metadata files are written to the **workdir** during benchmark execution. While these files are small (typically a few KB each), they can introduce I/O overhead in certain scenarios:

**When to disable metadata generation:**

- **Workdir on tested filesystem**: If your workdir is located on the filesystem being benchmarked, metadata writes can interfere with your measurements. For accurate I/O benchmarks, either disable metadata generation or place the workdir on a separate filesystem.
- **High-frequency short tests**: For benchmarks with thousands of very short tests (sub-second), the overhead of writing JSON files for each execution may become noticeable.
- **Network filesystems with high latency**: On slow network filesystems, metadata writes can add latency between test executions.

**When metadata is safe:**

- Workdir is on a separate filesystem from the test target
- Tests run for several seconds or longer
- You need `iops find` or `iops report` functionality

## Metadata Files Overview

| File | Location | Written When | Purpose |
|------|----------|--------------|---------|
| `__iops_run_metadata.json` | Run root | End of benchmark | Report generation |
| `__iops_index.json` | Run root | During execution | Fast execution lookup |
| `__iops_params.json` | Each exec folder | Before test runs | Parameter storage |
| `__iops_status.json` | Each exec/rep folder | After test completes | Status and cache tracking |
| `__iops_probe.sh` | Each repetition folder | Before test runs | System info collection |
| `__iops_sysinfo.json` | Each repetition folder | After test completes | Hardware/environment info |

## Controlling Metadata Generation

### Disable Execution Tracking

To disable `__iops_index.json`, `__iops_params.json`, and `__iops_status.json`:

```yaml
benchmark:
  track_executions: false
```

**Impact:**
- `iops find` command will not work for these runs
- Watch mode (`--watch`) will not work
- Reduces I/O by 3 small JSON writes per execution

### Disable System Information Collection

To disable `__iops_probe.sh` and `__iops_sysinfo.json`:

```yaml
benchmark:
  collect_system_info: false
```

**Impact:**
- System environment info will not appear in HTML reports
- Reduces I/O by 1 small JSON write per repetition
- Removes the probe script injection from generated scripts

### Disable All Metadata

For minimal I/O overhead (only results output):

```yaml
benchmark:
  track_executions: false
  collect_system_info: false
```

Note: `__iops_run_metadata.json` is always written as it's required for `iops report`.

## File Reference

### `__iops_run_metadata.json`

**Location:** `workdir/run_001/__iops_run_metadata.json`

**Written:** Once at the end of benchmark execution (or dry-run)

**Purpose:** Contains comprehensive metadata about the benchmark run, used by `iops report` to generate HTML reports without re-running the benchmark.

**Structure:**
```json
{
  "iops_version": "3.0.0",
  "benchmark": {
    "name": "IOR Performance Study",
    "description": "Benchmark description",
    "executor": "slurm",
    "repetitions": 3,
    "timestamp": "2026-01-10T14:30:00.000000",
    "test_count": 12,
    "search_method": "exhaustive",
    "hostname": "login-node",
    "benchmark_start_time": "2026-01-10T14:00:00.000000",
    "benchmark_end_time": "2026-01-10T14:30:00.000000",
    "total_runtime_seconds": 1800.0,
    "planner_stats": {
      "total_combinations": 48,
      "active_combinations": 36,
      "skipped_by_constraints": 12
    }
  },
  "system_environment": {
    "hostname": "compute-001",
    "cpu_model": "Intel Xeon Gold 6248",
    "cpu_cores": 40,
    "memory_kb": 196608000
  },
  "variables": {
    "nodes": {"type": "int", "swept": true, "sweep": {"mode": "list", "values": [1, 2, 4]}},
    "ppn": {"type": "int", "swept": false}
  },
  "metrics": [
    {"name": "throughput", "script": "benchmark"}
  ],
  "output": {
    "type": "csv",
    "path": "results.csv"
  },
  "command": {
    "template": "mpirun -np {{ nodes * ppn }} ./benchmark"
  },
  "reporting": {}
}
```

**Cannot be disabled** - required for report generation.

---

### `__iops_index.json`

**Location:** `workdir/run_001/__iops_index.json`

**Written:** Incrementally updated as each execution is prepared

**Purpose:** Indexes all executions with their parameters and paths, enabling fast lookup by `iops find`.

**Structure:**
```json
{
  "benchmark": "IOR Performance Study",
  "executions": {
    "exec_0001": {
      "path": "exec_0001",
      "params": {
        "nodes": 1,
        "ppn": 4,
        "block_size": 1024
      },
      "command": "mpirun -np 4 ./benchmark --nodes 1"
    },
    "exec_0002": {
      "path": "exec_0002",
      "params": {
        "nodes": 1,
        "ppn": 4,
        "block_size": 4096
      },
      "command": "mpirun -np 4 ./benchmark --nodes 1"
    }
  }
}
```

All paths are relative to the run root, making workdirs portable across systems.

**Controlled by:** `benchmark.track_executions`

---

### `__iops_params.json`

**Location:** `workdir/run_001/exec_0001/__iops_params.json`

**Written:** When the execution folder is created, before the test runs

**Purpose:** Stores parameter values for a specific execution, enabling `iops find` to filter by parameter values.

**Structure:**
```json
{
  "nodes": 4,
  "ppn": 8,
  "block_size": 4096
}
```

**Controlled by:** `benchmark.track_executions`

---

### `__iops_status.json`

**Location:**
- Test level: `workdir/run_001/exec_0001/__iops_status.json`
- Repetition level: `workdir/run_001/exec_0001/repetition_1/__iops_status.json`

**Written:**
- Test level: When a test is skipped (constraint or planner decision)
- Repetition level: After each repetition completes

**Purpose:** Tracks execution status for `iops find` filtering and watch mode.

**Structure:**
```json
{
  "status": "SUCCEEDED",
  "error": null,
  "end_time": "2026-01-09T14:23:45.678901",
  "cached": false,
  "duration_seconds": 125.3
}
```

**Status values:**

| Status | Meaning |
|--------|---------|
| `SUCCEEDED` | Execution completed successfully |
| `FAILED` | Execution failed with non-zero exit code |
| `ERROR` | Error during setup or execution |
| `SKIPPED` | Skipped due to constraint or planner decision |
| `RUNNING` | Currently executing |
| `PENDING` | Waiting to execute |
| `UNKNOWN` | Status could not be determined |

The `error` field contains the error message when status is FAILED or ERROR.

The `cached` field indicates whether the result was retrieved from cache (`true`) or freshly executed (`false`). This is set when running with `--use-cache` and a cached result is found.

The `duration_seconds` field contains the actual execution time in seconds from the probe script. This is available for both executed and cached results (the sysinfo is stored in the cache).

For skipped tests, a `reason` field explains why:
```json
{
  "status": "SKIPPED",
  "reason": "constraint:nodes * ppn <= 64"
}
```

**Controlled by:** `benchmark.track_executions`

---

### `__iops_probe.sh`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_probe.sh`

**Written:** When the repetition folder is created, before the test runs

**Purpose:** A shell script that collects system information from compute nodes. It is automatically sourced by the generated benchmark script and uses an EXIT trap to collect information after the benchmark completes.

**How it works:**
1. IOPS writes `__iops_probe.sh` to the repetition folder
2. The generated benchmark script sources this file at the start
3. The probe registers an EXIT trap
4. When the benchmark script exits (success or failure), the trap executes
5. System information is written to `__iops_sysinfo.json`

This approach ensures system info is collected even if the benchmark fails, and it runs on the actual compute node (important for SLURM jobs).

**Controlled by:** `benchmark.collect_system_info`

---

### `__iops_sysinfo.json`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_sysinfo.json`

**Written:** At the end of script execution (via EXIT trap in probe script)

**Purpose:** Contains hardware and environment information from the compute node where the test ran.

**Structure:**
```json
{
  "hostname": "compute-042",
  "cpu_model": "Intel(R) Xeon(R) Gold 6248 CPU @ 2.50GHz",
  "cpu_cores": 40,
  "memory_kb": 196608000,
  "kernel": "5.15.0-91-generic",
  "os": "Ubuntu 22.04.3 LTS",
  "ib_devices": "mlx5_0,mlx5_1",
  "filesystems": "lustre:/scratch,gpfs:/home",
  "duration_seconds": 125
}
```

**Fields:**

| Field | Description |
|-------|-------------|
| `hostname` | Compute node hostname |
| `cpu_model` | CPU model from `/proc/cpuinfo` |
| `cpu_cores` | Number of CPU cores (from `nproc`) |
| `memory_kb` | Total memory in KB |
| `kernel` | Linux kernel version |
| `os` | Operating system name and version |
| `ib_devices` | InfiniBand devices (comma-separated) |
| `filesystems` | Detected parallel filesystems (type:mountpoint) |
| `duration_seconds` | Script execution time in seconds |

**Detected parallel filesystems:** Lustre, GPFS, BeeGFS, CephFS, PanFS, WekaFS, PVFS2, OrangeFS, GlusterFS

**Controlled by:** `benchmark.collect_system_info`

## Best Practices

### For I/O Benchmarks

When benchmarking storage systems, place your workdir on a **different** filesystem than the one being tested:

```yaml
benchmark:
  name: "Lustre I/O Benchmark"
  workdir: "/local/scratch/iops_workdir"  # Local SSD, not Lustre
  # ... benchmark tests Lustre at /lustre/project/data
```

Or disable metadata if you must use the same filesystem:

```yaml
benchmark:
  name: "Lustre I/O Benchmark"
  workdir: "/lustre/project/benchmark"
  track_executions: false
  collect_system_info: false
```

### For Production Runs

Keep metadata enabled for:
- Post-run analysis with `iops find`
- HTML report generation with `iops report`
- Debugging failed executions
- Monitoring with watch mode

### For Large Parameter Sweeps

With thousands of executions, consider:
- Using `create_folders_upfront: false` (default) to create folders lazily
- Placing workdir on a fast local filesystem
- Using SSD storage for the workdir if available
