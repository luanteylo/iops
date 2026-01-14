"""
Planners for IOPS benchmark execution.

This module contains all planner implementations:
- BasePlanner: Abstract base class with registry pattern
- ExhaustivePlanner: Brute-force search of entire parameter space
- RandomSamplingPlanner: Random sampling of parameter space
- BayesianPlanner: Bayesian optimization for intelligent search
"""

from iops.logger import HasLogger
from iops.config.models import GenericBenchmarkConfig
from iops.execution.matrix import ExecutionInstance, build_execution_matrix, create_execution_instance
from iops.execution.constraints import check_constraints_for_vars

from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
from pathlib import Path
from collections import defaultdict
import random
import json
import warnings


# ============================================================================ #
# IOPS Script Injection Constants
# ============================================================================ #

# IOPS injects helper scripts into user benchmarks for monitoring and data
# collection. These scripts use a centralized exit handler architecture:
#
# 1. Exit Handler (__iops_exit_handler.sh):
#    - Sets a single EXIT trap for the entire script
#    - Features register their cleanup actions with the handler
#    - On exit, executes all registered actions in order
#
# 2. System Probe (__iops_probe.sh):
#    - Collects system information from compute nodes
#    - Registers _iops_collect_sysinfo with exit handler
#
# 3. Resource Sampler (__iops_sampler.sh):
#    - Collects CPU/memory utilization during execution
#    - For SLURM multi-node: uses srun to launch on all nodes
#    - Registers sentinel file cleanup with exit handler
#
# Key design decisions:
# - Single EXIT trap avoids conflicts between features
# - All commands have fallbacks and 2>/dev/null to never fail
# - Minimal overhead: registration is O(1), execution is O(n)
# - Extensible: new features just register their cleanup action

# Filename for the exit handler script (written to execution directory)
EXIT_HANDLER_FILENAME = "__iops_exit_handler.sh"

# Filename for the system probe script - runs at exit to collect node info
# Naming convention: __iops_atexit_* for scripts that run via the exit trap
ATEXIT_SYSINFO_FILENAME = "__iops_atexit_sysinfo.sh"

# Filename for the execution parameters (written to exec_XXXX directory)
PARAMS_FILENAME = "__iops_params.json"

# Filename for the execution index (written to run root)
INDEX_FILENAME = "__iops_index.json"

# Filename for the execution status (written to exec_XXXX directory after completion)
STATUS_FILENAME = "__iops_status.json"

# Test-level status constants (written by planner to exec_XXXX directory)
# These are distinct from repetition-level status (written by executor to repetition_YYY directory)
TEST_STATUS_SKIPPED = "SKIPPED"    # Test will not be executed (constraint or planner decision)
TEST_STATUS_PENDING = "PENDING"    # Test is queued, no repetitions started yet
TEST_STATUS_COMPLETE = "COMPLETE"  # All repetitions finished

# Exit handler template - centralized EXIT trap coordinator
# This script is sourced first and provides a single EXIT trap that other
# features can register their cleanup actions with.
# Note: This template has no placeholders - it's written as-is to the file.
EXIT_HANDLER_TEMPLATE = '''#!/bin/bash
# IOPS Exit Handler - Centralized exit coordination for all IOPS features
# This file is auto-generated and sourced by the main script.
# It provides a single EXIT trap that executes all registered cleanup actions.

# Registry of exit actions (function names to call on exit)
_IOPS_EXIT_ACTIONS=()

# Register a cleanup action to run on script exit
# Usage: _iops_register_exit "function_name"
# Performance: O(1) - just appends to array
_iops_register_exit() {
    _IOPS_EXIT_ACTIONS+=("$1")
}

# Execute all registered exit actions
# Called by the EXIT trap - runs each action in registration order
# Each action runs in isolation (failures don't affect other actions)
_iops_run_exit_actions() {
    for _iops_action in "${_IOPS_EXIT_ACTIONS[@]}"; do
        $_iops_action 2>/dev/null || true
    done
}

# Set the single EXIT trap for the entire script
trap '_iops_run_exit_actions' EXIT
'''

# System probe script template - written as a separate file and sourced by user script
# Note: This script does NOT set its own trap. Instead, it registers its cleanup
# action with the centralized exit handler.
SYSTEM_PROBE_TEMPLATE = '''#!/bin/bash
# IOPS System Probe - Collects system information from compute node
# This file is auto-generated and sourced by the main script.
# It registers with the exit handler to collect info after the benchmark completes.

_iops_detect_pfs() {{
  _pfs_result=""
  while read -r _fs _type _size _used _avail _pct _mount; do
    [ -z "$_mount" ] && continue
    [[ "$_fs" == "Filesystem" ]] && continue
    if [[ "$_type" =~ ^(lustre|gpfs|beegfs|cephfs|panfs|wekafs|pvfs2|orangefs|glusterfs)$ ]]; then
      [ -n "$_pfs_result" ] && _pfs_result="$_pfs_result,"
      _pfs_result="${{_pfs_result}}${{_type}}:${{_mount}}"
    elif [[ "$_type" == "fuse" ]] && [[ "$_mount" =~ (beegfs|lustre|gpfs|ceph|panfs|weka|pvfs|orangefs|gluster) ]]; then
      [ -n "$_pfs_result" ] && _pfs_result="$_pfs_result,"
      _pfs_result="${{_pfs_result}}fuse:${{_mount}}"
    fi
  done < <(df -T 2>/dev/null)
  echo "$_pfs_result"
}}

_iops_collect_sysinfo() {{
  (
    _iops_sysinfo="{execution_dir}/__iops_sysinfo.json"
    {{
      echo "{{"
      echo "  \\"hostname\\": \\"$(hostname 2>/dev/null || echo 'unknown')\\","
      echo "  \\"cpu_model\\": \\"$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | sed 's/^[ \\t]*//' | sed 's/"/\\\\"/g' || echo 'unknown')\\","
      echo "  \\"cpu_cores\\": $(nproc 2>/dev/null || echo 0),"
      echo "  \\"memory_kb\\": $(awk '/MemTotal/{{print $2}}' /proc/meminfo 2>/dev/null || echo 0),"
      echo "  \\"kernel\\": \\"$(uname -r 2>/dev/null || echo 'unknown')\\","
      echo "  \\"os\\": \\"$(grep -m1 PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '\\"' || uname -s 2>/dev/null || echo 'unknown')\\","
      echo "  \\"ib_devices\\": \\"$(ls /sys/class/infiniband/ 2>/dev/null | tr '\\n' ',' | sed 's/,$//' || echo '')\\","
      echo "  \\"filesystems\\": \\"$(_iops_detect_pfs)\\","
      echo "  \\"duration_seconds\\": ${{SECONDS}}"
      echo "}}"
    }} > "$_iops_sysinfo"
  ) 2>/dev/null || true
}}

# Register with the centralized exit handler
_iops_register_exit "_iops_collect_sysinfo"
'''

# Filename for the resource sampler script - runs during execution to collect metrics
# Naming convention: __iops_runtime_* for scripts that run during benchmark execution
RUNTIME_SAMPLER_FILENAME = "__iops_runtime_sampler.sh"

# Filename for the sentinel file (signals samplers to stop)
SAMPLER_SENTINEL_FILENAME = "__iops_trace_running"

# Filename for the resource trace output (written by sampler during execution)
TRACE_FILENAME_PREFIX = "__iops_trace_"

# Resource sampler script template - runs in background during execution
# Collects per-core CPU utilization and memory usage at configurable intervals
#
# For SLURM multi-node jobs:
# - Launched via srun on all nodes
# - Uses sentinel file for termination (removed by exit handler)
# - Each node writes to its own trace file (hostname in filename)
#
# This script can be:
# - Sourced by the main script (sets up launcher + registers cleanup)
# - Executed standalone via srun (just runs the sampling loop)
RESOURCE_SAMPLER_TEMPLATE = '''#!/bin/bash
# IOPS Resource Sampler - Collects CPU and memory utilization during execution
# This file is auto-generated. It can be sourced (to set up and launch) or
# executed directly via srun (for multi-node sampling).

_IOPS_EXEC_DIR="{execution_dir}"
_IOPS_TRACE_FILE="${{_IOPS_EXEC_DIR}}/{trace_prefix}$(hostname).csv"
_IOPS_INTERVAL={trace_interval}
_IOPS_SENTINEL="${{_IOPS_EXEC_DIR}}/{sentinel_filename}"

# Previous CPU stats for delta calculation (associative array: cpu_id -> "user nice system idle iowait irq softirq")
declare -A _iops_prev_cpu

_iops_sample() {{
    local ts=$(date +%s.%N 2>/dev/null || date +%s)
    local host=$(hostname 2>/dev/null || echo "unknown")

    # Memory stats (single sample per iteration)
    local mem_total=$(awk '/MemTotal/{{print $2}}' /proc/meminfo 2>/dev/null || echo 0)
    local mem_avail=$(awk '/MemAvailable/{{print $2}}' /proc/meminfo 2>/dev/null || echo 0)

    # CPU stats per core (from /proc/stat)
    while read -r line; do
        # Parse lines like: cpu0 1234 567 890 12345 678 90 12 0 0 0
        local cpu_id=$(echo "$line" | awk '{{print $1}}')
        local user=$(echo "$line" | awk '{{print $2}}')
        local nice=$(echo "$line" | awk '{{print $3}}')
        local system=$(echo "$line" | awk '{{print $4}}')
        local idle=$(echo "$line" | awk '{{print $5}}')
        local iowait=$(echo "$line" | awk '{{print $6}}')
        local irq=$(echo "$line" | awk '{{print $7}}')
        local softirq=$(echo "$line" | awk '{{print $8}}')

        # Skip if this is the aggregate "cpu" line (we want per-core)
        [[ "$cpu_id" == "cpu" ]] && continue

        # Extract core number (cpu0 -> 0, cpu1 -> 1, etc.)
        local core="${{cpu_id#cpu}}"

        # Get previous values
        local prev="${{_iops_prev_cpu[$cpu_id]:-}}"

        if [[ -n "$prev" ]]; then
            # Calculate deltas
            local prev_user=$(echo "$prev" | awk '{{print $1}}')
            local prev_nice=$(echo "$prev" | awk '{{print $2}}')
            local prev_system=$(echo "$prev" | awk '{{print $3}}')
            local prev_idle=$(echo "$prev" | awk '{{print $4}}')
            local prev_iowait=$(echo "$prev" | awk '{{print $5}}')
            local prev_irq=$(echo "$prev" | awk '{{print $6}}')
            local prev_softirq=$(echo "$prev" | awk '{{print $7}}')

            local d_user=$((user - prev_user))
            local d_nice=$((nice - prev_nice))
            local d_system=$((system - prev_system))
            local d_idle=$((idle - prev_idle))
            local d_iowait=$((iowait - prev_iowait))
            local d_irq=$((irq - prev_irq))
            local d_softirq=$((softirq - prev_softirq))

            local d_total=$((d_user + d_nice + d_system + d_idle + d_iowait + d_irq + d_softirq))

            if [[ $d_total -gt 0 ]]; then
                # Calculate percentages (using awk for floating point)
                local cpu_user_pct=$(awk "BEGIN {{printf \\"%.2f\\", ($d_user + $d_nice) / $d_total * 100}}")
                local cpu_system_pct=$(awk "BEGIN {{printf \\"%.2f\\", ($d_system + $d_irq + $d_softirq) / $d_total * 100}}")
                local cpu_idle_pct=$(awk "BEGIN {{printf \\"%.2f\\", ($d_idle + $d_iowait) / $d_total * 100}}")

                # Output CSV line
                echo "$ts,$host,$core,$cpu_user_pct,$cpu_system_pct,$cpu_idle_pct,$mem_total,$mem_avail"
            fi
        fi

        # Store current values for next iteration
        _iops_prev_cpu[$cpu_id]="$user $nice $system $idle $iowait $irq $softirq"

    done < <(grep '^cpu[0-9]' /proc/stat 2>/dev/null)
}}

_iops_sampler_loop() {{
    # Write CSV header
    echo "timestamp,hostname,core,cpu_user_pct,cpu_system_pct,cpu_idle_pct,mem_total_kb,mem_available_kb" > "$_IOPS_TRACE_FILE"

    # Initial read to populate baseline (first sample won't produce output)
    _iops_sample > /dev/null 2>&1

    # Main sampling loop - exits when sentinel file is removed
    while [[ -f "$_IOPS_SENTINEL" ]]; do
        sleep "$_IOPS_INTERVAL"
        _iops_sample >> "$_IOPS_TRACE_FILE" 2>/dev/null
    done
}}

# Cleanup function - removes sentinel file to signal all samplers to stop
_iops_stop_samplers() {{
    rm -f "$_IOPS_SENTINEL" 2>/dev/null || true
}}

# Check if running standalone (executed) vs sourced
if [[ "${{BASH_SOURCE[0]}}" == "${{0}}" ]]; then
    # Running standalone (via srun) - just run the sampling loop
    # The sentinel file and exit handler registration are done by the sourcing script
    _iops_sampler_loop
else
    # Being sourced - set up and launch the samplers

    # Create sentinel file (signals samplers to keep running)
    touch "$_IOPS_SENTINEL"

    # Register cleanup with the centralized exit handler
    _iops_register_exit "_iops_stop_samplers"

    # Launch samplers on all nodes
    if [[ -n "$SLURM_JOB_ID" && "${{SLURM_NNODES:-1}}" -gt 1 ]]; then
        # SLURM multi-node: use srun to launch sampler on all nodes
        # --overlap allows this srun to coexist with user's MPI srun
        # --ntasks-per-node=1 runs exactly one sampler per node
        srun --overlap --nodes=${{SLURM_NNODES}} --ntasks-per-node=1 \
            bash "${{BASH_SOURCE[0]}}" </dev/null >/dev/null 2>&1 &
    else
        # Single node (local or SLURM single-node): run sampler locally in background
        _iops_sampler_loop </dev/null >/dev/null 2>&1 &
        # Lower priority of sampler process
        renice -n 19 -p "$!" >/dev/null 2>&1 || true
    fi
fi
'''

# Optional imports for Bayesian optimization
try:
    from skopt import Optimizer
    from skopt.space import Integer, Real, Categorical
    import numpy as np
    SKOPT_AVAILABLE = True
    # Suppress skopt warning about duplicate points - it handles this by using random points
    warnings.filterwarnings('ignore', message='.*objective has been evaluated at point.*', category=UserWarning)
except ImportError:
    SKOPT_AVAILABLE = False


# ============================================================================ #
# Base Planner
# ============================================================================ #

class BasePlanner(ABC, HasLogger):
    """
    Abstract base class for all planners.

    Uses a registry pattern to allow dynamic selection of planners by name.
    """

    _registry = {}

    def __init__(self, cfg: GenericBenchmarkConfig):
        self.cfg = cfg
        # create a random generator with a fixed seed for reproducibility
        self.random = random.Random(cfg.benchmark.random_seed)
        # Track whether folders have been initialized upfront
        self._folders_initialized = False
        # Store skipped instances (from constraints or planner selection)
        self.skipped_matrix: List[ExecutionInstance] = []
        self._log_benchmark_config(cfg.benchmark)

    def _log_benchmark_config(self, bench) -> None:
        """Log benchmark configuration in a readable format."""
        self.logger.info("Planner initialized with benchmark config:")
        self.logger.info("  name: %s", bench.name)
        if bench.description:
            self.logger.info("  description: %s", bench.description)
        self.logger.info("  workdir: %s", bench.workdir)
        self.logger.info("  executor: %s", bench.executor)
        self.logger.info("  search_method: %s", bench.search_method)
        self.logger.info("  repetitions: %s", bench.repetitions)
        self.logger.info("  random_seed: %s", bench.random_seed)
        if bench.cache_file:
            self.logger.info("  cache_file: %s", bench.cache_file)
        if bench.cache_exclude_vars:
            self.logger.info("  cache_exclude_vars: %s", bench.cache_exclude_vars)
        if bench.exhaustive_vars:
            self.logger.info("  exhaustive_vars: %s", bench.exhaustive_vars)
        if bench.max_core_hours:
            self.logger.info("  max_core_hours: %s", bench.max_core_hours)
        if bench.cores_expr:
            self.logger.info("  cores_expr: %s", bench.cores_expr)
        if bench.estimated_time_seconds:
            self.logger.info("  estimated_time_seconds: %s", bench.estimated_time_seconds)
        if bench.report_vars:
            self.logger.info("  report_vars: %s", bench.report_vars)
        if bench.executor_options:
            self.logger.info("  executor_options: %s", bench.executor_options)
        if bench.bayesian_config:
            self.logger.info("  bayesian_config: %s", bench.bayesian_config)
        if bench.random_config:
            self.logger.info("  random_config: %s", bench.random_config)
        self.logger.info("  collect_system_info: %s", bench.collect_system_info)

    @classmethod
    def register(cls, name):
        def decorator(subclass):
            cls._registry[name.lower()] = subclass
            return subclass
        return decorator

    @classmethod
    def build(cls, cfg) -> "BasePlanner":
        name = cfg.benchmark.search_method
        executor_cls = cls._registry.get(name.lower())
        if executor_cls is None:
            raise ValueError(f"Executor '{name}' is not registered.")
        return executor_cls(cfg)

    def random_sample(self, items: List[ExecutionInstance]) -> List[ExecutionInstance]:
        # randomly sample all items of the list
        sample_size = len(items)
        if sample_size > 0:
            self.logger.debug(f"  [Planner] Shuffling execution order ({sample_size} tests)")
            items = self.random.sample(items, sample_size)
        return items

    @abstractmethod
    def next_test(self) -> Any:
        pass

    @abstractmethod
    def record_completed_test(self, test: Any) -> None:
        pass

    def get_progress(self) -> dict:
        """
        Get current execution progress information.

        Returns:
            Dictionary with progress metrics:
            - completed: Number of tests completed
            - total: Total number of tests expected
            - percentage: Completion percentage (0-100)
            - remaining: Number of tests remaining
        """
        # Use attributes that subclasses should have
        attempt_count = getattr(self, '_attempt_count', 0)
        attempt_total = getattr(self, '_attempt_total', 0)

        return {
            'completed': attempt_count,
            'total': attempt_total,
            'percentage': (attempt_count / attempt_total * 100) if attempt_total > 0 else 0,
            'remaining': attempt_total - attempt_count
        }

    def _prepare_execution_artifacts(self, test: Any, repetition: int) -> None:
        """
        Create folders + scripts for one test execution and one repetition.

        This method is shared by all planners. It:
        - Creates the execution directory structure (unless upfront mode)
        - Sets test.repetition and metadata["repetition"]
        - Writes the main script file (with optional system probe injection)
        - Writes the post script file (if present)

        In upfront mode (create_folders_upfront=True), exec_XXXX folders and
        params files are already created. This method only creates the
        repetition folder and writes scripts.

        Layout:
        <workdir>/
            ├── __iops_index.json (execution index for --find)
            └── runs/
                └── exec_0001/
                    ├── __iops_params.json (parameters for this execution)
                    └── repetition_001/
                        ├── run_<script>.sh (user script)
                        ├── post_<script>.sh (optional user post-script)
                        ├── __iops_probe.sh (system probe script)
                        └── __iops_sysinfo.json (generated at runtime by probe)

        Args:
            test: ExecutionInstance to prepare
            repetition: 1-based repetition number
        """
        # Set repetition
        test.repetition = repetition
        if not hasattr(test, "metadata") or test.metadata is None:
            test.metadata = {}
        test.metadata["repetition"] = repetition

        run_root = Path(self.cfg.benchmark.workdir)
        runs_root = run_root / "runs"

        # Create execution dir (exec_XXXX is parent, repetition_XXX is child)
        exec_parent_dir = runs_root / f"exec_{test.execution_id:04d}"
        exec_dir = exec_parent_dir / f"repetition_{repetition:03d}"

        if not self._folders_initialized:
            # Dynamic mode: create exec folder now
            runs_root.mkdir(parents=True, exist_ok=True)
            exec_parent_dir.mkdir(parents=True, exist_ok=True)

        # Always create repetition folder (not created upfront)
        exec_dir.mkdir(parents=True, exist_ok=True)

        # Point to repetition dir (useful for templates like {{ execution_dir }})
        # Must be set before _write_params_file so derived variables render correctly
        test.execution_dir = exec_dir

        # Write params/index files in exec folder (only on first repetition)
        # Can be disabled with track_executions: false to reduce file I/O
        if repetition == 1 and getattr(self.cfg.benchmark, 'track_executions', True):
            # In dynamic mode: create params file for the first time
            # In upfront mode: update params file with resolved values (execution_dir now known)
            self._write_params_file(test, exec_parent_dir)

        # Get the rendered script text
        script_text = test.script_text

        # Inject IOPS helper scripts (exit handler, runtime monitors, atexit scripts)
        # All sources are injected at a single point after shebang/#SBATCH directives
        script_text = self._inject_iops_scripts(script_text, exec_dir)

        # Write script files inside repetition dir
        test.script_file = exec_dir / f"run_{test.script_name}.sh"
        with open(test.script_file, "w") as f:
            f.write(script_text)

        script_info = f"main={test.script_file.name}"

        if getattr(test, "post_script", None):
            test.post_script_file = exec_dir / f"post_{test.script_name}.sh"
            with open(test.post_script_file, "w") as f:
                f.write(test.post_script)
            script_info += f", post={test.post_script_file.name}"

        self.logger.debug(f"  [Prepare] Scripts written: {script_info}")

    def _inject_iops_scripts(self, script_text: str, exec_dir: Path) -> str:
        """
        Inject all IOPS helper scripts into a user script.

        This method handles all IOPS script injection at a single point, right after
        the shebang and #SBATCH directives. Scripts are organized into two categories:

        1. Runtime scripts (__iops_runtime_*): Run during benchmark execution
           - Resource sampler: Collects CPU/memory metrics in background

        2. At-exit scripts (__iops_atexit_*): Run via EXIT trap when script completes
           - System info probe: Collects node information

        The exit handler coordinates all at-exit scripts via a single EXIT trap.
        Runtime scripts that need cleanup (like the sampler) register their cleanup
        functions with the exit handler.

        Injection order (all at single point after shebang/#SBATCH):
        1. Exit handler (sets up trap, must be first)
        2. Runtime scripts (start monitors before user code)
        3. At-exit scripts (register functions to run on exit)

        Args:
            script_text: Original script content
            exec_dir: Execution directory where helper scripts will be written

        Returns:
            Script text with all IOPS sources injected after shebang/#SBATCH
        """
        # Check which features are enabled
        trace_resources = getattr(self.cfg.benchmark, 'trace_resources', False)
        collect_system_info = getattr(self.cfg.benchmark, 'collect_system_info', True)

        # If no features enabled, return script unchanged
        if not trace_resources and not collect_system_info:
            return script_text

        # Build list of source lines to inject
        source_lines = ['\n# IOPS Helper Scripts - injected for monitoring and data collection']

        # 1. Exit handler (always needed if any feature is enabled)
        handler_file = exec_dir / EXIT_HANDLER_FILENAME
        with open(handler_file, "w") as f:
            f.write(EXIT_HANDLER_TEMPLATE)
        source_lines.append(f'source "{handler_file}"  # Exit trap coordinator')

        # 2. Runtime scripts (run during execution)
        if trace_resources:
            trace_interval = getattr(self.cfg.benchmark, 'trace_interval', 1.0)
            sampler_script = RESOURCE_SAMPLER_TEMPLATE.format(
                execution_dir=str(exec_dir),
                trace_prefix=TRACE_FILENAME_PREFIX,
                trace_interval=trace_interval,
                sentinel_filename=SAMPLER_SENTINEL_FILENAME
            )
            sampler_file = exec_dir / RUNTIME_SAMPLER_FILENAME
            with open(sampler_file, "w") as f:
                f.write(sampler_script)
            source_lines.append(f'source "{sampler_file}"  # CPU/memory monitoring')

        # 3. At-exit scripts (run on script exit via trap)
        if collect_system_info:
            probe_script = SYSTEM_PROBE_TEMPLATE.format(execution_dir=str(exec_dir))
            probe_file = exec_dir / ATEXIT_SYSINFO_FILENAME
            with open(probe_file, "w") as f:
                f.write(probe_script)
            source_lines.append(f'source "{probe_file}"  # System info collection')

        source_lines.append('')  # Empty line after IOPS block

        # Find insertion point after shebang and SLURM directives
        lines = script_text.split('\n')
        insert_idx = 0

        # Skip shebang if present
        if lines and lines[0].startswith('#!'):
            insert_idx = 1

        # Skip all #SBATCH directives (must stay at top for SLURM)
        while insert_idx < len(lines) and lines[insert_idx].startswith('#SBATCH'):
            insert_idx += 1

        # Insert all source lines at the found position
        for i, source_line in enumerate(source_lines):
            lines.insert(insert_idx + i, source_line)

        return '\n'.join(lines)

    def _write_params_file(self, test: ExecutionInstance, exec_parent_dir: Path) -> None:
        """
        Write the parameters file for this execution.

        Creates __iops_params.json in the exec_XXXX folder containing the
        variable values for this execution. This makes each execution folder
        self-documenting and enables the --find command.

        Also updates the global index file (__iops_index.json) in the run root.

        Args:
            test: ExecutionInstance with vars to save
            exec_parent_dir: The exec_XXXX directory (parent of repetition dirs)
        """
        # Filter out internal keys (starting with __)
        params = {
            k: v for k, v in test.vars.items()
            if not k.startswith("__")
        }

        # Write params file in exec folder
        params_file = exec_parent_dir / PARAMS_FILENAME
        with open(params_file, "w") as f:
            json.dump(params, f, indent=2, default=str)

        # Update global index
        self._update_index_file(test, params, exec_parent_dir)

    def _update_index_file(
        self,
        test: ExecutionInstance,
        params: Dict[str, Any],
        exec_parent_dir: Path
    ) -> None:
        """
        Update the global execution index file.

        Creates or updates __iops_index.json in the run root. The index maps
        execution IDs to their parameters and relative paths, enabling the
        --find command to quickly search executions.

        Args:
            test: ExecutionInstance being prepared
            params: Filtered parameters (without __ prefixed keys)
            exec_parent_dir: The exec_XXXX directory
        """
        run_root = Path(self.cfg.benchmark.workdir)
        index_file = run_root / INDEX_FILENAME

        # Load existing index or create new one
        if index_file.exists():
            with open(index_file, "r") as f:
                index = json.load(f)
        else:
            # Get expected total from planner progress
            # Note: progress['total'] already includes repetitions (it's _attempt_total)
            progress = self.get_progress()
            total_expected = progress.get('total', 0)
            repetitions = max(1, int(getattr(self.cfg.benchmark, "repetitions", 1) or 1))
            index = {
                "benchmark": self.cfg.benchmark.name,
                "total_expected": total_expected,
                "repetitions": repetitions,
                "executions": {}
            }

        # Get relative path from run_root to exec_parent_dir
        exec_rel_path = exec_parent_dir.relative_to(run_root)

        # Add this execution to the index
        exec_key = f"exec_{test.execution_id:04d}"
        index["executions"][exec_key] = {
            "path": str(exec_rel_path),
            "params": params,
            "command": test.command
        }

        # Write updated index
        with open(index_file, "w") as f:
            json.dump(index, f, indent=2, default=str)

    def _write_test_status(
        self,
        exec_dir: Path,
        status: str,
        reason: str = None,
        message: str = None
    ) -> None:
        """
        Write test-level status file in exec_XXXX folder.

        This is distinct from repetition-level status (written by runner).
        Test-level status tracks the overall state of a test configuration:
        - SKIPPED: Test will not be executed (constraint or planner decision)
        - PENDING: Test is queued, no repetitions started yet
        - COMPLETE: All repetitions finished

        Args:
            exec_dir: The exec_XXXX directory
            status: One of TEST_STATUS_SKIPPED, TEST_STATUS_PENDING, TEST_STATUS_COMPLETE
            reason: Skip reason (for SKIPPED status): "constraint" or "planner"
            message: Additional message (e.g., constraint violation message)
        """
        if not getattr(self.cfg.benchmark, 'track_executions', True):
            return

        status_file = exec_dir / STATUS_FILENAME
        status_data = {"status": status}
        if reason:
            status_data["reason"] = reason
        if message:
            status_data["message"] = message

        with open(status_file, "w") as f:
            json.dump(status_data, f, indent=2, default=str)

    def _initialize_all_folders(
        self,
        active_instances: List[ExecutionInstance],
        skipped_instances: List[ExecutionInstance]
    ) -> None:
        """
        Create all execution folders upfront with test-level status.

        Called when create_folders_upfront=True. Creates folders for both
        active tests (status=PENDING) and skipped tests (status=SKIPPED).

        This enables watch mode to show the full parameter space from the start,
        including which tests were skipped and why.

        Args:
            active_instances: Tests that will be executed
            skipped_instances: Tests that were skipped (constraint or planner)
        """
        if not getattr(self.cfg.benchmark, 'track_executions', True):
            return

        run_root = Path(self.cfg.benchmark.workdir)
        runs_root = run_root / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)

        # Track all instances for index
        all_index_entries = []

        # Active instances: create folder with PENDING status
        for instance in active_instances:
            exec_dir = runs_root / f"exec_{instance.execution_id:04d}"
            exec_dir.mkdir(parents=True, exist_ok=True)

            # Filter out internal keys for params
            params = {
                k: v for k, v in instance.vars.items()
                if not k.startswith("__")
            }

            # Write params file
            params_file = exec_dir / PARAMS_FILENAME
            with open(params_file, "w") as f:
                json.dump(params, f, indent=2, default=str)

            # Write test-level status
            self._write_test_status(exec_dir, TEST_STATUS_PENDING)

            # Add to index
            exec_rel_path = exec_dir.relative_to(run_root)
            all_index_entries.append({
                "exec_key": f"exec_{instance.execution_id:04d}",
                "path": str(exec_rel_path),
                "params": params,
                "command": instance.command,
                "status": TEST_STATUS_PENDING,
            })

        # Skipped instances: create folder with SKIPPED status
        for instance in skipped_instances:
            exec_dir = runs_root / f"exec_{instance.execution_id:04d}"
            exec_dir.mkdir(parents=True, exist_ok=True)

            # Filter out internal keys for params
            params = {
                k: v for k, v in instance.vars.items()
                if not k.startswith("__")
            }

            # Write params file
            params_file = exec_dir / PARAMS_FILENAME
            with open(params_file, "w") as f:
                json.dump(params, f, indent=2, default=str)

            # Get skip reason and message from metadata
            reason = instance.metadata.get("__skip_reason", "unknown")
            message = instance.metadata.get("__skip_message")

            # Write test-level status
            self._write_test_status(exec_dir, TEST_STATUS_SKIPPED, reason, message)

            # Add to index
            exec_rel_path = exec_dir.relative_to(run_root)
            entry = {
                "exec_key": f"exec_{instance.execution_id:04d}",
                "path": str(exec_rel_path),
                "params": params,
                "command": instance.command,
                "status": TEST_STATUS_SKIPPED,
                "skip_reason": reason,
            }
            if message:
                entry["skip_message"] = message
            all_index_entries.append(entry)

        # Write complete index
        self._write_complete_index(all_index_entries, len(active_instances), len(skipped_instances))

        self.logger.info(
            f"  [Upfront] Created {len(active_instances)} active + {len(skipped_instances)} skipped folders"
        )

    def _write_complete_index(
        self,
        index_entries: List[Dict[str, Any]],
        active_count: int,
        skipped_count: int
    ) -> None:
        """
        Write the complete execution index file upfront.

        Called by _initialize_all_folders when create_folders_upfront=True.

        Args:
            index_entries: List of dicts with exec_key, path, params, command, status
            active_count: Number of active (non-skipped) tests
            skipped_count: Number of skipped tests
        """
        if not getattr(self.cfg.benchmark, 'track_executions', True):
            return

        run_root = Path(self.cfg.benchmark.workdir)
        index_file = run_root / INDEX_FILENAME

        repetitions = max(1, int(getattr(self.cfg.benchmark, "repetitions", 1) or 1))
        total_expected = active_count * repetitions

        index = {
            "benchmark": self.cfg.benchmark.name,
            "folders_upfront": True,
            "total_expected": total_expected,
            "repetitions": repetitions,
            "active_tests": active_count,
            "skipped_tests": skipped_count,
            "executions": {}
        }

        for entry in index_entries:
            exec_key = entry.pop("exec_key")
            index["executions"][exec_key] = entry

        with open(index_file, "w") as f:
            json.dump(index, f, indent=2, default=str)


# ============================================================================ #
# Exhaustive Planner
# ============================================================================ #

@BasePlanner.register("exhaustive")
class ExhaustivePlanner(BasePlanner, HasLogger):
    """
    A brute-force planner that exhaustively searches the parameter space.

    Uses random interleaving of repetitions within the execution matrix.
    """

    def __init__(self, cfg: GenericBenchmarkConfig):
        super().__init__(cfg)

        self.execution_matrix: list[Any] | None = None
        self.current_index: int = 0
        self.total_tests: int = 0

        # Control flag to ensure we only build the matrix once
        self._matrix_built: bool = False

        # State for random interleaving of repetitions
        self._active_indices: list[int] = []          # tests with reps remaining
        self._next_rep_by_idx: dict[int, int] = {}    # next rep (0-based) per test index
        self._total_reps_by_idx: dict[int, int] = {}  # total reps per test index
        self._attempt_count: int = 0                  # attempts emitted in current matrix
        self._attempt_total: int = 0                  # sum(repetitions) in current matrix

        self.logger.info("Exhaustive planner initialized.")

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _init_interleaving_state(self) -> None:
        """
        Initialize the bookkeeping for the current execution_matrix.
        """
        assert self.execution_matrix is not None

        self._active_indices = []
        self._next_rep_by_idx = {}
        self._total_reps_by_idx = {}
        self._attempt_count = 0
        self._attempt_total = 0

        for i, t in enumerate(self.execution_matrix):
            reps = int(getattr(t, "repetitions", 1) or 1)
            if reps < 1:
                reps = 1
            self._next_rep_by_idx[i] = 0
            self._total_reps_by_idx[i] = reps
            self._attempt_total += reps
            self._active_indices.append(i)

        self.logger.debug(
            f"  [Matrix] Built: {self.total_tests} unique parameter combinations, "
            f"{self._attempt_total} total attempts (with repetitions)"
        )

    def _build_execution_matrix(self) -> bool:
        """
        Build the execution matrix.

        Returns:
            True if a new matrix with at least one test was built.
            False if the matrix was already built (no more tests).
        """
        if self._matrix_built:
            self.logger.info("Execution matrix already built. No more tests.")
            return False

        self.logger.info("Building execution matrix...")

        # Reset per-matrix state
        self.current_index = 0

        # build_execution_matrix now returns (kept, skipped)
        kept_instances, skipped_instances = build_execution_matrix(self.cfg)

        # Store skipped instances for reference
        self.skipped_matrix = skipped_instances

        # Shuffle the active execution matrix
        self.execution_matrix = self.random_sample(kept_instances)
        self.total_tests = len(self.execution_matrix)

        # Initialize folders upfront if configured
        if getattr(self.cfg.benchmark, 'create_folders_upfront', False):
            self._initialize_all_folders(kept_instances, skipped_instances)
            self._folders_initialized = True

        self._matrix_built = True  # mark as built

        self.logger.info("Total tests in execution matrix: %d", self.total_tests)
        if skipped_instances:
            self.logger.info("Skipped tests (constraints): %d", len(skipped_instances))

        if self.total_tests > 0:
            self._init_interleaving_state()

        return self.total_tests > 0

    def record_completed_test(self, test: Any) -> None:
        """
        Record a completed test.

        For the Exhaustive planner, this is a no-op since we don't need to track
        completed tests (no optimization/search happening).
        """
        pass

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def next_test(self) -> Any:
        """
        Returns the next test to run (including repetitions),
        or None when all tests are done.

        Uses random interleaving of repetitions.
        """
        while True:
            matrix_finished = (
                self.execution_matrix is not None
                and self.total_tests > 0
                and len(self._active_indices) == 0
            )

            # Need a matrix (first time) OR we finished the current one
            if self.execution_matrix is None or matrix_finished:
                # Attempt to build the matrix
                if not self._build_execution_matrix():
                    return None

                # The new matrix might be empty (weird config), so loop again if so
                if self.total_tests == 0:
                    continue

            # At this point we have a valid matrix with remaining attempts
            assert self.execution_matrix is not None, "Execution matrix should be populated"
            idx = self.random.choice(self._active_indices)
            test = self.execution_matrix[idx]

            rep_idx = self._next_rep_by_idx[idx]
            self._next_rep_by_idx[idx] += 1
            self._attempt_count += 1

            # If this test is done, remove it from the active pool
            if self._next_rep_by_idx[idx] >= self._total_reps_by_idx[idx]:
                # remove by value (list is small; fine)
                self._active_indices.remove(idx)

            # Logging: attempt-oriented
            self.logger.debug(
                f"  [Planner] Selected test (attempt {self._attempt_count}/{self._attempt_total}): "
                f"exec_id={getattr(test, 'execution_id', '?')} "
                f"rep={rep_idx + 1}/{getattr(test, 'repetitions', 1)}"
            )

            # Prepare filesystem artifacts (dirs + scripts) for this test+repetition
            # rep_idx is 0-based, _prepare_execution_artifacts expects 1-based
            self._prepare_execution_artifacts(test, rep_idx + 1)
            return test


# ============================================================================ #
# Random Sampling Planner
# ============================================================================ #

@BasePlanner.register("random")
class RandomSamplingPlanner(ExhaustivePlanner):
    """
    Random sampling planner that randomly samples N configurations from the
    full parameter space.

    Inherits from ExhaustivePlanner and overrides _build_execution_matrix to
    add random sampling before the standard matrix processing.

    Configuration (YAML):
        benchmark:
          search_method: "random"
          random_config:
            # Option 1: Explicit number of samples
            n_samples: 20

            # Option 2: Percentage of total space (mutually exclusive with n_samples)
            # percentage: 0.1  # 10% of parameter space

            # Optional: behavior when n_samples >= total_space
            fallback_to_exhaustive: true  # default: true

    Features:
    - Random sampling without replacement
    - Repetition interleaving for statistical robustness (inherited)
    - Reproducible sampling with random_seed
    - Two sampling modes: explicit n_samples or percentage
    """

    def __init__(self, cfg: GenericBenchmarkConfig):
        # Call parent __init__ first (sets up execution_matrix, interleaving state, etc.)
        super().__init__(cfg)

        # Sampling configuration (already validated by loader)
        rc = cfg.benchmark.random_config
        self.n_samples: Optional[int] = rc.n_samples
        self.percentage: Optional[float] = rc.percentage
        self.fallback_to_exhaustive: bool = rc.fallback_to_exhaustive

        # Random-specific attributes
        self.total_space_size: int = 0  # Full parameter space size
        self.sampled_size: int = 0  # Actual sample size used

        # Log sampling mode
        sampling_mode = f"n_samples={self.n_samples}" if self.n_samples is not None else f"percentage={self.percentage}"
        self.logger.info("Random sampling mode: %s", sampling_mode)

    def _compute_sample_size(self, total_space: int) -> int:
        """
        Compute the actual sample size based on configuration.

        Args:
            total_space: Total size of parameter space

        Returns:
            Sample size (clamped to valid range [1, total_space])
        """
        if self.n_samples is not None:
            # Explicit number of samples
            if self.n_samples >= total_space:
                if self.fallback_to_exhaustive:
                    self.logger.warning(
                        f"Requested n_samples={self.n_samples} >= total_space={total_space}. "
                        f"Using full exhaustive search."
                    )
                    return total_space
                else:
                    self.logger.warning(
                        f"Requested n_samples={self.n_samples} >= total_space={total_space}. "
                        f"Clamping to total_space."
                    )
                    return total_space
            return self.n_samples

        else:
            # Percentage-based sampling
            sample_size = max(1, int(total_space * self.percentage))
            self.logger.info(
                f"Sampling {self.percentage*100:.1f}% of parameter space: "
                f"{sample_size}/{total_space} configurations"
            )
            return sample_size

    def _sample_execution_matrix(self, full_matrix: list[Any]) -> list[Any]:
        """
        Randomly sample configurations from the full execution matrix.

        If exhaustive_vars is configured, groups instances by search point
        and samples search points (not individual instances), then returns
        all instances from selected search points.

        Args:
            full_matrix: Full execution matrix (all parameter combinations)

        Returns:
            Sampled subset of execution matrix
        """
        if not full_matrix:
            return full_matrix

        # Check if exhaustive_vars is being used
        has_exhaustive_vars = bool(full_matrix[0].exhaustive_var_names)

        if has_exhaustive_vars:
            # Group instances by search point
            search_point_groups = defaultdict(list)

            for instance in full_matrix:
                search_point = instance.get_search_point()
                search_point_groups[search_point].append(instance)

            # Total space size is the number of unique search points
            self.total_space_size = len(search_point_groups)
            self.sampled_size = self._compute_sample_size(self.total_space_size)

            if self.sampled_size >= self.total_space_size:
                # Use all search points (exhaustive)
                self.logger.info(
                    f"Using all {self.total_space_size} search points "
                    f"(each expanded with {len(full_matrix[0].exhaustive_var_names)} exhaustive vars)"
                )
                return full_matrix

            # Sample random search points
            search_points = list(search_point_groups.keys())
            sampled_search_points = self.random.sample(search_points, self.sampled_size)

            # Collect all instances from sampled search points
            sampled_matrix = []
            for sp in sampled_search_points:
                sampled_matrix.extend(search_point_groups[sp])

            exhaustive_count = len(search_point_groups[sampled_search_points[0]])
            self.logger.info(
                f"Randomly sampled {self.sampled_size}/{self.total_space_size} search points "
                f"({self.sampled_size/self.total_space_size*100:.1f}%), "
                f"each with {exhaustive_count} exhaustive var combinations. "
                f"Total instances: {len(sampled_matrix)}"
            )

            return sampled_matrix

        else:
            # Original behavior: no exhaustive vars, sample individual instances
            self.total_space_size = len(full_matrix)
            self.sampled_size = self._compute_sample_size(self.total_space_size)

            if self.sampled_size >= self.total_space_size:
                # Use full matrix (exhaustive)
                self.logger.info(
                    f"Using full parameter space: {self.total_space_size} configurations"
                )
                return full_matrix

            # Random sampling without replacement
            sampled_matrix = self.random.sample(full_matrix, self.sampled_size)

            self.logger.info(
                f"Randomly sampled {self.sampled_size}/{self.total_space_size} configurations "
                f"({self.sampled_size/self.total_space_size*100:.1f}%)"
            )

            return sampled_matrix

    def _build_execution_matrix(self) -> bool:
        """
        Build the execution matrix with random sampling.

        Returns:
            True if a new matrix with at least one test was built.
            False if the matrix was already built (no more tests).
        """
        if self._matrix_built:
            self.logger.info("Execution matrix already built. No more tests.")
            return False

        self.logger.info("Building execution matrix...")

        # Reset per-matrix state
        self.current_index = 0

        # Build full matrix, then sample
        # build_execution_matrix now returns (kept, skipped)
        kept_instances, constraint_skipped = build_execution_matrix(self.cfg)

        # Sample from kept instances
        sampled_matrix = self._sample_execution_matrix(kept_instances)

        # Track planner-skipped instances (not selected by random sampling)
        selected_ids = {t.execution_id for t in sampled_matrix}
        planner_skipped = []
        for t in kept_instances:
            if t.execution_id not in selected_ids:
                t.metadata["__skipped"] = True
                t.metadata["__skip_reason"] = "planner"
                t.metadata["__skip_message"] = "Not selected by random sampling"
                planner_skipped.append(t)

        # Combine all skipped instances
        all_skipped = constraint_skipped + planner_skipped
        self.skipped_matrix = all_skipped

        # Shuffle the sampled matrix
        self.execution_matrix = self.random_sample(sampled_matrix)
        self.total_tests = len(self.execution_matrix)

        # Initialize folders upfront if configured
        if getattr(self.cfg.benchmark, 'create_folders_upfront', False):
            self._initialize_all_folders(sampled_matrix, all_skipped)
            self._folders_initialized = True

        self._matrix_built = True  # mark as built

        self.logger.info(
            "Total tests in execution matrix: %d (sampled from %d)",
            self.total_tests,
            self.total_space_size,
        )
        if constraint_skipped:
            self.logger.info("Skipped tests (constraints): %d", len(constraint_skipped))
        if planner_skipped:
            self.logger.info("Skipped tests (random sampling): %d", len(planner_skipped))

        if self.total_tests > 0:
            self._init_interleaving_state()

        return self.total_tests > 0


# ============================================================================ #
# Bayesian Optimization Planner
# ============================================================================ #

@BasePlanner.register("bayesian")
class BayesianPlanner(BasePlanner, HasLogger):
    """
    Bayesian optimization planner that intelligently explores parameter space
    to find optimal configurations for a target metric.

    Configuration (YAML):
        benchmark:
          search_method: "bayesian"
          bayesian_config:
            objective_metric: "metric"  # REQUIRED: Metric to optimize (must match parser metric)
            objective: "minimize"        # "minimize" (default) or "maximize"
            n_iterations: 20             # Total configurations to evaluate (default: 20)
            n_initial_points: 5          # Random exploration before optimization (default: 5)
            acquisition_func: "EI"       # "EI" (default), "PI", or "LCB"
            base_estimator: "RF"         # Surrogate model: "RF" (default), "GP", "ET", or "GBRT"
            xi: 0.01                     # Exploration-exploitation for EI/PI (higher = more exploration)
            kappa: 1.96                  # Exploration parameter for LCB (higher = more exploration)

    Surrogate Models (base_estimator):
        - "RF": Random Forest (default) - Best for categorical/mixed spaces
        - "GP": Gaussian Process - Best for continuous spaces, struggles with categoricals
        - "ET": Extra Trees - Similar to RF, slightly different tree building
        - "GBRT": Gradient Boosted Regression Trees

    Acquisition Functions:
        - "EI": Expected Improvement (default) - Balanced exploration/exploitation
        - "PI": Probability of Improvement - More exploitative, faster convergence
        - "LCB": Lower Confidence Bound - More explorative, controlled by kappa

    Numeric List Handling:
        For variables with list mode and numeric types (int/float), uses ordinal
        encoding instead of categorical. This allows the model to learn that
        higher indices correlate with higher/lower metric values.

    The planner will:
    1. Start with random exploration (n_initial_points)
    2. Build a surrogate model (Random Forest by default) from observed results
    3. Use acquisition function to suggest next promising point
    4. Iteratively improve to find optimal parameters

    Requires scikit-optimize: pip install scikit-optimize
    """

    def __init__(self, cfg: GenericBenchmarkConfig):
        super().__init__(cfg)

        if not SKOPT_AVAILABLE:
            raise ImportError(
                "scikit-optimize is required for Bayesian optimization. "
                "Install it with: pip install scikit-optimize"
            )

        # Warn if upfront folder creation is enabled - not supported for Bayesian
        # because parameter combinations are determined dynamically during optimization
        if getattr(self.cfg.benchmark, 'create_folders_upfront', False):
            self.logger.warning(
                "create_folders_upfront is not supported for Bayesian optimization. "
                "Parameters are selected dynamically by the optimizer. Using dynamic folder creation."
            )

        # Bayesian config is guaranteed by loader to be set when search_method is "bayesian"
        self.bayesian_cfg = self.cfg.benchmark.bayesian_config

        # Optimization settings from BayesianConfig dataclass
        self.target_metric = self.bayesian_cfg.objective_metric
        self.objective = self.bayesian_cfg.objective
        self.n_initial_points = self.bayesian_cfg.n_initial_points
        self.n_iterations = self.bayesian_cfg.n_iterations
        self.acquisition_func = self.bayesian_cfg.acquisition_func
        self.xi = self.bayesian_cfg.xi
        self.kappa = self.bayesian_cfg.kappa
        self.base_estimator = self.bayesian_cfg.base_estimator

        # Build search space from swept variables
        # This also populates self.ordinal_mappings for index-to-value conversion
        self.ordinal_mappings: Dict[str, List[Any]] = {}  # var_name -> list of valid values
        self.search_space, self.var_names = self._build_search_space()

        if not self.search_space:
            raise ValueError("No swept variables found for Bayesian optimization")

        # Build acquisition function kwargs
        acq_func_kwargs = {}
        if self.acquisition_func in ['EI', 'PI']:
            acq_func_kwargs['xi'] = self.xi
        elif self.acquisition_func == 'LCB':
            acq_func_kwargs['kappa'] = self.kappa

        # Initialize Bayesian optimizer with Random Forest (better for categorical/mixed spaces)
        self.optimizer = Optimizer(
            dimensions=self.search_space,
            base_estimator=self.base_estimator,
            n_initial_points=self.n_initial_points,
            acq_func=self.acquisition_func,
            acq_func_kwargs=acq_func_kwargs,
            random_state=self.cfg.benchmark.random_seed,
        )

        # Execution tracking
        self.iteration = 0
        self.completed_tests: List[ExecutionInstance] = []
        self.X_observed: List[List[Any]] = []  # Parameter combinations tried
        self.y_observed: List[float] = []      # Observed metric values

        # Progress tracking for get_progress()
        self._attempt_count: int = 0
        self._attempt_total: int = self.n_iterations * (cfg.benchmark.repetitions or 1)

        # Total search space size (for comparison with exhaustive search)
        self.total_space_size = self._compute_total_space_size()

        # Check for exhaustive fallback
        self.fallback_to_exhaustive = self.bayesian_cfg.fallback_to_exhaustive
        self._use_exhaustive_fallback = False
        self._exhaustive_matrix: List[ExecutionInstance] = []
        self._exhaustive_index = 0

        if self.n_iterations >= self.total_space_size and self.total_space_size > 0:
            if self.fallback_to_exhaustive:
                self.logger.warning(
                    f"Requested n_iterations={self.n_iterations} >= total_space={self.total_space_size}. "
                    f"Using full exhaustive search instead of Bayesian optimization."
                )
                self._use_exhaustive_fallback = True
                # Build full execution matrix for exhaustive iteration
                kept, _ = build_execution_matrix(self.cfg, start_execution_id=1)
                self._exhaustive_matrix = kept
                self._attempt_total = len(kept) * (cfg.benchmark.repetitions or 1)
            else:
                self.logger.warning(
                    f"Requested n_iterations={self.n_iterations} >= total_space={self.total_space_size}. "
                    f"Clamping to total_space."
                )
                self.n_iterations = self.total_space_size

        # Best found so far
        self.best_params: Optional[Dict[str, Any]] = None
        self.best_value: Optional[float] = None

        # Repetitions per configuration
        self.repetitions = cfg.benchmark.repetitions or 1

        # Current test being evaluated
        self.current_test: Optional[ExecutionInstance] = None
        self.current_params: Optional[List[Any]] = None
        self.current_rep = 0

        if self._use_exhaustive_fallback:
            self.logger.info(
                f"Bayesian planner using exhaustive fallback: "
                f"{len(self._exhaustive_matrix)} configurations"
            )
        else:
            self.logger.info(
                f"Bayesian planner initialized: target={self.target_metric} "
                f"objective={self.objective} n_iterations={self.n_iterations} "
                f"n_initial={self.n_initial_points} estimator={self.base_estimator}"
            )
            self.logger.info(f"Search space: {len(self.search_space)} dimensions: {self.var_names}")
            if self.ordinal_mappings:
                self.logger.info(f"Using ordinal encoding for: {list(self.ordinal_mappings.keys())}")

            # Log search space coverage
            if self.total_space_size > 0:
                coverage_pct = (self.n_iterations / self.total_space_size) * 100
                savings_pct = 100 - coverage_pct
                self.logger.info(
                    f"Total search space: {self.total_space_size} configurations. "
                    f"Bayesian will explore {self.n_iterations} ({coverage_pct:.1f}%), "
                    f"saving {savings_pct:.1f}% vs exhaustive search."
                )

    def _compute_total_space_size(self) -> int:
        """
        Compute the total number of configurations in the search space.

        Uses build_execution_matrix to get the exact count of all possible
        parameter combinations.

        Returns:
            Total number of possible configurations
        """
        kept, skipped = build_execution_matrix(self.cfg, start_execution_id=0)
        return len(kept) + len(skipped)

    def _build_search_space(self):
        """
        Build scikit-optimize search space from swept variables.

        For numeric list variables, uses ordinal encoding (index-based) instead of
        Categorical to allow the surrogate model to interpolate between values.
        This is crucial for Random Forest to learn patterns like "higher values = better".

        Returns:
            Tuple of (dimensions, var_names)
        """
        dimensions = []
        var_names = []

        for var_name, var_config in self.cfg.vars.items():
            if not var_config.sweep:
                continue  # Skip non-swept variables

            sweep_cfg = var_config.sweep

            if sweep_cfg.mode == "range":
                # Continuous or integer range
                if var_config.type == "int":
                    dim = Integer(
                        low=sweep_cfg.start,
                        high=sweep_cfg.end,
                        name=var_name
                    )
                else:  # float
                    dim = Real(
                        low=float(sweep_cfg.start),
                        high=float(sweep_cfg.end),
                        name=var_name
                    )
                dimensions.append(dim)
                var_names.append(var_name)

            elif sweep_cfg.mode == "list":
                values = sweep_cfg.values

                if var_config.type in ["int", "float"]:
                    # Numeric list: use ordinal encoding (index-based Integer dimension)
                    # This allows the model to interpolate: index 0 < index 1 < index 2
                    # Sort values to ensure ordering makes sense
                    sorted_values = sorted(values)
                    self.ordinal_mappings[var_name] = sorted_values

                    dim = Integer(
                        low=0,
                        high=len(sorted_values) - 1,
                        name=f"{var_name}_idx"
                    )
                    self.logger.debug(
                        f"  [Bayesian] Variable '{var_name}': ordinal encoding "
                        f"{sorted_values} -> indices [0, {len(sorted_values) - 1}]"
                    )
                else:
                    # Categorical (string) values - keep as Categorical
                    dim = Categorical(
                        categories=values,
                        name=var_name
                    )

                dimensions.append(dim)
                var_names.append(var_name)

        return dimensions, var_names

    def _params_to_dict(self, params: List[Any]) -> Dict[str, Any]:
        """
        Convert parameter list to dictionary, converting numpy types to native Python.

        For ordinal-encoded variables (numeric lists), converts the index back to
        the actual value from the sorted list.
        """
        result = {}
        for name, value in zip(self.var_names, params):
            # Convert numpy types to native Python types
            if hasattr(value, 'item'):
                # numpy scalar (np.int64, np.float64, etc.)
                value = value.item()

            # Convert ordinal index back to actual value
            if name in self.ordinal_mappings:
                idx = int(value)
                # Clamp to valid range (shouldn't be needed, but safety check)
                idx = max(0, min(idx, len(self.ordinal_mappings[name]) - 1))
                value = self.ordinal_mappings[name][idx]

            result[name] = value
        return result

    def _check_constraints(self, params: List[Any]) -> bool:
        """
        Check if parameters satisfy all constraints.

        Args:
            params: List of parameter values

        Returns:
            True if all constraints pass (or only have "warn" policy)
        """
        if not self.cfg.constraints:
            return True

        vars_dict = self._params_to_dict(params)
        is_valid, violations = check_constraints_for_vars(vars_dict, self.cfg.constraints)

        if violations:
            for constraint, msg in violations:
                if constraint.violation_policy == "warn":
                    self.logger.warning(f"  [Bayesian] {msg} (proceeding anyway)")
                else:
                    self.logger.debug(f"  [Bayesian] Constraint violated: {msg}")

        return is_valid

    def next_test(self) -> Optional[ExecutionInstance]:
        """
        Return the next test to execute.

        Returns:
            ExecutionInstance or None when optimization is complete
        """
        # If using exhaustive fallback, delegate to simpler iteration
        if self._use_exhaustive_fallback:
            return self._next_test_exhaustive()

        # Handle repetitions for current test first
        # (must finish all reps before checking termination)
        if self.current_test and self.current_rep < self.repetitions:
            # Continue with repetitions of current configuration
            self.current_rep += 1
            self._attempt_count += 1
            test = self._create_test_instance(self.current_params, self.current_rep)
            self.logger.debug(
                f"  [Bayesian] Repetition {self.current_rep}/{self.repetitions} "
                f"of iteration {self.iteration}"
            )
            return test

        # Check if we've completed all iterations (after finishing repetitions)
        if self.iteration >= self.n_iterations:
            self.logger.info("=" * 70)
            self.logger.info("BAYESIAN OPTIMIZATION COMPLETE")
            self.logger.info("=" * 70)
            if self.best_params:
                self.logger.info(f"Best parameters found: {self.best_params}")
                self.logger.info(f"Best {self.target_metric}: {self.best_value:.4f}")
            self.logger.info(f"Total evaluations: {len(self.y_observed)}")
            self.logger.info("=" * 70)
            return None

        # Get next point from optimizer, checking constraints
        max_constraint_retries = 100  # Avoid infinite loop if space is heavily constrained
        for retry in range(max_constraint_retries):
            next_params = self.optimizer.ask()

            if self._check_constraints(next_params):
                break

            # Constraint violated - tell optimizer this is a bad point
            self.logger.debug(
                f"  [Bayesian] Suggested point violates constraints, asking for another "
                f"(retry {retry + 1}/{max_constraint_retries})"
            )
            # Tell optimizer this point is infeasible with a large penalty
            # Note: scikit-optimize always minimizes internally, so large positive is "worst"
            # (for maximization, actual values are negated before telling the optimizer)
            # Using 1e10 instead of inf because sklearn doesn't accept infinity values
            self.optimizer.tell(next_params, 1e10)
        else:
            self.logger.warning(
                f"  [Bayesian] Could not find valid point after {max_constraint_retries} retries. "
                f"Using last suggested point anyway."
            )

        self.current_params = next_params
        self.current_rep = 1
        self.iteration += 1
        self._attempt_count += 1

        # Create test instance
        test = self._create_test_instance(next_params, self.current_rep)
        self.current_test = test

        params_dict = self._params_to_dict(next_params)
        self.logger.info(
            f"[Bayesian] Iteration {self.iteration}/{self.n_iterations}: "
            f"Testing {params_dict}"
        )

        return test

    def _next_test_exhaustive(self) -> Optional[ExecutionInstance]:
        """
        Return the next test when using exhaustive fallback mode.

        Iterates through all configurations in the execution matrix.

        Returns:
            ExecutionInstance or None when all tests are complete
        """
        # Handle repetitions for current test first
        if self.current_test and self.current_rep < self.repetitions:
            self.current_rep += 1
            self._attempt_count += 1
            test = self._exhaustive_matrix[self._exhaustive_index - 1]
            test.repetition = self.current_rep
            self._prepare_execution_artifacts(test, self.current_rep)
            self.logger.debug(
                f"  [Exhaustive fallback] Repetition {self.current_rep}/{self.repetitions} "
                f"of test {self._exhaustive_index}/{len(self._exhaustive_matrix)}"
            )
            return test

        # Check if we've exhausted all configurations
        if self._exhaustive_index >= len(self._exhaustive_matrix):
            self.logger.info("=" * 70)
            self.logger.info("EXHAUSTIVE SEARCH COMPLETE (Bayesian fallback)")
            self.logger.info("=" * 70)
            self.logger.info(f"Total configurations tested: {len(self._exhaustive_matrix)}")
            self.logger.info("=" * 70)
            return None

        # Get next test from matrix
        test = self._exhaustive_matrix[self._exhaustive_index]
        self._exhaustive_index += 1
        self.current_rep = 1
        self._attempt_count += 1
        test.repetition = self.current_rep
        self.current_test = test

        # Prepare artifacts
        self._prepare_execution_artifacts(test, self.current_rep)

        self.logger.info(
            f"[Exhaustive fallback] Test {self._exhaustive_index}/{len(self._exhaustive_matrix)}: "
            f"{test.vars}"
        )

        return test

    def _create_test_instance(self, params: List[Any], repetition: int) -> ExecutionInstance:
        """
        Create an ExecutionInstance from parameters.

        Uses create_execution_instance from matrix.py for clean instance creation.

        Args:
            params: List of parameter values
            repetition: Repetition number (1-based)

        Returns:
            ExecutionInstance
        """
        vars_dict = self._params_to_dict(params)

        # Create instance directly using the matrix helper
        test = create_execution_instance(
            cfg=self.cfg,
            base_vars=vars_dict,
            execution_id=self.iteration,
            script_index=0,  # Use first script
            search_var_names=self.var_names,
        )

        test.repetition = repetition
        test.repetitions = self.repetitions

        # Prepare execution artifacts (folders and scripts)
        self._prepare_execution_artifacts(test, repetition)

        return test

    def record_completed_test(self, test: ExecutionInstance) -> None:
        """
        Record a completed test and update the Bayesian model.

        This is essential for Bayesian optimization - the optimizer needs
        to learn from completed tests to suggest better parameters.

        Args:
            test: Completed ExecutionInstance with metrics
        """
        self.completed_tests.append(test)

        # Only update optimizer after all repetitions are complete
        if test.repetition == self.repetitions:
            # Extract target metric value
            metrics = test.metadata.get('metrics', {})
            metric_value = metrics.get(self.target_metric)

            if metric_value is None:
                self.logger.warning(
                    f"Target metric '{self.target_metric}' not found in results. "
                    f"Available metrics: {list(metrics.keys())}"
                )
                return

            # Aggregate metric across repetitions (use mean)
            rep_values = []
            for completed_test in self.completed_tests:
                if (completed_test.execution_id == test.execution_id and
                    completed_test.metadata.get('metrics', {}).get(self.target_metric) is not None):
                    rep_values.append(completed_test.metadata['metrics'][self.target_metric])

            if not rep_values:
                return

            aggregated_value = float(np.mean(rep_values))

            # For maximization, negate the value (scikit-optimize minimizes)
            if self.objective == 'maximize':
                y_value = -aggregated_value
            else:
                y_value = aggregated_value

            # Update optimizer with observation
            self.X_observed.append(self.current_params)
            self.y_observed.append(y_value)

            self.optimizer.tell(self.current_params, y_value)

            # Update best found
            if self.best_value is None or aggregated_value > (self.best_value if self.objective == 'maximize' else -self.best_value):
                self.best_params = self._params_to_dict(self.current_params)
                self.best_value = aggregated_value

            self.logger.info(
                f"  [Bayesian] Iteration {self.iteration} complete: "
                f"{self.target_metric}={aggregated_value:.4f} (mean of {len(rep_values)} reps)"
            )
            self.logger.info(
                f"  [Bayesian] Best so far: {self.best_value:.4f} at {self.best_params}"
            )

            # Reset for next iteration
            self.current_test = None
            self.current_params = None
            self.current_rep = 0


# Backwards compatibility alias
Exhaustive = ExhaustivePlanner
