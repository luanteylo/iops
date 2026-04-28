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
3. [Inspecting the Cache](#inspecting-the-cache)
4. [Rebuilding the Cache](#rebuilding-the-cache)

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


## Inspecting the Cache

IOPS provides three read-only subcommands to explore what is stored in a cache database.

### `iops cache stats`

Print a summary of the cache: total entries, unique parameter sets, and date range.

```bash
$ iops cache stats cache.db

Cache: cache.db
--------------------------------------------------
Total entries:          28
Unique parameter sets:  14
Distinct repetitions:   2
Oldest entry:           2026-04-06T18:58:32.285294
Newest entry:           2026-04-17T23:53:07.035720
```

### `iops cache list`

List cached entries, collapsed per unique parameter hash. Each row shows a short (8-character) hash, the parameter values, the number of cached repetitions, and metric averages across repetitions.

```bash
$ iops cache list cache.db

Hash      dataset       light_conv  Reps  average_epoch_time_sec  peak_gpu_memory_mib  Last Cached
-----------------------------------------------------------------------------------------------------
57c77ec3  moving_mnist  tied        2     430.72                  10996.97             2026-04-17T23:53:07
096cd29f  taasrad19     sqnxt       2     391.29                  11134.85             2026-04-17T12:21:38
9ec8f1cb  moving_mnist  dws         2     454.16                  11957.98             2026-04-17T11:51:36
...
```

Filter by parameter values using the same `VAR=VALUE` syntax as `iops find`:

```bash
# Only entries where dataset=moving_mnist
iops cache list cache.db dataset=moving_mnist

# Hide metric columns, keep just params and repetition counts
iops cache list cache.db --no-metrics

# Show full parameter values without truncation
iops cache list cache.db --full

# Limit to the 10 most recently cached parameter sets
iops cache list cache.db --limit 10

# Emit JSON for scripting
iops cache list cache.db --json
```

### `iops cache show`

Show full details for a single cached parameter set, including every repetition's metrics and metadata. The hash argument accepts a git-style short prefix:

```bash
$ iops cache show cache.db 57c77e

Hash: 57c77ec316e9b66f3aa9861227fa1a83
Short: 57c77ec3

Parameters:
  dataset: moving_mnist
  light_conv: tied

Repetitions: 2

  rep=1  cached_at=2026-04-08T08:01:27.580146
    metrics:
      average_epoch_time_sec: 428.96
      min_epoch_gen_loss: -293.98
      peak_gpu_memory_mib: 10996.97
      ...
    metadata:
      __executor_status: SUCCEEDED
      __jobid: 4646245
      ...

  rep=2  cached_at=2026-04-17T23:53:07.035720
    ...
```

If the prefix matches multiple hashes, IOPS reports the candidates and asks for a longer prefix:

```bash
$ iops cache show cache.db 5
ERROR | Hash prefix '5' is ambiguous: matches 2 entries (57c77ec3, 58abbe6f). Provide a longer prefix.
```

Use `--full` to disable truncation of long values and `--json` for machine-readable output.

### Python API

The CLI subcommands are thin wrappers around helpers in `iops.cache` that you can call directly:

```python
from iops.cache import (
    list_cache_entries,
    get_cache_entry,
    get_cache_stats,
    resolve_hash_prefix,
    ExecutionCache,
)

# Summary statistics
stats = get_cache_stats("cache.db")
print(f"Total entries: {stats['total_entries']}")
print(f"Unique parameter sets: {stats['unique_parameter_sets']}")

# List entries, filtered and collapsed per parameter hash
entries = list_cache_entries(
    "cache.db",
    param_filters={"dataset": "moving_mnist"},
    limit=10,
)
for e in entries:
    print(e["hash"][:8], e["params"], e["rep_count"], e["metrics"])

# Full detail for a single entry (git-style prefix accepted)
entry = get_cache_entry("cache.db", "57c77e")
for rep in entry["repetitions"]:
    print(rep["repetition"], rep["metrics"])

# Resolve a prefix to a full hash (raises HashPrefixError on ambiguity)
full_hash = resolve_hash_prefix("cache.db", "57c77e")

# Mutating operations still go through ExecutionCache
cache = ExecutionCache("cache.db")
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

