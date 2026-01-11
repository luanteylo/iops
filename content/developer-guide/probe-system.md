---
title: "Probe System"
weight: 20
---

This page documents the IOPS system probe mechanism that collects runtime information from compute nodes. Understanding this system is essential for developers who want to extend the collected metrics or modify the probe behavior.

## Overview

The probe system collects system information (CPU, memory, filesystems, etc.) from the actual compute node where the benchmark runs. This is particularly important for SLURM jobs where the login node differs from compute nodes.

**Key files:**
- `__iops_probe.sh` - Probe script (written before test runs)
- `__iops_sysinfo.json` - Collected data (generated at runtime)

## Architecture

```
User Script                     Probe Script
┌─────────────────────┐        ┌─────────────────────┐
│ #!/bin/bash         │        │ #!/bin/bash         │
│                     │        │                     │
│ # User's benchmark  │        │ # EXIT trap setup   │
│ mpirun ./benchmark  │        │ trap '_iops_collect │
│                     │        │      _sysinfo' EXIT │
│ # Source probe      │───────►│                     │
│ source probe.sh     │        │ # Collection func   │
│                     │        │ _iops_collect_      │
└─────────────────────┘        │   sysinfo() { ... } │
         │                     └─────────────────────┘
         │
         ▼ (on script exit)
┌─────────────────────┐
│ __iops_sysinfo.json │
│ {                   │
│   "hostname": ...,  │
│   "cpu_model": ..., │
│   "duration": ...   │
│ }                   │
└─────────────────────┘
```

## How It Works

### 1. Probe Script Generation

When preparing execution artifacts, the planner writes the probe script to each repetition folder:

```python
# iops/execution/planner.py
def _inject_system_probe(self, script_text: str, exec_dir: Path) -> str:
    # Write probe script to separate file
    probe_script = SYSTEM_PROBE_TEMPLATE.format(execution_dir=str(exec_dir))
    probe_file = exec_dir / PROBE_FILENAME
    with open(probe_file, "w") as f:
        f.write(probe_script)

    # Add source line to user script
    script_text += f'\nsource "{probe_file}"\n'
    return script_text
```

### 2. EXIT Trap Mechanism

The probe uses bash's `trap` command to register a function that runs when the script exits:

```bash
trap '_iops_collect_sysinfo' EXIT
```

This ensures the probe runs:
- After the benchmark completes (success or failure)
- On the actual compute node (not the login node)
- Without affecting the script's exit code

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

### Why a Separate File?

The probe is written as a separate file (`__iops_probe.sh`) rather than inlined into the user script:

1. **Clean user scripts** - Users can inspect their scripts without probe code clutter
2. **Easy debugging** - Probe can be examined or modified independently
3. **Consistent behavior** - Same probe code across all scripts

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
- `__iops_probe.sh` is not written
- `__iops_sysinfo.json` is not generated
- User scripts run without modification
- `duration_seconds` is not available in status files

### Impact on Features

| Feature | With Probe | Without Probe |
|---------|-----------|---------------|
| System info in reports | Yes | No |
| `duration_seconds` in status | Yes | No (uses timestamps) |
| Watch mode timing | Accurate | Includes queue time |
| Cache duration | Available | Not available |


s
## Source Code References

| File | Purpose |
|------|---------|
| `iops/execution/planner.py` | Probe template and injection |
| `iops/execution/executors.py` | Sysinfo collection after execution |
| `iops/execution/runner.py` | Stores sysinfo in status file |

### Key Constants

```python
# iops/execution/planner.py
PROBE_FILENAME = "__iops_probe.sh"
SYSTEM_PROBE_TEMPLATE = '''...'''

# iops/execution/executors.py
SYSINFO_FILENAME = "__iops_sysinfo.json"
```

### Key Functions

| Function | Location | Purpose |
|----------|----------|---------|
| `_inject_system_probe()` | planner.py | Writes probe and modifies script |
| `_collect_system_info()` | executors.py | Reads sysinfo after execution |
| `_iops_collect_sysinfo()` | probe script | Bash function that collects data |
| `_iops_detect_pfs()` | probe script | Detects parallel filesystems |

