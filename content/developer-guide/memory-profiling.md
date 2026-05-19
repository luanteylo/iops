---
title: "Memory Profiling"
weight: 40
---

IOPS ships with an optional, env-gated memory profiler for diagnosing leaks in the runner itself. Use it when peak RSS grows linearly with the number of executions in a single `iops run` invocation, or when a long-running campaign exhausts node memory.

The profiler has zero overhead when its env var is unset, so it is safe to leave the wiring in place on every code path.

## Quick start

Run any benchmark with `IOPS_MEMPROFILE=1`:

```bash
IOPS_MEMPROFILE=1 iops run config.yaml
```

Per-tick output appears in the runner log every N executions, and a final summary is printed at the end of `run()` (in a `finally` block, so it fires even on Ctrl+C):

```
MemProfiler: enabled (interval=10, top_n=20, initial RSS=196.0 MiB)
...
MemProfiler[#10]: RSS=199.4 MiB (delta from start: +3.4 MiB)
MemProfiler[#20]: RSS=201.1 MiB (delta from start: +5.1 MiB)
...
======================================================================
MemProfiler: final report
  Initial RSS: 196.0 MiB
  Final RSS:   205.4 MiB
  Peak RSS:    205.4 MiB
  Top 20 allocation growth sites (since start):
    +189.4 KiB (count +979) jinja2/environment.py:709
    +81.9 KiB (count +1200) json/decoder.py:353
    ...
======================================================================
```

## Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `IOPS_MEMPROFILE` | unset | Set to `1`, `true`, or `yes` to enable. Anything else (including unset) is a no-op. |
| `IOPS_MEMPROFILE_INTERVAL` | `10` | Take a snapshot and log RSS every N completed executions. |
| `IOPS_MEMPROFILE_TOP_N` | `20` | Number of allocation sites to print in the final report. |

For long runs, raise `IOPS_MEMPROFILE_INTERVAL` to keep the snapshot list small. For short runs where you only care about totals, set it to a value larger than your matrix size.

## How it works

The profiler combines two signals:

1. **Process RSS** read from `/proc/self/status` (Linux only). Captures all memory the OS sees, including C extensions like pandas, pyarrow, and SQLite.
2. **Python heap snapshots** via stdlib `tracemalloc` with a traceback depth of 25. Captures Python-level allocations with file and line attribution.

RSS tells you *whether* memory is growing. The tracemalloc diff tells you *where* in Python it grew, by comparing the final snapshot to the very first one taken at runner construction time.

Snapshots are taken at sampling boundaries (every `interval` executions) rather than per-test, to keep the profiler's own memory overhead bounded.

## Implementation

The profiler lives in a single file with no dependencies beyond stdlib:

- `iops/execution/memprofile.py` defines `MemProfiler`.
- `iops/execution/runner.py` constructs it in `IOPSRunner.__init__`, calls `tick()` in `_process_completed`, and `report()` in the `run()` finally block.

When `IOPS_MEMPROFILE` is unset, `MemProfiler.__init__` returns immediately after setting `self.enabled = False`. `tick()` and `report()` short-circuit on the flag, so there is no measurable cost on normal runs.

## Regression test

`tests/test_memory_leak.py` runs 60 trivial executions with the local executor and asserts that the Python heap grows by no more than 5 MiB after a warmup snapshot. The warmup snapshot is taken right after `IOPSRunner(...)` construction so it excludes one-time allocations (planner build, cache open, logging setup) and measures only per-execution growth.

Run it directly:

```bash
~/.venvs/iops_env/bin/pytest tests/test_memory_leak.py -v
```

If this test fails after a code change, do not just raise `MAX_GROWTH_BYTES`. Re-run the same scenario with `IOPS_MEMPROFILE=1` and look at the top growth sites in the runner log to find the leak.

## When to reach for a heavier tool

The built-in profiler is enough to catch coarse leaks (caches that never evict, lists that grow with the matrix, snapshots retained between executions). For deeper investigation, use one of:

- **`memray run -o iops.bin -m iops run config.yaml`** then `memray flamegraph iops.bin` for a clickable flamegraph of allocations. Best for one-off deep dives.
- **`/usr/bin/time -v iops run config.yaml`** for a single max-RSS number, useful in CI smoke tests where you do not want to install anything.
- **`tracemalloc.take_snapshot()` calls hand-placed at suspect call sites** when the per-execution profiler is too coarse to localize a leak inside a single test.

## Likely suspects in this codebase

When tracking down a real leak, the historical hotspots are:

- `iops/cache.py`: SQLite connection lifetime and result accumulation.
- `iops/execution/runner.py`: `self.completed_tests` retains every `ExecutionInstance`, and the metadata dicts attached to each test can be large.
- `iops/reporting/report_generator.py`: Plotly figure objects hold their full underlying DataFrames. If reports are generated mid-run rather than once at the end, this compounds.
- Jinja2 environment caches: expected to grow with the number of unique templates rendered, not with the number of executions. If you see growth proportional to executions, you are recompiling templates per-test.
