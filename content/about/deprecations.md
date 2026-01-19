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


