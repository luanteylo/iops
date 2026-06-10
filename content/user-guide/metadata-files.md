---
title: "Metadata Files"
weight: 80
---

IOPS generates metadata files with the `__iops_` prefix to track executions, enable fast lookups, and support report generation. This page documents each file, when it is written, and how to control its generation.

---

## Table of Contents

1. [I/O Overhead Considerations](#io-overhead-considerations)
2. [Metadata Files Overview](#metadata-files-overview)
3. [Controlling Metadata Generation](#controlling-metadata-generation)
4. [File Reference](#file-reference)
5. [Best Practices](#best-practices)

---

## I/O Overhead Considerations

Metadata files are written to the **workdir** during benchmark execution. They are small (typically a few KB each), but consider disabling them when:

- **Workdir is on the tested filesystem**: metadata writes can interfere with measurements; either disable them or place the workdir on a separate filesystem.
- **Running thousands of sub-second tests**: per-execution JSON writes may become noticeable.
- **Using high-latency network filesystems**: metadata writes can add latency between tests.

Metadata is safe when the workdir is on a separate filesystem from the test target, tests run for several seconds or longer, or you need `iops find` or `iops report` functionality.

## Metadata Files Overview

### Run-Level Files

Located in `workdir/run_XXX/`:

| File | Purpose |
|------|---------|
| `__iops_run_metadata.json` | Report generation (config, timing, variables) |
| `__iops_index.json` | Fast execution lookup for `iops find` |
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

These files capture all output from script execution and parsing, useful for debugging failed tests; parser output files are only created if the parser produces output.

### System Info Files

Located in `workdir/run_XXX/exec_XXXX/repetition_X/`:

| File | Purpose |
|------|---------|
| `__iops_exit_handler.sh` | Centralized EXIT trap coordinator |
| `__iops_atexit_sysinfo.sh` | System info collection script |
| `__iops_sysinfo.json` | Hardware/environment info (generated at exit) |
| `__iops_atexit_versions.sh` | Software version capture script (versions probe) |
| `__iops_versions.json` | Captured software/library versions (generated at exit) |

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

Disables `__iops_index.json`, `__iops_params.json`, `__iops_skipped`, and `__iops_status.json`:

```yaml
benchmark:
  probes:
    execution_index: false
```

**Impact:** `iops find` and watch mode (`--watch`) will not work for these runs; reduces I/O by 3 small JSON writes per execution.

### Disable System Information Collection

Disables `__iops_atexit_sysinfo.sh` and `__iops_sysinfo.json`:

```yaml
benchmark:
  probes:
    system_snapshot: false
```

**Impact:** system environment info will not appear in HTML reports; removes the system info script injection from generated scripts; reduces I/O by 1 small JSON write per repetition.

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

**Purpose:** Metadata about the benchmark run, used by `iops report` to generate HTML reports without re-running the benchmark.

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

**Purpose:** Marker file for skipped tests; if absent, watch mode assumes the test is pending or active.

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

**Written:** When a job is submitted (initial status), after each repetition completes or fails, and during SLURM job execution when status changes (PENDING → RUNNING)

**Purpose:** Tracks repetition execution status for `iops find` filtering and watch mode, including real-time status updates during SLURM jobs.

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

**Other fields:**

- `error` - error message when status is FAILED or ERROR
- `cached` - `true` if the result was retrieved from cache (set when running with `--use-cache` and a cached result is found)
- `duration_seconds` - actual execution time in seconds from the probe script, available for both executed and cached results (the sysinfo is stored in the cache)

**Controlled by:** `benchmark.probes.execution_index`

---

### `__iops_exit_handler.sh`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_exit_handler.sh`

**Written:** When the repetition folder is created, before the test runs

**Purpose:** Centralized EXIT trap that coordinates cleanup for all IOPS features. The generated benchmark script sources this file first; it sets a single EXIT trap, and other IOPS scripts register cleanup functions via `_iops_register_exit` instead of setting their own traps, avoiding trap conflicts. On exit, registered functions run in order.

**Always written** when any IOPS feature is enabled.

---

### `__iops_atexit_sysinfo.sh`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_atexit_sysinfo.sh`

**Written:** When the repetition folder is created, before the test runs

**Purpose:** Collects system information from compute nodes. The generated benchmark script sources it after the exit handler; it registers `_iops_collect_sysinfo`, which writes `__iops_sysinfo.json` when the script exits (success or failure). This ensures system info is collected even if the benchmark fails, and on the actual compute node (important for SLURM jobs).

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

### `__iops_atexit_versions.sh`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_atexit_versions.sh`

**Written:** When the repetition folder is created, before the test runs (when `benchmark.probes.versions` is configured)

**Purpose:** Captures software and library versions for the execution. The generated benchmark script sources it, registering the capture function with the centralized exit handler. On exit, after the benchmark body (so tools loaded by the benchmark's own `module load` commands are in scope), it runs each configured command, captures stdout (up to 4000 bytes), and writes `__iops_versions.json`. Capture is best-effort: a failing command records an empty string rather than aborting the run.

**Controlled by:** `benchmark.probes.versions`

---

### `__iops_versions.json`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_versions.json`

**Written:** On script exit, after the benchmark body has run (via the exit handler)

**Purpose:** Contains software and library versions captured by the version probe. The HTML report reads these files to render the Software Versions section. The same values are also written to the results sink as `version.<component>` columns, so versions can be queried alongside the metrics.

**Structure:**
```json
{
  "app": "myapp 2.3.1",
  "mpi": "OpenMPI 4.1.5",
  "compiler": "gcc (GCC) 11.3.0"
}
```

Each key is the component name defined in `benchmark.probes.versions`. The value is the trimmed stdout of the configured command, or an empty string if the command failed.

**Drift detection:** During report generation, components with more than one distinct value across executions trigger a drift warning in the Software Versions section (the study may mix results from different software environments or cached results from an older run).

**Controlled by:** `benchmark.probes.versions`

---

### `__iops_runtime_sampler.sh`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_runtime_sampler.sh`

**Written:** When the repetition folder is created, before the test runs

**Purpose:** Collects CPU and memory utilization during benchmark execution. The generated benchmark script sources it after the exit handler. It creates the sentinel file `__iops_trace_running` and starts sampling: locally in the background for single-node jobs, or via `srun --overlap` on all nodes for multi-node SLURM jobs. Each node writes its own trace file (`__iops_trace_<hostname>.csv`). On exit, the exit handler removes the sentinel file, stopping all samplers.

**Controlled by:** `benchmark.probes.resource_sampling`

---

### `__iops_trace_running`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_trace_running`

**Written:** When resource tracing starts (before benchmark runs)

**Removed:** When benchmark script exits (via exit handler)

**Purpose:** Sentinel file that signals resource samplers to keep running. Removing it gracefully terminates all samplers, including those on remote nodes in multi-node SLURM jobs.

**Controlled by:** `benchmark.probes.resource_sampling`

---

### `__iops_trace_<host>.csv`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_trace_<hostname>.csv`

**Written:** Continuously during benchmark execution by the resource sampler

**Purpose:** Contains per-core CPU and memory utilization samples, one file per node.

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

**Purpose:** Collects GPU metrics (utilization, memory, temperature, power draw, clock speeds) at configurable intervals. Currently supports NVIDIA GPUs via `nvidia-smi` (detected with `command -v nvidia-smi`), with vendor detection designed for future AMD and Intel support; gracefully skips if no supported GPU is detected. Follows the same architecture as the CPU/memory sampler: a sentinel file (`__iops_gpu_trace_running`), local or `srun --overlap` multi-node sampling, one trace file per node, and shutdown via the exit handler.

**Controlled by:** `benchmark.probes.gpu_sampling`

---

### `__iops_gpu_trace_running`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_gpu_trace_running`

**Written:** When GPU tracing starts (before benchmark runs)

**Removed:** When benchmark script exits (via exit handler)

**Purpose:** Sentinel file that signals GPU samplers to keep running; independent of the CPU/memory sampler sentinel.

**Controlled by:** `benchmark.probes.gpu_sampling`

---

### `__iops_gpu_trace_<host>.csv`

**Location:** `workdir/run_001/exec_0001/repetition_1/__iops_gpu_trace_<hostname>.csv`

**Written:** Continuously during benchmark execution by the GPU sampler

**Purpose:** Contains GPU metrics samples for all GPUs on each node, one file per node.

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
...
```

**Key features:**
- User-provided SBATCH directives come from `allocation_script`; IOPS adds the shebang, job-name (`iops_single_alloc`), and output/error paths
- User setup commands (module loads, exports) run once at the start
- Tests run sequentially via the `run_test()` dispatcher; each respects `test_timeout` (default: 3600s)
- Status files (`__iops_status.json`) updated for each test (RUNNING → SUCCEEDED/FAILED/TIMEOUT)

**Controlled by:** `slurm_options.allocation.mode: "single"`

---

### `__iops_plots/`

**Location:** `workdir/run_001/__iops_plots/`

**Written:** When generating HTML reports via `iops report --export-plots` (requires kaleido)

**Purpose:** Contains image exports of all plots from the HTML report, for use in publications or presentations.

**Structure:**
```
__iops_plots/
├── 001_test_summary.pdf
├── 002_best_configurations_bandwidth.pdf
└── ...
```

**File naming:** Files are numbered in report order (001, 002, ...); names include the plot type and metric, with special characters sanitized to underscores; the extension matches the chosen format (pdf, png, svg, jpg, webp).

**Controlled by:** `--export-plots` flag when running `iops report` (use `--plot-format FORMAT` to select the format, default: pdf). Requires the `kaleido` package (`pip install iops-benchmark[plots]`).

## Best Practices

### For I/O Benchmarks

When benchmarking storage systems, place your workdir on a **different** filesystem than the one being tested (e.g., `workdir: "/local/scratch/iops_workdir"` while the benchmark targets `/lustre/project/data`). If you must use the same filesystem, disable metadata:

```yaml
benchmark:
  name: "Lustre I/O Benchmark"
  workdir: "/lustre/project/benchmark"
  probes:
    execution_index: false
    system_snapshot: false
```

### For Production Runs

Keep metadata enabled for post-run analysis with `iops find`, HTML report generation, debugging failed executions, and watch mode monitoring.

### For Large Parameter Sweeps

With thousands of executions, consider:
- Using `create_folders_upfront: false` (default) to create folders lazily
- Placing workdir on a fast local filesystem (SSD if available)
