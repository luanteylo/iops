---
title: "Exploring Executions"
---


IOPS provides tools to explore, search, and inspect execution folders after running benchmarks. This is especially useful for large parameter sweeps where you need to find specific configurations or investigate failures.

## Finding Executions

Use the `find` command to locate and display execution folders with their parameters:

```bash
iops find /path/to/workdir
```

The `find` command works with three types of paths:

1. **Run root directory** - Contains `__iops_index.json`
2. **Workdir with multiple runs** - Contains `run_001/`, `run_002/`, etc.
3. **Specific execution folder** - Contains `__iops_params.json`

### List All Executions in a Run

```bash
iops find ./workdir/run_001
```

Output example:
```
Benchmark: IOR Performance Study
Found 12 execution(s)

Path           Status      nodes  ppn  block_size
exec_001       SUCCEEDED   1      4    1024
exec_002       SUCCEEDED   1      4    4096
exec_003       FAILED      1      8    1024
exec_004       SUCCEEDED   1      8    4096
...
```



### List Executions from Multiple Runs

If you point to a workdir containing multiple `run_XXX` folders, IOPS displays executions from all runs:

```bash
iops find ./workdir
```

Output:
```
=== run_001 ===
Benchmark: IOR Performance Study
Found 12 execution(s)
...

=== run_002 ===
Benchmark: IOR Performance Study
Found 8 execution(s)
...
```

### Show Details for Specific Execution

```bash
iops find ./workdir/run_001/exec_042
```

Output:
```
Execution: exec_042
Path: /absolute/path/to/workdir/run_001/exec_042

Parameters:
  block_size: 4096
  nodes: 4
  ppn: 8

Repetitions: 3
  repetition_1/
  repetition_2/
  repetition_3/
```

## Filtering Executions

Filters are specified as positional arguments to find executions matching specific parameter values:

```bash
# Find large block size experiments
iops find ./workdir/run_001 block_size=16384

# Find specific configuration
iops find ./workdir/run_001 nodes=8 ppn=16 block_size=4096

# Search across all runs in workdir
iops find ./workdir nodes=4
```

## Advanced Options

### Show Full Parameter Values

By default, IOPS truncates parameter values at 30 characters for readability. Use `--full` to show complete values:

```bash
iops find ./workdir/run_001 --full
```

This is useful when working with long string parameters like file paths.

### Hide Columns

Hide specific columns to focus on relevant parameters:

```bash
# Hide nodes and ppn columns
iops find ./workdir/run_001 --hide nodes,ppn

# Hide multiple columns
iops find ./workdir/run_001 --hide block_size,transfer_size,command
```

Column names are comma-separated without spaces.

### Filter by Status

Find executions based on their completion status:

```bash
# Find all failed executions
iops find ./workdir/run_001 --status FAILED

# Find successful executions
iops find ./workdir/run_001 --status SUCCEEDED

# Find executions with errors
iops find ./workdir/run_001 --status ERROR

# Find pending executions
iops find ./workdir/run_001 --status PENDING
```

**Status values:**
- `SUCCEEDED` - Execution completed successfully
- `FAILED` - Execution failed with non-zero exit code
- `ERROR` - Execution encountered an error during setup
- `SKIPPED` - Execution was skipped (constraint violation or planner selection)
- `UNKNOWN` - Status could not be determined
- `PENDING` - Execution has not yet completed

### Combining Options

Options can be combined with parameter filters:

```bash
# Find failed executions with specific parameters
iops find ./workdir/run_001 nodes=8 --status FAILED

# Show full values for specific configuration
iops find ./workdir/run_001 nodes=4 ppn=8 --full --show-command

# Hide columns and filter by status
iops find ./workdir/run_001 --hide block_size --status SUCCEEDED
```

## Watch Mode

Watch mode provides real-time monitoring of benchmark execution progress. It displays a live-updating table showing execution status, parameters, and progress.

### Enabling Watch Mode

```bash
iops find ./workdir/run_001 --watch
```

Or using the short flag:

```bash
iops find ./workdir/run_001 -w
```

### Requirements

Watch mode requires the `rich` library. Install it with:

```bash
pip install iops-benchmark[watch]
```

Or install `rich` directly:

```bash
pip install rich
```

### Display Features

The watch mode display includes:

- **Progress bar** showing overall completion percentage
- **Status summary** with counts for each status (RUNNING, PENDING, SUCCEEDED, etc.)
- **Live table** with execution parameters and status
- **Repetition tracking** showing status of each repetition (e.g., `SSS` for 3 succeeded)
- **Auto-refresh** at configurable intervals

![Watch Mode Interface](/images/watch_feature.png)

### Watch Mode Options

```bash
# Custom refresh interval (default: 5 seconds)
iops find ./workdir/run_001 --watch --interval 2

# Watch with parameter filters
iops find ./workdir/run_001 nodes=4 --watch

# Watch with status filter
iops find ./workdir/run_001 --watch --status RUNNING

# Watch with hidden columns
iops find ./workdir/run_001 --watch --hide block_size,transfer_size
```

### Status Indicators

In watch mode, status is displayed using compact symbols:

| Symbol | Status | Meaning |
|--------|--------|---------|
| `S` | SUCCEEDED | Execution completed successfully |
| `R` | RUNNING | Currently executing |
| `W` | PENDING | Waiting to execute |
| `F` | FAILED | Execution failed |
| `E` | ERROR | Error during setup |
| `X` | SKIPPED | Skipped (constraint or planner) |
| `?` | UNKNOWN | Status unknown |

For multiple repetitions, status is shown as a sequence (e.g., `SRW` means repetition 1 succeeded, repetition 2 is running, repetition 3 is pending).

### Exiting Watch Mode

Press `Ctrl+C` to exit watch mode and return to the terminal.

## IOPS Metadata Files

IOPS generates metadata files with the `__iops_` prefix to enable fast execution lookup without parsing full result databases:

### `__iops_index.json`

Created in the run root directory. Contains an index of all executions with their parameters and relative paths.

**Location:** `workdir/run_001/__iops_index.json`

**Structure:**
```json
{
  "benchmark": "IOR Performance Study",
  "executions": {
    "exec_001": {
      "path": "exec_001",
      "params": {
        "nodes": 1,
        "ppn": 4,
        "block_size": 1024
      },
      "command": "mpirun -np 4 ./benchmark --nodes 1"
    },
    "exec_002": {
      "path": "exec_002",
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

### `__iops_params.json`

Created in each execution folder. Stores the parameter values for that specific execution.

**Location:** `workdir/run_001/exec_042/__iops_params.json`

**Structure:**
```json
{
  "nodes": 4,
  "ppn": 8,
  "block_size": 4096
}
```

### `__iops_status.json`

Created in each execution folder after execution completes. Stores execution status and error information.

**Location:** `workdir/run_001/exec_042/__iops_status.json`

**Structure:**
```json
{
  "status": "SUCCEEDED",
  "error": null,
  "end_time": "2026-01-09T14:23:45.678901"
}
```

The `error` field contains the error message when status is FAILED or ERROR.

### `__iops_sysinfo.json`

Created by the system probe (if enabled). Contains system information about the execution environment.

**Location:** `workdir/run_001/exec_001/repetition_1/__iops_sysinfo.json`

This file includes CPU, memory, and OS information collected when the execution runs.

## Disabling Metadata Generation

If file I/O overhead is a concern or you don't need the `iops find` functionality, you can disable metadata generation:

```yaml
benchmark:
  track_executions: false
```

When disabled, IOPS will not create `__iops_index.json`, `__iops_params.json`, or `__iops_status.json` files, and the `iops find` command will not work for those runs.



## Portable Workdirs

All paths in `__iops_index.json` are stored as relative paths. This means you can:

- **Archive workdirs** and unpack them anywhere
- **Move workdirs** between systems
- **Share results** with collaborators
- **Access workdirs** from different mount points

The `find` command will work correctly regardless of where the workdir is located.

