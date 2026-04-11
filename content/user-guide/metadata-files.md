---
title: "Metadata Files"
weight: 65
---

IOPS generates metadata files with the `__iops_` prefix to track executions, enable fast lookups, and support report generation. This page documents all metadata files, their purpose, when they are written, and how to control their generation.

---

## Table of Contents

1. [I/O Overhead Considerations](#io-overhead-considerations)
2. [Metadata Files Overview](#metadata-files-overview)
3. [Controlling Metadata Generation](#controlling-metadata-generation)
4. [File Reference](#file-reference)
5. [Best Practices](#best-practices)

---

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

### Run-Level Files

Located in `workdir/run_XXX/`:

| File | Purpose |
|------|---------|
| `__iops_run_metadata.json` | Report generation (config, timing, variables) |
| `__iops_index.json` | Fast execution lookup for `iops find` |
| `__iops_config.yaml` | Copy of the original input config for this run |
| `__iops_config_resume_<timestamp>.yaml` | Config used for a subsequent `--resume` invocation (one per resume) |
| `__iops_resume.lock` | Concurrency guard held while an `--resume` invocation is active; removed on exit |
| `__iops_resource_summary.csv` | Aggregated CPU/memory and GPU metrics |
| `__iops_kickoff.sh` | Single-allocation mode execution script (SLURM only) |
| `__iops_plots/` | PDF exports of report plots (requires kaleido) |

### Execution Tracking Files

Located in `workdir/run_XXX/exec_XXXX/`:

| File | Purpose |
|------|---------|
| `__iops_params.json` | Parameter values for this execution |
| `__iops_skipped` | Marker file for skipped tests (only present if skipped) |

Located in `workdir/run_XXX/exec_XXXX/repetition_X/`:

| File | Purpose |
|------|---------|
| `__iops_status.json` | Repetition execution status |

### Script Output Files

Located in `workdir/run_XXX/exec_XXXX/repetition_X/`:

| File | Purpose |
|------|---------|
| `stdout` | Script standard output |
| `stderr` | Script standard error |
| `post_stdout` | Post-script standard output (if post-script defined) |
| `post_stderr` | Post-script standard error (if post-script defined) |
| `parser_stdout` | Parser script print() output (if any) |
| `parser_stderr` | Parser script errors/warnings (if any) |

These files capture all output from script execution and parsing, useful for debugging failed tests. Parser output files are only created if the parser produces output.

### System Info Files

Located in `workdir/run_XXX/exec_XXXX/repetition_X/`:

| File | Purpose |
|------|---------|
| `__iops_exit_handler.sh` | Centralized EXIT trap coordinator |
| `__iops_atexit_sysinfo.sh` | System info collection script |
| `__iops_sysinfo.json` | Hardware/environment info (generated at exit) |

### Resource Tracing Files

Located in `workdir/run_XXX/exec_XXXX/repetition_X/`:

| File | Purpose |
|------|---------|
| `__iops_runtime_sampler.sh` | CPU/memory sampling script |
| `__iops_trace_running` | Sentinel file (signals CPU/memory samplers to run) |
| `__iops_trace_<host>.csv` | Per-node CPU/memory trace data |
| `__iops_runtime_gpu_sampler.sh` | GPU metrics sampling script |
| `__iops_gpu_trace_running` | Sentinel file (signals GPU samplers to run) |
| `__iops_gpu_trace_<host>.csv` | Per-node GPU trace data |

## Controlling Metadata Generation

### Disable Execution Tracking

To disable `__iops_index.json`, `__iops_params.json`, `__iops_skipped`, and `__iops_status.json`:

```yaml
benchmark:
  probes:
    execution_index: false
```

**Impact:**
- `iops find` command will not work for these runs
- Watch mode (`--watch`) will not work
- Reduces I/O by 3 small JSON writes per execution

### Disable System Information Collection

To disable `__iops_atexit_sysinfo.sh` and `__iops_sysinfo.json`:

```yaml
benchmark:
  probes:
    system_snapshot: false
```

**Impact:**
- System environment info will not appear in HTML reports
- Reduces I/O by 1 small JSON write per repetition
- Removes the system info script injection from generated scripts

### Disable All Metadata

For minimal I/O overhead (only results output):

```yaml
benchmark:
  probes:
    execution_index: false
    system_snapshot: false
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

**Controlled by:** `benchmark.probes.execution_index`

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

**Controlled by:** `benchmark.probes.execution_index`

---

### `__iops_skipped`

**Location:** `workdir/run_001/exec_0001/__iops_skipped`

**Written:** When a test is skipped (constraint violation or planner decision)

**Purpose:** Marker file indicating that a test was skipped. Only present for skipped tests. If this file does not exist, watch mode assumes the test is pending or active.

**Structure:**
```json
{
  "reason": "constraint:nodes * ppn <= 64",
  "message": "Optional detailed message"
}
```

**Fields:**

| Field | Description |
|-------|-------------|
| `reason` | Why the test was skipped (constraint rule, planner decision, etc.) |
| `message` | Optional detailed explanation |

**Controlled by:** `benchmark.probes.execution_index`

---

### `__iops_status.json`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_status.json`

**Written:**
- When a job is submitted (initial status)
- After each repetition completes or fails
- During SLURM job execution when status changes (PENDING → RUNNING)

**Purpose:** Tracks repetition execution status for `iops find` filtering and watch mode. Enables real-time status updates during SLURM job execution.

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
| `RUNNING` | Currently executing |
| `PENDING` | Waiting in queue (SLURM jobs) |
| `UNKNOWN` | Status could not be determined |

**Initial status by executor:**

| Executor | Initial Status | Reason |
|----------|----------------|--------|
| `local` | `RUNNING` | Local jobs start executing immediately |
| `slurm` | `PENDING` | SLURM jobs go to queue before running |

The `error` field contains the error message when status is FAILED or ERROR.

The `cached` field indicates whether the result was retrieved from cache (`true`) or freshly executed (`false`). This is set when running with `--use-cache` and a cached result is found.

The `duration_seconds` field contains the actual execution time in seconds from the probe script. This is available for both executed and cached results (the sysinfo is stored in the cache).

**Controlled by:** `benchmark.probes.execution_index`

---

### `__iops_exit_handler.sh`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_exit_handler.sh`

**Written:** When the repetition folder is created, before the test runs

**Purpose:** Provides a centralized EXIT trap that coordinates cleanup for all IOPS features. Other scripts register their cleanup functions with this handler rather than setting their own traps.

**How it works:**
1. IOPS writes `__iops_exit_handler.sh` to the repetition folder
2. The generated benchmark script sources this file first
3. The handler sets a single EXIT trap for the entire script
4. Other IOPS scripts register cleanup functions via `_iops_register_exit`
5. When the script exits, all registered functions are called in order

This architecture avoids trap conflicts between multiple IOPS features.

**Always written** when any IOPS feature is enabled.

---

### `__iops_atexit_sysinfo.sh`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_atexit_sysinfo.sh`

**Written:** When the repetition folder is created, before the test runs

**Purpose:** A shell script that collects system information from compute nodes. It registers with the exit handler to collect information after the benchmark completes.

**How it works:**
1. IOPS writes `__iops_atexit_sysinfo.sh` to the repetition folder
2. The generated benchmark script sources this file after the exit handler
3. The script registers `_iops_collect_sysinfo` with the exit handler
4. When the benchmark script exits (success or failure), the function executes
5. System information is written to `__iops_sysinfo.json`

This approach ensures system info is collected even if the benchmark fails, and it runs on the actual compute node (important for SLURM jobs).

**Controlled by:** `benchmark.probes.system_snapshot`

---

### `__iops_sysinfo.json`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_sysinfo.json`

**Written:** At the end of script execution (via exit handler)

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

**Controlled by:** `benchmark.probes.system_snapshot`

---

### `__iops_runtime_sampler.sh`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_runtime_sampler.sh`

**Written:** When the repetition folder is created, before the test runs

**Purpose:** A shell script that collects CPU and memory utilization during benchmark execution. For multi-node SLURM jobs, it launches samplers on all nodes using `srun`.

**How it works:**
1. IOPS writes `__iops_runtime_sampler.sh` to the repetition folder
2. The generated benchmark script sources this file after the exit handler
3. The script creates a sentinel file (`__iops_trace_running`) and starts sampling
4. For single-node: runs the sampling loop locally in the background
5. For multi-node SLURM: uses `srun --overlap` to launch samplers on all nodes
6. Each node writes to its own trace file (`__iops_trace_<hostname>.csv`)
7. When the script exits, the exit handler removes the sentinel file, stopping all samplers

**Controlled by:** `benchmark.probes.resource_sampling`

---

### `__iops_trace_running`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_trace_running`

**Written:** When resource tracing starts (before benchmark runs)

**Removed:** When benchmark script exits (via exit handler)

**Purpose:** A sentinel file that signals resource samplers to keep running. When removed, all samplers (including those on remote nodes in multi-node SLURM jobs) terminate gracefully.

**Controlled by:** `benchmark.probes.resource_sampling`

---

### `__iops_trace_<host>.csv`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_trace_<hostname>.csv`

**Written:** Continuously during benchmark execution by the resource sampler

**Purpose:** Contains per-core CPU and memory utilization samples. For multi-node jobs, each node produces its own file with its hostname in the filename.

**Format:**
```csv
timestamp,hostname,core,cpu_user_pct,cpu_system_pct,cpu_idle_pct,mem_total_kb,mem_available_kb
1705123456.123,node01,0,45.2,5.1,49.7,128000000,64000000
1705123456.123,node01,1,42.1,4.8,53.1,128000000,64000000
```

**Controlled by:** `benchmark.probes.resource_sampling`

---

### `__iops_runtime_gpu_sampler.sh`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_runtime_gpu_sampler.sh`

**Written:** During artifact preparation (before benchmark runs)

**Purpose:** Background GPU sampler script that collects GPU metrics (utilization, memory, temperature, power draw, clock speeds) at configurable intervals. Currently supports NVIDIA GPUs via `nvidia-smi`, with vendor detection designed for future AMD and Intel GPU support. Gracefully skips if no supported GPU is detected.

The sampler follows the same architecture as the CPU/memory sampler:

1. Detects GPU vendor at runtime (`command -v nvidia-smi`)
2. Creates a sentinel file (`__iops_gpu_trace_running`) and starts sampling
3. For single-node: runs the sampling loop locally in the background
4. For multi-node SLURM: uses `srun --overlap` to launch samplers on all nodes
5. Each node writes to its own trace file (`__iops_gpu_trace_<hostname>.csv`)
6. When the script exits, the exit handler removes the sentinel file, stopping all samplers

**Controlled by:** `benchmark.probes.gpu_sampling`

---

### `__iops_gpu_trace_running`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_gpu_trace_running`

**Written:** When GPU tracing starts (before benchmark runs)

**Removed:** When benchmark script exits (via exit handler)

**Purpose:** A sentinel file that signals GPU samplers to keep running. Independent of the CPU/memory sampler sentinel. When removed, all GPU samplers terminate gracefully.

**Controlled by:** `benchmark.probes.gpu_sampling`

---

### `__iops_gpu_trace_<host>.csv`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_gpu_trace_<hostname>.csv`

**Written:** Continuously during benchmark execution by the GPU sampler

**Purpose:** Contains GPU metrics samples for all GPUs on each node. For multi-node jobs, each node produces its own file with its hostname in the filename.

**Format:**
```csv
timestamp,hostname,gpu_index,gpu_name,utilization_gpu_pct,utilization_mem_pct,memory_used_mib,memory_total_mib,temperature_c,power_draw_w,clock_sm_mhz,clock_mem_mhz
1705123456.5,node01,0,NVIDIA A100-SXM4-80GB,85,40,30000,81920,62,250.50,1410,1215
```

**Controlled by:** `benchmark.probes.gpu_sampling`

---

### `__iops_kickoff.sh`

**Location:** `workdir/run_001/__iops_kickoff.sh`

**Written:** When using single-allocation mode, before submitting to SLURM

**Purpose:** The execution script submitted via `sbatch` that runs all tests sequentially within a single SLURM allocation.

**Structure:**
```bash
#!/bin/bash
#SBATCH --nodes=8
#SBATCH --time=02:00:00
#SBATCH --partition=batch
#SBATCH --account=myaccount
#SBATCH --exclusive

# IOPS-managed directives
#SBATCH --job-name=iops_single_alloc
#SBATCH --output=/path/to/workdir/logs/single_alloc_%j.out
#SBATCH --error=/path/to/workdir/logs/single_alloc_%j.err

# User setup commands (modules, env vars from allocation_script)
module purge
module load mpi/openmpi/4.0.1

# IOPS-generated test dispatcher
run_test() {
    # Runs each test with timeout, writes status to __iops_status.json
    ...
}

# Sequential test execution
run_test "/path/to/exec_0001/repetition_001" "run_script.sh" "exec_0001" "1"
run_test "/path/to/exec_0001/repetition_002" "run_script.sh" "exec_0001" "2"
...
```

**Key features:**
- Contains user-provided SBATCH directives from `allocation_script`
- IOPS adds: shebang, job-name (`iops_single_alloc`), output/error paths
- User setup commands (module loads, exports) run once at the start
- Tests run sequentially via the `run_test()` dispatcher function
- Each test respects `test_timeout` (default: 3600s)
- Status files (`__iops_status.json`) updated for each test (RUNNING → SUCCEEDED/FAILED/TIMEOUT)

**Controlled by:** `slurm_options.allocation.mode: "single"`

---

### `__iops_plots/`

**Location:** `workdir/run_001/__iops_plots/`

**Written:** When generating HTML reports via `iops report --export-plots` (requires kaleido)

**Purpose:** Contains image exports of all plots from the HTML report, allowing users to include plots in publications or presentations.

**Structure:**
```
__iops_plots/
├── 001_test_summary.pdf
├── 002_best_configurations_bandwidth.pdf
├── 003_bayesian_evolution_bandwidth.pdf
├── 004_variable_impact_bandwidth.pdf
└── ...
```

**File naming:**
- Files are numbered in the order they appear in the report (001, 002, ...)
- Names include the plot type and metric for easy identification
- Special characters are sanitized to underscores
- Extension matches the chosen format (pdf, png, svg, jpg, webp)

**Controlled by:** `--export-plots` flag when running `iops report`. Requires `kaleido` package (`pip install iops-benchmark[plots]`)

**Supported formats:** Use `--plot-format FORMAT` to select output format (default: pdf)

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
  probes:
    execution_index: false
    system_snapshot: false
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
