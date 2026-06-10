---
title: "Budget Control"
---

IOPS can track core-hours consumption and automatically stop execution when a budget limit is reached, helping prevent exceeding compute allocations on HPC systems.

---

## Table of Contents

1. [Configuration](#configuration)
2. [How Core-Hours Are Calculated](#how-core-hours-are-calculated)
3. [Duration Source and Accuracy](#duration-source-and-accuracy)
4. [Budget Enforcement Behavior](#budget-enforcement-behavior)
5. [Dry-Run Estimation](#dry-run-estimation)
6. [Cache Interaction](#cache-interaction)

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

The `cores_expr` should reflect the cores you're actually charged for on your HPC system:

```yaml
# Total MPI tasks
cores_expr: "{{ nodes * processes_per_node }}"

# Fixed cores per node (e.g., exclusive mode with 128-core nodes)
cores_expr: "{{ nodes * 128 }}"

# From a derived variable
cores_expr: "{{ ntasks }}"
```

**Important for exclusive mode:** If you reserve entire nodes but only use some cores, set `cores_expr` to the total reserved cores (`{{ nodes * 128 }}` for 128-core nodes), not just the ones your application uses (`{{ ntasks }}` would undercount if you run only 64 tasks per node).

---

## Duration Source and Accuracy

IOPS uses two sources for duration, in order of preference:

### 1. System Probe (Preferred)

When `probes.system_snapshot: true` (default), IOPS injects a probe into your scripts that captures the actual execution time using bash's `$SECONDS` variable. This measures only the script runtime on the compute node.

### 2. Job Timestamps (Fallback)

If the system probe is disabled (`probes.system_snapshot: false`) or unavailable, IOPS falls back to job timestamps recorded during execution:

- **`__submission_time`**: When the job was submitted (sbatch called)
- **`__job_start`**: When the job started running (transitioned from PENDING to RUNNING)
- **`__end`**: When the job completed

The fallback prioritizes `__job_start` over `__submission_time`, so queue wait time is excluded from core-hours calculations.

**Accuracy implications:**

| Executor | With Probe | Without Probe |
|----------|------------|---------------|
| Local | Accurate | Accurate (no queue) |
| SLURM | Accurate | Reasonably accurate (excludes queue wait) |
| Single-allocation | Accurate | Includes monitoring overhead |

**Recommendation:** Keep `probes.system_snapshot: true` (default) for accurate budget tracking with SLURM; it captures the exact script execution time.

---

## Budget Enforcement Behavior

IOPS checks the budget **before submitting** each test, not during execution. This means:

1. **A test may exceed the budget**: If a test is submitted when budget remains, it runs to completion even if its actual duration pushes the total past `max_core_hours`.

2. **No mid-execution cancellation**: Once a job is submitted to SLURM or starts locally, IOPS won't kill it based on budget; it only prevents new submissions.

**Example scenario:**

```
Core-hours: 1178.74/1200.00 (98.2% used, 21.26 remaining)
SLURM job submitted: 3363545
```

Here, 21.26 core-hours remain. The next test is still submitted even if it requires 30 core-hours, so the final total may exceed 1200.

**Why this design?** Killing running HPC jobs wastes already-consumed resources, and partial results from interrupted jobs are often unusable. The budget serves as a guideline, not a hard cutoff.

**Recommendation:** Set `max_core_hours` slightly below your actual allocation, especially if individual tests consume significant core-hours.

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

When using cache (`--use-cache`), cached tests don't count toward the budget (they're not re-executed), and IOPS tracks and reports the core-hours saved by cache hits in progress logs and the final summary:

```
Core-hours: 93.30/1200.00 (7.8% used, 1106.70 remaining, 45.20 saved by cache)

Budget: 93.30 / 1200.00 core-hours (7.8% utilized) [OK]
Cache savings: 45.20 core-hours saved by cache hits
```
