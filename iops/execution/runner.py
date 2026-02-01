
from iops.logger import HasLogger
from iops.execution.planner import BasePlanner, STATUS_FILENAME, TRACE_FILENAME_PREFIX
from iops.execution.executors import BaseExecutor
from iops.cache import ExecutionCache
from iops.config.models import GenericBenchmarkConfig
from iops.results.writer import save_test_execution
from iops.reporting.config_template import serialize_reporting_config, save_report_config_template

from typing import Optional, List, Set, Dict, Any
from pathlib import Path
from jinja2 import Template
from datetime import datetime
import json
import signal
import sys
import subprocess
import shlex
import socket
import glob
import csv

# IOPS metadata filename
METADATA_FILENAME = "__iops_run_metadata.json"

# Resource trace summary filename
RESOURCE_SUMMARY_FILENAME = "__iops_resource_summary.csv"


def _get_iops_version() -> str:
    """Load the IOPS version from the VERSION file."""
    version_file = Path(__file__).parent.parent / "VERSION"
    if version_file.exists():
        with version_file.open() as f:
            return f.read().strip()
    return "unknown"

class IOPSRunner(HasLogger):
    def __init__(self, cfg: GenericBenchmarkConfig, args):
        super().__init__()
        self.cfg = cfg
        self.args = args
        self.planner = BasePlanner.build(cfg=self.cfg)

        # Initialize cache if cache_file is configured (always populate, use only with --use_cache)
        self.cache: Optional[ExecutionCache] = None
        self.use_cache_reads = args.use_cache  # Flag to control reading from cache

        if cfg.benchmark.cache_file:
            exclude_vars = cfg.benchmark.cache_exclude_vars or []

            # For Bayesian optimization, configure cache to return best results
            # instead of most recent (improves optimization consistency)
            objective_metric = None
            objective = "maximize"
            if cfg.benchmark.search_method == "bayesian" and cfg.benchmark.bayesian_config:
                objective_metric = cfg.benchmark.bayesian_config.objective_metric
                objective = cfg.benchmark.bayesian_config.objective or "maximize"

            self.cache = ExecutionCache(
                cfg.benchmark.cache_file,
                exclude_vars=exclude_vars,
                objective_metric=objective_metric,
                objective=objective,
            )

            if args.use_cache:
                stats = self.cache.get_cache_stats()
                self.logger.info(
                    f"Cache: ENABLED for reads and writes "
                    f"({stats['total_entries']} entries, {stats['unique_parameter_sets']} unique parameter sets)"
                )
            else:
                self.logger.info("Cache: WRITE-ONLY mode (use --use_cache to enable reads)")
        elif args.use_cache:
            self.logger.warning(
                "Cache requested (--use_cache) but benchmark.cache_file not configured. "
                "Cache disabled."
            )

        # Check for single-allocation mode (must be done after cache initialization, before executor)
        self.kickoff_mode = self._is_kickoff_mode()
        kickoff_path = None

        if self.kickoff_mode:
            # Single-allocation mode: prepare all tests upfront and generate execution script
            # Pass cache for filtering out cached tests (if --use-cache is enabled)
            cache_for_kickoff = self.cache if self.use_cache_reads else None
            kickoff_path = self.planner.prepare_kickoff_mode(cache=cache_for_kickoff)

        # Create executor (single-allocation mode requires kickoff_path)
        self.executor = BaseExecutor.build(cfg=self.cfg, kickoff_path=kickoff_path)

        # Pass runner reference to executor for job tracking (used by SLURM)
        self.executor.set_runner(self)

        # Cache-only mode: skip tests not in cache instead of executing
        self.cache_only = getattr(args, 'cache_only', False) and self.cache is not None
        if self.cache_only:
            self.logger.info("Cache-only mode: uncached tests will be SKIPPED")

        # Statistics
        self.cache_hits = 0
        self.cache_misses = 0
        self.skipped_cache_only = 0  # Tests skipped due to cache-only mode

        # Track actual output path (rendered from template)
        self.actual_output_path: Optional[Path] = None

        # Budget tracking
        self.max_core_hours: Optional[float] = None
        self.accumulated_core_hours: float = 0.0
        self.saved_core_hours: float = 0.0  # Core-hours saved by cache hits
        self.budget_exceeded: bool = False

        # Determine effective budget (CLI overrides config)
        if hasattr(args, 'max_core_hours') and args.max_core_hours is not None:
            self.max_core_hours = args.max_core_hours
        elif cfg.benchmark.max_core_hours is not None:
            self.max_core_hours = cfg.benchmark.max_core_hours

        # Prepare cores expression template (defaults to 1 if not specified)
        self.cores_expr = cfg.benchmark.cores_expr or "1"
        self.cores_template = Template(self.cores_expr)

        if self.max_core_hours is not None:
            self.logger.info(f"Budget: {self.max_core_hours} core-hours (cores expr: {self.cores_expr})")

        # Determine estimated time scenarios (CLI overrides config)
        # Validation is done in main.py _validate_args()
        self.estimated_time_scenarios: List[float] = []
        if hasattr(args, 'time_estimate') and args.time_estimate is not None and isinstance(args.time_estimate, str):
            self.estimated_time_scenarios = [float(x.strip()) for x in args.time_estimate.split(',')]
        elif cfg.benchmark.estimated_time_seconds is not None:
            self.estimated_time_scenarios = [cfg.benchmark.estimated_time_seconds]

        # Keep single value for backward compatibility
        self.estimated_time_seconds: Optional[float] = self.estimated_time_scenarios[0] if self.estimated_time_scenarios else None

        # Get expected metrics from configuration
        self.expected_metrics = self._get_expected_metrics()

        if self.cache and self.expected_metrics:
            self.logger.debug(
                f"Cache validation: Expecting {len(self.expected_metrics)} metrics: "
                f"{sorted(self.expected_metrics)}"
            )

        # Track submitted SLURM jobs for cleanup on interrupt
        self.submitted_job_ids: Set[str] = set()
        self.interrupted = False

        # Track system info collected from compute nodes
        # Key: hostname, Value: full sysinfo dict
        self.collected_system_info: Dict[str, Dict[str, Any]] = {}

        # Track completed tests for resource trace aggregation
        self.completed_tests: List = []

        # TODO check if signal handling is also done when executor=local
        # Register signal handler for Ctrl+C (SIGINT) if using SLURM executor
        if cfg.benchmark.executor == "slurm":
            signal.signal(signal.SIGINT, self._signal_handler)

    def _is_kickoff_mode(self) -> bool:
        """
        Check if the runner is configured for single-allocation mode.

        Single-allocation mode is enabled when:
        - executor is "slurm"
        - slurm_options.allocation.mode is "single"

        Returns:
            True if single-allocation mode is enabled, False otherwise
        """
        if self.cfg.benchmark.executor != "slurm":
            return False

        slurm_opts = self.cfg.benchmark.slurm_options
        if slurm_opts is None:
            return False

        allocation = slurm_opts.allocation
        if allocation is None:
            return False

        return allocation.mode == "single"

    def _get_expected_metrics(self) -> set:
        """Get set of expected metric names from configuration."""
        expected = set()
        for script in self.cfg.scripts:
            if script.parser and script.parser.metrics:
                for metric in script.parser.metrics:
                    expected.add(metric.name)
        return expected

    def _track_system_info(self, test) -> None:
        """
        Track system info from a completed test.

        Collects unique system configurations by hostname. If multiple nodes
        are used, each unique configuration is stored.

        Args:
            test: Completed ExecutionInstance with potential __sysinfo in metadata
        """
        sysinfo = test.metadata.get("__sysinfo")
        if not sysinfo:
            return

        hostname = sysinfo.get("hostname", "unknown")
        if hostname not in self.collected_system_info:
            self.collected_system_info[hostname] = sysinfo
            self.logger.debug(
                f"  [SysInfo] New node discovered: {hostname} "
                f"({sysinfo.get('cpu_model', 'unknown CPU')}, "
                f"{sysinfo.get('cpu_cores', '?')} cores)"
            )

    def _aggregate_system_info(self) -> Dict[str, Any]:
        """
        Aggregate collected system info into a summary for the report.

        Returns a dictionary with:
        - nodes: List of unique hostnames
        - node_count: Number of unique nodes used
        - hardware: Summarized hardware info (if consistent across nodes)
        - filesystems: All parallel filesystems discovered
        - interconnect: InfiniBand devices (if any)
        - nodes_detail: Full details per node

        Returns:
            Dictionary with aggregated system environment info
        """
        if not self.collected_system_info:
            return {}

        nodes = list(self.collected_system_info.keys())
        node_count = len(nodes)

        # Collect unique values for each field
        cpu_models = set()
        total_cores = []
        total_memory = []
        kernels = set()
        os_names = set()
        all_filesystems = set()
        all_ib_devices = set()

        for info in self.collected_system_info.values():
            if info.get('cpu_model'):
                cpu_models.add(info['cpu_model'])
            if info.get('cpu_cores'):
                total_cores.append(info['cpu_cores'])
            if info.get('memory_kb'):
                total_memory.append(info['memory_kb'])
            if info.get('kernel'):
                kernels.add(info['kernel'])
            if info.get('os'):
                os_names.add(info['os'])
            if info.get('filesystems'):
                # Parse "type:mount,type:mount" format
                for fs in info['filesystems'].split(','):
                    fs = fs.strip()
                    if fs and ':' in fs:
                        all_filesystems.add(fs)
            if info.get('ib_devices'):
                for dev in info['ib_devices'].split(','):
                    dev = dev.strip()
                    if dev:
                        all_ib_devices.add(dev)

        # Build summary
        result = {
            "nodes": nodes,
            "node_count": node_count,
        }

        # Hardware summary (show range if values differ)
        if cpu_models:
            result["cpu_model"] = list(cpu_models)[0] if len(cpu_models) == 1 else list(cpu_models)

        if total_cores:
            if len(set(total_cores)) == 1:
                result["cpu_cores_per_node"] = total_cores[0]
            else:
                result["cpu_cores_per_node"] = f"{min(total_cores)}-{max(total_cores)}"

        if total_memory:
            # Convert KB to GB for readability
            memory_gb = [m / (1024 * 1024) for m in total_memory]
            if len(set(total_memory)) == 1:
                result["memory_gb_per_node"] = round(memory_gb[0], 1)
            else:
                result["memory_gb_per_node"] = f"{round(min(memory_gb), 1)}-{round(max(memory_gb), 1)}"

        if kernels:
            result["kernel"] = list(kernels)[0] if len(kernels) == 1 else list(kernels)

        if os_names:
            result["os"] = list(os_names)[0] if len(os_names) == 1 else list(os_names)

        if all_filesystems:
            result["filesystems"] = sorted(list(all_filesystems))

        if all_ib_devices:
            result["interconnect"] = sorted(list(all_ib_devices))

        # Include full per-node details for comprehensive reports
        result["nodes_detail"] = self.collected_system_info

        return result

    def _compute_trace_metrics(self, trace_files: List[Path]) -> Dict[str, Any]:
        """
        Compute aggregated metrics from trace files.

        Reads all trace CSV files (one per node) and computes summary metrics.

        Args:
            trace_files: List of paths to __iops_trace_*.csv files

        Returns:
            Dictionary with aggregated metrics:
            - mem_peak_gb: Maximum memory used across all nodes
            - mem_avg_gb: Average memory used
            - mem_peak_per_node_gb: Peak memory per node (max of node peaks)
            - cpu_avg_pct: Average CPU utilization across all samples and cores
            - cpu_max_pct: Peak CPU utilization
            - cpu_imbalance_pct: Max - Min core utilization (load balancing indicator)
            - nodes_traced: Number of nodes with trace data
            - samples_collected: Total number of samples
            - trace_duration_s: Time span of trace data
        """
        all_cpu_user = []
        all_cpu_system = []
        all_mem_used_kb = []
        per_node_mem_peak = {}
        per_core_max_cpu = {}
        timestamps = []
        nodes_seen = set()

        for trace_file in trace_files:
            try:
                with open(trace_file, 'r', newline='') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        try:
                            hostname = row.get('hostname', 'unknown')
                            nodes_seen.add(hostname)

                            # Parse values
                            ts = float(row.get('timestamp', 0))
                            cpu_user = float(row.get('cpu_user_pct', 0))
                            cpu_system = float(row.get('cpu_system_pct', 0))
                            mem_total = int(row.get('mem_total_kb', 0))
                            mem_avail = int(row.get('mem_available_kb', 0))

                            timestamps.append(ts)
                            all_cpu_user.append(cpu_user)
                            all_cpu_system.append(cpu_system)

                            # Calculate memory used
                            mem_used = mem_total - mem_avail
                            all_mem_used_kb.append(mem_used)

                            # Track per-node peak memory
                            if hostname not in per_node_mem_peak:
                                per_node_mem_peak[hostname] = 0
                            per_node_mem_peak[hostname] = max(per_node_mem_peak[hostname], mem_used)

                            # Track per-core CPU for imbalance calculation
                            core = row.get('core', '0')
                            core_key = f"{hostname}:{core}"
                            cpu_total = cpu_user + cpu_system
                            if core_key not in per_core_max_cpu:
                                per_core_max_cpu[core_key] = 0
                            per_core_max_cpu[core_key] = max(per_core_max_cpu[core_key], cpu_total)

                        except (ValueError, KeyError) as e:
                            self.logger.debug(f"Skipping malformed trace row: {e}")
                            continue

            except Exception as e:
                self.logger.debug(f"Failed to read trace file {trace_file}: {e}")
                continue

        # Compute aggregated metrics
        metrics = {
            "nodes_traced": len(nodes_seen),
            "samples_collected": len(timestamps),
        }

        if not timestamps:
            return metrics

        # Memory metrics (convert KB to GB)
        if all_mem_used_kb:
            metrics["mem_peak_gb"] = round(max(all_mem_used_kb) / (1024 * 1024), 3)
            metrics["mem_avg_gb"] = round(sum(all_mem_used_kb) / len(all_mem_used_kb) / (1024 * 1024), 3)

        if per_node_mem_peak:
            # Peak per node is the max of all node peaks
            metrics["mem_peak_per_node_gb"] = round(max(per_node_mem_peak.values()) / (1024 * 1024), 3)

        # CPU metrics
        if all_cpu_user and all_cpu_system:
            all_cpu_total = [u + s for u, s in zip(all_cpu_user, all_cpu_system)]
            metrics["cpu_avg_pct"] = round(sum(all_cpu_total) / len(all_cpu_total), 2)
            metrics["cpu_max_pct"] = round(max(all_cpu_total), 2)

        # CPU imbalance (difference between most and least utilized cores)
        if per_core_max_cpu:
            max_core_cpu = max(per_core_max_cpu.values())
            min_core_cpu = min(per_core_max_cpu.values())
            metrics["cpu_imbalance_pct"] = round(max_core_cpu - min_core_cpu, 2)

        # Trace duration
        if len(timestamps) >= 2:
            metrics["trace_duration_s"] = round(max(timestamps) - min(timestamps), 2)
        else:
            metrics["trace_duration_s"] = 0

        return metrics

    def _aggregate_resource_traces(self, completed_tests: List) -> None:
        """
        Aggregate resource traces from all completed executions into a summary CSV.

        Creates __iops_resource_summary.csv in the run root directory with one row
        per execution+repetition, containing all user vars and aggregated resource metrics.

        This enables heatmap visualizations correlating variables with resource footprint.

        Args:
            completed_tests: List of completed ExecutionInstance objects
        """
        probes = self.cfg.benchmark.probes
        resource_sampling = probes.resource_sampling if probes else self.cfg.benchmark.trace_resources
        if not resource_sampling:
            return

        rows = []
        fieldnames = None

        # Group tests by execution_id to handle repetitions
        tests_by_exec = {}
        for test in completed_tests:
            exec_id = test.execution_id
            rep = test.repetition
            key = (exec_id, rep)
            tests_by_exec[key] = test

        for (exec_id, rep), test in sorted(tests_by_exec.items()):
            if test.execution_dir is None:
                self.logger.debug(f"Skipping exec_{exec_id} rep_{rep}: no execution_dir")
                continue

            # Find trace files for this execution
            trace_pattern = str(test.execution_dir / f"{TRACE_FILENAME_PREFIX}*.csv")
            trace_files = [Path(f) for f in glob.glob(trace_pattern)]

            if not trace_files:
                self.logger.debug(f"No trace files found for exec_{exec_id} rep_{rep}")
                continue

            try:
                # Compute metrics from trace files
                metrics = self._compute_trace_metrics(trace_files)

                # Build row with all vars + metrics
                row = {
                    "execution_id": f"exec_{exec_id:04d}",
                    "repetition": rep,
                }

                # Add all user vars (filter out internal keys)
                for k, v in test.vars.items():
                    if not k.startswith("__"):
                        row[k] = v

                # Add computed metrics
                row.update(metrics)

                rows.append(row)

                # Capture fieldnames from first row
                if fieldnames is None:
                    fieldnames = list(row.keys())

            except Exception as e:
                self.logger.warning(f"Failed to aggregate traces for exec_{exec_id} rep_{rep}: {e}")
                continue

        if not rows:
            self.logger.info("No resource traces to aggregate")
            return

        # Write summary CSV
        summary_path = Path(self.cfg.benchmark.workdir) / RESOURCE_SUMMARY_FILENAME
        try:
            with open(summary_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            self.logger.info(f"Resource trace summary: {summary_path} ({len(rows)} rows)")

        except Exception as e:
            self.logger.warning(f"Failed to write resource summary: {e}")

    def _signal_handler(self, signum, frame):
        """Handle Ctrl+C (SIGINT) to cancel all submitted SLURM jobs."""
        if self.interrupted:
            # Second Ctrl+C - force exit
            self.logger.warning("\nForce exit - some jobs may still be running")
            sys.exit(1)

        self.interrupted = True
        self.logger.info("\n" + "=" * 70)
        self.logger.info("INTERRUPT RECEIVED (Ctrl+C)")
        self.logger.info("=" * 70)

        # Show progress summary
        progress = self.planner.get_progress()
        self.logger.info(f"Progress: {progress['completed']}/{progress['total']} tests ({progress['percentage']:.1f}%)")

        if self.accumulated_core_hours > 0 or self.saved_core_hours > 0:
            self.logger.info(f"Core-hours used: {self.accumulated_core_hours:.2f}")
            if self.saved_core_hours > 0:
                self.logger.info(f"Core-hours saved by cache: {self.saved_core_hours:.2f}")
            if self.max_core_hours:
                remaining = self.max_core_hours - self.accumulated_core_hours
                self.logger.info(f"Budget remaining: {remaining:.2f}/{self.max_core_hours:.2f} core-hours")

        if hasattr(self, 'benchmark_start_time') and self.benchmark_start_time:
            elapsed = datetime.now() - self.benchmark_start_time
            self.logger.info(f"Elapsed time: {elapsed}")

        self.logger.info("-" * 70)

        if not self.submitted_job_ids:
            self.logger.info("No SLURM jobs to cancel")
            self.logger.info("Exiting...")
            sys.exit(0)

        self.logger.info(f"Canceling {len(self.submitted_job_ids)} submitted SLURM job(s)...")

        # Cancel all submitted jobs
        failed_cancellations = []
        # Get cancel command template from executor (handles command wrappers)
        cancel_cmd_template = getattr(self.executor, 'cmd_cancel', 'scancel {job_id}')

        for job_id in self.submitted_job_ids:
            try:
                self.logger.info(f"  Canceling job {job_id}...")
                # Format the command template with job_id
                cmd_str = cancel_cmd_template.format(job_id=job_id)
                cmd = shlex.split(cmd_str)
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    self.logger.info(f"  ✓ Job {job_id} canceled")
                else:
                    # Job may have already completed, which is fine
                    if "Invalid job id specified" in result.stderr:
                        self.logger.debug(f"  Job {job_id} already completed or not found")
                    else:
                        self.logger.warning(f"  Failed to cancel job {job_id}: {result.stderr.strip()}")
                        failed_cancellations.append(job_id)

            except subprocess.TimeoutExpired:
                self.logger.warning(f"  Timeout canceling job {job_id}")
                failed_cancellations.append(job_id)
            except Exception as e:
                self.logger.warning(f"  Error canceling job {job_id}: {e}")
                failed_cancellations.append(job_id)

        if failed_cancellations:
            self.logger.warning(
                f"\nFailed to cancel {len(failed_cancellations)} job(s): {', '.join(failed_cancellations)}"
            )
            # Show template with placeholder for manual reference
            manual_cmd = cancel_cmd_template.replace('{job_id}', '<job_id>')
            self.logger.warning(f"You may need to cancel them manually with: {manual_cmd}")
        else:
            self.logger.info(f"\n✓ All {len(self.submitted_job_ids)} job(s) canceled successfully")

        self.logger.info("=" * 70)
        self.logger.info("Cleanup complete - Exiting")
        sys.exit(0)

    def register_slurm_job(self, job_id: str):
        """Register a submitted SLURM job ID for cleanup on interrupt."""
        self.submitted_job_ids.add(job_id)
        self.logger.debug(f"  [JobTracker] Registered SLURM job {job_id} (total tracked: {len(self.submitted_job_ids)})")

    def _validate_cached_metrics(self, cached_metrics: dict) -> bool:
        """
        Validate that cached metrics contain all expected metrics.

        Args:
            cached_metrics: Metrics from cache

        Returns:
            True if all expected metrics are present, False otherwise
        """
        if not self.expected_metrics:
            # No expected metrics defined, accept cache
            return True

        cached_metric_names = set(cached_metrics.keys())
        missing_metrics = self.expected_metrics - cached_metric_names

        if missing_metrics:
            self.logger.warning(
                f"  [Cache] INVALID: Cached result missing metrics: {sorted(missing_metrics)}. "
                f"Will re-execute to collect all metrics."
            )
            return False

        return True

    def _compute_cores(self, test) -> int:
        """Compute the number of cores for a test using cores_expr."""
        try:
            cores_str = self.cores_template.render(**test.vars)
            cores = int(eval(cores_str))
            return max(1, cores)  # Ensure at least 1 core
        except Exception as e:
            self.logger.warning(f"Failed to compute cores for test {test.execution_id}: {e}. Defaulting to 1.")
            return 1

    def _compute_core_hours(self, test) -> float:
        """
        Compute core-hours used by a test.

        Prefers duration_seconds from sysinfo (actual script execution time on compute node)
        over __job_start/__end timestamps. Falls back to __submission_time/__end if
        __job_start is not available (e.g., SLURM polling missed the transition).
        """
        duration_seconds = None

        # Try to get actual execution time from sysinfo (preferred - accurate execution time)
        sysinfo = test.metadata.get("__sysinfo")
        if sysinfo and "duration_seconds" in sysinfo:
            try:
                duration_seconds = float(sysinfo["duration_seconds"])
                self.logger.debug(
                    f"Using sysinfo duration_seconds ({duration_seconds:.1f}s) for test {test.execution_id}"
                )
            except (ValueError, TypeError):
                self.logger.debug(
                    f"Invalid sysinfo duration_seconds for test {test.execution_id}, falling back to timestamps"
                )

        # Fall back to __job_start/__end timestamps (actual job execution time)
        # If __job_start not available, fall back to __submission_time (includes queue wait)
        if duration_seconds is None:
            # Prefer __job_start (actual execution start) over __submission_time (includes queue wait)
            start = test.metadata.get("__job_start") or test.metadata.get("__submission_time")
            end = test.metadata.get("__end")

            if not start or not end:
                self.logger.debug(f"Missing timing info for test {test.execution_id}, cannot compute core-hours")
                return 0.0

            try:
                # Parse timestamps
                if isinstance(start, str):
                    start = datetime.fromisoformat(start)
                if isinstance(end, str):
                    end = datetime.fromisoformat(end)

                duration_seconds = (end - start).total_seconds()
                source = "__job_start" if test.metadata.get("__job_start") else "__submission_time"
                self.logger.debug(
                    f"Using {source}/__end timestamps ({duration_seconds:.1f}s) for test {test.execution_id}"
                )
            except Exception as e:
                self.logger.warning(f"Failed to parse timestamps for test {test.execution_id}: {e}")
                return 0.0

        try:
            # Compute hours
            duration_hours = duration_seconds / 3600.0

            # Get cores
            cores = self._compute_cores(test)

            # Compute core-hours
            core_hours = cores * duration_hours

            return core_hours

        except Exception as e:
            self.logger.warning(f"Failed to compute core-hours for test {test.execution_id}: {e}")
            return 0.0

    def _write_status_file(self, test, status: str = None) -> None:
        """
        Write execution status to a JSON file in the repetition folder.

        Creates __iops_status.json containing the execution status,
        any error message, and completion timestamp. This enables the
        'iops find' command to display and filter by execution status.

        The status file is written to the repetition folder (e.g., exec_0001/repetition_001/)
        so each repetition has its own status.

        Args:
            test: ExecutionInstance with metadata
            status: Optional status override (e.g., "RUNNING" before execution starts)
        """
        if test.execution_dir is None:
            self.logger.debug("Cannot write status file: execution_dir is None")
            return

        # Write status to the execution_dir (which is the repetition folder)
        status_file = test.execution_dir / STATUS_FILENAME

        # Use provided status or get from metadata
        final_status = status if status else test.metadata.get("__executor_status", "UNKNOWN")

        # Get duration from sysinfo (stored in metadata for both executed and cached results)
        # For executed: comes from __iops_sysinfo.json file read by _store_system_info()
        # For cached: comes from cached metadata which includes __sysinfo
        duration = None
        sysinfo = test.metadata.get("__sysinfo")
        if sysinfo and "duration_seconds" in sysinfo:
            duration = sysinfo.get("duration_seconds")

        # Get metrics if available (only for completed executions)
        metrics = None
        if final_status in ("SUCCEEDED", "FAILED", "ERROR"):
            raw_metrics = test.metadata.get("metrics", {})
            # Only include metrics that have non-None values
            if raw_metrics:
                metrics = {k: v for k, v in raw_metrics.items() if v is not None}
                if not metrics:
                    metrics = None

        status_data = {
            "status": final_status,
            "error": test.metadata.get("__error"),
            "end_time": test.metadata.get("__end"),
            "cached": test.metadata.get("__cached", False),
            "duration_seconds": duration,
            "metrics": metrics,
            # Timing for queue wait calculation (SLURM)
            "submission_time": test.metadata.get("__submission_time"),
            "job_start": test.metadata.get("__job_start"),
        }

        try:
            with open(status_file, "w") as f:
                json.dump(status_data, f, indent=2, default=str)
            self.logger.debug(f"  [Status] Wrote status file: {status_file} (status={final_status})")
        except Exception as e:
            self.logger.warning(f"Failed to write status file {status_file}: {e}")

    def _make_progress_bar(self, percentage: float, width: int = 30) -> str:
        """
        Create a visual progress bar.

        Args:
            percentage: Completion percentage (0-100)
            width: Width of the progress bar in characters

        Returns:
            Progress bar string like "[==============>           ]"
        """
        filled = int(width * percentage / 100)
        bar = "=" * filled + ">" * (1 if filled < width else 0)
        bar = bar.ljust(width)
        return f"[{bar}]"

    def _get_planner_stats(self) -> Optional[Dict[str, Any]]:
        """Get search space statistics from the planner."""
        if not self.planner:
            return None

        stats = {}

        # Total search space size (available on RandomPlanner and BayesianPlanner)
        if hasattr(self.planner, 'total_space_size'):
            stats['total_space_size'] = self.planner.total_space_size

        # For RandomPlanner: sampled size
        if hasattr(self.planner, 'sampled_size'):
            stats['sampled_size'] = self.planner.sampled_size

        # For BayesianPlanner: n_iterations
        if hasattr(self.planner, 'n_iterations'):
            stats['n_iterations'] = self.planner.n_iterations

        return stats if stats else None

    def _save_run_metadata(self, test_count: int = 0, benchmark_start_time: Optional[datetime] = None, benchmark_end_time: Optional[datetime] = None, planner_stats: Optional[Dict[str, Any]] = None):
        """Save runtime metadata for report generation."""
        try:
            # Calculate timing metrics if provided
            timing_metadata = {}
            if benchmark_start_time and benchmark_end_time:
                total_runtime_seconds = (benchmark_end_time - benchmark_start_time).total_seconds()
                timing_metadata = {
                    "benchmark_start_time": benchmark_start_time.isoformat(),
                    "benchmark_end_time": benchmark_end_time.isoformat(),
                    "total_runtime_seconds": total_runtime_seconds,
                }

            # Try to get hostname (best effort - don't fail if unavailable)
            hostname = None
            try:
                hostname = socket.gethostname()
            except Exception:
                pass  # Hostname unavailable, continue without it

            # Build system environment from collected system info
            system_environment = self._aggregate_system_info()

            # Get relative output path (relative to workdir for portability)
            output_path = Path(self.actual_output_path or self.cfg.output.sink.path)
            workdir = Path(self.cfg.benchmark.workdir)
            try:
                relative_output_path = str(output_path.relative_to(workdir))
            except ValueError:
                # Output path is outside workdir, keep absolute
                relative_output_path = str(output_path)

            metadata = {
                "iops_version": _get_iops_version(),
                "benchmark": {
                    "name": self.cfg.benchmark.name,
                    "description": self.cfg.benchmark.description or "",
                    "executor": self.cfg.benchmark.executor,
                    "repetitions": self.cfg.benchmark.repetitions,
                    "random_seed": self.cfg.benchmark.random_seed,
                    "timestamp": datetime.now().isoformat(),
                    "test_count": test_count,
                    "report_vars": self.cfg.benchmark.report_vars,
                    "search_method": self.cfg.benchmark.search_method,
                    "bayesian_config": self.cfg.benchmark.bayesian_config,
                    "cores_expr": self.cfg.benchmark.cores_expr,
                    "max_core_hours": self.cfg.benchmark.max_core_hours,
                    "hostname": hostname,  # Add hostname if available (best effort)
                    "planner_stats": planner_stats,  # Search space statistics from planner
                    **timing_metadata,  # Add timing information if available
                },
                "system_environment": system_environment,  # Aggregated system info from compute nodes
                "variables": {},
                "metrics": [],
                "output": {
                    "type": self.cfg.output.sink.type,
                    "path": relative_output_path,  # Relative path for portability
                    "table": self.cfg.output.sink.table if self.cfg.output.sink.type == "sqlite" else None,
                },
                "command": {
                    "template": self.cfg.command.template,
                    "labels": self.cfg.command.labels or {},
                },
                "reporting": serialize_reporting_config(self.cfg.reporting),
            }

            # Add variable definitions
            for var_name, var_config in self.cfg.vars.items():
                var_info = {
                    "type": var_config.type,
                    "swept": var_config.sweep is not None,
                }
                if var_config.sweep:
                    var_info["sweep"] = {
                        "mode": var_config.sweep.mode,
                    }
                    if var_config.sweep.mode == "range":
                        var_info["sweep"]["start"] = var_config.sweep.start
                        var_info["sweep"]["end"] = var_config.sweep.end
                        var_info["sweep"]["step"] = var_config.sweep.step
                    elif var_config.sweep.mode == "list":
                        var_info["sweep"]["values"] = var_config.sweep.values
                if var_config.expr:
                    var_info["expr"] = var_config.expr

                metadata["variables"][var_name] = var_info

            # Add metric definitions from scripts
            for script in self.cfg.scripts:
                if script.parser and script.parser.metrics:
                    for metric in script.parser.metrics:
                        metadata["metrics"].append({
                            "name": metric.name,
                            "script": script.name,
                        })

            # Save to file with custom encoder for numpy types
            metadata_path = self.cfg.benchmark.workdir / METADATA_FILENAME
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2, default=self._json_serialize_helper)

            self.logger.debug(f"Saved runtime metadata to: {metadata_path}")

        except Exception as e:
            self.logger.warning(f"Failed to save runtime metadata: {e}")

    @staticmethod
    def _json_serialize_helper(obj):
        """Helper to serialize numpy/pandas types and dataclasses to JSON."""
        import dataclasses
        import numpy as np
        import pandas as pd

        # Handle dataclasses (like BayesianConfig, RandomSamplingConfig)
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)

        # Handle numpy types
        if isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        # Handle pandas types
        elif isinstance(obj, (pd.Int64Dtype, pd.Int32Dtype)):
            return int(obj)
        elif hasattr(obj, 'item'):  # numpy scalar
            return obj.item()
        elif hasattr(obj, 'tolist'):  # numpy array-like
            return obj.tolist()

        # Fall back to string representation
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    def _generate_report(self):
        """Generate HTML report after execution completes."""
        try:
            from iops.reporting.report_generator import ReportGenerator

            self.logger.info("=" * 70)
            self.logger.info("Generating HTML report...")
            self.logger.info("=" * 70)

            # Determine output path
            output_dir = self.cfg.reporting.output_dir or self.cfg.benchmark.workdir
            output_filename = self.cfg.reporting.output_filename
            output_path = Path(output_dir) / output_filename

            # Create report generator
            generator = ReportGenerator(
                workdir=self.cfg.benchmark.workdir,
                report_config=self.cfg.reporting
            )
            generator.load_metadata()
            generator.load_results()
            report_path = generator.generate_report(output_path=output_path)

            self.logger.info(f"✓ Report generated: {report_path}")
            self.logger.info("=" * 70)

        except Exception as e:
            self.logger.warning(f"Failed to generate report: {e}")
            self.logger.warning("You can manually generate the report later using:")
            self.logger.warning(f"  iops report {self.cfg.benchmark.workdir}")

    def _cleanup_remaining_jobs(self) -> None:
        """
        Cancel any remaining SLURM jobs at the end of a run.

        This is primarily needed for single-allocation mode where the allocation
        job stays alive (sleeping) until explicitly cancelled. It's also a safety
        measure to clean up any jobs that might still be tracked.
        """
        if not self.submitted_job_ids:
            return

        self.logger.info(f"Cleaning up {len(self.submitted_job_ids)} remaining SLURM job(s)...")

        # Get cancel command template from executor (handles command wrappers)
        cancel_cmd_template = getattr(self.executor, 'cmd_cancel', 'scancel {job_id}')

        for job_id in list(self.submitted_job_ids):
            try:
                cmd_str = cancel_cmd_template.format(job_id=job_id)
                cmd = shlex.split(cmd_str)
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    self.logger.debug(f"  Cancelled job {job_id}")
                else:
                    # Job may have already completed, which is fine
                    if "Invalid job id specified" in result.stderr:
                        self.logger.debug(f"  Job {job_id} already completed or not found")
                    else:
                        self.logger.warning(f"  Failed to cancel job {job_id}: {result.stderr.strip()}")

                self.submitted_job_ids.discard(job_id)

            except subprocess.TimeoutExpired:
                self.logger.warning(f"  Timeout cancelling job {job_id}")
            except Exception as e:
                self.logger.warning(f"  Error cancelling job {job_id}: {e}")

    def run_dry(self):
        """
        Dry-run mode: Preview execution plan without running tests.
        Generates all scripts and creates detailed analysis report.
        """
        self.logger.info("=" * 70)
        self.logger.info(f"DRY-RUN MODE: {self.cfg.benchmark.name}")
        self.logger.info("=" * 70)
        self.logger.info("")
        self.logger.info("This mode will:")
        self.logger.info("  ✓ Generate all execution scripts")
        self.logger.info("  ✓ Calculate core-hours estimates")
        self.logger.info("  ✓ Create analysis report")
        self.logger.info("  ✗ NOT execute any tests")
        self.logger.info("")

        # Report constraints if configured
        if self.cfg.constraints:
            self.logger.info("=" * 70)
            self.logger.info("CONSTRAINTS CONFIGURED:")
            self.logger.info("=" * 70)
            for constraint in self.cfg.constraints:
                self.logger.info(f"  • {constraint.name}")
                self.logger.info(f"    Rule: {constraint.rule}")
                self.logger.info(f"    Policy: {constraint.violation_policy}")
                if constraint.description:
                    self.logger.info(f"    Description: {constraint.description}")
                self.logger.info("")
            self.logger.info("Note: Invalid parameter combinations will be filtered during matrix generation.")
            self.logger.info("")

        # Generate all test scripts using the planner
        # Note: The planner reuses the same test object for each repetition,
        # so we capture (test_ref, repetition, vars_snapshot) at collection time
        self.logger.info("Generating execution scripts...")
        all_executions = []  # List of (test, repetition, vars_dict) tuples

        while True:
            test = self.planner.next_test()
            if test is None:
                break
            # Capture current state: repetition and vars snapshot
            # (test object will be reused with different repetition values)
            all_executions.append((test, test.repetition, dict(test.vars)))

        total_executions = len(all_executions)
        # Count unique tests (unique execution_ids)
        unique_test_ids = set(t.execution_id for t, _, _ in all_executions)
        num_unique_tests = len(unique_test_ids)
        repetitions = self.cfg.benchmark.repetitions

        self.logger.info(f"✓ Generated {total_executions} scripts ({num_unique_tests} tests × {repetitions} repetitions)")
        self.logger.info(f"  Output directory: {self.cfg.benchmark.workdir}")
        self.logger.info("")

        # Check cache for each execution if --use-cache is enabled
        # Store full cached results to access actual duration
        cached_results = {}  # Dict of (execution_id, repetition) -> cached_result
        if self.cache and self.use_cache_reads:
            self.logger.info("Checking cache for existing results...")
            for test, repetition, vars_snapshot in all_executions:
                cached_result = self.cache.get_cached_result(
                    params=vars_snapshot,
                    repetition=repetition,
                )
                if cached_result and self._validate_cached_metrics(cached_result['metrics']):
                    cached_results[(test.execution_id, repetition)] = cached_result

            cached_count = len(cached_results)
            # Count how many unique tests have all repetitions cached
            cached_test_ids = set(eid for eid, _ in cached_results.keys())
            fully_cached_tests = sum(
                1 for tid in unique_test_ids
                if all((tid, rep) in cached_results for rep in range(1, repetitions + 1))
            )
            self.logger.info(f"✓ Cache check complete:")
            self.logger.info(f"    {cached_count}/{total_executions} executions cached")
            self.logger.info(f"    {fully_cached_tests}/{num_unique_tests} tests fully cached (all {repetitions} repetitions)")
            self.logger.info("")

        # Compute cores and core-hours for each execution
        cores_list = []
        core_hours_list = []
        # Separate lists for executions that will actually run (not cached)
        exec_cores_list = []
        exec_core_hours_list = []
        # Track cached core-hours using actual durations
        cached_core_hours_list = []
        execution_details = []

        for test, repetition, vars_snapshot in all_executions:
            cores = self._compute_cores(test)
            cores_list.append(cores)
            cache_key = (test.execution_id, repetition)
            cached_result = cached_results.get(cache_key)
            is_cached = cached_result is not None

            # For cached executions, try to use actual duration from cache metadata
            if is_cached:
                # Extract duration from cached metadata (sysinfo or timestamps)
                cached_meta = cached_result.get('metadata', {})
                cached_sysinfo = cached_meta.get('__sysinfo', {})
                cached_duration = cached_sysinfo.get('duration_seconds')

                # Fall back to timestamps if sysinfo not available
                if cached_duration is None:
                    job_start = cached_meta.get('__job_start') or cached_meta.get('__submission_time')
                    end_time = cached_meta.get('__end')
                    if job_start and end_time:
                        try:
                            start_dt = datetime.fromisoformat(job_start.replace('Z', '+00:00')) if isinstance(job_start, str) else job_start
                            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00')) if isinstance(end_time, str) else end_time
                            cached_duration = (end_dt - start_dt).total_seconds()
                        except (ValueError, TypeError):
                            cached_duration = None

                if cached_duration is not None:
                    time_hours = cached_duration / 3600.0
                    core_hours = cores * time_hours
                    cached_core_hours_list.append(core_hours)
                    core_hours_list.append(core_hours)
                elif self.estimated_time_seconds:
                    # Fall back to estimate if no actual duration available
                    time_hours = self.estimated_time_seconds / 3600.0
                    core_hours = cores * time_hours
                    cached_core_hours_list.append(core_hours)
                    core_hours_list.append(core_hours)
            else:
                # Non-cached executions use estimated time
                if self.estimated_time_seconds:
                    time_hours = self.estimated_time_seconds / 3600.0
                    core_hours = cores * time_hours
                    core_hours_list.append(core_hours)
                    exec_core_hours_list.append(core_hours)
                exec_cores_list.append(cores)

            execution_details.append({
                'execution_id': test.execution_id,
                'repetition': repetition,
                'cores': cores,
                'vars': vars_snapshot,
                'cached': is_cached
            })

        # Statistics
        self.logger.info("\n" + "=" * 70)
        self.logger.info("EXECUTION PLAN SUMMARY")
        self.logger.info("=" * 70)

        # Basic counts
        self.logger.info(f"\nExecution Plan:")
        self.logger.info(f"  Unique tests: {num_unique_tests}")
        self.logger.info(f"  Repetitions per test: {repetitions}")
        self.logger.info(f"  Total executions: {total_executions}")

        # Cache summary (if cache checking was performed)
        if cached_results:
            cached_count = len(cached_results)
            to_execute_count = total_executions - cached_count
            cache_hit_rate = (cached_count / total_executions * 100) if total_executions > 0 else 0
            self.logger.info(f"\nCache Status (--use-cache enabled):")
            self.logger.info(f"  Cached executions (will skip): {cached_count} ({cache_hit_rate:.1f}%)")
            self.logger.info(f"  Executions to run: {to_execute_count}")

        # Cores statistics
        min_cores = min(cores_list)
        max_cores = max(cores_list)
        avg_cores = sum(cores_list) / len(cores_list)
        total_cores = sum(cores_list)

        self.logger.info(f"\nCore Configuration:")
        self.logger.info(f"  Cores expression: {self.cores_expr}")
        self.logger.info(f"  Min cores per execution: {min_cores}")
        self.logger.info(f"  Max cores per execution: {max_cores}")
        self.logger.info(f"  Avg cores per execution: {avg_cores:.1f}")

        # Core-hours estimation/calculation
        # We can report core-hours if we have either:
        # 1. An estimated time for non-cached tests, or
        # 2. Actual durations from cached tests
        has_core_hours_data = core_hours_list or cached_core_hours_list

        if has_core_hours_data:
            # If we have cached tests with actual durations, report on savings
            if cached_results and cached_core_hours_list:
                cached_total_core_hours = sum(cached_core_hours_list)
                self.logger.info(f"\nCache Savings (from {len(cached_results)} cached executions):")
                self.logger.info(f"  Core-hours saved: {cached_total_core_hours:.2f} (using actual recorded durations)")

            # Report on executions to run (only if we have an estimate)
            can_estimate_budget = False
            if self.estimated_time_seconds and exec_core_hours_list:
                exec_total_core_hours = sum(exec_core_hours_list)
                exec_count = len(exec_core_hours_list)
                exec_avg_core_hours = exec_total_core_hours / exec_count if exec_count > 0 else 0
                can_estimate_budget = True

                self.logger.info(f"\nEstimated Core-Hours (for {exec_count} executions to run):")
                self.logger.info(f"  Estimated time per execution: {self.estimated_time_seconds:.1f} seconds ({self.estimated_time_seconds/60:.1f} minutes)")
                self.logger.info(f"  Total core-hours: {exec_total_core_hours:.2f}")
            elif self.estimated_time_seconds and not cached_results:
                # No cache - all executions will run
                total_core_hours = sum(core_hours_list)
                min_core_hours = min(core_hours_list)
                max_core_hours = max(core_hours_list)
                avg_core_hours = total_core_hours / len(core_hours_list)
                can_estimate_budget = True

                self.logger.info(f"\nEstimated Core-Hours (all {total_executions} executions):")
                self.logger.info(f"  Estimated time per execution: {self.estimated_time_seconds:.1f} seconds ({self.estimated_time_seconds/60:.1f} minutes)")
                self.logger.info(f"  Min core-hours: {min_core_hours:.4f}")
                self.logger.info(f"  Max core-hours: {max_core_hours:.4f}")
                self.logger.info(f"  Avg core-hours: {avg_core_hours:.4f}")
                self.logger.info(f"  Total core-hours: {total_core_hours:.2f}")
                exec_total_core_hours = total_core_hours
                exec_count = total_executions
            elif len(cached_results) == total_executions:
                # All executions are cached
                exec_total_core_hours = 0
                exec_count = 0
                can_estimate_budget = True
                self.logger.info(f"\nAll {total_executions} executions are cached - nothing to run")
            else:
                # We have executions to run but no time estimate - can't calculate their core-hours
                exec_total_core_hours = None
                exec_count = total_executions - len(cached_results)
                can_estimate_budget = False

            # Estimated wall-clock time (assuming sequential execution)
            if self.estimated_time_seconds and exec_count > 0:
                exec_time_seconds = exec_count * self.estimated_time_seconds
                exec_time_hours = exec_time_seconds / 3600.0
                self.logger.info(f"\nEstimated Wall-Clock Time (sequential):")
                if cached_results:
                    self.logger.info(f"  Total (to run): {exec_time_hours:.2f} hours ({exec_time_hours/24:.2f} days)")
                else:
                    self.logger.info(f"  Total: {exec_time_hours:.2f} hours ({exec_time_hours/24:.2f} days)")

            # Budget comparison (use actual execution cost when cache is enabled)
            if self.max_core_hours:
                self.logger.info(f"\nBudget Analysis:")
                self.logger.info(f"  Budget limit: {self.max_core_hours:.2f} core-hours")

                if can_estimate_budget and exec_total_core_hours is not None:
                    budget_ratio = (exec_total_core_hours / self.max_core_hours) * 100
                    remaining = self.max_core_hours - exec_total_core_hours

                    if cached_results:
                        self.logger.info(f"  Estimated usage (with cache): {exec_total_core_hours:.2f} core-hours ({budget_ratio:.1f}%)")
                    else:
                        self.logger.info(f"  Estimated usage: {exec_total_core_hours:.2f} core-hours ({budget_ratio:.1f}%)")

                    if exec_total_core_hours > self.max_core_hours:
                        excess = exec_total_core_hours - self.max_core_hours
                        exec_avg = exec_total_core_hours / exec_count if exec_count > 0 else 0
                        executions_that_fit = int((self.max_core_hours / exec_avg)) if exec_avg > 0 else 0
                        self.logger.warning(f"  ⚠️  BUDGET EXCEEDED by {excess:.2f} core-hours!")
                        self.logger.warning(f"  ⚠️  Only ~{executions_that_fit} executions will complete before budget limit")
                    else:
                        self.logger.info(f"  ✓ Remaining budget: {remaining:.2f} core-hours")
                else:
                    # Can't estimate - have executions to run but no time estimate
                    self.logger.info(f"  ⚠️  Cannot estimate usage: {exec_count} executions to run but no --time-estimate provided")

        if not has_core_hours_data and not self.estimated_time_seconds:
            self.logger.info(f"\nCore-Hours Estimation:")
            self.logger.info(f"  ℹ️  No time estimate provided. Use --time-estimate <seconds> or set")
            self.logger.info(f"     benchmark.estimated_time_seconds in config for core-hours estimation.")

        # Multiple scenario analysis
        if len(self.estimated_time_scenarios) > 1:
            self.logger.info(f"\n" + "=" * 70)
            scenario_label = "SCENARIO ANALYSIS"
            if cached_results:
                scenario_label += " (excluding cached executions)"
            self.logger.info(f"{scenario_label} ({len(self.estimated_time_scenarios)} time estimates)")
            self.logger.info("=" * 70)

            # Use exec_cores_list if cache is enabled, otherwise use all cores
            scenario_cores = exec_cores_list if cached_results else cores_list
            scenario_exec_count = len(scenario_cores) if cached_results else total_executions

            scenario_results = []
            for time_est in self.estimated_time_scenarios:
                time_hours = time_est / 3600.0
                total_ch = sum([cores * time_hours for cores in scenario_cores]) if scenario_cores else 0
                total_time_hrs = (scenario_exec_count * time_est) / 3600.0

                scenario_results.append({
                    'time_seconds': time_est,
                    'total_core_hours': total_ch,
                    'total_time_hours': total_time_hrs,
                    'budget_ratio': (total_ch / self.max_core_hours * 100) if self.max_core_hours else None,
                    'executions_that_fit': int((self.max_core_hours / (total_ch/scenario_exec_count))) if self.max_core_hours and scenario_exec_count > 0 and total_ch > 0 else scenario_exec_count
                })

            self.logger.info(f"\n{'Time/Exec':<15} {'Core-Hours':<15} {'Wall-Clock':<15} {'Budget %':<12} {'Execs Fit':<12}")
            self.logger.info("-" * 70)
            for sc in scenario_results:
                time_str = f"{sc['time_seconds']:.0f}s ({sc['time_seconds']/60:.1f}m)"
                ch_str = f"{sc['total_core_hours']:.2f}"
                wall_str = f"{sc['total_time_hours']:.2f}h"
                budget_str = f"{sc['budget_ratio']:.1f}%" if sc['budget_ratio'] else "N/A"
                fit_str = f"{sc['executions_that_fit']}/{scenario_exec_count}"

                self.logger.info(f"{time_str:<15} {ch_str:<15} {wall_str:<15} {budget_str:<12} {fit_str:<12}")

        # Generate detailed report file
        report_path = self.cfg.benchmark.workdir / "dry-run-report.txt"
        self.logger.info(f"\n" + "=" * 70)
        self.logger.info("GENERATING REPORT")
        self.logger.info("=" * 70)

        with open(report_path, "w") as f:
            f.write("=" * 70 + "\n")
            f.write(f"IOPS DRY-RUN ANALYSIS REPORT\n")
            f.write(f"Benchmark: {self.cfg.benchmark.name}\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 70 + "\n\n")

            # Execution Summary
            f.write("EXECUTION SUMMARY\n")
            f.write("-" * 70 + "\n")
            f.write(f"Unique tests: {num_unique_tests}\n")
            f.write(f"Repetitions per test: {repetitions}\n")
            f.write(f"Total executions: {total_executions}\n")
            if cached_results:
                executions_to_run = total_executions - len(cached_results)
                f.write(f"Cached executions (will skip): {len(cached_results)}\n")
                if executions_to_run > 0:
                    f.write(f"Executions to run: {executions_to_run}\n")
                else:
                    f.write(f"All executions cached - nothing to run\n")
            f.write(f"Scripts location: {self.cfg.benchmark.workdir}\n")
            f.write(f"Executor: {self.cfg.benchmark.executor}\n")
            f.write("\n")

            # Core Configuration
            f.write("CORE CONFIGURATION\n")
            f.write("-" * 70 + "\n")
            f.write(f"Cores expression: {self.cores_expr}\n")
            f.write(f"Min cores per execution: {min_cores}\n")
            f.write(f"Max cores per execution: {max_cores}\n")
            f.write(f"Avg cores per execution: {avg_cores:.1f}\n")
            f.write("\n")

            # Cache Savings (if cache is enabled and has actual durations)
            if cached_results and cached_core_hours_list:
                f.write("CACHE SAVINGS\n")
                f.write("-" * 70 + "\n")
                cached_total_core_hours = sum(cached_core_hours_list)
                f.write(f"Cached executions: {len(cached_results)}\n")
                f.write(f"Core-hours saved: {cached_total_core_hours:.2f} (using actual recorded durations)\n")
                f.write("\n")

            # Scenario Analysis (uses cache-aware values if --use-cache is enabled)
            if self.estimated_time_scenarios:
                f.write("SCENARIO ANALYSIS")
                if cached_results:
                    f.write(" (excluding cached executions)")
                f.write("\n")
                f.write("-" * 70 + "\n")

                # Use cache-aware lists
                report_cores = exec_cores_list if cached_results else cores_list
                report_exec_count = len(report_cores) if cached_results else total_executions

                for i, time_est in enumerate(self.estimated_time_scenarios, 1):
                    time_hours = time_est / 3600.0
                    total_ch = sum([cores * time_hours for cores in report_cores]) if report_cores else 0
                    total_time_hrs = (report_exec_count * time_est) / 3600.0

                    f.write(f"\nScenario {i}: {time_est:.0f} seconds ({time_est/60:.1f} minutes) per execution\n")
                    f.write(f"  Executions to run: {report_exec_count}\n")
                    f.write(f"  Total core-hours: {total_ch:.2f}\n")
                    f.write(f"  Wall-clock time: {total_time_hrs:.2f} hours ({total_time_hrs/24:.2f} days)\n")

                    if self.max_core_hours:
                        budget_ratio = (total_ch / self.max_core_hours) * 100 if total_ch > 0 else 0
                        f.write(f"  Budget usage: {budget_ratio:.1f}%\n")
                        if total_ch > self.max_core_hours:
                            excess = total_ch - self.max_core_hours
                            execs_fit = int((self.max_core_hours / (total_ch/report_exec_count))) if report_exec_count > 0 and total_ch > 0 else 0
                            f.write(f"  ⚠️  EXCEEDS BUDGET by {excess:.2f} core-hours\n")
                            f.write(f"  ⚠️  Only ~{execs_fit} executions will complete\n")
                        else:
                            remaining = self.max_core_hours - total_ch
                            f.write(f"  ✓ Within budget (remaining: {remaining:.2f} core-hours)\n")
                f.write("\n")

        self.logger.info(f"✓ Report saved to: {report_path}")

        # Save runtime metadata for report generation
        self._save_run_metadata(test_count=total_executions, planner_stats=self._get_planner_stats())

        self.logger.info("\n" + "=" * 70)
        self.logger.info("DRY-RUN COMPLETE - Nothing was executed")
        self.logger.info(f"  • {num_unique_tests} unique tests × {repetitions} repetitions = {total_executions} executions")
        if cached_results:
            executions_to_run = total_executions - len(cached_results)
            self.logger.info(f"  • {len(cached_results)} executions cached (will be skipped with --use-cache)")
            if executions_to_run > 0:
                self.logger.info(f"  • {executions_to_run} executions to run")
            else:
                self.logger.info(f"  • All executions cached - nothing to run")
        self.logger.info(f"  • Report: {report_path}")
        self.logger.info(f"  • Metadata: {self.cfg.benchmark.workdir / METADATA_FILENAME}")
        self.logger.info("=" * 70)

    def run(self):
        # Record benchmark start time (class attribute for signal handler access)
        self.benchmark_start_time = datetime.now()

        self.logger.info("=" * 70)
        self.logger.info(f"Starting IOPS Runner: {self.cfg.benchmark.name}")
        self.logger.info(f"Benchmark start time: {self.benchmark_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info("=" * 70)

        test_count = 0

        while True:
            # Check budget before scheduling next test
            if self.max_core_hours is not None and self.accumulated_core_hours >= self.max_core_hours:
                self.budget_exceeded = True
                self.logger.warning("=" * 70)
                self.logger.warning(f"Budget limit reached: {self.accumulated_core_hours:.2f} / {self.max_core_hours:.2f} core-hours")
                self.logger.warning("Stopping execution of further tests.")
                self.logger.warning("=" * 70)
                break

            test = self.planner.next_test()
            if test is None:
                break

            test_count += 1

            # Log test start
            self.logger.debug(
                f"[Test {test_count:3d}] Starting: exec_id={test.execution_id} "
                f"rep={test.repetition}/{test.repetitions}"
            )

            # Check cache if reads are enabled
            used_cache = False
            if self.cache and self.use_cache_reads:
                cached_result = self.cache.get_cached_result(
                    params=test.vars,
                    repetition=test.repetition,
                )

                if cached_result:
                    # Validate that cached metrics contain all expected metrics
                    if not self._validate_cached_metrics(cached_result['metrics']):
                        # Cached result is incomplete, treat as cache miss
                        self.cache_misses += 1
                        self.logger.debug(f"  [Cache] MISS: Cached result missing required metrics")
                        cached_result = None  # Will trigger execution below
                    else:
                        # Use cached result
                        self.cache_hits += 1
                        used_cache = True

                        # Populate test with cached data
                        test.metadata.update(cached_result['metadata'])
                        test.metadata['metrics'] = cached_result['metrics']
                        test.metadata['__cached'] = True
                        test.metadata['__cached_at'] = cached_result['cached_at']

                        metrics_preview = ", ".join(list(cached_result['metrics'].keys())[:3])
                        if len(cached_result['metrics']) > 3:
                            metrics_preview += f" (+{len(cached_result['metrics'])-3} more)"

                        self.logger.debug(
                            f"  [Cache] HIT: Loaded from cache (cached_at={cached_result['cached_at']}) "
                            f"metrics=[{metrics_preview}]"
                        )
                else:
                    self.cache_misses += 1
                    self.logger.debug(f"  [Cache] MISS: Will execute and cache result")

            # Execute if not using cache
            if not used_cache:
                # In cache-only mode, skip execution for tests not in cache
                if self.cache_only:
                    self.skipped_cache_only += 1
                    test.metadata['__executor_status'] = 'SKIPPED'
                    test.metadata['__skip_reason'] = 'Not in cache (cache-only mode)'
                    self.logger.info(
                        f"[{test_count:3d}] {test.execution_id} (rep {test.repetition}/{test.repetitions}) "
                        f"-> SKIPPED (not in cache)"
                    )
                    probes = self.cfg.benchmark.probes
                    execution_index = probes.execution_index if probes else self.cfg.benchmark.track_executions
                    if execution_index:
                        self._write_status_file(test, status='SKIPPED')
                    # Still notify planner so it can aggregate available repetitions
                    self.planner.record_completed_test(test)
                    continue

                # Write initial status before execution starts
                # Local executor: RUNNING (runs immediately)
                # SLURM executor: PENDING (job goes to queue first)
                probes = self.cfg.benchmark.probes
                execution_index = probes.execution_index if probes else self.cfg.benchmark.track_executions
                if execution_index:
                    self._write_status_file(test, status=self.executor.INITIAL_STATUS)

                self.executor.submit(test)
                self.executor.wait_and_collect(test)

                # Store in cache if configured and execution succeeded
                if self.cache and test.metadata.get("__executor_status") == self.executor.STATUS_SUCCEEDED:
                    self.cache.store_result(
                        params=test.vars,
                        repetition=test.repetition,
                        metrics=test.metadata.get('metrics', {}),
                        metadata={
                            k: v for k, v in test.metadata.items()
                            if k not in ['metrics']  # Don't duplicate metrics
                        },
                    )

            # Write status file for 'iops find' command (for both executed and cached results)
            # Can be disabled with probes.execution_index: false to reduce file I/O
            probes = self.cfg.benchmark.probes
            execution_index = probes.execution_index if probes else self.cfg.benchmark.track_executions
            if execution_index:
                self._write_status_file(test)

            # Log test summary (clean single-line output at INFO level)
            status = test.metadata.get("__executor_status", "UNKNOWN")
            cache_marker = "[CACHED]" if used_cache else "[EXECUTED]"

            # Full execution details at DEBUG level
            self.logger.debug(
                f"  [Result] Status={status} cached={used_cache} "
                f"metrics_count={len(test.metadata.get('metrics', {}))}"
            )

            if self.args.log_level.upper() == 'DEBUG' and not used_cache:
                # Detailed execution info for executed tests only (cached tests don't have new execution details)
                self.logger.debug("-" * 80)
                self.logger.debug(test.describe())
                self.logger.debug("-" * 80)

            if self.args.log_level.upper() != 'DEBUG':
                # Clean single-line output for INFO
                metrics_str = ""
                if test.metadata.get('metrics'):
                    metrics = test.metadata['metrics']
                    # Show first 3 metrics as preview
                    metrics_preview = ", ".join([f"{k}={v}" for k, v in list(metrics.items())[:3]])
                    if len(metrics) > 3:
                        metrics_preview += f", ... ({len(metrics)} total)"
                    metrics_str = f" | {metrics_preview}"

                self.logger.info(
                    f"[{test_count:3d}] {test.execution_id} (rep {test.repetition}/{test.repetitions}) "
                    f"→ {status} {cache_marker}{metrics_str}"
                )

            # Check for fail-fast mode
            if getattr(self.args, 'fail_fast', False) and status in ("FAILED", "ERROR"):
                self.logger.error("=" * 70)
                self.logger.error(f"Test failed and --fail-fast is enabled. Stopping execution.")
                self.logger.error("=" * 70)
                # Still save this test before breaking
                save_test_execution(test)
                self._track_system_info(test)
                self.planner.record_completed_test(test)
                self.completed_tests.append(test)
                break

            # Add test to output file
            save_test_execution(test)

            # Track system info from compute node (if collected)
            self._track_system_info(test)

            # Track actual output path from first test (for final summary)
            if self.actual_output_path is None:
                self.actual_output_path = getattr(test, "output_path", None)

            # Record completed test (used by Bayesian planner for optimization)
            self.planner.record_completed_test(test)

            # Track completed tests for resource trace aggregation
            self.completed_tests.append(test)

            # Track core-hours (always, for reporting even without budget)
            core_hours_used = self._compute_core_hours(test)
            if used_cache:
                self.saved_core_hours += core_hours_used
            else:
                self.accumulated_core_hours += core_hours_used

            # Display progress and budget information periodically
            progress = self.planner.get_progress()
            show_progress = (
                test_count % 10 == 0 or  # Every 10 tests
                progress['percentage'] in [25, 50, 75] or  # At milestone percentages
                progress['remaining'] == 0  # Last test
            )

            if show_progress and progress['total'] > 0:
                progress_bar = self._make_progress_bar(progress['percentage'])
                self.logger.info("-" * 70)
                self.logger.info(f"Progress: {progress_bar} {progress['percentage']:.1f}%")
                self.logger.info(f"  Completed: {progress['completed']}/{progress['total']} tests ({progress['remaining']} remaining)")

                # Show core-hour usage (with budget info if configured)
                if self.max_core_hours is not None:
                    used_pct = (self.accumulated_core_hours / self.max_core_hours * 100) if self.max_core_hours > 0 else 0
                    remaining_budget = self.max_core_hours - self.accumulated_core_hours
                    saved_str = f", {self.saved_core_hours:.2f} saved by cache" if self.saved_core_hours > 0 else ""
                    self.logger.info(f"  Core-hours: {self.accumulated_core_hours:.2f}/{self.max_core_hours:.2f} ({used_pct:.1f}% used, {remaining_budget:.2f} remaining{saved_str})")
                else:
                    # Show core-hours without budget
                    saved_str = f", {self.saved_core_hours:.2f} saved by cache" if self.saved_core_hours > 0 else ""
                    self.logger.info(f"  Core-hours: {self.accumulated_core_hours:.2f}{saved_str}")

                self.logger.info("-" * 70)

        # Final statistics
        self.logger.info("=" * 70)

        if self.budget_exceeded:
            self.logger.info(f"Benchmark stopped: {test_count} tests completed (budget limit reached)")
        elif self.cache_only and self.skipped_cache_only > 0:
            self.logger.info(f"Benchmark completed (cache-only mode): {test_count} tests processed")
            self.logger.info(f"  From cache: {self.cache_hits}")
            self.logger.info(f"  Skipped (not in cache): {self.skipped_cache_only}")
        else:
            self.logger.info(f"Benchmark completed: {test_count} tests total")

        # Core-hours statistics (always show if any core-hours tracked)
        if self.accumulated_core_hours > 0 or self.saved_core_hours > 0:
            if self.max_core_hours is not None:
                utilization = (self.accumulated_core_hours / self.max_core_hours * 100) if self.max_core_hours > 0 else 0
                status_msg = "EXCEEDED" if self.budget_exceeded else "OK"
                self.logger.info(
                    f"Budget: {self.accumulated_core_hours:.2f} / {self.max_core_hours:.2f} core-hours "
                    f"({utilization:.1f}% utilized) [{status_msg}]"
                )
            else:
                self.logger.info(f"Core-hours: {self.accumulated_core_hours:.2f}")
            if self.saved_core_hours > 0:
                self.logger.info(f"Cache savings: {self.saved_core_hours:.2f} core-hours saved by cache hits")

        if self.cache and self.use_cache_reads:
            hit_rate = (self.cache_hits / test_count * 100) if test_count > 0 else 0
            cache_stats = f"Cache statistics: {self.cache_hits} hits, {self.cache_misses} misses ({hit_rate:.1f}% hit rate)"
            if self.skipped_cache_only > 0:
                cache_stats += f", {self.skipped_cache_only} skipped (cache-only mode)"
            self.logger.info(cache_stats)
        elif self.cache:
            self.logger.info(f"Cache: {test_count} results written to database")

        # Render output path if it's a template
        output_path_display = self.actual_output_path
        if output_path_display is None:
            # Fallback: render the template manually
            try:
                template = Template(str(self.cfg.output.sink.path))
                output_path_display = template.render(workdir=str(self.cfg.benchmark.workdir))
            except Exception:
                output_path_display = self.cfg.output.sink.path

        self.logger.info(f"Results saved to: {output_path_display}")
        self.logger.info("=" * 70)

        # Record benchmark end time and calculate timing metrics
        benchmark_end_time = datetime.now()
        total_runtime = (benchmark_end_time - self.benchmark_start_time).total_seconds()

        # Format runtime for display
        if total_runtime < 60:
            runtime_str = f"{total_runtime:.1f}s"
        elif total_runtime < 3600:
            runtime_str = f"{total_runtime/60:.1f}m ({total_runtime:.1f}s)"
        else:
            runtime_str = f"{total_runtime/3600:.2f}h ({total_runtime/60:.1f}m)"

        # Log timing summary
        self.logger.info("=" * 70)
        self.logger.info("BENCHMARK TIMING SUMMARY")
        self.logger.info("=" * 70)
        self.logger.info(f"Start time:    {self.benchmark_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"End time:      {benchmark_end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"Total runtime: {runtime_str}")
        self.logger.info("=" * 70)

        # Save runtime metadata for report generation
        self._save_run_metadata(
            test_count=test_count,
            benchmark_start_time=self.benchmark_start_time,
            benchmark_end_time=benchmark_end_time,
            planner_stats=self._get_planner_stats()
        )

        # Aggregate resource traces if enabled
        self._aggregate_resource_traces(self.completed_tests)

        # Save report config template for easy regeneration
        save_report_config_template(self.cfg, logger=self.logger)

        # Auto-generate report if enabled
        if self.cfg.reporting and self.cfg.reporting.enabled:
            self._generate_report()

        # Cleanup: Cancel any remaining SLURM allocations (e.g., single-allocation mode)
        self._cleanup_remaining_jobs()
