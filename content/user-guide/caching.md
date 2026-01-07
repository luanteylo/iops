---
title: "Execution Cache Usage Guide"
---


## Overview

IOPS now supports intelligent caching of execution results using SQLite. This allows you to:
- Skip re-running tests with identical parameters
- Speed up iterative development and testing
- Safely retry failed runs without re-executing successful tests
- Handle repetitions correctly (each repetition is cached separately)

## Configuration

Add `sqlite_db` to your YAML config:

```yaml
benchmark:
  name: "IOR Benchmark"
  description: "I/O performance testing"
  workdir: "/home/user/workdir/"
  sqlite_db: "/home/user/iops_cache.db"  # Cache database
  repetitions: 3
  executor: "local"
```

## Usage Examples

### Basic Usage

```bash
# First run: executes all tests and caches results
iops config.yaml

# Second run with --use-cache: reuses cached results
iops config.yaml --use-cache
```

### Example Workflow

```bash
# Run with 10 parameter combinations, 3 repetitions each = 30 executions
iops benchmark.yaml

# Oops, let's change the number of repetitions to 5
# Edit YAML: repetitions: 3 -> repetitions: 5

# Re-run with cache: only executes 2 new repetitions per test (20 total)
# The first 3 repetitions are loaded from cache
iops benchmark.yaml --use-cache
```

### Development Workflow

```bash
# Test run with small parameter space
iops test_config.yaml

# Fix a bug in your benchmark script
# Edit scripts[].script_template in YAML

# Re-run: cache is parameter-based, not script-based
# All tests execute again (scripts changed)
iops test_config.yaml

# But if you only change output settings...
# Edit output.sink.path in YAML

# Re-run with cache: tests are skipped, only output regenerated
iops test_config.yaml --use-cache
```

## How It Works

### Parameter Hashing

Each test is uniquely identified by:
1. **Parameters**: All swept and fixed variables (e.g., `nodes=2, processes=16`)
2. **Repetition**: Which repetition this is (1, 2, 3, ...)
3. **Round** (optional): For multi-round optimization workflows

Parameters are normalized before hashing:
- Type normalization: `"8"` and `8` are treated as identical
- Internal keys removed: `__test_index`, `__phase_index`, etc. are ignored
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
- Run 2: `summary_file=/workdir/run_002/summary.txt` → Cache key: `def456` ❌ **Cache miss!**

**Solution**: Use `cache_exclude_vars` to exclude path-based variables:

```yaml
benchmark:
  name: "IOR Benchmark"
  workdir: "/home/user/workdir/"
  sqlite_db: "/home/user/iops_cache.db"
  cache_exclude_vars: ["summary_file"]  # Exclude from cache hash
  repetitions: 3
```

Now both runs match the same cache entry:
- Run 1: Cache key based on `nodes` only → `xyz789`
- Run 2: Cache key based on `nodes` only → `xyz789` ✅ **Cache hit!**

**When to use `cache_exclude_vars`**:
- ✅ Variables containing `{{ execution_dir }}` (changes per run)
- ✅ Variables containing `{{ workdir }}` if workdir changes
- ✅ Timestamp-based variables
- ✅ Any derived path that includes the run number

**When NOT to use `cache_exclude_vars`**:
- ❌ Core benchmark parameters (block_size, transfer_size, etc.)
- ❌ Variables that affect benchmark behavior
- ❌ Variables that affect output correctness

### Cache Schema

```sql
CREATE TABLE cached_executions (
    id INTEGER PRIMARY KEY,
    param_hash TEXT NOT NULL,           -- MD5 hash of normalized params
    params_json TEXT NOT NULL,          -- Full parameters as JSON
    repetition INTEGER NOT NULL,        -- 1, 2, 3, ...
    metrics_json TEXT,                  -- Benchmark metrics
    metadata_json TEXT,                 -- Execution metadata
    round_name TEXT,                    -- Optional round name
    round_index INTEGER,                -- Optional round index
    created_at TEXT NOT NULL,           -- Timestamp
    UNIQUE(param_hash, repetition, round_name)
);
```

### What Gets Cached

**Cached:**
- ✅ Execution metrics (e.g., `bwMiB`, `iops`, `latency`)
- ✅ Execution metadata (status, timestamps, stdout/stderr paths)
- ✅ Only `STATUS_SUCCEEDED` executions

**Not Cached:**
- ❌ Failed executions (`STATUS_FAILED`, `STATUS_ERROR`)
- ❌ Script files (regenerated each time)
- ❌ Log files

### Cache Statistics

When running with `--use-cache`, you'll see:

```
Cache enabled: 45 entries, 15 unique parameter sets
...
Test 1 (repetition 1): Using CACHED result from 2025-12-19T14:30:00
Test 1 (repetition 2): Using CACHED result from 2025-12-19T14:31:00
Test 1 (repetition 3): Executing (not in cache)
...
Cache statistics: 30 hits, 15 misses (66.7% hit rate)
```

## Advanced Usage

### Multi-Round Workflows

Cache is round-aware for optimization workflows:

```yaml
rounds:
  - name: "optimize_nodes"
    sweep_vars: ["nodes"]
    repetitions: 3

  - name: "optimize_processes"
    sweep_vars: ["processes_per_node"]
    repetitions: 3
```

Each round caches results separately. If you re-run:
- Round 1 results are cached and reused
- Round 2 results are cached and reused
- If rounds change, cache is not affected

### Inspecting the Cache

```python
from iops.execution.cache import ExecutionCache
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

### Cache Behavior Details

**When cache is used:**
1. Before each test execution, check if `(params, repetition, round)` exists in cache
2. If found: populate test with cached metrics and metadata, skip execution
3. If not found: execute normally

**When cache is updated:**
1. After successful execution (`STATUS_SUCCEEDED`)
2. Store `(params, repetition, metrics, metadata)` in cache
3. On duplicate (same params/repetition/round): update with latest result

## Troubleshooting

### Cache Not Working

**Problem**: Tests execute even with `--use-cache`

**Solutions**:
1. Check `sqlite_db` is set in YAML:
   ```yaml
   benchmark:
     sqlite_db: "/absolute/path/to/cache.db"
   ```

2. Verify cache file exists and has entries:
   ```bash
   sqlite3 /path/to/cache.db "SELECT COUNT(*) FROM cached_executions;"
   ```

3. Enable debug logging to see cache hits/misses:
   ```bash
   iops config.yaml --use-cache --log-level DEBUG
   ```

### Parameter Mismatch

**Problem**: Parameters seem the same but cache misses

**Possible causes**:

1. **Derived variables with run-specific paths**:
   ```bash
   # Enable debug logging to see what's being hashed
   iops config.yaml --use-cache --log-level DEBUG | grep "param_hash"
   ```

   If you see different hashes for identical parameters, check for variables containing:
   - `{{ execution_dir }}` (contains `run_001`, `run_002`, etc.)
   - `{{ workdir }}` (if workdir changes between runs)
   - Dynamic timestamps or paths

   **Solution**: Add `cache_exclude_vars` to exclude these variables:
   ```yaml
   benchmark:
     cache_exclude_vars: ["summary_file", "output_path", "log_file"]
   ```

2. **Parameter type differences**:
   ```yaml
   # Run 1
   vars:
     nodes:
       type: int
       sweep:
         mode: list
         values: [2, 4, 8]

   # Run 2 (won't match cache!)
   vars:
     nodes:
       type: str
       sweep:
         mode: list
         values: ["2", "4", "8"]
   ```

   **Solution**: Keep parameter types consistent, or rely on normalization (string "8" == int 8)

### Cache Growing Too Large

**Problem**: Cache database is very large

**Solutions**:
1. Clear old entries periodically:
   ```python
   from iops.execution.cache import ExecutionCache
   cache = ExecutionCache(Path("/path/to/cache.db"))
   cache.clear_cache()
   ```

2. Use separate cache files for different experiments:
   ```yaml
   benchmark:
     sqlite_db: "/path/to/experiment1_cache.db"
   ```

## Implementation Details

### File: `iops/execution/cache.py`

**Class**: `ExecutionCache(db_path)`

**Key Methods**:
- `get_cached_result(params, repetition, round_name)` → `Dict | None`
- `store_result(params, repetition, metrics, metadata, ...)`
- `get_cached_repetitions_count(params, round_name)` → `int`
- `get_cache_stats()` → `Dict`
- `clear_cache()`

### Integration: `iops/execution/runner.py`

```python
# In IOPSRunner.__init__()
if args.use_cache and cfg.benchmark.sqlite_db:
    self.cache = ExecutionCache(cfg.benchmark.sqlite_db)

# In IOPSRunner.run()
if self.cache:
    cached = self.cache.get_cached_result(test.vars, test.repetition)
    if cached:
        # Use cached result
        test.metadata.update(cached['metadata'])
    else:
        # Execute and cache
        self.executor.submit(test)
        self.executor.wait_and_collect(test)
        self.cache.store_result(...)
```

## Best Practices

1. **Use absolute paths** for `sqlite_db` to avoid confusion
2. **Keep cache files per project** for organization
3. **Clear cache** when benchmark logic changes significantly
4. **Monitor cache hit rate** to ensure it's working as expected
5. **Commit cache strategy** but not cache files (add `*.db` to `.gitignore`)

## Example .gitignore

```gitignore
# Cache databases
*.db
*_cache.db
iops_cache.db

# But keep schema documentation
!docs/cache_schema.sql
```
