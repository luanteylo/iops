---
title: "Caching"
weight: 6
---

---

## Table of Contents

1. [Overview](#overview)
2. [Configuration](#configuration)
   - [Basic Usage](#basic-usage)
   - [Consolidating Runs with --resume](#consolidating-runs-with---resume)
   - [Cache-Only Mode](#cache-only-mode)
3. [Rebuilding the Cache](#rebuilding-the-cache)

---

## Overview

IOPS supports intelligent caching of execution results using SQLite. This allows you to:
- Skip re-running tests with identical parameters
- Speed up iterative development and testing
- Safely retry failed runs without re-executing successful tests
- Handle repetitions correctly (each repetition is cached separately)

**Warning: Use caching with caution.** The cache key is computed only from variable values, not from the command template. If you change your command (e.g., from `./benchmark {{ var1 }}` to `./benchmark -F {{ var1 }}`), the cache will still return old results because the parameters haven't changed. This can lead to incorrect results. See [Command Changes Are Not Detected](#important-command-changes-are-not-detected) for details and workarounds.

## Configuration

Add `cache_file` to your YAML config:

```yaml
benchmark:
  name: "IOR Benchmark"
  description: "I/O performance testing"
  workdir: "/home/user/workdir/"
  cache_file: "/home/user/iops_cache.db"  # Cache database
  repetitions: 3
  executor: "local"
```


### Basic Usage

```bash
# First run: executes all tests and caches results
iops run config.yaml

# Second run with --use-cache: reuses cached results
iops run config.yaml --use-cache
```

### Consolidating Runs with `--resume`

By default, every invocation of `iops run` creates a fresh `run_NNN/` folder. When combined with `--use-cache`, this scatters a single study across many folders: each new `run_NNN/results.csv` contains rows for cached executions, but the actual `exec_XXXX/` artifact folders stay in the original run where they first executed. Browsing the study means hopping between `run_002/`, `run_003/`, etc.

The `--resume` flag reuses an existing run folder instead of creating a new one, so new executions land alongside the existing ones:

```bash
# First run: creates run_001 with exec_0001, exec_0002
iops run config.yaml

# ... edit config to add a new sweep value ...

# Resume the latest run: adds exec_0003 to run_001 (existing execs untouched)
iops run config.yaml --resume

# Or resume a specific run folder
iops run config.yaml --resume run_001
```

On resume:
- New `exec_XXXX` ids start strictly above the current max in `runs/`, so folders never collide.
- Combinations already recorded in `__iops_index.json` are skipped before id assignment. No duplicate rows in `results.csv`, no ghost ids pointing to non-existent folders.
- The original `benchmark_start_time` in `__iops_run_metadata.json` is preserved; only the end time and total runtime are refreshed.
- The original `__iops_config.yaml` is kept intact. The new config is archived as `__iops_config_resume_<timestamp>.yaml` for audit.
- A `__iops_resume.lock` file guards against concurrent resumes into the same folder.

`--resume` is not currently supported with `--dry-run`, adaptive search, or Bayesian optimization.

### Cache-Only Mode

The `--cache-only` flag runs IOPS using only cached results, skipping any tests not found in the cache. This is useful for:

- Regenerating CSV/output files from an existing cache without running new tests
- Extracting a subset of results from a large campaign
- Verifying what's in the cache without executing anything

```bash
# Only use cached results, skip tests not in cache
iops run config.yaml --cache-only

# Preview what would be cached vs skipped
iops run config.yaml --cache-only --dry-run
```

**Behavior:**
- Tests found in cache are loaded and written to the output file
- Tests not in cache are marked as `SKIPPED` with reason "Not in cache (cache-only mode)"
- Skipped tests appear in `iops find --status SKIPPED`
- The final summary shows how many tests were from cache vs skipped

**Example output:**
```
[  1] exec_0001 (rep 1/1) → SUCCEEDED [CACHED] | result=100
[  2] exec_0002 (rep 1/1) -> SKIPPED (not in cache)
[  3] exec_0003 (rep 1/1) → SUCCEEDED [CACHED] | result=200

Benchmark completed (cache-only mode): 3 tests processed
  From cache: 2
  Skipped (not in cache): 1
```

**Note:** `--cache-only` requires `benchmark.cache_file` to be configured in the YAML file. Using `--cache-only` automatically enables `--use-cache`.


### Parameter Hashing

Each test is uniquely identified by:
1. **Parameters**: All swept and fixed variables (e.g., `nodes=2, processes=16`)
2. **Repetition**: Which repetition this is (1, 2, 3, ...)

Parameters are normalized before hashing:
- Type normalization: `"8"` and `8` are treated as identical
- Internal keys removed: `__test_index`, etc. are ignored
- Excluded variables removed: Variables in `cache_exclude_vars` are skipped
- Sorted consistently: Order doesn't matter

### Excluding Variables from Cache

**Problem**: Some derived variables contain run-specific paths that change between executions, causing unnecessary cache misses.

**Example**:
```yaml
vars:
  nodes:
    type: int
    sweep: { mode: list, values: [2, 4, 8] }

  summary_file:
    type: str
    expr: "{{ execution_dir }}/summary.txt"  # Contains run_001, run_002, etc.
```

Without exclusion:
- Run 1: `summary_file=/workdir/run_001/summary.txt` → Cache key: `abc123`
- Run 2: `summary_file=/workdir/run_002/summary.txt` → Cache key: `def456` **Cache miss!**

(Note: using `--resume` sidesteps this by keeping all executions inside the same `run_NNN/` folder so `execution_dir` stays stable. `cache_exclude_vars` is still the right tool when you need cache hits across distinct run folders, machines, or archives.)

**Solution**: Use `cache_exclude_vars` to exclude path-based variables:

```yaml
benchmark:
  name: "IOR Benchmark"
  workdir: "/home/user/workdir/"
  cache_file: "/home/user/iops_cache.db"
  cache_exclude_vars: ["summary_file"]  # Exclude from cache hash
  repetitions: 3
```


### Cache Schema

```sql
CREATE TABLE cached_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    param_hash TEXT NOT NULL,           -- MD5 hash of normalized params
    params_json TEXT NOT NULL,          -- Full parameters as JSON
    repetition INTEGER NOT NULL,        -- 1, 2, 3, ...
    metrics_json TEXT,                  -- Benchmark metrics
    metadata_json TEXT,                 -- Execution metadata
    created_at TEXT NOT NULL,           -- Timestamp
    UNIQUE(param_hash, repetition)
);

-- Index for fast lookups
CREATE INDEX idx_param_hash ON cached_executions(param_hash, repetition);
```

### Important: Command Changes Are Not Detected

**Warning**: The cache hash is computed **only from variables**, not from the command template itself. This is intentional—commands often contain paths like `{{ execution_dir }}` that change between runs but shouldn't invalidate the cache.

However, this means that if you modify your command template in ways that affect results, the cache will still return old results:

```yaml
# Original command
command:
  template: "fio --name=test --rw=read --bs={{ block_size }}"

# Modified command (added --direct=1 for unbuffered I/O)
command:
  template: "fio --name=test --rw=read --bs={{ block_size }} --direct=1"
```

Since `block_size` hasn't changed, the cache hash remains the same, and you'll get stale results that don't reflect the `--direct=1` behavior.

**Solutions:**
1. **Clear the cache** when changing command behavior: delete the cache file or use `cache.clear_cache()`
2. **Add a version variable** to force cache invalidation:
   ```yaml
   vars:
     cache_version:
       type: int
       value: 2  # Increment when command changes
   ```
3. **Use a new cache file** for different command configurations

### What Gets Cached

**Cached:**
- Execution metrics (e.g., `bwMiB`, `iops`, `latency`)
- Execution metadata (status, timestamps, job IDs)
- Only `STATUS_SUCCEEDED` executions

**Not Cached:**
- Failed executions (`STATUS_FAILED`, `STATUS_ERROR`)
- Script files (regenerated each time)
- stdout/stderr file contents (only exist for executed tests)
- Log files


### Inspecting the Cache

```python
from iops.cache import ExecutionCache
from pathlib import Path

cache = ExecutionCache(Path("/path/to/cache.db"))

# Get statistics
stats = cache.get_cache_stats()
print(f"Total entries: {stats['total_entries']}")
print(f"Unique parameter sets: {stats['unique_parameter_sets']}")
print(f"Date range: {stats['oldest_entry']} to {stats['newest_entry']}")

# Clear cache if needed
cache.clear_cache()
```

## Rebuilding the Cache

The `iops cache rebuild` command allows you to modify an existing cache database by:
- **Excluding variables** from the hash (consolidating entries that now hash to the same value)
- **Adding variables** with constant values to all entries (enabling cache reuse after config changes)

### Usage

```bash
# Exclude variables from hash
iops cache rebuild cache.db --exclude summary_file,output_path -o new_cache.db

# Add a variable to all entries (with type)
iops cache rebuild cache.db --add use_new_flag:bool=false -o new_cache.db

# Add multiple variables
iops cache rebuild cache.db --add cluster:str=skylake --add version:int=2 -o new_cache.db

# Combine exclude and add
iops cache rebuild cache.db --exclude output_path --add use_feature:bool=true -o new_cache.db
```

### Adding Variables (Type Syntax)

When adding variables, you can specify the type to ensure it matches your YAML config:

```bash
--add VAR:TYPE=VALUE
```

| Type | Examples | Notes |
|------|----------|-------|
| `str` | `--add label=test` | Default if no type specified |
| `int` | `--add count:int=10` | |
| `float` | `--add rate:float=1.5` | |
| `bool` | `--add flag:bool=false` | Accepts: true/false, yes/no, 1/0 |

**Why types matter**: The cache hash depends on both the value and its type. If your YAML defines `use_feature: { type: bool, ... }`, you must add it as `--add use_feature:bool=false` (not just `--add use_feature=false`) for the hashes to match.

### Example: Excluding Path Variables

You ran 100 executions but forgot to exclude a path-based variable:

```yaml
vars:
  nodes:
    type: int
    sweep: { mode: list, values: [2, 4, 8] }
  output_file:
    type: str
    expr: "{{ execution_dir }}/results.txt"  # Oops! Should have been excluded
```

The cache has 100 unique hashes because `output_file` differs for each execution. After rebuilding:

```bash
$ iops cache rebuild cache.db --exclude output_file

Cache Rebuild Summary
==================================================
Source entries:        100
Source unique hashes:  100
Excluded variables:    output_file
Added variables:       (none)
--------------------------------------------------
Output entries:        100
Output unique hashes:  3
Collapsed entries:     97
==================================================
Rebuilt cache saved to: cache_rebuilt.db
```

### Example: Adding a New Variable

You have a cache from previous runs and want to add a new variable to your config:

**Original config (already executed):**
```yaml
vars:
  nodes:
    type: int
    sweep: { mode: list, values: [2, 4, 8] }
```

**New config (with additional variable):**
```yaml
vars:
  nodes:
    type: int
    sweep: { mode: list, values: [2, 4, 8] }
  use_new_optimization:
    type: bool
    sweep: { mode: list, values: [false, true] }
```

To reuse the existing cache for `use_new_optimization=false` cases:

```bash
$ iops cache rebuild cache.db --add use_new_optimization:bool=false -o new_cache.db

Cache Rebuild Summary
==================================================
Source entries:        3
Source unique hashes:  3
Excluded variables:    (none)
Added variables:       use_new_optimization=False
--------------------------------------------------
Output entries:        3
Output unique hashes:  3
Collapsed entries:     0
==================================================
Rebuilt cache saved to: new_cache.db
```

Now `iops run new_config.yaml --use-cache` will find cache hits for `use_new_optimization=false` and only execute the `use_new_optimization=true` cases.

### How It Works

1. Reads all entries from the source cache
2. Adds new variables to each entry's parameters (if `--add` specified)
3. Re-normalizes parameters excluding specified variables (if `--exclude` specified)
4. Re-computes the hash for each entry
5. Writes all entries to the new database

**Important**: When multiple entries collapse to the same `(hash, repetition)`, all entries are preserved. The rebuilt database does not enforce uniqueness, allowing you to keep all historical data. When reading from the cache, IOPS uses `ORDER BY created_at DESC LIMIT 1` to return the most recent entry.

### After Rebuilding

1. Update your YAML config to use the rebuilt cache:
   ```yaml
   benchmark:
     cache_file: "./workdir/new_cache.db"
     cache_exclude_vars: ["output_file"]  # If you excluded variables
   ```

2. Future runs with `--use-cache` will now find cache hits for matching parameters.

### Cache Behavior Details

**When cache is used:**
1. Before each test execution, check if `(params, repetition)` exists in cache
2. If found: populate test with cached metrics and metadata, skip execution
3. If not found: execute normally

**When cache is updated:**
1. After successful execution (`STATUS_SUCCEEDED`)
2. Store `(params, repetition, metrics, metadata)` in cache
3. On duplicate (same params/repetition): update with latest result

### Core-Hours Savings Tracking

When using cache with a core-hours budget (`max_core_hours`), cached tests don't count toward the budget and IOPS tracks how many core-hours were saved. This appears in progress logs and final summary.

See the **[Budget Control](../budget-control#cache-interaction)** guide for details.

