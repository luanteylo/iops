---
title: "Data Sources"
weight: 10
---

This page documents where IOPS CLI commands retrieve their data from. Understanding these data sources is essential for developers working on the codebase.

## Overview

IOPS commands read from metadata files generated during benchmark execution and from result files. Metadata files have the `__iops_` prefix and are documented in the [Metadata Files]({{< relref "/user-guide/metadata-files" >}}) user guide.


## Data Sources by Command

```
iops find ◄─── __iops_index.json
          ◄─── __iops_status.json
          ◄─── __iops_run_metadata.json (optional metadata)

iops find --watch ◄─── __iops_index.json (polling)
                  ◄─── __iops_status.json (polling)

iops report ◄─── __iops_run_metadata.json
            ◄─── results.csv/parquet/sqlite
```


### `iops find`

| Information | Source File | Location | Field(s) | Notes |
|-------------|-------------|----------|----------|-------|
| Benchmark name | `__iops_index.json` | Run root | `benchmark` | |
| Execution list | `__iops_index.json` | Run root | `executions` | Dict keyed by exec_XXXX |
| Execution path | `__iops_index.json` | Run root | `executions[key].path` | Relative to run root |
| Parameters | `__iops_index.json` | Run root | `executions[key].params` | |
| Command | `__iops_index.json` | Run root | `executions[key].command` | Shown with `--show-command` |
| Execution status | `__iops_status.json` | exec_XXXX or repetition_N | `status` | Aggregated from repetitions |
| Error message | `__iops_status.json` | exec_XXXX or repetition_N | `error` | |
| End time | `__iops_status.json` | exec_XXXX or repetition_N | `end_time` | |
| Cache status | `__iops_status.json` | repetition_N | `cached` | True/False/"partial" |
| Skip reason | `__iops_status.json` | exec_XXXX | `reason` | Only for SKIPPED tests |
| Description | `__iops_run_metadata.json` | Run root | `benchmark.description` | |
| Hostname | `__iops_run_metadata.json` | Run root | `benchmark.hostname` | |
| Timestamp | `__iops_run_metadata.json` | Run root | `benchmark.timestamp` | |

**Single execution view** (when pointing to exec_XXXX folder):

| Information | Source File | Location | Field(s) |
|-------------|-------------|----------|----------|
| Parameters | `__iops_params.json` | exec_XXXX | All fields |
| Command | `__iops_index.json` | Run root | `executions[key].command` |

---

### `iops find --watch`

Watch mode is designed to work **during** execution, so it only reads from files that exist before the benchmark completes. It does **not** read from `__iops_run_metadata.json` (which is written at the end).

| Information | Source File | Location | Field(s) | Notes |
|-------------|-------------|----------|----------|-------|
| Benchmark name | `__iops_index.json` | Run root | `benchmark` | |
| Execution list | `__iops_index.json` | Run root | `executions` | |
| Total expected | `__iops_index.json` | Run root | `total_expected` | Total repetitions across all tests |
| Repetitions | `__iops_index.json` | Run root | `repetitions` | Per-test repetition count |
| Folders upfront | `__iops_index.json` | Run root | `folders_upfront` | True if folders created upfront |
| Active tests | `__iops_index.json` | Run root | `active_tests` | Tests that will execute |
| Skipped tests | `__iops_index.json` | Run root | `skipped_tests` | Tests skipped by constraints |
| Test status (upfront) | `__iops_index.json` | Run root | `executions[key].status` | Only in upfront mode |
| Skip reason (upfront) | `__iops_index.json` | Run root | `executions[key].skip_reason` | Only in upfront mode |
| Execution path | `__iops_index.json` | Run root | `executions[key].path` | |
| Parameters | `__iops_index.json` | Run root | `executions[key].params` | |
| Command | `__iops_index.json` | Run root | `executions[key].command` | |
| Repetition status | `__iops_status.json` | repetition_N | `status` | Per-repetition status |
| Cache status | `__iops_status.json` | repetition_N | `cached` | |
| Duration | `__iops_status.json` | repetition_N | `duration_seconds` | Actual execution time |
| Error message | `__iops_status.json` | repetition_N | `error` | |
| Metrics | `__iops_status.json` | repetition_N | `metrics` | Dict of metric values (with --metrics flag) |
| Skip reason | `__iops_status.json` | exec_XXXX | `reason` | For SKIPPED tests |

---

### `iops report`

The report command reads from the run metadata file and the results output file. It does **not** read from index or status files.

| Information | Source File | Location | Field(s) | Notes |
|-------------|-------------|----------|----------|-------|
| IOPS version | `__iops_run_metadata.json` | Run root | `iops_version` | For compatibility check |
| Benchmark config | `__iops_run_metadata.json` | Run root | `benchmark.*` | Name, description, executor, etc. |
| Variables config | `__iops_run_metadata.json` | Run root | `variables` | Variable definitions and sweep info |
| Metrics config | `__iops_run_metadata.json` | Run root | `metrics` | Metric names and parser info |
| Output config | `__iops_run_metadata.json` | Run root | `output` | Path and type of results file |
| Reporting config | `__iops_run_metadata.json` | Run root | `reporting` | Plot configs, sections, theme |
| System environment | `__iops_run_metadata.json` | Run root | `system_environment` | CPU, memory, hostname, etc. |
| Planner stats | `__iops_run_metadata.json` | Run root | `benchmark.planner_stats` | Total/active/skipped combinations |
| Results data | Results file | `output.path` | All columns | CSV, Parquet, or SQLite |
| Execution status | Results file | `output.path` | `metadata.__executor_status` | Filters to SUCCEEDED only |
| Duration | Results file | `output.path` | `metadata.__sysinfo.duration_seconds` | For runtime calculations |
| Timestamps | Results file | `output.path` | `metadata.__job_start`, `metadata.__submission_time`, `metadata.__end` | Fallback for duration |

**Results file types:**

| Type | Read Method | Notes |
|------|-------------|-------|
| CSV | `pd.read_csv()` | Default format |
| Parquet | `pd.read_parquet()` | Requires pyarrow |
| SQLite | `pd.read_sql_query()` | Reads from `output.table` |

---

## File Locations

```
workdir/
  run_001/                              # Run root
    __iops_index.json                   # Index file (find, watch)
    __iops_run_metadata.json            # Run metadata (find, report)
    results.csv                         # Results file (report)
    exec_0001/                          # Execution folder
      __iops_params.json                # Parameter values (find single)
      __iops_status.json                # Test-level status (SKIPPED only)
      repetition_1/
        __iops_status.json              # Repetition status (find, watch)
        __iops_sysinfo.json             # System info (stored in results)
      repetition_2/
        ...
    exec_0002/
      ...
```

## Source Code References

| Module | File | Purpose |
|--------|------|---------|
| find | `iops/results/find.py` | Static execution listing |
| watch | `iops/results/watch.py` | Live execution monitoring |
| report | `iops/reporting/report_generator.py` | HTML report generation |

### Key Functions

**find.py:**
- `find_executions()` - Main entry point
- `_read_status()` - Reads and aggregates status from status files
- `_read_run_metadata()` - Reads run metadata file
- `_show_executions_from_index()` - Displays execution table

**watch.py:**
- `watch_executions()` - Main entry point with live updates
- `_load_index()` - Loads index file with execution metadata
- `_collect_execution_data()` - Collects current status from all executions
- `_build_table()` - Builds Rich table for display
- `_build_progress_bar()` - Builds progress bar with status counts

**report_generator.py:**
- `ReportGenerator.__init__()` - Initializes with workdir path
- `load_metadata()` - Loads `__iops_run_metadata.json`
- `load_results()` - Loads results from CSV/Parquet/SQLite
- `generate_report()` - Generates HTML report

---

## Data Flow Diagrams

### During Execution

```
Runner
  │
  ├──► __iops_index.json (updated incrementally)
  │
  ├──► exec_XXXX/
  │      ├──► __iops_params.json (before test)
  │      └──► __iops_status.json (if SKIPPED)
  │
  └──► exec_XXXX/repetition_N/
         ├──► __iops_status.json (after completion)
         └──► __iops_sysinfo.json (via probe script)
```

### After Execution

```
Runner
  │
  ├──► __iops_run_metadata.json (at end)
  │
  └──► results.csv (incrementally during execution)
```

