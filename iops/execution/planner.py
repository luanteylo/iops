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
from iops.execution.matrix import ExecutionInstance, build_execution_matrix, _cast_value

from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
from pathlib import Path
from collections import defaultdict
import logging
import random
import json
import warnings
import copy

# Try to import rich for progress bars
try:
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskProgressColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


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

# Filename for the repetition-level status (written to repetition_XXX directory)
STATUS_FILENAME = "__iops_status.json"

# Filename for skipped test marker (written to exec_XXXX directory for skipped tests only)
# This simple marker file indicates a test was skipped. If absent, test is active.
SKIPPED_MARKER_FILENAME = "__iops_skipped"

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
      echo "  \\"cpu_cores\\": $(getconf _NPROCESSORS_CONF 2>/dev/null || nproc 2>/dev/null || echo 0),"
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
        if bench.slurm_options:
            self.logger.info("  slurm_options: %s", bench.slurm_options)
        if bench.bayesian_config:
            self.logger.info("  bayesian_config: %s", bench.bayesian_config)
        if bench.random_config:
            self.logger.info("  random_config: %s", bench.random_config)
        if bench.probes:
            self.logger.info("  probes: system_snapshot=%s, execution_index=%s, resource_sampling=%s",
                           bench.probes.system_snapshot, bench.probes.execution_index, bench.probes.resource_sampling)

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

    # ------------------------------------------------------------------ #
    # Single-Allocation Mode Support
    # ------------------------------------------------------------------ #

    def prepare_kickoff_mode(self, cache=None) -> Path:
        """
        Prepare all test folders and generate the single-allocation execution script.

        This method is called by the runner when allocation.mode='single'.
        It generates ALL test folders and scripts upfront, then creates
        an execution script that runs uncached tests sequentially.

        The execution script is a dispatcher that calls existing per-test scripts,
        reusing all existing logic (resource tracing, exit handlers, MPI wrapping).

        Args:
            cache: Optional ExecutionCache to filter out cached tests

        Returns:
            Path to the generated execution script
        """
        from iops.execution.matrix import build_execution_matrix

        self.logger.info("=" * 70)
        self.logger.info("SINGLE-ALLOCATION MODE: Preparing all tests upfront")
        self.logger.info("=" * 70)

        # Build execution matrix
        self.logger.info("Building execution matrix...")
        kept_instances, skipped_instances = build_execution_matrix(self.cfg)

        # Store for tracking
        self.execution_matrix = kept_instances
        self.skipped_matrix = skipped_instances
        self._matrix_built = True

        total_tests = len(kept_instances)
        total_skipped = len(skipped_instances)
        repetitions = max(1, int(getattr(self.cfg.benchmark, "repetitions", 1) or 1))

        self.logger.info(f"  Total unique parameter combinations: {total_tests}")
        self.logger.info(f"  Skipped by constraints: {total_skipped}")
        self.logger.info(f"  Repetitions per test: {repetitions}")

        # Create folders root
        run_root = Path(self.cfg.benchmark.workdir)
        runs_root = run_root / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        self._folders_initialized = True  # Skip folder creation in _prepare_execution_artifacts
        self._kickoff_preparation = True  # Flag for writing PENDING status in repetition folders

        # Initialize interleaving state FIRST to use planner's selection logic
        # This ensures execution script order matches what next_test() would produce
        self._init_interleaving_state()

        self.logger.info("Creating folders and scripts using planner selection order...")

        # Determine execution order using planner's selection logic
        # This simulates what next_test() would do, ensuring order consistency
        self._kickoff_order = []  # List of (test_idx, repetition) tuples for next_test() replay
        kickoff_tests = []  # For execution script generation

        total_preparations = total_tests * repetitions

        def _prepare_in_selection_order(progress=None, task=None):
            """Prepare tests in planner's selection order (random interleaving)."""
            while self._active_indices:
                # Use same selection logic as next_test()
                idx = self.random.choice(self._active_indices)
                rep = self._next_rep_by_idx[idx] + 1  # 1-based

                test = self.execution_matrix[idx]

                # Prepare artifacts (creates folders, writes scripts)
                self._prepare_execution_artifacts(test, rep)

                # Check cache if available
                is_cached = False
                if cache is not None:
                    cached_result = cache.get_cached_result(
                        params=test.vars,
                        repetition=rep,
                    )
                    is_cached = cached_result is not None

                # Always add to order tracking (for next_test() to replay)
                # Runner will handle cached tests by reading from cache and writing to sink
                self._kickoff_order.append((idx, rep))

                if not is_cached:
                    # Add to execution script list (only non-cached tests run in bash)
                    kickoff_tests.append({
                        'execution_id': test.execution_id,
                        'repetition': rep,
                        'execution_dir': str(test.execution_dir),
                        'script_file': str(test.script_file),
                    })
                else:
                    self.logger.debug(
                        f"  [Cache] exec_id={test.execution_id} rep={rep} will use cached result"
                    )

                # Update selection state (same as next_test would)
                self._next_rep_by_idx[idx] += 1
                if self._next_rep_by_idx[idx] >= self._total_reps_by_idx[idx]:
                    self._active_indices.remove(idx)

                # Update progress bar if available
                if progress is not None and task is not None:
                    progress.update(task, advance=1)

        if RICH_AVAILABLE and total_preparations > 0:
            # Use rich progress bar
            progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TextColumn("[dim]{task.completed}/{task.total}"),
            )
            with progress:
                task = progress.add_task("Preparing tests", total=total_preparations)
                _prepare_in_selection_order(progress, task)
        else:
            # Fall back to simple logging
            _prepare_in_selection_order()

        # Write complete index with single-allocation mode fields (folders_upfront, active_tests, etc.)
        # This is needed for watch mode to properly track execution progress.
        # Always call this, even with no skipped instances, to ensure index has all fields.
        self._initialize_all_folders(kept_instances, skipped_instances)

        cached_count = (total_tests * repetitions) - len(kickoff_tests)
        self.logger.info(f"  Tests prepared: {total_tests * repetitions}")
        self.logger.info(f"  Cached (from previous runs): {cached_count}")
        self.logger.info(f"  To execute in single allocation: {len(kickoff_tests)}")

        # Generate execution script (uses order from selection loop above)
        kickoff_path = self._generate_kickoff_script(kickoff_tests)

        self.logger.info(f"  Execution script: {kickoff_path}")
        self.logger.info("=" * 70)

        # Reset index for next_test() to replay from stored order
        self._kickoff_index = 0
        self._kickoff_mode_active = True
        self._kickoff_preparation = False  # Done with initial preparation

        return kickoff_path

    def _generate_kickoff_script(self, tests: list) -> Path:
        """
        Generate the single-allocation execution script that runs all tests sequentially.

        The execution script is a dispatcher that:
        1. Sets up SBATCH directives (from user's allocation_script)
        2. Defines a run_test() function with timeout and status reporting
        3. Calls existing per-test scripts sequentially

        This reuses all existing per-test logic (MPI wrapping, resource tracing,
        exit handlers) by calling the generated scripts.

        Args:
            tests: List of test dicts with execution_id, repetition, execution_dir, script_file

        Returns:
            Path to the generated execution script
        """
        from datetime import datetime

        allocation = self.cfg.benchmark.slurm_options.allocation
        test_timeout = allocation.test_timeout
        workdir = Path(self.cfg.benchmark.workdir)

        # Create logs directory
        logs_dir = workdir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        # Parse allocation_script: separate SBATCH directives from setup commands
        # SLURM stops parsing #SBATCH when it encounters non-SBATCH lines,
        # so we must put ALL #SBATCH directives at the top.
        user_script = allocation.allocation_script.strip()
        if user_script.startswith("#!"):
            # Skip user's shebang
            user_script = "\n".join(user_script.split('\n')[1:])

        sbatch_lines = []
        setup_lines = []
        for line in user_script.split('\n'):
            stripped = line.strip()
            if stripped.startswith("#SBATCH"):
                sbatch_lines.append(line)
            else:
                setup_lines.append(line)

        # Build the execution script
        lines = [
            "#!/bin/bash",
        ]

        # 1. User's SBATCH directives
        lines.extend(sbatch_lines)

        # 2. IOPS-managed SBATCH directives
        lines.extend([
            "#SBATCH --job-name=iops_single_alloc",
            f"#SBATCH --output={logs_dir}/single_alloc_%j.out",
            f"#SBATCH --error={logs_dir}/single_alloc_%j.err",
        ])

        # 3. Informational comments
        lines.extend([
            "",
            "# IOPS Single-Allocation Script - Runs all tests sequentially within allocation",
            f"# Generated: {datetime.now().isoformat()}",
            f"# Total tests: {len(tests)}",
            f"# Timeout per test: {test_timeout}s",
            "",
        ])

        # 4. User's setup commands (modules, env vars, etc.)
        # Strip leading empty lines but preserve the rest
        while setup_lines and not setup_lines[0].strip():
            setup_lines.pop(0)
        if setup_lines:
            lines.extend(setup_lines)
            lines.append("")

        lines.extend([
            "# ===== SINGLE-ALLOCATION DISPATCHER =====",
            "",
            f"_IOPS_TEST_TIMEOUT={test_timeout}",
            "",
            "run_test() {",
            '    local test_dir="$1"',
            '    local script_path="$2"',
            '    local exec_id="$3"',
            '    local rep="$4"',
            '    local status_file="$test_dir/__iops_status.json"',
            "",
            '    cd "$test_dir" || {',
            '        echo "{\\"status\\":\\"ERROR\\",\\"error\\":\\"Failed to cd to $test_dir\\"}" > "$status_file"',
            "        return 0",
            "    }",
            "",
            '    echo "{\\"status\\":\\"RUNNING\\",\\"start_time\\":\\"$(date -Iseconds)\\"}" > "$status_file"',
            '    echo "[$(date +%H:%M:%S)] Starting $exec_id rep $rep"',
            "",
            "    # Run with timeout, capture exit code",
            '    timeout "$_IOPS_TEST_TIMEOUT" bash "$script_path"',
            "    local rc=$?",
            "",
            "    if [ $rc -eq 0 ]; then",
            '        echo "{\\"status\\":\\"SUCCEEDED\\",\\"end_time\\":\\"$(date -Iseconds)\\"}" > "$status_file"',
            '        echo "[$(date +%H:%M:%S)] $exec_id rep $rep: SUCCEEDED"',
            "    elif [ $rc -eq 124 ]; then",
            f'        echo "{{\\"status\\":\\"TIMEOUT\\",\\"end_time\\":\\"$(date -Iseconds)\\",\\"error\\":\\"Test timed out after {test_timeout}s\\"}}" > "$status_file"',
            '        echo "[$(date +%H:%M:%S)] $exec_id rep $rep: TIMEOUT"',
            "    else",
            '        echo "{\\"status\\":\\"FAILED\\",\\"exit_code\\":$rc,\\"end_time\\":\\"$(date -Iseconds)\\"}" > "$status_file"',
            '        echo "[$(date +%H:%M:%S)] $exec_id rep $rep: FAILED (rc=$rc)"',
            "    fi",
            "",
            "    return 0  # Always continue to next test",
            "}",
            "",
            f'echo "===== IOPS Single-Allocation Start: $(date -Iseconds) ====="',
            f'echo "Total tests: {len(tests)}"',
            'echo ""',
            "",
        ])

        # Add test calls
        for i, test in enumerate(tests, 1):
            exec_id = f"exec_{test['execution_id']:04d}"
            lines.extend([
                f"# === Test {i}/{len(tests)}: {exec_id} rep {test['repetition']} ===",
                f'run_test "{test["execution_dir"]}" "{test["script_file"]}" "{exec_id}" "{test["repetition"]}"',
                "",
            ])

        lines.extend([
            'echo ""',
            f'echo "===== IOPS Single-Allocation Complete: $(date -Iseconds) ====="',
        ])

        # Write execution script
        kickoff_path = workdir / "__iops_kickoff.sh"
        with open(kickoff_path, "w") as f:
            f.write("\n".join(lines))
        kickoff_path.chmod(0o755)

        return kickoff_path

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

        # In single-allocation preparation mode, write PENDING status to repetition folder
        # This allows watch mode to properly count pending tests before execution starts
        probes = self.cfg.benchmark.probes
        execution_index = probes.execution_index if probes else self.cfg.benchmark.track_executions
        if getattr(self, '_kickoff_preparation', False) and execution_index:
            rep_status_file = exec_dir / STATUS_FILENAME
            with open(rep_status_file, "w") as f:
                json.dump({"status": "PENDING"}, f)

        # Point to repetition dir (useful for templates like {{ execution_dir }})
        # Must be set before _write_params_file so derived variables render correctly
        test.execution_dir = exec_dir

        # Write params/index files in exec folder (only on first repetition)
        # Can be disabled with probes.execution_index: false to reduce file I/O
        if repetition == 1 and execution_index:
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
        # Check which features are enabled (use probes config or fallback to deprecated fields)
        probes = self.cfg.benchmark.probes
        resource_sampling = probes.resource_sampling if probes else self.cfg.benchmark.trace_resources
        system_snapshot = probes.system_snapshot if probes else self.cfg.benchmark.collect_system_info

        # If no features enabled, return script unchanged
        if not resource_sampling and not system_snapshot:
            return script_text

        # Build list of source lines to inject
        source_lines = [
            '',
            '# ===== IOPS INJECTION START =====',
        ]

        # 1. Exit handler (always needed if any feature is enabled)
        handler_file = exec_dir / EXIT_HANDLER_FILENAME
        with open(handler_file, "w") as f:
            f.write(EXIT_HANDLER_TEMPLATE)
        source_lines.append(f'source "{handler_file}"')

        # 2. Runtime scripts (run during execution)
        if resource_sampling:
            # To disable: set probes.resource_sampling: false in config
            sampling_interval = probes.sampling_interval if probes else self.cfg.benchmark.trace_interval
            sampler_script = RESOURCE_SAMPLER_TEMPLATE.format(
                execution_dir=str(exec_dir),
                trace_prefix=TRACE_FILENAME_PREFIX,
                trace_interval=sampling_interval,
                sentinel_filename=SAMPLER_SENTINEL_FILENAME
            )
            sampler_file = exec_dir / RUNTIME_SAMPLER_FILENAME
            with open(sampler_file, "w") as f:
                f.write(sampler_script)
            source_lines.append(f'source "{sampler_file}"  # disable: probes.resource_sampling: false')

        # 3. At-exit scripts (run on script exit via trap)
        if system_snapshot:
            # To disable: set probes.system_snapshot: false in config
            probe_script = SYSTEM_PROBE_TEMPLATE.format(execution_dir=str(exec_dir))
            probe_file = exec_dir / ATEXIT_SYSINFO_FILENAME
            with open(probe_file, "w") as f:
                f.write(probe_script)
            source_lines.append(f'source "{probe_file}"  # disable: probes.system_snapshot: false')

        source_lines.append('# ===== IOPS INJECTION END =====')

        # Find insertion point after the SLURM header block
        # SLURM reads #SBATCH directives through blank lines and comments until it
        # hits an actual command. We must inject AFTER all #SBATCH directives.
        lines = script_text.split('\n')
        insert_idx = 0

        # Skip shebang if present
        if lines and lines[0].startswith('#!'):
            insert_idx = 1

        # Skip the entire SLURM header block: #SBATCH directives, comments, blank lines
        # Stop when we hit an actual command (non-comment, non-blank line)
        while insert_idx < len(lines):
            line = lines[insert_idx]
            stripped = line.strip()
            if stripped == '':  # Blank line - continue
                insert_idx += 1
            elif stripped.startswith('#'):  # Comment or #SBATCH - continue
                insert_idx += 1
            else:  # Actual command - stop here
                break

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

    def _write_skipped_marker(
        self,
        exec_dir: Path,
        reason: str = None,
        message: str = None
    ) -> None:
        """
        Write a marker file indicating this test was skipped.

        The presence of __iops_skipped in exec_XXXX indicates the test was
        skipped due to constraints or planner decision. If absent, the test
        is active (watch will check repetition directories for status).

        Args:
            exec_dir: The exec_XXXX directory
            reason: Skip reason: "constraint" or "planner"
            message: Additional message (e.g., constraint violation message)
        """
        probes = self.cfg.benchmark.probes
        execution_index = probes.execution_index if probes else self.cfg.benchmark.track_executions
        if not execution_index:
            return

        marker_file = exec_dir / SKIPPED_MARKER_FILENAME
        marker_data = {"reason": reason or "unknown"}
        if message:
            marker_data["message"] = message

        with open(marker_file, "w") as f:
            json.dump(marker_data, f, indent=2, default=str)

    def _initialize_all_folders(
        self,
        active_instances: List[ExecutionInstance],
        skipped_instances: List[ExecutionInstance]
    ) -> None:
        """
        Create all execution folders upfront.

        Called when create_folders_upfront=True. Creates folders for both
        active tests and skipped tests. Skipped tests get a marker file.

        This enables watch mode to show the full parameter space from the start,
        including which tests were skipped and why.

        Args:
            active_instances: Tests that will be executed
            skipped_instances: Tests that were skipped (constraint or planner)
        """
        probes = self.cfg.benchmark.probes
        execution_index = probes.execution_index if probes else self.cfg.benchmark.track_executions
        if not execution_index:
            return

        run_root = Path(self.cfg.benchmark.workdir)
        runs_root = run_root / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)

        # Track all instances for index
        all_index_entries = []

        # Active instances: create folder with params only (no status file needed)
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

            # Add to index (no status field - watch infers PENDING from absence of skipped marker)
            exec_rel_path = exec_dir.relative_to(run_root)
            all_index_entries.append({
                "exec_key": f"exec_{instance.execution_id:04d}",
                "path": str(exec_rel_path),
                "params": params,
                "command": instance.command,
            })

        # Skipped instances: create folder with params + skipped marker
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

            # Write skipped marker file
            self._write_skipped_marker(exec_dir, reason, message)

            # Add to index with skip info
            exec_rel_path = exec_dir.relative_to(run_root)
            entry = {
                "exec_key": f"exec_{instance.execution_id:04d}",
                "path": str(exec_rel_path),
                "params": params,
                "command": instance.command,
                "skipped": True,
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
        probes = self.cfg.benchmark.probes
        execution_index = probes.execution_index if probes else self.cfg.benchmark.track_executions
        if not execution_index:
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
    def _next_test_kickoff(self) -> Optional[Any]:
        """
        Return next test in pre-determined single-allocation order.

        In single-allocation mode, prepare_kickoff_mode() already determined the
        execution order and stored it in _kickoff_order. This method replays that
        order to ensure the runner waits for tests in the same sequence the
        execution script runs them.
        """
        if self._kickoff_index >= len(self._kickoff_order):
            return None

        test_idx, rep = self._kickoff_order[self._kickoff_index]
        self._kickoff_index += 1
        self._attempt_count += 1

        test = self.execution_matrix[test_idx]

        # Re-prepare artifacts to ensure test.execution_dir is set correctly
        # (artifacts already exist from prepare_kickoff_mode, this just updates the object)
        self._prepare_execution_artifacts(test, rep)

        self.logger.debug(
            f"  [Planner] Single-allocation test {self._kickoff_index}/{len(self._kickoff_order)}: "
            f"exec_id={test.execution_id} rep={rep}"
        )

        return test

    def next_test(self) -> Any:
        """
        Returns the next test to run (including repetitions),
        or None when all tests are done.

        In single-allocation mode, returns tests in the pre-determined order from
        prepare_kickoff_mode(). Otherwise, uses random interleaving.
        """
        # Single-allocation mode: replay from stored order
        if getattr(self, '_kickoff_mode_active', False):
            return self._next_test_kickoff()

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
    1. Build the full execution matrix upfront (like other planners)
    2. Start with random exploration (n_initial_points)
    3. Build a surrogate model (Random Forest by default) from observed results
    4. Use acquisition function to suggest next promising point
    5. Map suggestions to nearest valid pre-built instance
    6. Iteratively improve to find optimal parameters

    Requires scikit-optimize: pip install scikit-optimize
    """

    def __init__(self, cfg: GenericBenchmarkConfig):
        super().__init__(cfg)

        # Store exhaustive_var_names for filtering search space
        self.exhaustive_var_names = set(cfg.benchmark.exhaustive_vars or [])

        if not SKOPT_AVAILABLE:
            raise ImportError(
                "scikit-optimize is required for Bayesian optimization. "
                "Install it with: pip install scikit-optimize"
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
        self.fixed_values: Dict[str, Any] = {}  # var_name -> fixed value (for single-value sweeps)
        self.search_space, self.var_names = self._build_search_space()

        if not self.search_space:
            if self.fixed_values:
                raise ValueError(
                    f"No optimizable variables for Bayesian optimization. "
                    f"All swept variables have single values and are treated as fixed: "
                    f"{list(self.fixed_values.keys())}. "
                    f"Ensure at least one variable has multiple values to optimize."
                )
            else:
                raise ValueError("No swept variables found for Bayesian optimization")

        # Build instance lookup from pre-built execution matrix
        # This replaces dynamic instance creation with a lookup table
        self._instance_lookup, self._skipped_instances = self._build_instance_lookup()
        self._valid_search_points = list(self._instance_lookup.keys())

        # Track variable ranges for distance calculation
        self._var_ranges = self._compute_var_ranges()

        # Total search space size (number of valid search points)
        self.total_space_size = len(self._valid_search_points)

        # Check for exhaustive fallback
        self.fallback_to_exhaustive = self.bayesian_cfg.fallback_to_exhaustive
        self.early_stop_on_convergence = self.bayesian_cfg.early_stop_on_convergence
        self.convergence_patience = self.bayesian_cfg.convergence_patience
        self.xi_boost_factor = self.bayesian_cfg.xi_boost_factor
        self._use_exhaustive_fallback = False
        self._exhaustive_matrix: List[ExecutionInstance] = []
        self._exhaustive_index = 0

        # Convergence tracking for early stop with xi boost
        self._convergence_count = 0
        self._original_xi = self.xi

        if self.n_iterations >= self.total_space_size and self.total_space_size > 0:
            if self.fallback_to_exhaustive:
                self.logger.warning(
                    f"Requested n_iterations={self.n_iterations} >= total_space={self.total_space_size}. "
                    f"Using full exhaustive search instead of Bayesian optimization."
                )
                self._use_exhaustive_fallback = True
                # Flatten lookup into a list for exhaustive iteration
                self._exhaustive_matrix = []
                for instances in self._instance_lookup.values():
                    self._exhaustive_matrix.extend(instances)
            else:
                self.logger.warning(
                    f"Requested n_iterations={self.n_iterations} >= total_space={self.total_space_size}. "
                    f"Clamping to total_space."
                )
                self.n_iterations = self.total_space_size

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
        # Account for multiple exhaustive instances per search point
        self._attempt_count: int = 0
        if self._use_exhaustive_fallback:
            self._attempt_total = len(self._exhaustive_matrix) * (cfg.benchmark.repetitions or 1)
        elif self._instance_lookup:
            # Average number of exhaustive instances per search point
            avg_exhaustive = sum(len(v) for v in self._instance_lookup.values()) / len(self._instance_lookup)
            self._attempt_total = int(self.n_iterations * avg_exhaustive * (cfg.benchmark.repetitions or 1))
        else:
            self._attempt_total = self.n_iterations * (cfg.benchmark.repetitions or 1)

        # Best found so far
        self.best_params: Optional[Dict[str, Any]] = None
        self.best_value: Optional[float] = None

        # Repetitions per configuration
        self.repetitions = cfg.benchmark.repetitions or 1

        # Current iteration state
        self.current_test: Optional[ExecutionInstance] = None
        self.current_params: Optional[List[Any]] = None
        self.current_rep = 0
        self._current_search_point: Optional[tuple] = None
        self._current_instances: List[ExecutionInstance] = []
        self._current_instance_idx = 0

        # Track exhaustive instance results for aggregation
        # When exhaustive_vars is used, each search point has multiple instances
        # We collect metric values from each instance and aggregate before updating optimizer
        self._exhaustive_instance_results: List[float] = []

        # Track metrics per iteration for repetition aggregation
        # Key: (iteration, exhaustive_instance_idx), Value: list of metric values per repetition
        self._iteration_metrics: Dict[tuple, List[float]] = {}

        # Track which search points have been visited
        self._visited_search_points: set = set()

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

    def _build_instance_lookup(self) -> tuple:
        """
        Build lookup index from search points to pre-built instances.

        Returns:
            Tuple of (lookup_dict, skipped_instances):
            - lookup_dict: Dict mapping search point tuples to lists of ExecutionInstance
            - skipped_instances: List of instances that were skipped due to constraints
        """
        kept, skipped = build_execution_matrix(self.cfg, start_execution_id=1)

        lookup: Dict[tuple, List[ExecutionInstance]] = defaultdict(list)
        for instance in kept:
            search_point = self._instance_to_search_point(instance)
            lookup[search_point].append(instance)

        return dict(lookup), skipped

    def _instance_to_search_point(self, instance: ExecutionInstance) -> tuple:
        """
        Convert an ExecutionInstance to a search point tuple.

        The search point only includes variables that are in the optimizer's search space
        (excluding fixed values and exhaustive vars).
        """
        return tuple(instance.base_vars.get(name) for name in sorted(self.var_names))

    def _compute_var_ranges(self) -> Dict[str, float]:
        """
        Compute the range of each variable for distance normalization.

        Returns:
            Dictionary mapping variable names to their ranges
        """
        ranges = {}
        for var_name in self.var_names:
            var_cfg = self.cfg.vars[var_name]
            if var_cfg.sweep.mode == "range":
                ranges[var_name] = float(var_cfg.sweep.end - var_cfg.sweep.start)
            elif var_name in self.ordinal_mappings:
                values = self.ordinal_mappings[var_name]
                ranges[var_name] = float(max(values) - min(values)) if len(values) > 1 else 1.0
            else:
                # Categorical: use 1.0 (0 if same, 1 if different)
                ranges[var_name] = 1.0
        return ranges

    def _suggestion_to_search_point(self, params: List[Any]) -> tuple:
        """
        Convert optimizer suggestion to a search point tuple.

        Args:
            params: List of parameter values from optimizer.ask()

        Returns:
            Tuple of variable values in sorted order
        """
        vars_dict = self._params_to_dict(params)
        return tuple(vars_dict.get(name) for name in sorted(self.var_names))

    def _search_point_to_params(self, search_point: tuple) -> List[Any]:
        """
        Convert a search point tuple back to optimizer parameter format.

        This is the inverse of _suggestion_to_search_point. For ordinal-encoded
        variables, converts the actual value back to an index.

        Args:
            search_point: Tuple of variable values in sorted(var_names) order

        Returns:
            List of parameter values in var_names order (optimizer format)
        """
        # First, build a dict from search point (sorted order)
        sorted_names = sorted(self.var_names)
        values_dict = {name: search_point[i] for i, name in enumerate(sorted_names)}

        # Then, convert to optimizer format (var_names order, with indices for ordinals)
        params = []
        for name in self.var_names:
            value = values_dict[name]

            # Convert ordinal values back to indices
            if name in self.ordinal_mappings:
                try:
                    idx = self.ordinal_mappings[name].index(value)
                    params.append(idx)
                except ValueError:
                    # Value not in mapping, find nearest
                    sorted_values = self.ordinal_mappings[name]
                    idx = min(range(len(sorted_values)),
                              key=lambda i: abs(sorted_values[i] - value))
                    params.append(idx)
            else:
                params.append(value)

        return params

    def _find_nearest_valid_point_by_indices(self, suggested_params: List[Any]) -> tuple:
        """
        Find the nearest valid search point using index-based distance.

        This method works directly with the optimizer's raw suggestions (which may be
        floating-point for Integer dimensions) and finds the nearest valid configuration
        using squared Euclidean distance in index space. This matches the behavior of
        standalone scikit-optimize usage and provides better nearest-neighbor selection
        than truncating indices first.

        When multiple points have the same minimum distance (ties), the point with
        the lexicographically largest index vector is chosen. This provides consistent,
        deterministic tie-breaking that tends to favor higher parameter values
        (which often correlate with better performance for I/O benchmarks).

        Args:
            suggested_params: Raw parameter values from optimizer.ask() (may be floats)

        Returns:
            Nearest valid search point tuple (actual values, not indices)
        """
        # Convert suggested params to index representation (keeping floats)
        suggested_indices = []
        for i, name in enumerate(self.var_names):
            value = suggested_params[i]
            # Convert numpy types to native Python
            if hasattr(value, 'item'):
                value = value.item()
            suggested_indices.append(float(value))

        # Build index representation for all valid points (once, cached)
        if not hasattr(self, '_valid_points_indices'):
            self._valid_points_indices = []
            for valid_point in self._valid_search_points:
                indices = self._search_point_to_params(valid_point)
                self._valid_points_indices.append((valid_point, tuple(float(x) for x in indices)))

        # Find all points with minimum distance, then break ties deterministically
        candidates = []
        best_distance = float('inf')

        for valid_point, valid_indices in self._valid_points_indices:
            # Compute squared Euclidean distance in index space
            dist = sum((s - v) ** 2 for s, v in zip(suggested_indices, valid_indices))
            if dist < best_distance:
                best_distance = dist
                candidates = [(valid_point, valid_indices)]
            elif dist == best_distance:
                candidates.append((valid_point, valid_indices))

        if len(candidates) == 1:
            return candidates[0][0]

        # Break ties: prefer lexicographically largest index vector
        # This tends to favor higher parameter values (more nodes, higher transfer sizes, etc.)
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    def _find_nearest_valid_point(self, suggested: tuple) -> tuple:
        """
        Find the nearest valid search point to the suggested point.

        Uses normalized Euclidean distance for numeric vars, exact match for categorical.

        Args:
            suggested: Tuple of suggested parameter values

        Returns:
            Nearest valid search point tuple from the pre-built matrix
        """
        if suggested in self._instance_lookup:
            return suggested  # Exact match

        # Compute distances to all valid points
        best_point = None
        best_distance = float('inf')

        for valid_point in self._valid_search_points:
            dist = self._compute_distance(suggested, valid_point)
            if dist < best_distance:
                best_distance = dist
                best_point = valid_point

        return best_point

    def _compute_distance(self, p1: tuple, p2: tuple) -> float:
        """
        Compute normalized distance between two search points.

        Uses normalized Euclidean distance for numeric variables and
        0/1 distance for categorical variables.

        Args:
            p1: First search point tuple
            p2: Second search point tuple

        Returns:
            Distance between the two points
        """
        total = 0.0
        for i, var_name in enumerate(sorted(self.var_names)):
            v1, v2 = p1[i], p2[i]
            var_cfg = self.cfg.vars[var_name]

            if var_cfg.type in ('int', 'float'):
                # Normalize by range
                range_size = self._var_ranges.get(var_name, 1.0)
                if range_size > 0:
                    total += ((float(v1) - float(v2)) / range_size) ** 2
            else:
                # Categorical: 0 if same, 1 if different
                total += 0 if v1 == v2 else 1

        return total ** 0.5

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

            # Skip exhaustive variables - they are tested exhaustively, not optimized
            if var_name in self.exhaustive_var_names:
                self.logger.debug(
                    f"  [Bayesian] Variable '{var_name}': excluded from search space "
                    f"(exhaustive variable)"
                )
                continue

            sweep_cfg = var_config.sweep

            if sweep_cfg.mode == "range":
                # Continuous or integer range
                # Skip if start == end (single value, not a dimension to optimize)
                if sweep_cfg.start == sweep_cfg.end:
                    self.fixed_values[var_name] = sweep_cfg.start
                    self.logger.debug(
                        f"  [Bayesian] Variable '{var_name}': fixed value {sweep_cfg.start} "
                        f"(range start == end, not added to search space)"
                    )
                    continue

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

                # Skip if only one value (not a dimension to optimize)
                if len(values) == 1:
                    self.fixed_values[var_name] = values[0]
                    self.logger.debug(
                        f"  [Bayesian] Variable '{var_name}': fixed value {values[0]} "
                        f"(single-value list, not added to search space)"
                    )
                    continue

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

        Also includes fixed values (single-value sweeps) that are not part of
        the search space but need to be included in the parameter dict.

        Values are cast to their proper types (int, float, bool, str) as defined
        in the config to ensure cache hash consistency with the exhaustive planner.
        """
        result = {}

        # First, add all fixed values (single-value sweeps)
        # These also need type casting
        for name, value in self.fixed_values.items():
            var_type = self.cfg.vars[name].type
            result[name] = _cast_value(var_type, value)

        # Then add optimized parameters
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

            # Cast value to proper type (int, float, bool, str) as defined in config
            # This ensures cache hash consistency with exhaustive planner
            var_type = self.cfg.vars[name].type
            result[name] = _cast_value(var_type, value)

        return result

    def next_test(self) -> Optional[ExecutionInstance]:
        """
        Return the next test to execute.

        Uses pre-built instances from the execution matrix instead of
        creating instances dynamically. Maps optimizer suggestions to
        the nearest valid search point in the pre-built matrix.

        When exhaustive_vars is configured, each search point may have multiple
        instances (one for each combination of exhaustive variable values).
        All instances for a search point are executed before moving to the
        next search point from the optimizer.

        Returns:
            ExecutionInstance or None when optimization is complete
        """
        # If using exhaustive fallback, delegate to simpler iteration
        if self._use_exhaustive_fallback:
            return self._next_test_exhaustive()

        # Handle repetitions for current exhaustive instance first
        if self.current_test and self.current_rep < self.repetitions:
            # Continue with repetitions of current instance
            self.current_rep += 1
            self._attempt_count += 1

            # Get the current exhaustive instance (not always instances[0])
            test = self._current_instances[self._current_instance_idx]
            test.repetition = self.current_rep
            test.repetitions = self.repetitions
            self._prepare_execution_artifacts(test, self.current_rep)

            self.logger.debug(
                f"  [Bayesian] Instance {self._current_instance_idx + 1}/{len(self._current_instances)}, "
                f"Repetition {self.current_rep}/{self.repetitions}"
            )
            return test

        # Current instance's repetitions are done - check for more exhaustive instances
        if self._current_instances and self._current_instance_idx < len(self._current_instances) - 1:
            # Move to next exhaustive instance for this search point
            self._current_instance_idx += 1
            self.current_rep = 1
            self._attempt_count += 1

            test = self._current_instances[self._current_instance_idx]
            test.execution_id = self.iteration
            test.repetition = self.current_rep
            test.repetitions = self.repetitions
            self._prepare_execution_artifacts(test, self.current_rep)
            self.current_test = test

            self.logger.debug(
                f"  [Bayesian] Moving to exhaustive instance "
                f"{self._current_instance_idx + 1}/{len(self._current_instances)}"
            )
            if len(self._current_instances) > 1:
                self.logger.info(
                    f"  [Bayesian] Testing exhaustive config {self._current_instance_idx + 1}/"
                    f"{len(self._current_instances)}: {test.base_vars}"
                )
            return test

        # All exhaustive instances and their repetitions are done for this search point
        # Check if we've completed all iterations
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

        # Get next point from optimizer, avoiding already-visited configurations
        # The optimizer may suggest points that map to visited configs (due to nearest-neighbor mapping)
        # We retry a few times before falling back to random sampling from unvisited configs
        max_retries = 10
        search_point = None
        was_mapped = False

        for attempt in range(max_retries):
            next_params = self.optimizer.ask()

            # Use index-based nearest-neighbor search for better accuracy
            # This works directly with the optimizer's raw suggestions (which may be floats)
            # and finds the nearest valid configuration in index space
            candidate_point = self._find_nearest_valid_point_by_indices(next_params)

            if candidate_point is None:
                self.logger.error(
                    f"  [Bayesian] No valid search points available. "
                    f"This indicates a configuration issue."
                )
                return None

            # Check if suggestion was mapped (for logging)
            suggested_point = self._suggestion_to_search_point(next_params)
            was_mapped = (suggested_point != candidate_point)

            # Check if we've already visited this search point
            if candidate_point not in self._visited_search_points:
                search_point = candidate_point
                break

            # This point was already visited; tell optimizer about it to help it learn
            # and then request a new suggestion
            actual_params = self._search_point_to_params(candidate_point)
            self.logger.debug(
                f"  [Bayesian] Attempt {attempt + 1}: suggestion maps to visited point, requesting new"
            )

        # If all retries exhausted, handle convergence
        if search_point is None:
            unvisited = [p for p in self._valid_search_points if p not in self._visited_search_points]
            if not unvisited:
                # All configurations visited - we're done
                self.logger.info(
                    f"  [Bayesian] All {len(self._valid_search_points)} configurations visited"
                )
                return None

            # Convergence detected - optimizer keeps suggesting visited points
            self._convergence_count += 1

            if self.early_stop_on_convergence:
                if self._convergence_count >= self.convergence_patience:
                    # Patience exhausted - stop optimization
                    self.logger.info("=" * 70)
                    self.logger.info("BAYESIAN OPTIMIZATION COMPLETE (early stop)")
                    self.logger.info("=" * 70)
                    self.logger.info(
                        f"Optimizer converged {self._convergence_count} times after "
                        f"{self.iteration} iterations. {len(unvisited)} configs remain unvisited."
                    )
                    if self.best_params:
                        self.logger.info(f"Best parameters found: {self.best_params}")
                        self.logger.info(f"Best {self.target_metric}: {self.best_value:.4f}")
                    self.logger.info(f"Total evaluations: {len(self.y_observed)}")
                    self.logger.info("=" * 70)
                    return None
                else:
                    # Boost xi to encourage exploration
                    new_xi = self._original_xi * (self.xi_boost_factor ** self._convergence_count)
                    self.logger.info(
                        f"  [Bayesian] Convergence detected ({self._convergence_count}/{self.convergence_patience}). "
                        f"Boosting xi: {self.xi:.4f} -> {new_xi:.4f}"
                    )
                    self.xi = new_xi
                    # Update optimizer's acquisition function kwargs
                    if self.acquisition_func in ['EI', 'PI']:
                        self.optimizer.acq_func_kwargs['xi'] = self.xi

                    # Random sample to continue exploration
                    import random
                    rng = random.Random(self.cfg.benchmark.random_seed + self.iteration)
                    search_point = rng.choice(unvisited)
                    self.logger.info(
                        f"  [Bayesian] Randomly sampling from {len(unvisited)} unvisited configurations"
                    )
            else:
                # Random fallback: sample from unvisited configurations
                import random
                rng = random.Random(self.cfg.benchmark.random_seed + self.iteration)
                search_point = rng.choice(unvisited)
                self.logger.info(
                    f"  [Bayesian] Optimizer converged; randomly sampling from "
                    f"{len(unvisited)} unvisited configurations"
                )
        else:
            # Valid new point found - reset convergence counter and restore xi
            if self._convergence_count > 0:
                self.logger.debug(
                    f"  [Bayesian] Resetting convergence counter (was {self._convergence_count})"
                )
                self._convergence_count = 0
                if self.xi != self._original_xi:
                    self.logger.info(
                        f"  [Bayesian] Restoring xi: {self.xi:.4f} -> {self._original_xi:.4f}"
                    )
                    self.xi = self._original_xi
                    if self.acquisition_func in ['EI', 'PI']:
                        self.optimizer.acq_func_kwargs['xi'] = self.xi

        # Log if we mapped to a different point (this affects model learning)
        if was_mapped:
            self.logger.info(
                f"  [Bayesian] Suggestion mapped to nearest valid point "
                f"(optimizer will learn about actual point evaluated)"
            )
            self.logger.debug(
                f"  [Bayesian] Mapping details: {suggested_point} -> {search_point}"
            )

        self._visited_search_points.add(search_point)

        # Get instances for this search point
        instances = self._instance_lookup[search_point]

        # Set up current iteration state
        self._current_search_point = search_point
        self._current_instances = instances
        self._current_instance_idx = 0

        # Reset exhaustive instance results for new search point
        self._exhaustive_instance_results = []

        # CRITICAL: Store the actual indices for the search point we're evaluating,
        # not the suggested indices. This ensures the optimizer receives correct
        # feedback about what was actually evaluated, not what was suggested.
        # When suggestions are mapped to nearest valid points, this prevents
        # the surrogate model from learning incorrect associations.
        self.current_params = self._search_point_to_params(search_point)

        self.current_rep = 1
        self.iteration += 1
        self._attempt_count += 1

        # Get the first instance for this search point
        test = instances[0]
        test.execution_id = self.iteration
        test.repetition = self.current_rep
        test.repetitions = self.repetitions
        self._prepare_execution_artifacts(test, self.current_rep)
        self.current_test = test

        self.logger.info(
            f"[Bayesian] Iteration {self.iteration}/{self.n_iterations}: "
            f"Testing {test.base_vars}"
        )
        if len(instances) > 1:
            self.logger.info(
                f"  [Bayesian] {len(instances)} exhaustive configurations for this search point"
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

    def record_completed_test(self, test: ExecutionInstance) -> None:
        """
        Record a completed test and update the Bayesian model.

        This is essential for Bayesian optimization - the optimizer needs
        to learn from completed tests to suggest better parameters.

        When exhaustive_vars is configured, metrics are collected from each
        exhaustive instance and aggregated before updating the optimizer.
        The optimizer receives one feedback point per search point (the mean
        across all exhaustive combinations).

        Args:
            test: Completed ExecutionInstance with metrics
        """
        self.completed_tests.append(test)

        # Store metric value for this repetition (for later aggregation)
        metrics = test.metadata.get('metrics', {})
        metric_value = metrics.get(self.target_metric)
        if metric_value is not None:
            key = (self.iteration, self._current_instance_idx)
            if key not in self._iteration_metrics:
                self._iteration_metrics[key] = []
            self._iteration_metrics[key].append(metric_value)

        # In exhaustive fallback mode, we don't update the optimizer
        # (we're just running all configs, not optimizing)
        if self._use_exhaustive_fallback:
            if test.repetition == self.repetitions:
                self.current_test = None
                self.current_rep = 0
            return

        # Only process after all repetitions for this exhaustive instance are complete
        if test.repetition != self.repetitions:
            return

        # Aggregate metrics across repetitions for this exhaustive instance
        key = (self.iteration, self._current_instance_idx)
        rep_values = self._iteration_metrics.get(key, [])

        if not rep_values:
            self.logger.warning(
                f"Target metric '{self.target_metric}' not found in any repetition results."
            )
            # Still need to check if we should update optimizer (even with missing metric)
        else:
            # Use best value (max for maximize, min for minimize) instead of mean
            if self.objective == 'maximize':
                instance_best = float(np.max(rep_values))
            else:
                instance_best = float(np.min(rep_values))
            self._exhaustive_instance_results.append(instance_best)
            self.logger.debug(
                f"  [Bayesian] Exhaustive instance {self._current_instance_idx + 1}/"
                f"{len(self._current_instances)} complete: "
                f"{self.target_metric}={instance_best:.4f} (best of {len(rep_values)} reps)"
            )

        # Only update optimizer after ALL exhaustive instances and their repetitions are complete
        is_last_exhaustive_instance = self._current_instance_idx >= len(self._current_instances) - 1

        if not is_last_exhaustive_instance:
            # More exhaustive instances to run for this search point
            return

        # All exhaustive instances complete - aggregate and update optimizer
        if not self._exhaustive_instance_results:
            self.logger.warning(
                f"  [Bayesian] No valid metrics collected for search point. "
                f"Cannot update optimizer."
            )
            # Reset for next iteration
            self.current_test = None
            self.current_params = None
            self.current_rep = 0
            return

        # Aggregate across all exhaustive instances (use best value)
        if self.objective == 'maximize':
            aggregated_value = float(np.max(self._exhaustive_instance_results))
        else:
            aggregated_value = float(np.min(self._exhaustive_instance_results))

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

        n_exhaustive = len(self._exhaustive_instance_results)
        if n_exhaustive > 1:
            self.logger.info(
                f"  [Bayesian] Iteration {self.iteration} complete: "
                f"{self.target_metric}={aggregated_value:.4f} "
                f"(best of {n_exhaustive} exhaustive configs)"
            )
        else:
            self.logger.info(
                f"  [Bayesian] Iteration {self.iteration} complete: "
                f"{self.target_metric}={aggregated_value:.4f}"
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
