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

Path           nodes  ppn  block_size
exec_001       1      4    1024
exec_002       1      4    4096
exec_003       1      8    1024
exec_004       1      8    4096
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
iops find ./workdir/run_001 VAR=VALUE [VAR2=VALUE2 ...]
```

### Filter by Single Variable

Find all executions with `nodes=4`:

```bash
iops find ./workdir/run_001 nodes=4
```

Output:
```
Benchmark: IOR Performance Study
Found 3 execution(s)
Filter: {'nodes': '4'}

Path           nodes  ppn  block_size
exec_007       4      4    1024
exec_008       4      4    4096
exec_009       4      8    1024
```

### Filter by Multiple Variables

Find executions matching multiple conditions:

```bash
iops find ./workdir/run_001 nodes=4 ppn=8
```

Only executions where **both** `nodes=4` AND `ppn=8` will be shown.

### Filter Examples

```bash
# Find large block size experiments
iops find ./workdir/run_001 block_size=16384

# Find specific configuration
iops find ./workdir/run_001 nodes=8 ppn=16 block_size=4096

# Search across all runs in workdir
iops find ./workdir nodes=4
```

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

### `__iops_sysinfo.json`

Created by the system probe (if enabled). Contains system information about the execution environment.

**Location:** `workdir/run_001/exec_001/repetition_1/__iops_sysinfo.json`

This file includes CPU, memory, and OS information collected when the execution runs.

## Use Cases

### Find Failed Executions

After a benchmark run, you might want to investigate failures:

```bash
# List all executions to see which ones exist
iops find ./workdir/run_001

# Check specific execution folder for error logs
iops find ./workdir/run_001/exec_042
cd ./workdir/run_001/exec_042/repetition_1
cat stderr.txt
```

### Locate Specific Configuration

Find a specific parameter combination for manual inspection:

```bash
# Find the execution with nodes=8, ppn=16
iops find ./workdir/run_001 nodes=8 ppn=16

# Navigate to that execution folder
cd ./workdir/run_001/exec_XXX/repetition_1
ls -la
```

### Explore Large Parameter Sweeps

For experiments with many variables, use filters to narrow down results:

```bash
# How many executions used block_size=4096?
iops find ./workdir/run_001 block_size=4096 | grep "Found"

# What parameter values were tested?
iops find ./workdir/run_001
```

### Extract Results for Specific Tests

Combine `find` with manual result extraction:

```bash
# Find matching executions
iops find ./workdir/run_001 nodes=4

# Navigate to execution folder
cd ./workdir/run_001/exec_007/repetition_1

# Extract specific results
cat stdout.txt | grep "Bandwidth"
```

## Portable Workdirs

All paths in `__iops_index.json` are stored as relative paths. This means you can:

- **Archive workdirs** and unpack them anywhere
- **Move workdirs** between systems
- **Share results** with collaborators
- **Access workdirs** from different mount points

The `find` command will work correctly regardless of where the workdir is located.

## Next Steps

- Learn about [Analysis & Reports](analysis.md) for generating visualizations
- Understand [Result Caching](caching.md) to skip redundant tests
- Explore [Custom Reports & Visualization](reporting.md) for customizing report output
