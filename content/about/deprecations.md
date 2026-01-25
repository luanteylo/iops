---
title: "Deprecations"
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


