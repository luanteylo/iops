---
title: "Probe System"
weight: 20
---

This page documents the IOPS system probe mechanism for developers who want to extend the collected metrics or modify probe behavior.

## Overview

The probe system collects system information (CPU, memory, filesystems, etc.) from the actual compute node where the benchmark runs. This matters for SLURM jobs, where the login node differs from compute nodes.

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

The exit handler provides a centralized EXIT trap that other IOPS features (system probe, resource sampler) register cleanup actions with, avoiding trap conflicts.

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

The probe therefore runs after the benchmark completes (success or failure), on the actual compute node, without affecting the script's exit code or conflicting with other features' cleanup actions.

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

The probe is written as separate files (`__iops_exit_handler.sh`, `__iops_atexit_sysinfo.sh`) rather than inlined into the user script. This keeps user scripts clean and inspectable, makes each script debuggable on its own, guarantees identical probe code across scripts, and lets features be enabled or disabled independently.

### Why Centralized Exit Handler?

A single EXIT trap with registration, instead of multiple traps, avoids trap conflicts between features, runs actions in a predictable (registration) order, and isolates failures so one action cannot break the others.

### Why EXIT Trap?

Using `trap ... EXIT` instead of appending code at the end means collection runs even if the benchmark crashes or receives SIGTERM/SIGINT, and works regardless of the user script's structure.

### Why Subshell with `|| true`?

```bash
_iops_collect_sysinfo() {
  (
    # ... collection code ...
  ) 2>/dev/null || true
}
```

The subshell with `|| true` and stderr redirected guarantees the probe never changes the benchmark's exit code and that probe failures stay silent and isolated.

### Why `$SECONDS`?

The bash `$SECONDS` variable tracks time since script start with no explicit timing code, covering setup, benchmark, and cleanup time.

## Configuration

### Disabling the Probe

```yaml
benchmark:
  probes:
    system_snapshot: false
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


## Version Probe

The version probe captures software and library versions once per execution. This is metadata, not a measured metric, and it is the cache-mixing detector: the HTML report warns when a component reports more than one distinct version across executions, catching studies that mix fresh results with older cached results from a different software environment.

### How It Works

1. When `benchmark.probes.versions` is configured, `_inject_iops_scripts()` calls `_build_version_probe_script()` and writes the result to `__iops_atexit_versions.sh` in the repetition folder.
2. The generated benchmark script sources `__iops_atexit_versions.sh` after the shebang/`#SBATCH` header. The script defines `_iops_capture_versions()` and registers it with the centralized exit handler via `_iops_register_exit` (falling back to immediate execution when no handler is present, e.g. standalone runs).
3. Capture therefore runs **after the benchmark body** via the `EXIT` trap, in the same shell. This is deliberate: version tools are frequently only on `PATH` after the benchmark's own `module load` commands, and the trap sees that modified environment.
4. `_iops_capture_versions()` runs each configured command, captures its stdout (up to 4000 bytes), JSON-escapes it, and writes `__iops_versions.json`.
5. Capture is best-effort: a failing command yields an empty string and does not abort the run.

```yaml
benchmark:
  probes:
    versions:
      app: "myapp --version"
      mpi: "mpirun --version | head -1"
      compiler: "gcc --version | head -1"
```

### Version Probe Script Structure

```bash
#!/bin/bash
# IOPS Version Probe - captures software/library versions once per execution.
_iops_capture_versions() {
  (
    _iops_versions_file="/path/to/exec/repetition_1/__iops_versions.json"
    _iops_json_escape() { ... }
    {
      echo "{"
      _iops_vraw=$( { myapp --version ; } 2>/dev/null | head -c 4000 )
      _iops_vesc=$(printf "%s" "$_iops_vraw" | _iops_json_escape)
      printf '  %s: "%s"\n' '"app"' "$_iops_vesc"
      echo "}"
    } > "$_iops_versions_file" 2>/dev/null
  ) 2>/dev/null || true
}
_iops_capture_versions
```

### Output File

`__iops_versions.json` is written to each repetition directory:

```json
{
  "app": "myapp 2.3.1",
  "mpi": "OpenMPI 4.1.5",
  "compiler": "gcc (GCC) 11.3.0"
}
```

Constants and functions for the version probe are listed in [Source Code References](#source-code-references) below.

---

## Source Code References

| File | Purpose |
|------|---------|
| `iops/execution/planner.py` | Exit handler, probe templates, and script injection |
| `iops/execution/executors.py` | Sysinfo collection after execution |
| `iops/execution/runner.py` | Stores sysinfo in status file |
| `iops/reporting/report_generator.py` | Gallery and Software Versions HTML sections |

### Key Constants

```python
# iops/execution/planner.py
EXIT_HANDLER_FILENAME = "__iops_exit_handler.sh"
ATEXIT_SYSINFO_FILENAME = "__iops_atexit_sysinfo.sh"
EXIT_HANDLER_TEMPLATE = '''...'''
SYSTEM_PROBE_TEMPLATE = '''...'''
ATEXIT_VERSION_FILENAME = "__iops_atexit_versions.sh"
VERSIONS_FILENAME = "__iops_versions.json"

# iops/execution/executors.py
SYSINFO_FILENAME = "__iops_sysinfo.json"
```

### Key Functions

| Function | Location | Purpose |
|----------|----------|---------|
| `_inject_iops_scripts()` | planner.py | Writes all IOPS scripts and modifies user script |
| `_build_version_probe_script()` | planner.py | Builds the version capture shell script |
| `_collect_system_info()` | executors.py | Reads sysinfo after execution |
| `_iops_register_exit()` | exit handler | Registers cleanup action |
| `_iops_run_exit_actions()` | exit handler | Executes all registered actions |
| `_iops_collect_sysinfo()` | sysinfo script | Bash function that collects data |
| `_iops_detect_pfs()` | sysinfo script | Detects parallel filesystems |
| `_iops_capture_versions()` | version probe script | Bash function that captures software versions |
| `_generate_versions_section()` | report_generator.py | Renders the Software Versions HTML section with drift detection |
| `_load_execution_versions()` | report_generator.py | Reads all `__iops_versions.json` files for a run |

