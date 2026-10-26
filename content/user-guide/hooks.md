---
title: "Hooks"
weight: 72
---

Hooks run a command of your choice when something happens during a run: the run starts, a share of the tests has concluded, too many tests are failing, or the run ends. The typical use is monitoring a long run on a cluster, for example sending a mail when the run is half done and another when it finishes. They are equally useful for housekeeping, such as copying the results somewhere once the run is over.

IOPS decides when the events happen. You decide what to run.

---

## Table of Contents

1. [Overview](#overview)
2. [Events](#events)
3. [Thresholds](#thresholds)
4. [Hook Fields](#hook-fields)
5. [Command Context](#command-context)
6. [Environment Variables](#environment-variables)
7. [Examples](#examples)
8. [How Hooks Run](#how-hooks-run)
9. [Testing Hooks](#testing-hooks)
10. [Limitations](#limitations)

---

## Overview

Hooks are a top-level list in the YAML file:

```yaml
hooks:
  - name: halfway_mail
    event: progress
    at: "50%"
    command: >
      echo {{ message | quote }} |
      mail -s "IOPS: {{ benchmark.name }} at {{ progress.percent }}%" me@example.org
```

Each entry names an `event`, says when it fires (`at` and/or `every`, for the events that need it), and gives a `command`. The command is a Jinja2 template rendered with the run context (progress counters, elapsed time, run directory, and so on), then executed with bash.

A hook never affects the benchmark. It runs in the background, has a timeout, and if it fails, IOPS logs a warning and carries on.

Hooks are not fired in `--dry-run` (the dry run lists them), and `iops run --no-hooks` disables them for one run.

---

## Events

| Event | Fires | Needs | Notes |
|-------|-------|-------|-------|
| `start` | Once, after the planner yields the first test | nothing | The total number of tests is known at this point |
| `progress` | When the number of concluded tests crosses a threshold | `at` and/or `every` | Concluded means succeeded, failed, error, skipped, or cached |
| `failures` | When the number or rate of failed tests crosses a threshold | `at` and/or `every` | Failed means `FAILED` or `ERROR` |
| `consecutive_failures` | When the current streak of failures reaches a threshold | `at` and/or `every` (counts only) | Re-arms after a success breaks the streak |
| `finish` | Once, when the run ends | nothing (`when` is optional) | Waits for the hook to complete before IOPS exits |

```yaml
hooks:
  # Progress: percentages are relative to the planner's current total
  - name: quarter_marks
    event: progress
    at: ["25%", "50%", "75%"]
    command: "..."

  - name: every_hundred
    event: progress
    every: 100
    command: "..."

  # Failures: a count, or a failure rate
  - name: five_failures
    event: failures
    at: 5
    command: "..."

  - name: high_failure_rate
    event: failures
    at: "20%"
    min_tests: 10
    command: "..."

  # Consecutive failures: counts only
  - name: streak
    event: consecutive_failures
    at: 3
    command: "..."

  # Finish: optionally only for some outcomes
  - name: problem_report
    event: finish
    when: [interrupted, budget_exceeded, fail_fast, crashed]
    command: "..."
```

### progress

Counts every concluded test: succeeded, failed, error, skipped, and results served from the cache. A percentage is relative to the total the planner reports at that moment. For adaptive searches the total is re-estimated as the run goes, so a percentage there is approximate.

### failures

A count threshold (`at: 5`) fires when five tests have failed. A percentage threshold (`at: "20%"`) is the failure rate among the tests that ran (succeeded plus failed; skipped tests are not counted). To avoid alerting on the first test failing out of one, a percentage is only evaluated once `min_tests` tests have run (default 10). On a small run with fewer runnable tests than `min_tests`, the guard is lowered to the number of runnable tests so the hook can still report.

`every` for this event must be a count: the failure rate can go down as well as up, so a repeating percentage is ambiguous. Use `at` with a list of percentages instead.

### consecutive_failures

Counts the current streak of failed tests. Thresholds are counts only. A successful test resets the streak and re-arms the hook, so it can fire again if a new streak builds up.

### finish

Fires once when the run ends, with `run.outcome` set to one of:

| Outcome | Meaning |
|---------|---------|
| `completed` | All planned tests concluded |
| `interrupted` | The run was stopped with Ctrl+C |
| `budget_exceeded` | The `max_core_hours` budget stopped the run |
| `fail_fast` | `--fail-fast` stopped the run after a failure |
| `crashed` | IOPS stopped on an unexpected exception |

Use `when` to restrict the hook to some outcomes. Without it the hook fires on every outcome. The finish hooks run after the report is generated, so `report_path` points to it when one was produced.

---

## Thresholds

`at` and `every` take thresholds written as:

- an **integer**: a count (`5` means five tests)
- a **string ending in `%`**: a percentage (`"25%"`). Quote it, since a bare `25%` is not valid YAML.

Rules:

- `at` accepts a single value or a list. Each `at` threshold fires **once**, the first time it is reached.
- `every` takes a single value and fires at each multiple of it (`every: 100` fires at 100, 200, 300, ...).
- If one update crosses several multiples of `every` (a percentage on a small run, for example), the hook fires once, for the highest one.
- If one update crosses several `at` thresholds, the hook fires once and reports the last one reached.
- Counts are in **attempts**, that is, executions times repetitions. A study with 10 executions and 3 repetitions has 30 attempts.
- Percentages must be greater than 0% and at most 100%, counts at least 1.
- `consecutive_failures` accepts counts only.
- Write percentages as strings. A float such as `0.25` is rejected.

---

## Hook Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | no | `hook_<index>` | Unique name, used in logs and with `iops hooks test --hook` |
| `event` | yes | | One of `start`, `progress`, `failures`, `consecutive_failures`, `finish` |
| `command` | yes | | Shell command, a Jinja2 template (see [Command Context](#command-context)) |
| `at` | see below | | One-shot threshold or list of thresholds |
| `every` | see below | | Repeating threshold |
| `when` | no | all outcomes | `finish` only: outcomes that fire the hook (scalar or list) |
| `min_tests` | no | `10` | `failures` only: tests that must have run before a percentage is evaluated |
| `timeout` | no | `60` | Seconds before the command is killed |

`progress`, `failures`, and `consecutive_failures` hooks need `at`, `every`, or both. `start` and `finish` hooks must not set them.

**Note:** The key is `event`, not `on`. YAML reads a bare `on` key as the boolean `true`, so `on: progress` would silently become `true: progress`. IOPS detects this and tells you to use `event:`.

Hooks can also be set under `machines.<name>` to change them per system. They merge by `name` like `scripts` and `constraints` (see [Machine Overrides](../machines)).

---

## Command Context

The `command` is rendered with Jinja2 in strict mode: an undefined name is an error, not an empty string. The benchmark variables from `vars` are **not** available, since a hook describes the run, not one test.

| Variable | Description |
|----------|-------------|
| `event.name` | Event name (`progress`, `finish`, ...) |
| `event.hook` | Name of the hook |
| `event.threshold` | The threshold that fired, as written (`50%`, `100`); empty for `start` and `finish` |
| `progress.completed` | Concluded tests so far |
| `progress.total` | Total tests planned |
| `progress.percent` | `completed` as a percentage of `total` |
| `progress.succeeded` | Tests that succeeded |
| `progress.failed` | Tests that failed or errored |
| `progress.skipped` | Tests that were skipped |
| `progress.failed_percent` | Failure rate among tests that ran |
| `progress.consecutive_failures` | Current failure streak |
| `run.outcome` | Outcome of the run (`finish` hooks; empty otherwise) |
| `run.elapsed` | Elapsed time as `H:MM:SS` |
| `run.elapsed_seconds` | Elapsed time in seconds |
| `run.start_time` | Run start, ISO 8601 |
| `run.core_hours` | Core-hours consumed so far |
| `benchmark.name` | The `benchmark.name` value |
| `workdir` | The run directory (`<workdir>/run_XXX`) |
| `report_path` | Path of the HTML report (`finish` hooks, when a report was generated; empty otherwise) |
| `hostname` | Host running IOPS |
| `os_env` | System environment variables (`{{ os_env.USER }}`) |
| `message` | A ready-made, multi-line description of the event |

The `quote` filter wraps a value for safe use in a shell command (it is `shlex.quote`). Use it for anything that may contain spaces or quotes, `message` in particular:

```yaml
command: "echo {{ message | quote }} | mail -s 'IOPS update' me@example.org"
```

---

## Environment Variables

The same values are exported to the command as environment variables, which is convenient when the command is a script and you would rather not template it:

| Variable | Context equivalent |
|----------|--------------------|
| `IOPS_HOOK` | `event.hook` |
| `IOPS_EVENT` | `event.name` |
| `IOPS_THRESHOLD` | `event.threshold` |
| `IOPS_OUTCOME` | `run.outcome` |
| `IOPS_COMPLETED` | `progress.completed` |
| `IOPS_TOTAL` | `progress.total` |
| `IOPS_PERCENT` | `progress.percent` |
| `IOPS_SUCCEEDED` | `progress.succeeded` |
| `IOPS_FAILED` | `progress.failed` |
| `IOPS_SKIPPED` | `progress.skipped` |
| `IOPS_FAILED_PERCENT` | `progress.failed_percent` |
| `IOPS_CONSECUTIVE_FAILURES` | `progress.consecutive_failures` |
| `IOPS_ELAPSED_SECONDS` | `run.elapsed_seconds` |
| `IOPS_CORE_HOURS` | `run.core_hours` |
| `IOPS_BENCHMARK` | `benchmark.name` |
| `IOPS_WORKDIR` | `workdir` |
| `IOPS_REPORT_PATH` | `report_path` |
| `IOPS_MESSAGE` | `message` |

---

## Examples

### Email progress with `mail`

```yaml
hooks:
  - name: started
    event: start
    command: >
      echo {{ message | quote }} |
      mail -s "IOPS started: {{ benchmark.name }}" me@example.org

  - name: progress_mail
    event: progress
    at: ["25%", "50%", "75%"]
    command: >
      echo {{ message | quote }} |
      mail -s "IOPS {{ benchmark.name }}: {{ event.threshold }} done" me@example.org

  - name: finished
    event: finish
    command: >
      echo {{ message | quote }} |
      mail -s "IOPS {{ benchmark.name }} finished ({{ run.outcome }})" me@example.org
```

### A notification script driven by environment variables

```yaml
hooks:
  - name: notify
    event: progress
    every: "10%"
    command: "/home/me/bin/notify.sh"
```

```bash
#!/bin/bash
# notify.sh: IOPS exports the event details as IOPS_* variables
curl -s -X POST -d "text=${IOPS_BENCHMARK}: ${IOPS_COMPLETED}/${IOPS_TOTAL} done (${IOPS_FAILED} failed)" \
  "$WEBHOOK_URL"
```

### Copy the results when the run completes

```yaml
hooks:
  - name: sync_results
    event: finish
    when: completed
    timeout: 1800
    command: "rsync -a {{ workdir | quote }}/ me@storage:/archive/{{ benchmark.name | quote }}/"
```

The default timeout is 60 seconds, so raise it for commands that move data.

### Alert on failures

```yaml
hooks:
  - name: many_failures
    event: failures
    at: ["10%", "25%"]
    min_tests: 20
    command: >
      echo {{ message | quote }} |
      mail -s "IOPS: {{ progress.failed }} tests failing" me@example.org

  - name: stuck
    event: consecutive_failures
    at: 5
    command: >
      echo {{ message | quote }} |
      mail -s "IOPS: {{ progress.consecutive_failures }} failures in a row" me@example.org
```

A complete runnable configuration is in `examples/hooks/hooks.yaml`.

---

## How Hooks Run

- **Where**: on the host running IOPS, not inside the benchmark jobs. On a SLURM cluster this is the login node (or wherever you started `iops run`), including in [single-allocation mode](../single-allocation-mode), since the runner stays on the submitting host. Commands such as `mail` therefore need to exist there.
- **Shell and directory**: the rendered command is run with bash, with the run directory as the working directory.
- **Order and isolation**: hooks run one at a time, in the order they fired, on a background worker, so a slow hook does not stall the benchmark. Each command runs in its own session, so pressing Ctrl+C on IOPS does not kill a hook that is reporting the interruption.
- **Timeout**: after `timeout` seconds the command and its child processes are killed.
- **Failures**: a hook that cannot be rendered, exits non-zero, or times out is logged as a warning. It never changes the outcome of the run.
- **Finish**: IOPS waits for pending hooks before exiting, so the last notification is not lost.
- **Log**: the command, exit status, duration, and its output (truncated) are appended to `__iops_hooks.log` in the run directory.
- **Dry run**: `iops run --dry-run` lists the configured hooks and does not fire them.

---

## Testing Hooks

`iops check` validates the `hooks` section, including rendering every command against a sample context, so a misspelled name such as `{{ progres.total }}` is caught before the run.

`iops hooks test` goes further and executes the commands, so a mail command or a script can be tried before a long run:

```bash
iops hooks test config.yaml                       # fire every hook once
iops hooks test config.yaml --hook halfway_mail   # only this hook (repeatable)
iops hooks test config.yaml --event finish        # only hooks for one event
iops hooks test config.yaml --render-only         # print the commands, run nothing
iops hooks test config.yaml --machine cluster     # apply machine overrides
```

The commands are rendered against a sample context: a run of 100 tests, halfway through, with the numbers adjusted to agree with the hook's first threshold (a `progress` hook at `"25%"` sees 25 concluded tests). `workdir` is set to the configured base working directory rather than a run folder. No folders are created and nothing is benchmarked. For each hook the rendered command, exit code, and output are printed, and the exit status is 1 if any hook failed.

---

## Limitations

- If the IOPS process is killed with SIGKILL or reaches a walltime limit, it cannot run the `finish` hooks. Use `progress` hooks if you need to know a run went silent.
- Hooks see run-level information only. Per-test variables are not part of the context.
- Percentages for adaptive searches are approximate, because the total is re-estimated during the run.
- Hooks run on the host running IOPS. They cannot run on the compute nodes.
- Hook commands cannot change the run (for example, they cannot stop it).

---

## See Also

- [YAML Schema Reference](../yaml-schema#hooks-optional)
- [Budget Control](../budget-control) for the `budget_exceeded` outcome
- [Metadata Files](../metadata-files) for `__iops_hooks.log`
