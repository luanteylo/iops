---
title: "Caching"
weight: 6
---

---

## Table of Contents

1. [Overview](#overview)
2. [Configuration](#configuration)
   - [Basic Usage](#basic-usage)
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

Sometimes you discover after a long campaign of executions that a variable should have been excluded from the cache hash. For example, a path-based variable was included, causing every execution to have a unique hash even when the benchmark parameters were identical.

The `iops cache rebuild` command allows you to create a new cache database with different excluded variables, consolidating entries that now hash to the same value.

### Usage

```bash
# Rebuild cache excluding additional variables
iops cache rebuild ./workdir/__iops_cache.db --exclude summary_file,output_path

# Specify output file (default: <source>_rebuilt.db)
iops cache rebuild ./workdir/__iops_cache.db --exclude summary_file -o new_cache.db
```

### Example Scenario

You ran 100 executions with this configuration:

```yaml
vars:
  nodes:
    type: int
    sweep: { mode: list, values: [2, 4, 8] }
  output_file:
    type: str
    expr: "{{ execution_dir }}/results.txt"  # Oops! Should have been excluded
```

The cache now has 100 unique hashes because `output_file` differs for each execution. After rebuilding with `--exclude output_file`, entries with the same `nodes` value will collapse to the same hash.

```bash
$ iops cache rebuild cache.db --exclude output_file

Cache Rebuild Summary
==================================================
Source entries:        100
Source unique hashes:  100
Excluded variables:    output_file
--------------------------------------------------
Output entries:        100
Output unique hashes:  3
Collapsed entries:     97
==================================================
Rebuilt cache saved to: cache_rebuilt.db
```

### How It Works

1. Reads all entries from the source cache
2. Re-normalizes parameters excluding the specified variables
3. Re-computes the hash for each entry
4. Writes all entries to the new database

**Important**: When multiple entries collapse to the same `(hash, repetition)`, all entries are preserved. The rebuilt database does not enforce uniqueness, allowing you to keep all historical data. When reading from the cache, IOPS uses `ORDER BY created_at DESC LIMIT 1` to return the most recent entry.

### After Rebuilding

1. Update your YAML config to use the rebuilt cache and add the excluded variables:
   ```yaml
   benchmark:
     cache_file: "./workdir/cache_rebuilt.db"
     cache_exclude_vars: ["output_file"]  # Prevent future issues
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

