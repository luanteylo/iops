---
title: "Probe System"
weight: 20
---

This page documents the IOPS system probe mechanism that collects runtime information from compute nodes. Understanding this system is essential for developers who want to extend the collected metrics or modify the probe behavior.

## Overview

The probe system collects system information (CPU, memory, filesystems, etc.) from the actual compute node where the benchmark runs. This is particularly important for SLURM jobs where the login node differs from compute nodes.

**Key files:**
- `__iops_exit_handler.sh` - Centralized EXIT trap coordinator
- `__iops_atexit_sysinfo.sh` - System info collection script
- `__iops_sysinfo.json` - Collected data (generated at runtime)

## Architecture

```
User Script                     Exit Handler                    Sysinfo Script
┌─────────────────────┐        ┌─────────────────────┐        ┌─────────────────────┐
│ #!/bin/bash         │        │ # Sets EXIT trap    │        │ # Registers cleanup │
│ #SBATCH ...         │        │ trap '_iops_run_    │        │ _iops_register_exit │
│                     │        │   exit_actions' EXIT│        │   "_iops_collect_   │
│ # IOPS injection    │        │                     │        │    sysinfo"         │
│ source handler.sh   │───────►│ # Registry array    │        │                     │
│ source sysinfo.sh   │───────────────────────────────────────►│ # Collection func   │
│                     │        │ _iops_register_exit │        │ _iops_collect_      │
│ # User's benchmark  │        │   () { ... }        │        │   sysinfo() { ... } │
│ mpirun ./benchmark  │        └─────────────────────┘        └─────────────────────┘
└─────────────────────┘                  │
         │                               │
         ▼ (on script exit)              ▼
┌─────────────────────┐        ┌─────────────────────┐
│ __iops_sysinfo.json │◄───────│ _iops_run_exit_     │
│ {                   │        │   actions() calls   │
│   "hostname": ...,  │        │ all registered      │
│   "cpu_model": ..., │        │ functions           │
│   "duration": ...   │        └─────────────────────┘
│ }                   │
└─────────────────────┘
```

The exit handler provides a centralized EXIT trap that other IOPS features register with. This avoids trap conflicts when multiple features (system probe, resource sampler) need cleanup actions.

## How It Works

### 1. Script Injection

When preparing execution artifacts, the planner writes all IOPS helper scripts and injects source lines into the user script:

```python
# iops/execution/planner.py
def _inject_iops_scripts(self, script_text: str, exec_dir: Path) -> str:
    # 1. Write exit handler (always needed)
    handler_file = exec_dir / EXIT_HANDLER_FILENAME
    with open(handler_file, "w") as f:
        f.write(EXIT_HANDLER_TEMPLATE)

    # 2. Write sysinfo script (if enabled)
    if collect_system_info:
        probe_script = SYSTEM_PROBE_TEMPLATE.format(execution_dir=str(exec_dir))
        probe_file = exec_dir / ATEXIT_SYSINFO_FILENAME
        with open(probe_file, "w") as f:
            f.write(probe_script)

    # 3. Inject source lines after shebang/#SBATCH
    # ... insertion logic ...
```

### 2. Exit Handler Mechanism

The exit handler sets a single EXIT trap and provides a registration function:

```bash
# __iops_exit_handler.sh
_IOPS_EXIT_ACTIONS=()

_iops_register_exit() {
    _IOPS_EXIT_ACTIONS+=("$1")
}

_iops_run_exit_actions() {
    for _iops_action in "${_IOPS_EXIT_ACTIONS[@]}"; do
        $_iops_action 2>/dev/null || true
    done
}

trap '_iops_run_exit_actions' EXIT
```

The sysinfo script registers its collection function:

```bash
# __iops_atexit_sysinfo.sh
_iops_register_exit "_iops_collect_sysinfo"
```

This ensures the probe runs:
- After the benchmark completes (success or failure)
- On the actual compute node (not the login node)
- Without affecting the script's exit code
- Without conflicting with other IOPS features' cleanup actions

### 3. Data Collection

When the script exits, `_iops_collect_sysinfo()` runs and writes JSON to `__iops_sysinfo.json`:

```bash
_iops_collect_sysinfo() {
  (
    _iops_sysinfo="{execution_dir}/__iops_sysinfo.json"
    {
      echo "{"
      echo "  \"hostname\": \"$(hostname)\","
      echo "  \"cpu_model\": \"...\","
      # ... more fields
      echo "  \"duration_seconds\": ${SECONDS}"
      echo "}"
    } > "$_iops_sysinfo"
  ) 2>/dev/null || true
}
```

### 4. Data Retrieval

After execution, the executor reads the sysinfo and stores it in test metadata:

```python
# iops/execution/executors.py
def _collect_system_info(self, test: ExecutionInstance) -> Optional[Dict]:
    sysinfo_path = Path(test.execution_dir) / SYSINFO_FILENAME
    with open(sysinfo_path, 'r') as f:
        return json.load(f)

# Called after test completion
sysinfo = self._collect_system_info(test)
if sysinfo:
    test.metadata["__sysinfo"] = sysinfo
```

## Collected Fields

| Field | Source | Description |
|-------|--------|-------------|
| `hostname` | `hostname` command | Compute node hostname |
| `cpu_model` | `/proc/cpuinfo` | CPU model name |
| `cpu_cores` | `nproc` command | Number of CPU cores |
| `memory_kb` | `/proc/meminfo` | Total memory in KB |
| `kernel` | `uname -r` | Linux kernel version |
| `os` | `/etc/os-release` | OS name and version |
| `ib_devices` | `/sys/class/infiniband/` | InfiniBand devices (comma-separated) |
| `filesystems` | `df -T` | Detected parallel filesystems |
| `duration_seconds` | `$SECONDS` | Script execution time |

### Parallel Filesystem Detection

The probe detects these parallel/distributed filesystems:

| Type | Detection Method |
|------|-----------------|
| Lustre | `df -T` type = `lustre` |
| GPFS | `df -T` type = `gpfs` |
| BeeGFS | `df -T` type = `beegfs` |
| CephFS | `df -T` type = `cephfs` |
| PanFS | `df -T` type = `panfs` |
| WekaFS | `df -T` type = `wekafs` |
| PVFS2 | `df -T` type = `pvfs2` |
| OrangeFS | `df -T` type = `orangefs` |
| GlusterFS | `df -T` type = `glusterfs` |
| FUSE mounts | `df -T` type = `fuse` with known mount patterns |

Output format: `type:mountpoint,type:mountpoint,...`

Example: `lustre:/scratch,gpfs:/home`

## Design Decisions

### Why Separate Files?

The probe is written as separate files (`__iops_exit_handler.sh`, `__iops_atexit_sysinfo.sh`) rather than inlined into the user script:

1. **Clean user scripts** - Users can inspect their scripts without probe code clutter
2. **Easy debugging** - Each script can be examined or modified independently
3. **Consistent behavior** - Same code across all scripts
4. **Modular design** - Features can be enabled/disabled independently

### Why Centralized Exit Handler?

Using a single EXIT trap with registration instead of multiple traps:

1. **No conflicts** - Multiple features can register cleanup actions
2. **Predictable order** - Actions run in registration order
3. **Isolated failures** - One action's failure doesn't affect others

### Why EXIT Trap?

Using `trap ... EXIT` instead of appending code at the end:

1. **Runs on failure** - Collects info even if benchmark crashes
2. **Runs on signals** - Handles SIGTERM, SIGINT gracefully
3. **No user code modification** - Works regardless of script structure

### Why Subshell with `|| true`?

```bash
_iops_collect_sysinfo() {
  (
    # ... collection code ...
  ) 2>/dev/null || true
}
```

1. **Never affects exit code** - Benchmark's exit code is preserved
2. **Isolated errors** - Probe failures don't break the benchmark
3. **Silent failures** - stderr redirected to avoid noise

### Why `$SECONDS`?

The bash `$SECONDS` variable automatically tracks time since script start:

1. **Accurate** - Measures actual script execution time
2. **Simple** - No need for explicit timing code
3. **Includes everything** - Setup, benchmark, and cleanup time

## Configuration

### Disabling the Probe

```yaml
benchmark:
  collect_system_info: false
```

When disabled:
- `__iops_atexit_sysinfo.sh` is not written
- `__iops_sysinfo.json` is not generated
- `duration_seconds` is not available in status files

Note: The exit handler (`__iops_exit_handler.sh`) is still written if other features (like resource tracing) are enabled.

### Impact on Features

| Feature | With Probe | Without Probe |
|---------|-----------|---------------|
| System info in reports | Yes | No |
| `duration_seconds` in status | Yes | No (uses timestamps) |
| Watch mode timing | Accurate | Includes queue time |
| Cache duration | Available | Not available |


## Source Code References

| File | Purpose |
|------|---------|
| `iops/execution/planner.py` | Exit handler, probe template, and injection |
| `iops/execution/executors.py` | Sysinfo collection after execution |
| `iops/execution/runner.py` | Stores sysinfo in status file |

### Key Constants

```python
# iops/execution/planner.py
EXIT_HANDLER_FILENAME = "__iops_exit_handler.sh"
ATEXIT_SYSINFO_FILENAME = "__iops_atexit_sysinfo.sh"
EXIT_HANDLER_TEMPLATE = '''...'''
SYSTEM_PROBE_TEMPLATE = '''...'''

# iops/execution/executors.py
SYSINFO_FILENAME = "__iops_sysinfo.json"
```

### Key Functions

| Function | Location | Purpose |
|----------|----------|---------|
| `_inject_iops_scripts()` | planner.py | Writes all IOPS scripts and modifies user script |
| `_collect_system_info()` | executors.py | Reads sysinfo after execution |
| `_iops_register_exit()` | exit handler | Registers cleanup action |
| `_iops_run_exit_actions()` | exit handler | Executes all registered actions |
| `_iops_collect_sysinfo()` | sysinfo script | Bash function that collects data |
| `_iops_detect_pfs()` | sysinfo script | Detects parallel filesystems |

