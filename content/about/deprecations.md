---
title: "Deprecations"
weight: 30
---

This page lists deprecated features and provides migration guidance.

## Backwards Compatibility Policy

IOPS follows a **2 minor version deprecation cycle**:

| Version | Behavior |
|---------|----------|
| N | Feature deprecated with warning, old behavior still works |
| N+1 | Warning remains, old behavior still works |
| N+2 | Feature removed, error with migration guidance |

This gives users at least two releases to migrate their configurations.

## Current Deprecations

### `benchmark.executor_options` → `benchmark.slurm_options`

| | |
|---|---|
| **Deprecated in** | 3.5.0 |
| **Remove after** | 3.7.0 |
| **Reason** | Renamed for clarity (options are SLURM-specific) |

**Before:**
```yaml
benchmark:
  executor: slurm
  executor_options:
    poll_interval: 30
    commands:
      submit: "sbatch"
```

**After:**
```yaml
benchmark:
  executor: slurm
  slurm_options:
    poll_interval: 30
    commands:
      submit: "sbatch"
```

### Probe Configuration Fields → `benchmark.probes` Section

The flat probe configuration fields have been consolidated into a nested `probes:` section for better organization.

| Deprecated Field | New Field | Deprecated in | Remove after |
|------------------|-----------|---------------|--------------|
| `benchmark.collect_system_info` | `benchmark.probes.system_snapshot` | 3.5.0 | 3.7.0 |
| `benchmark.track_executions` | `benchmark.probes.execution_index` | 3.5.0 | 3.7.0 |
| `benchmark.trace_resources` | `benchmark.probes.resource_sampling` | 3.5.0 | 3.7.0 |
| `benchmark.trace_interval` | `benchmark.probes.sampling_interval` | 3.5.0 | 3.7.0 |

**Before:**
```yaml
benchmark:
  name: "My Study"
  workdir: "./results"
  collect_system_info: true
  track_executions: true
  trace_resources: true
  trace_interval: 0.5
```

**After:**
```yaml
benchmark:
  name: "My Study"
  workdir: "./results"
  probes:
    system_snapshot: true      # Collect system info from compute nodes
    execution_index: true      # Write metadata files for 'iops find'
    resource_sampling: true    # Enable CPU/memory tracing
    sampling_interval: 0.5     # Sampling interval in seconds
```

**Benefits:**
- Clearer organization: all probe-related settings in one place
- More descriptive names: `system_snapshot` vs `collect_system_info`
- Easier to enable/disable all probing with a single section

### Adaptive Probe Result Fields

The per-probe result fields have been renamed to describe the probe's progression instead of assuming that stopping means failure.

| Deprecated Field | New Field | Deprecated in | Remove after |
|------------------|-----------|---------------|--------------|
| `found_value` | `last_value_before_stop` | 3.5.9 | 3.7.0 |
| `failed_value` | `stop_value` | 3.5.9 | 3.7.0 |

The old names were correct only for the usual stop condition, `stop_when: "exit_code != 0"`, where the probe steps forward while the benchmark works and stops on the first failure. An inverted condition is equally valid: `stop_when: "exit_code == 0"` keeps stepping while the benchmark fails and stops at the first value that succeeds. In that case the value stored in `failed_value` was the one that worked, so the results read backwards.

**Before:**
```
Adaptive probing results for 'block_size':
  problem_size=8000: found=64, failed=128, iterations=4, stop_reason=condition_met
```

**After:**
```
Adaptive probing results for 'block_size':
  problem_size=8000: stop_value=128, last_value_before_stop=64, iterations=4, stop_reason=condition_met
```

**What this affects:**
- The run summary printed at the end of a benchmark
- The `adaptive_results` block in `__iops_run_metadata.json`
- The "Probe Results Summary" table in HTML reports
- The `ProbeResult` attributes, if you drive the planner from Python

**Migration:** if you post-process `__iops_run_metadata.json`, read `stop_value` and `last_value_before_stop`. Until the removal, both key sets are written to every metadata file and both attribute names resolve on `ProbeResult`, so existing scripts keep working. Reports generated from runs recorded before 3.5.9 fall back to the old keys automatically and will keep doing so.


