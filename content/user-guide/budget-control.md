---
title: "Budget Control"
---

IOPS can track core-hours consumption and automatically stop execution when a budget limit is reached. This helps prevent exceeding compute allocations on HPC systems.

---

## Table of Contents

1. [Configuration](#configuration)
2. [How Core-Hours Are Calculated](#how-core-hours-are-calculated)
3. [Duration Source and Accuracy](#duration-source-and-accuracy)
4. [Dry-Run Estimation](#dry-run-estimation)
5. [Cache Interaction](#cache-interaction)

---

## Configuration

Set a budget limit in your YAML config:

```yaml
benchmark:
  max_core_hours: 1000  # Stop after 1000 core-hours
  cores_expr: "{{ nodes * processes_per_node }}"
```

Or from command line (overrides config value):

```bash
iops run config.yaml --max-core-hours 1000
```

| Option | Description |
|--------|-------------|
| `max_core_hours` | Maximum core-hours budget. Execution stops when reached. |
| `cores_expr` | Jinja2 expression to compute cores per test. Defaults to `1` if not set. |

---

## How Core-Hours Are Calculated

```
core_hours = cores × (duration_seconds / 3600)
```

- **`cores`**: Evaluated from `cores_expr` using test variables
- **`duration_seconds`**: Actual script execution time (see [Duration Source](#duration-source-and-accuracy))

### Setting cores_expr Correctly

The `cores_expr` should reflect the cores you're actually being charged for on your HPC system.

**Common patterns:**

```yaml
# Total MPI tasks
cores_expr: "{{ nodes * processes_per_node }}"

# Fixed cores per node (e.g., exclusive mode with 128-core nodes)
cores_expr: "{{ nodes * 128 }}"

# From a derived variable
cores_expr: "{{ ntasks }}"
```

**Important for exclusive mode:** If you reserve entire nodes but only use some cores, set `cores_expr` to the total reserved cores, not just the ones your application uses:

```yaml
# Correct: actual cores reserved in exclusive mode
cores_expr: "{{ nodes * 128 }}"

# Wrong: would undercount if nodes have 128 cores but you only run 64 tasks
cores_expr: "{{ ntasks }}"
```

---

## Duration Source and Accuracy

IOPS uses two sources for duration, in order of preference:

### 1. System Probe (Preferred)

When `collect_system_info: true` (default), IOPS injects a probe into your scripts that captures the actual execution time using bash's `$SECONDS` variable. This measures only the script runtime on the compute node.

### 2. Job Timestamps (Fallback)

If the system probe is disabled (`collect_system_info: false`) or unavailable, IOPS falls back to job timestamps recorded during execution.

IOPS tracks three timestamps:
- **`__submission_time`**: When the job was submitted (sbatch called)
- **`__job_start`**: When the job started running (transitioned from PENDING to RUNNING)
- **`__end`**: When the job completed

The fallback prioritizes `__job_start` over `__submission_time` to exclude queue wait time from the calculation.

**Accuracy implications:**

| Executor | With Probe | Without Probe |
|----------|------------|---------------|
| Local | Accurate | Accurate (no queue) |
| SLURM | Accurate | Reasonably accurate (excludes queue wait) |
| Single-allocation | Accurate | Includes monitoring overhead |

For SLURM jobs, the queue wait time (`__job_start - __submission_time`) is excluded from core-hours calculations when using timestamp fallback. However, the system probe is still preferred as it captures the exact script execution time.

**Recommendation:** Keep `collect_system_info: true` (default) for accurate budget tracking with SLURM.

---

## Dry-Run Estimation

Estimate core-hours before running with `--dry-run` and `--time-estimate`:

```bash
# Single estimate (300 seconds per test)
iops run config.yaml --dry-run --time-estimate 300

# Multiple scenarios
iops run config.yaml --dry-run --time-estimate "300,600,900"
```

This shows estimated total core-hours, budget utilization, and how many tests fit within the budget.

---

## Cache Interaction

When using cache (`--use-cache`):

- **Cached tests don't count** toward the budget (they're not re-executed)
- IOPS tracks and reports core-hours saved by cache hits

Progress logs show savings:

```
Core-hours: 93.30/1200.00 (7.8% used, 1106.70 remaining, 45.20 saved by cache)
```

Final summary:

```
Budget: 93.30 / 1200.00 core-hours (7.8% utilized) [OK]
Cache savings: 45.20 core-hours saved by cache hits
```

This helps you understand the value of caching in terms of compute resources saved.

