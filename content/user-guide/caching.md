---
title: "Caching"
weight: 50
---

---

## Table of Contents

1. [Overview](#overview)
2. [Configuration](#configuration)
   - [Basic Usage](#basic-usage)
   - [Cache-Only Mode](#cache-only-mode)
   - [Parameter Hashing](#parameter-hashing)
   - [Excluding Variables from Cache](#excluding-variables-from-cache)
   - [Command Changes](#command-changes)
   - [Caches from Older Versions](#caches-from-older-versions)
   - [Cache Schema](#cache-schema)
   - [What Gets Cached](#what-gets-cached)
3. [Inspecting the Cache](#inspecting-the-cache)
4. [Rebuilding the Cache](#rebuilding-the-cache)

---

## Overview

IOPS caches execution results in SQLite so that tests with identical parameters can be skipped on re-runs. This speeds up iterative development, lets you safely retry failed runs without re-executing successful tests, and handles repetitions correctly (each repetition is cached separately).

The cache key is made of the variable values and a fingerprint of the `command` section. Changing `command.template` or `command.env` (e.g., from `./benchmark {{ var1 }}` to `./benchmark -F {{ var1 }}`) makes earlier results stop matching. Changes to the script template do **not** affect the key. See [Command Changes](#command-changes) for what this means when writing a configuration.

## Configuration

Add `cache_file` to your YAML config:

```yaml
benchmark:
  name: "IOR Benchmark"
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

The `--cache-only` flag runs IOPS using only cached results, skipping any tests not found in the cache. Use it to regenerate CSV/output files from an existing cache, extract a subset of results from a large campaign, or verify what's in the cache without executing anything.

```bash
# Only use cached results, skip tests not in cache
iops run config.yaml --cache-only

# Preview what would be cached vs skipped
iops run config.yaml --cache-only --dry-run
```

Tests found in cache are loaded and written to the output file. Tests not in cache are marked as `SKIPPED` with reason "Not in cache (cache-only mode)" and appear in `iops find --status SKIPPED`. The final summary shows how many tests came from cache vs were skipped:

```
[  1] exec_0001 (rep 1/1) → SUCCEEDED [CACHED] | result=100
[  2] exec_0002 (rep 1/1) -> SKIPPED (not in cache)

Benchmark completed (cache-only mode): 3 tests processed
  From cache: 2
  Skipped (not in cache): 1
```

**Note:** `--cache-only` requires `benchmark.cache_file` to be configured in the YAML file. Using `--cache-only` automatically enables `--use-cache`.


### Parameter Hashing

Each test is uniquely identified by:
1. **Parameters**: All swept and fixed variables (e.g., `nodes=2, processes=16`)
2. **Command fingerprint**: A hash of `command.template` and `command.env` (see [Command Changes](#command-changes))
3. **Repetition**: Which repetition this is (1, 2, 3, ...)

Parameters are normalized before hashing:
- Numeric strings: a string is coerced to a number only when the numeric form round-trips back to the exact original string. `"8"` and `8` hash the same, but `"1.10"` and `"1.1"` (or `"08"` and `"8"`, `"1e3"` and `"1000.0"`) keep distinct hashes.
- Internal keys removed: `__test_index`, etc. are ignored
- Excluded variables removed: Variables in `cache_exclude_vars` are skipped
- Sorted consistently: Order doesn't matter

### Excluding Variables from Cache

Some derived variables contain run-specific paths that change between executions, causing unnecessary cache misses:

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

Use `cache_exclude_vars` to exclude path-based variables:

```yaml
benchmark:
  cache_file: "/home/user/iops_cache.db"
  cache_exclude_vars: ["summary_file"]  # Exclude from cache hash
```


### Command Changes

Cached results are tied to the `command` section. IOPS stores a fingerprint of `command.template` and `command.env` with every result, and a result is reused only when the current fingerprint matches:

```yaml
# Original command
command:
  template: "fio --name=test --rw=read --bs={{ block_size }}"

# Modified command (added --direct=1 for unbuffered I/O): earlier results no longer match
command:
  template: "fio --name=test --rw=read --bs={{ block_size }} --direct=1"
```

Results for both commands are kept side by side, so reverting the command makes the earlier results available again.

The fingerprint is computed from the **unrendered** templates. The rendered command is fully determined by the template and the variable values, and the variable values are already part of the key, so nothing is lost. The benefit is that run-specific values rendered into the command, such as `{{ execution_dir }}`, do not invalidate the cache. Runs of whitespace are collapsed before hashing, so reflowing a long template over several YAML lines keeps the same fingerprint. `command.labels` is not part of the fingerprint, since labels describe a test rather than change it.

**The script is not part of the key.** Script templates mostly hold launch details (`#SBATCH` directives, partitions, time limits, module paths, output redirection) that should not throw away results when edited. Keep anything that changes what is being measured in one of these two places:

- **A variable**, which is part of the parameters, for example a stripe count or a library version you compare.
- **The `command` section**, either in `command.template` or in `command.env` (e.g. `OMP_NUM_THREADS`).

Values read from `os_env` or from files included by the template are not tracked by the fingerprint.

If you need to invalidate results for a reason the key cannot see, use a new cache file, or add a constant variable (e.g. `cache_version`) and change its value.

### Caches from Older Versions

Caches created before command fingerprinting are upgraded automatically the first time a newer IOPS opens them:

- The original file is copied to `<cache_file>.v0.bak` before anything is changed.
- The upgrade runs in a single transaction. If it fails, the cache is left exactly as it was.
- Existing results are kept with an **unknown** command. They still match on parameters alone, exactly as before the upgrade, so `--use-cache` keeps finding them.
- When a test is run again, the new result is stored with the current fingerprint and is preferred over the old one from then on.

At the end of a run, IOPS reports how many results came from entries with an unknown command, since it cannot check that those were produced by the current command:

```
WARNING | Cache: 12 cached results predate command fingerprinting; their command could not be verified against
WARNING | the current command.template. Use --cache-strict to ignore them.
```

Pass `--cache-strict` to ignore entries with an unknown command. Nothing is deleted, so a later run without the flag can still use them. Caches built with `iops cache create` from a CSV file also have no command information, and behave the same way.

An older IOPS version can still read an upgraded cache. It ignores fingerprints and matches on parameters alone, as it always did. Its writes, however, can overwrite results stored by the newer version for the same test, so avoid running old and new versions of IOPS against the same cache file. A cache written by a newer IOPS than the one opening it is refused with a request to upgrade.

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
    command_fingerprint TEXT            -- SHA-256 of the command section (NULL: unknown)
);

-- Index for fast lookups
CREATE INDEX idx_param_hash ON cached_executions(param_hash, repetition);

-- One entry per key (not created for caches written by `iops cache rebuild`)
CREATE UNIQUE INDEX idx_unique_entry
    ON cached_executions(param_hash, IFNULL(command_fingerprint, ''), repetition);

-- Command text, one row per fingerprint
CREATE TABLE cached_commands (
    fingerprint TEXT PRIMARY KEY,       -- Matches cached_executions.command_fingerprint
    template TEXT NOT NULL,             -- command.template as first stored
    env_json TEXT,                      -- command.env as JSON
    first_seen TEXT NOT NULL            -- Timestamp
);
```

The schema version is stored in SQLite's `PRAGMA user_version` (currently 1).

The command text is stored once per distinct command, so `iops cache show` and `iops cache stats` can display the command behind each fingerprint. It is recorded when a result is stored, and also when IOPS opens a cache that already holds results for the current command but not its text (for example results stored by a development version before the table existed). The text is the template as first stored: a reflowed template with the same fingerprint does not replace it. Entries with an unknown command have no text, since IOPS cannot tell which command produced them.

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

Print a summary of the cache: total entries, unique parameter sets, number of distinct commands, entries with an unknown command, schema version, and date range. It never upgrades the file, so it is safe to run on a cache from an older version.

```bash
$ iops cache stats cache.db

Cache: cache.db
--------------------------------------------------
Total entries:          28
Unique parameter sets:  14
Distinct repetitions:   2
Distinct commands:      1
Unknown command:        0
Schema version:         1
Oldest entry:           2026-04-06T18:58:32.285294
Newest entry:           2026-04-17T23:53:07.035720

Commands:
  3f9a0c21     28 entries  python train.py --dataset {{ dataset }} --conv {{ light_conv }}
```

Each command is listed with its short fingerprint, the number of entries recorded with it, and its template on one line. Use `--json` for the full text.

### `iops cache list`

List cached entries, one row per parameter set and command. Each row shows a short (8-character) parameter hash, the short command fingerprint (`Cmd`, or `unknown` for entries without one), the parameter values, the number of cached repetitions, and metric averages across repetitions.

```bash
$ iops cache list cache.db

Hash      Cmd       dataset       light_conv  Reps  average_epoch_time_sec  peak_gpu_memory_mib  Last Cached
---------------------------------------------------------------------------------------------------------------
57c77ec3  3f9a0c21  moving_mnist  tied        2     430.72                  10996.97             2026-04-17T23:53:07
096cd29f  3f9a0c21  taasrad19     sqnxt       2     391.29                  11134.85             2026-04-17T12:21:38
...

14 row(s): 14 unique parameter set(s), 1 command(s)
```

When the same parameters were measured with different commands, each command gets its own row with the same `Hash`, so repetition counts and metric averages never mix results from two commands. Use `iops cache show <hash>` to see the command text behind a fingerprint. `Reps` counts distinct repetitions: a cache written by `iops cache rebuild` can hold several entries for one repetition, which are averaged together. With `--json`, each row also carries the full `command_fingerprint`, the `command` template (when stored), and the number of stored `entries`.

Filter by parameter values using the same `VAR=VALUE` syntax as `iops find`:

```bash
# Only entries where dataset=moving_mnist
iops cache list cache.db dataset=moving_mnist

# Hide metric columns, keep just params and repetition counts
iops cache list cache.db --no-metrics

# Show full parameter values without truncation
iops cache list cache.db --full

# Limit to the 10 most recently cached rows
iops cache list cache.db --limit 10

# Emit JSON for scripting
iops cache list cache.db --json
```

### `iops cache show`

Show full details for a single cached parameter set, including every repetition's metrics and metadata. Each repetition shows the short command fingerprint it was recorded with (`unknown` for entries without one). The hash argument accepts a git-style short prefix:

```bash
$ iops cache show cache.db 57c77e

Hash: 57c77ec316e9b66f3aa9861227fa1a83
Short: 57c77ec3

Parameters:
  dataset: moving_mnist
  light_conv: tied

Repetitions: 2

  rep=1  cached_at=2026-04-08T08:01:27.580146  command=3f9a0c21
    metrics:
      average_epoch_time_sec: 428.96
      ...
    metadata:
      __executor_status: SUCCEEDED
      ...

Commands:

  3f9a0c21:
    python train.py --dataset {{ dataset }} --conv {{ light_conv }}
```

The `Commands` section prints the template (and `command.env`) for every fingerprint used by the entry. A fingerprint whose text was never stored shows `(command text not stored)`.

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
    list_cache_entries, get_cache_entry, get_cache_stats,
    resolve_hash_prefix, ExecutionCache,
)

stats = get_cache_stats("cache.db")  # total_entries, unique_parameter_sets, ...

# List entries, filtered and collapsed per parameter hash
entries = list_cache_entries("cache.db", param_filters={"dataset": "moving_mnist"}, limit=10)

# Full detail for a single entry (git-style prefix accepted)
entry = get_cache_entry("cache.db", "57c77e")

# Resolve a prefix to a full hash (raises HashPrefixError on ambiguity)
full_hash = resolve_hash_prefix("cache.db", "57c77e")

# Mutating operations still go through ExecutionCache
ExecutionCache("cache.db").clear_cache()
```

## Rebuilding the Cache

The `iops cache rebuild` command modifies an existing cache database by:
- **Excluding variables** from the hash (consolidating entries that now hash to the same value)
- **Adding variables** with constant values to all entries (enabling cache reuse after config changes)

Command fingerprints and the stored command text are carried over unchanged, so entries recorded with different commands stay separate. The source file is only read: a cache from an older version is not upgraded, and its entries keep an unknown command in the output.

### Usage

```bash
# Exclude variables from hash
iops cache rebuild cache.db --exclude summary_file,output_path -o new_cache.db

# Add a variable to all entries (with type); repeat --add for multiple variables
iops cache rebuild cache.db --add use_new_flag:bool=false -o new_cache.db

# Combine exclude and add
iops cache rebuild cache.db --exclude output_path --add use_feature:bool=true -o new_cache.db
```

### Adding Variables (Type Syntax)

When adding variables, specify the type to ensure it matches your YAML config:

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
Output unique hashes:  3
Collapsed entries:     97
==================================================
Rebuilt cache saved to: cache_rebuilt.db
```

### Example: Adding a New Variable

You have a cache from previous runs and add a new swept variable to your config:

```yaml
vars:
  nodes:
    type: int
    sweep: { mode: list, values: [2, 4, 8] }
  use_new_optimization:                       # New variable, not in the cache
    type: bool
    sweep: { mode: list, values: [false, true] }
```

To reuse the existing cache for `use_new_optimization=false` cases:

```bash
iops cache rebuild cache.db --add use_new_optimization:bool=false -o new_cache.db
```

Now `iops run new_config.yaml --use-cache` will find cache hits for `use_new_optimization=false` and only execute the `use_new_optimization=true` cases.

### How It Works

Rebuild reads all entries from the source cache, adds new variables to each entry's parameters (`--add`), re-normalizes parameters excluding specified variables (`--exclude`), re-computes each hash, and writes all entries to the new database.

**Important**: When multiple entries collapse to the same `(hash, repetition)`, all entries are preserved. The rebuilt database does not enforce uniqueness, so all historical data is kept. When reading from the cache, IOPS uses `ORDER BY created_at DESC LIMIT 1` to return the most recent entry.

### After Rebuilding

Update your YAML config to use the rebuilt cache; future runs with `--use-cache` will find cache hits for matching parameters:

```yaml
benchmark:
  cache_file: "./workdir/new_cache.db"
  cache_exclude_vars: ["output_file"]  # If you excluded variables
```

### Cache Behavior Details

**When cache is used:** before each test execution, IOPS checks whether `(params, repetition)` exists in the cache. If found, the test is populated with cached metrics and metadata and execution is skipped; otherwise it executes normally.

**When cache is updated:** after each successful execution (`STATUS_SUCCEEDED`), IOPS stores `(params, repetition, metrics, metadata)`. On duplicate (same params/repetition), the entry is updated with the latest result.

### Core-Hours Savings Tracking

When using cache with a core-hours budget (`max_core_hours`), cached tests don't count toward the budget and IOPS tracks how many core-hours were saved. This appears in progress logs and the final summary.

See the **[Budget Control](../budget-control#cache-interaction)** guide for details.
