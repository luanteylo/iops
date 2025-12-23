
from iops.logger import HasLogger
from iops.execution.planner import BasePlanner
from iops.execution.executors import BaseExecutor
from iops.execution.cache import ExecutionCache
from iops.config.models import GenericBenchmarkConfig
from iops.results.writer import save_test_execution

from typing import Optional, List, Set
from pathlib import Path
from jinja2 import Template
from datetime import datetime
import json
import signal
import sys
import subprocess
import shlex
import socket

class IOPSRunner(HasLogger):
    def __init__(self, cfg: GenericBenchmarkConfig, args):
        super().__init__()
        self.cfg = cfg
        self.args = args
        self.planner = BasePlanner.build(cfg=self.cfg)
        self.executor = BaseExecutor.build(cfg=self.cfg)

        # Pass runner reference to executor for job tracking (used by SLURM)
        self.executor.set_runner(self)

        # Initialize cache if sqlite_db is configured (always populate, use only with --use_cache)
        self.cache: Optional[ExecutionCache] = None
        self.use_cache_reads = args.use_cache  # Flag to control reading from cache

        if cfg.benchmark.sqlite_db:
            exclude_vars = cfg.benchmark.cache_exclude_vars or []
            self.cache = ExecutionCache(
                cfg.benchmark.sqlite_db,
                exclude_vars=exclude_vars
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
                "Cache requested (--use_cache) but benchmark.sqlite_db not configured. "
                "Cache disabled."
            )

        # Statistics
        self.cache_hits = 0
        self.cache_misses = 0

        # Track actual output path (rendered from template)
        self.actual_output_path: Optional[Path] = None

        # Budget tracking
        self.max_core_hours: Optional[float] = None
        self.accumulated_core_hours: float = 0.0
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
        self.estimated_time_scenarios: List[float] = []
        if hasattr(args, 'estimated_time') and args.estimated_time is not None and isinstance(args.estimated_time, str):
            # Parse comma-separated values: "120" or "60,120,300"
            try:
                self.estimated_time_scenarios = [float(x.strip()) for x in args.estimated_time.split(',')]
            except ValueError:
                self.logger.warning(f"Invalid --estimated-time format: {args.estimated_time}. Expected number or comma-separated numbers.")
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

        # Register signal handler for Ctrl+C (SIGINT) if using SLURM executor
        if cfg.benchmark.executor == "slurm":
            signal.signal(signal.SIGINT, self._signal_handler)

    def _get_expected_metrics(self) -> set:
        """Get set of expected metric names from configuration."""
        expected = set()
        for script in self.cfg.scripts:
            if script.parser and script.parser.metrics:
                for metric in script.parser.metrics:
                    expected.add(metric.name)
        return expected

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
        """Compute core-hours used by a test."""
        # Get execution time from metadata
        start = test.metadata.get("__start")
        end = test.metadata.get("__end")

        if not start or not end:
            self.logger.debug(f"Missing start/end times for test {test.execution_id}, cannot compute core-hours")
            return 0.0

        try:
            # Parse timestamps
            if isinstance(start, str):
                start = datetime.fromisoformat(start)
            if isinstance(end, str):
                end = datetime.fromisoformat(end)

            # Compute hours
            duration_seconds = (end - start).total_seconds()
            duration_hours = duration_seconds / 3600.0

            # Get cores
            cores = self._compute_cores(test)

            # Compute core-hours
            core_hours = cores * duration_hours

            return core_hours

        except Exception as e:
            self.logger.warning(f"Failed to compute core-hours for test {test.execution_id}: {e}")
            return 0.0

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

    def _save_run_metadata(self, test_count: int = 0, benchmark_start_time: Optional[datetime] = None, benchmark_end_time: Optional[datetime] = None):
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

            metadata = {
                "benchmark": {
                    "name": self.cfg.benchmark.name,
                    "description": self.cfg.benchmark.description or "",
                    "workdir": str(self.cfg.benchmark.workdir),
                    "executor": self.cfg.benchmark.executor,
                    "repetitions": self.cfg.benchmark.repetitions,
                    "timestamp": datetime.now().isoformat(),
                    "test_count": test_count,
                    "report_vars": self.cfg.benchmark.report_vars,
                    "search_method": self.cfg.benchmark.search_method,
                    "bayesian_config": self.cfg.benchmark.bayesian_config,
                    "cores_expr": self.cfg.benchmark.cores_expr,
                    "max_core_hours": self.cfg.benchmark.max_core_hours,
                    "hostname": hostname,  # Add hostname if available (best effort)
                    **timing_metadata,  # Add timing information if available
                },
                "variables": {},
                "metrics": [],
                "output": {
                    "type": self.cfg.output.sink.type,
                    "path": str(self.actual_output_path or self.cfg.output.sink.path),
                    "table": self.cfg.output.sink.table if self.cfg.output.sink.type == "sqlite" else None,
                },
                "command": {
                    "template": self.cfg.command.template,
                    "metadata": self.cfg.command.metadata or {},
                },
                "reporting": self._serialize_reporting_config(),
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
            metadata_path = self.cfg.benchmark.workdir / "run_metadata.json"
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2, default=self._json_serialize_helper)

            self.logger.debug(f"Saved runtime metadata to: {metadata_path}")

        except Exception as e:
            self.logger.warning(f"Failed to save runtime metadata: {e}")

    @staticmethod
    def _json_serialize_helper(obj):
        """Helper to serialize numpy/pandas types to JSON."""
        import numpy as np
        import pandas as pd

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

    def _serialize_reporting_config(self):
        """Serialize ReportingConfig to JSON-serializable dict."""
        if not self.cfg.reporting:
            return None

        def serialize_plot_config(plot_cfg):
            """Serialize a PlotConfig to dict."""
            return {
                "type": plot_cfg.type,
                "x_var": plot_cfg.x_var,
                "y_var": plot_cfg.y_var,
                "z_metric": plot_cfg.z_metric,
                "group_by": plot_cfg.group_by,
                "color_by": plot_cfg.color_by,
                "size_by": plot_cfg.size_by,
                "title": plot_cfg.title,
                "xaxis_label": plot_cfg.xaxis_label,
                "yaxis_label": plot_cfg.yaxis_label,
                "colorscale": plot_cfg.colorscale,
                "show_error_bars": plot_cfg.show_error_bars,
                "show_outliers": plot_cfg.show_outliers,
                "height": plot_cfg.height,
                "width": plot_cfg.width,
                "per_variable": plot_cfg.per_variable,
                "include_metric": plot_cfg.include_metric,
            }

        reporting = self.cfg.reporting
        return {
            "enabled": reporting.enabled,
            "output_dir": str(reporting.output_dir) if reporting.output_dir else None,
            "output_filename": reporting.output_filename,
            "theme": {
                "style": reporting.theme.style,
                "colors": reporting.theme.colors,
                "font_family": reporting.theme.font_family,
            },
            "sections": {
                "test_summary": reporting.sections.test_summary,
                "best_results": reporting.sections.best_results,
                "variable_impact": reporting.sections.variable_impact,
                "parallel_coordinates": reporting.sections.parallel_coordinates,
                "pareto_frontier": reporting.sections.pareto_frontier,
                "bayesian_evolution": reporting.sections.bayesian_evolution,
                "custom_plots": reporting.sections.custom_plots,
            },
            "best_results": {
                "top_n": reporting.best_results.top_n,
                "show_command": reporting.best_results.show_command,
            },
            "plot_defaults": {
                "height": reporting.plot_defaults.height,
                "width": reporting.plot_defaults.width,
                "margin": reporting.plot_defaults.margin,
            },
            "metrics": {
                metric_name: {
                    "plots": [serialize_plot_config(p) for p in metric_plots.plots]
                }
                for metric_name, metric_plots in reporting.metrics.items()
            },
            "default_plots": [serialize_plot_config(p) for p in reporting.default_plots],
        }

    def _save_report_config_template(self):
        """
        Save a report_config.yaml template to workdir for easy report regeneration.

        If user provided reporting config, saves a clean version they can expand.
        Otherwise, generates a smart template based on detected metrics and variables.
        """
        try:
            import yaml

            output_path = self.cfg.benchmark.workdir / "report_config.yaml"

            if self.cfg.reporting:
                # User provided config - create clean version they can expand
                config_dict = self._create_clean_report_config()
            else:
                # Generate smart template based on execution
                config_dict = self._generate_report_config_template()

            # Get swept variables and metrics for reference comments
            swept_vars = [name for name, var in self.cfg.vars.items() if var.sweep is not None]
            all_metrics = []
            for script in self.cfg.scripts:
                if script.parser and script.parser.metrics:
                    all_metrics.extend([m.name for m in script.parser.metrics])

            # Wrap in reporting section
            yaml_content = {"reporting": config_dict}

            with open(output_path, 'w') as f:
                # Add header comment
                f.write("# IOPS Report Configuration\n")
                f.write("# This file was auto-generated based on your benchmark execution.\n")
                f.write("# Edit and use with: iops --analyze <workdir> --report-config report_config.yaml\n")
                f.write("#\n")
                if self.cfg.reporting:
                    f.write("# This config is based on your provided reporting settings.\n")
                    f.write("# You can expand it by adding more plot types or customizing existing ones.\n")
                else:
                    f.write("# This config is a template based on your benchmark metrics and variables.\n")
                    f.write("# Customize the plots and settings, then set enabled: true to auto-generate reports.\n")
                f.write("#\n")
                f.write("# Documentation: https://lgouveia.gitlabpages.inria.fr/iops/user-guide/reporting/\n")
                f.write("#\n")

                # Add reference section for available variables and metrics
                f.write("# ============================================================================\n")
                f.write("# AVAILABLE VARIABLES AND METRICS (for use in plot configurations)\n")
                f.write("# ============================================================================\n")
                f.write("#\n")

                if swept_vars:
                    f.write("# Swept Variables (use for x_var, y_var, group_by, color_by):\n")
                    for var in swept_vars:
                        var_type = self.cfg.vars[var].type
                        f.write(f"#   - {var} ({var_type})\n")
                    f.write("#\n")
                else:
                    f.write("# No swept variables detected\n")
                    f.write("#\n")

                if all_metrics:
                    f.write("# Metrics (use for configuring plots):\n")
                    for metric in all_metrics:
                        f.write(f"#   - {metric}\n")
                    f.write("#\n")
                else:
                    f.write("# No metrics detected\n")
                    f.write("#\n")

                f.write("# Plot Types Available:\n")
                f.write("#   - bar, line, scatter, heatmap, box, violin, surface_3d, parallel_coordinates\n")
                f.write("#\n")
                f.write("# ============================================================================\n")
                f.write("\n")

                yaml.dump(yaml_content, f, default_flow_style=False, sort_keys=False, indent=2)

            self.logger.info(f"Report config template saved: {output_path.relative_to(self.cfg.benchmark.workdir.parent)}")

        except Exception as e:
            self.logger.debug(f"Failed to save report config template: {e}")

    def _create_clean_report_config(self):
        """
        Create a clean, editable version of the user's reporting config.
        Includes what they specified + suggestions for expansion based on execution.
        """
        reporting = self.cfg.reporting

        # Start with user's settings
        config = {
            "enabled": reporting.enabled,
            "output_filename": reporting.output_filename,
        }

        # Add output_dir only if specified
        if reporting.output_dir:
            config["output_dir"] = str(reporting.output_dir)

        # Theme (only include if non-default)
        if reporting.theme.style != "plotly_white" or reporting.theme.colors or reporting.theme.font_family != "Segoe UI, sans-serif":
            theme = {"style": reporting.theme.style}
            if reporting.theme.colors:
                theme["colors"] = reporting.theme.colors
            if reporting.theme.font_family != "Segoe UI, sans-serif":
                theme["font_family"] = reporting.theme.font_family
            config["theme"] = theme

        # Sections (only include if not all True)
        sections_dict = {
            "test_summary": reporting.sections.test_summary,
            "best_results": reporting.sections.best_results,
            "variable_impact": reporting.sections.variable_impact,
            "custom_plots": reporting.sections.custom_plots,
        }
        if not all(sections_dict.values()):
            config["sections"] = sections_dict

        # User's metric configs
        if reporting.metrics:
            metrics_config = {}
            for metric_name, metric_plots_config in reporting.metrics.items():
                plots = []
                for plot_cfg in metric_plots_config.plots:
                    plot_dict = {"type": plot_cfg.type}
                    if plot_cfg.x_var:
                        plot_dict["x_var"] = plot_cfg.x_var
                    if plot_cfg.y_var:
                        plot_dict["y_var"] = plot_cfg.y_var
                    if plot_cfg.group_by:
                        plot_dict["group_by"] = plot_cfg.group_by
                    if plot_cfg.title:
                        plot_dict["title"] = plot_cfg.title
                    if plot_cfg.colorscale != "Viridis":
                        plot_dict["colorscale"] = plot_cfg.colorscale
                    plots.append(plot_dict)
                metrics_config[metric_name] = {"plots": plots}
            config["metrics"] = metrics_config

        # Get metrics from execution to suggest expansions
        all_metrics = []
        for script in self.cfg.scripts:
            if script.parser and script.parser.metrics:
                all_metrics.extend([m.name for m in script.parser.metrics])

        # Add suggestions for metrics not yet configured
        unconfigured_metrics = [m for m in all_metrics if m not in reporting.metrics.keys()]
        if unconfigured_metrics:
            config["_suggestions"] = {
                "unconfigured_metrics": unconfigured_metrics,
                "hint": "Add plot configurations for these metrics to customize their visualizations"
            }

        # Default plots
        if reporting.default_plots:
            default_plots = []
            for plot_cfg in reporting.default_plots:
                plot_dict = {"type": plot_cfg.type}
                if plot_cfg.per_variable:
                    plot_dict["per_variable"] = plot_cfg.per_variable
                if plot_cfg.show_error_bars:
                    plot_dict["show_error_bars"] = plot_cfg.show_error_bars
                default_plots.append(plot_dict)
            config["default_plots"] = default_plots

        return config

    def _generate_report_config_template(self):
        """Generate a smart report config template based on execution."""
        # Get swept variables
        swept_vars = [name for name, var in self.cfg.vars.items() if var.sweep is not None]

        # Get metrics from scripts
        metrics = []
        for script in self.cfg.scripts:
            if script.parser and script.parser.metrics:
                metrics.extend([m.name for m in script.parser.metrics])

        # Build template
        template = {
            "enabled": False,  # User must opt-in
            "output_filename": "analysis_report.html",
            "theme": {
                "style": "plotly_white",
                "colors": ["#3498db", "#e74c3c", "#2ecc71"],
            },
            "sections": {
                "test_summary": True,
                "best_results": True,
                "variable_impact": True,
                "custom_plots": True,
            },
        }

        # Add metric-specific plot examples if we have metrics
        if metrics and swept_vars:
            template["metrics"] = {}

            # Add examples for first metric
            if metrics:
                first_metric = metrics[0]
                plots = []

                # Line plot if we have variables
                if len(swept_vars) >= 1:
                    line_plot = {
                        "type": "line",
                        "x_var": swept_vars[0],
                    }
                    if len(swept_vars) >= 2:
                        line_plot["group_by"] = swept_vars[1]
                    plots.append(line_plot)

                # Heatmap if we have 2+ variables
                if len(swept_vars) >= 2:
                    plots.append({
                        "type": "heatmap",
                        "x_var": swept_vars[0],
                        "y_var": swept_vars[1],
                    })

                template["metrics"][first_metric] = {"plots": plots}

            # Add comment about other metrics
            if len(metrics) > 1:
                template["_comment"] = f"Add plot configs for other metrics: {', '.join(metrics[1:])}"

        # Add default plots
        template["default_plots"] = [
            {
                "type": "bar",
                "per_variable": True,
                "show_error_bars": True,
            }
        ]

        return template

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
            self.logger.warning(f"  iops --analyze {self.cfg.benchmark.workdir}")

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
        self.logger.info("Generating execution scripts...")
        test_count = 0
        all_tests = []

        while True:
            test = self.planner.next_test()
            if test is None:
                break
            test_count += 1
            all_tests.append(test)

        total_tests = len(all_tests)
        self.logger.info(f"✓ Generated {total_tests} test scripts in: {self.cfg.benchmark.workdir}")
        self.logger.info("")

        # Compute cores and core-hours for each test
        cores_list = []
        core_hours_list = []
        test_details = []

        for test in all_tests:
            cores = self._compute_cores(test)
            cores_list.append(cores)

            if self.estimated_time_seconds:
                time_hours = self.estimated_time_seconds / 3600.0
                core_hours = cores * time_hours
                core_hours_list.append(core_hours)

            test_details.append({
                'execution_id': test.execution_id,
                'repetition': test.repetition,
                'round': test.round_name or 'single',
                'cores': cores,
                'vars': test.vars
            })

        # Statistics
        self.logger.info("\n" + "=" * 70)
        self.logger.info("EXECUTION PLAN SUMMARY")
        self.logger.info("=" * 70)

        # Cores statistics
        min_cores = min(cores_list)
        max_cores = max(cores_list)
        avg_cores = sum(cores_list) / len(cores_list)
        total_cores = sum(cores_list)

        self.logger.info(f"\nCore Configuration:")
        self.logger.info(f"  Cores expression: {self.cores_expr}")
        self.logger.info(f"  Min cores per test: {min_cores}")
        self.logger.info(f"  Max cores per test: {max_cores}")
        self.logger.info(f"  Avg cores per test: {avg_cores:.1f}")
        self.logger.info(f"  Total core-count: {total_cores} (sum across all tests)")

        # Core-hours estimation
        if self.estimated_time_seconds:
            total_core_hours = sum(core_hours_list)
            min_core_hours = min(core_hours_list)
            max_core_hours = max(core_hours_list)
            avg_core_hours = total_core_hours / len(core_hours_list)

            self.logger.info(f"\nEstimated Core-Hours:")
            self.logger.info(f"  Estimated time per test: {self.estimated_time_seconds:.1f} seconds ({self.estimated_time_seconds/60:.1f} minutes)")
            self.logger.info(f"  Min core-hours per test: {min_core_hours:.4f}")
            self.logger.info(f"  Max core-hours per test: {max_core_hours:.4f}")
            self.logger.info(f"  Avg core-hours per test: {avg_core_hours:.4f}")
            self.logger.info(f"  Total core-hours: {total_core_hours:.2f}")

            # Estimated wall-clock time (assuming sequential execution)
            total_time_seconds = total_tests * self.estimated_time_seconds
            total_time_hours = total_time_seconds / 3600.0
            self.logger.info(f"\nEstimated Wall-Clock Time (sequential):")
            self.logger.info(f"  Total: {total_time_hours:.2f} hours ({total_time_hours/24:.2f} days)")

            # Budget comparison
            if self.max_core_hours:
                budget_ratio = (total_core_hours / self.max_core_hours) * 100
                remaining = self.max_core_hours - total_core_hours

                self.logger.info(f"\nBudget Analysis:")
                self.logger.info(f"  Budget limit: {self.max_core_hours:.2f} core-hours")
                self.logger.info(f"  Estimated usage: {total_core_hours:.2f} core-hours ({budget_ratio:.1f}%)")

                if total_core_hours > self.max_core_hours:
                    excess = total_core_hours - self.max_core_hours
                    tests_that_fit = int((self.max_core_hours / avg_core_hours))
                    self.logger.warning(f"  ⚠️  BUDGET EXCEEDED by {excess:.2f} core-hours!")
                    self.logger.warning(f"  ⚠️  Only ~{tests_that_fit} tests will complete before budget limit")
                else:
                    self.logger.info(f"  ✓ Remaining budget: {remaining:.2f} core-hours")
        else:
            self.logger.info(f"\nCore-Hours Estimation:")
            self.logger.info(f"  ℹ️  No time estimate provided. Use --estimated-time <seconds> or set")
            self.logger.info(f"     benchmark.estimated_time_seconds in config for core-hours estimation.")

        # Show sample tests
        self.logger.info(f"\n" + "=" * 70)
        self.logger.info("SAMPLE TESTS (first 10)")
        self.logger.info("=" * 70)

        for i, detail in enumerate(test_details[:10]):
            vars_str = ", ".join([f"{k}={v}" for k, v in list(detail['vars'].items())[:5]])
            if len(detail['vars']) > 5:
                vars_str += f", ... ({len(detail['vars'])} total)"

            core_hours_str = ""
            if self.estimated_time_seconds:
                ch = detail['cores'] * (self.estimated_time_seconds / 3600.0)
                core_hours_str = f" | {ch:.4f} core-hrs"

            self.logger.info(
                f"  [{i+1:3d}] exec_id={detail['execution_id']} rep={detail['repetition']} "
                f"round={detail['round']} | {detail['cores']} cores{core_hours_str}"
            )
            self.logger.info(f"        {vars_str}")

        if total_tests > 10:
            self.logger.info(f"  ... ({total_tests - 10} more tests)")

        # Multiple scenario analysis
        if len(self.estimated_time_scenarios) > 1:
            self.logger.info(f"\n" + "=" * 70)
            self.logger.info(f"SCENARIO ANALYSIS ({len(self.estimated_time_scenarios)} time estimates)")
            self.logger.info("=" * 70)

            scenario_results = []
            for time_est in self.estimated_time_scenarios:
                time_hours = time_est / 3600.0
                total_ch = sum([cores * time_hours for cores in cores_list])
                total_time_hrs = (total_tests * time_est) / 3600.0

                scenario_results.append({
                    'time_seconds': time_est,
                    'total_core_hours': total_ch,
                    'total_time_hours': total_time_hrs,
                    'budget_ratio': (total_ch / self.max_core_hours * 100) if self.max_core_hours else None,
                    'tests_that_fit': int((self.max_core_hours / (total_ch/total_tests))) if self.max_core_hours else total_tests
                })

            self.logger.info(f"\n{'Time/Test':<15} {'Core-Hours':<15} {'Wall-Clock':<15} {'Budget %':<12} {'Tests Fit':<12}")
            self.logger.info("-" * 70)
            for sc in scenario_results:
                time_str = f"{sc['time_seconds']:.0f}s ({sc['time_seconds']/60:.1f}m)"
                ch_str = f"{sc['total_core_hours']:.2f}"
                wall_str = f"{sc['total_time_hours']:.2f}h"
                budget_str = f"{sc['budget_ratio']:.1f}%" if sc['budget_ratio'] else "N/A"
                fit_str = f"{sc['tests_that_fit']}/{total_tests}"

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
            f.write(f"Total tests: {total_tests}\n")
            f.write(f"Scripts location: {self.cfg.benchmark.workdir}\n")
            f.write(f"Executor: {self.cfg.benchmark.executor}\n")
            f.write(f"Repetitions: {self.cfg.benchmark.repetitions}\n")
            if self.cfg.rounds:
                f.write(f"Rounds: {len(self.cfg.rounds)} ({', '.join([r.name for r in self.cfg.rounds])})\n")
            f.write("\n")

            # Core Configuration
            f.write("CORE CONFIGURATION\n")
            f.write("-" * 70 + "\n")
            f.write(f"Cores expression: {self.cores_expr}\n")
            f.write(f"Min cores per test: {min_cores}\n")
            f.write(f"Max cores per test: {max_cores}\n")
            f.write(f"Avg cores per test: {avg_cores:.1f}\n")
            f.write(f"Total core-count: {total_cores}\n")
            f.write("\n")

            # Scenario Analysis
            if self.estimated_time_scenarios:
                f.write("SCENARIO ANALYSIS\n")
                f.write("-" * 70 + "\n")
                for i, time_est in enumerate(self.estimated_time_scenarios, 1):
                    time_hours = time_est / 3600.0
                    total_ch = sum([cores * time_hours for cores in cores_list])
                    total_time_hrs = (total_tests * time_est) / 3600.0

                    f.write(f"\nScenario {i}: {time_est:.0f} seconds ({time_est/60:.1f} minutes) per test\n")
                    f.write(f"  Total core-hours: {total_ch:.2f}\n")
                    f.write(f"  Wall-clock time: {total_time_hrs:.2f} hours ({total_time_hrs/24:.2f} days)\n")

                    if self.max_core_hours:
                        budget_ratio = (total_ch / self.max_core_hours) * 100
                        f.write(f"  Budget usage: {budget_ratio:.1f}%\n")
                        if total_ch > self.max_core_hours:
                            excess = total_ch - self.max_core_hours
                            tests_fit = int((self.max_core_hours / (total_ch/total_tests)))
                            f.write(f"  ⚠️  EXCEEDS BUDGET by {excess:.2f} core-hours\n")
                            f.write(f"  ⚠️  Only ~{tests_fit} tests will complete\n")
                        else:
                            remaining = self.max_core_hours - total_ch
                            f.write(f"  ✓ Within budget (remaining: {remaining:.2f} core-hours)\n")
                f.write("\n")

            # Test Details
            f.write("TEST DETAILS (all tests)\n")
            f.write("-" * 70 + "\n")
            for i, detail in enumerate(test_details, 1):
                vars_str = ", ".join([f"{k}={v}" for k, v in list(detail['vars'].items())[:5]])
                if len(detail['vars']) > 5:
                    vars_str += f", ... ({len(detail['vars'])} vars)"

                f.write(f"\n[{i:3d}] exec_id={detail['execution_id']} rep={detail['repetition']} ")
                f.write(f"round={detail['round']} cores={detail['cores']}\n")
                f.write(f"      {vars_str}\n")

        self.logger.info(f"✓ Report saved to: {report_path}")

        # Save runtime metadata for report generation
        self._save_run_metadata(test_count=total_tests)

        self.logger.info("\n" + "=" * 70)
        self.logger.info("DRY-RUN COMPLETE - No tests were executed")
        self.logger.info(f"  • {total_tests} scripts generated")
        self.logger.info(f"  • Report: {report_path}")
        self.logger.info(f"  • Metadata: {self.cfg.benchmark.workdir / 'run_metadata.json'}")
        self.logger.info("=" * 70)

    def run(self):
        # Record benchmark start time
        benchmark_start_time = datetime.now()

        self.logger.info("=" * 70)
        self.logger.info(f"Starting IOPS Runner: {self.cfg.benchmark.name}")
        self.logger.info(f"Benchmark start time: {benchmark_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info("=" * 70)

        test_count = 0

        while True:
            # Check budget before scheduling next test
            if self.max_core_hours is not None and self.accumulated_core_hours >= self.max_core_hours:
                self.budget_exceeded = True
                self.logger.warning("=" * 70)
                self.logger.warning(f"Budget limit reached: {self.accumulated_core_hours:.2f} / {self.max_core_hours:.2f} core-hours")
                self.logger.warning("Stopping execution (current tests will complete)")
                self.logger.warning("=" * 70)
                break

            test = self.planner.next_test()
            if test is None:
                break

            test_count += 1

            # Log test start
            round_info = f"round={test.round_name}" if test.round_name else "single-round"
            self.logger.debug(
                f"[Test {test_count:3d}] Starting: exec_id={test.execution_id} "
                f"rep={test.repetition}/{test.repetitions} {round_info}"
            )

            # Check cache if reads are enabled
            used_cache = False
            if self.cache and self.use_cache_reads:
                cached_result = self.cache.get_cached_result(
                    params=test.vars,
                    repetition=test.repetition,
                    round_name=test.round_name,
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
                        round_name=test.round_name,
                        round_index=test.round_index,
                    )

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

            # Add test to output file
            save_test_execution(test)

            # Track actual output path from first test (for final summary)
            if self.actual_output_path is None:
                self.actual_output_path = getattr(test, "output_path", None)

            # Record completed test for round-based search
            self.planner.record_completed_test(test)

            # Track core-hours budget if enabled
            if self.max_core_hours is not None and not used_cache:
                core_hours_used = self._compute_core_hours(test)
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

                # Show core-hour usage if enabled
                if self.max_core_hours is not None:
                    used_pct = (self.accumulated_core_hours / self.max_core_hours * 100) if self.max_core_hours > 0 else 0
                    remaining_budget = self.max_core_hours - self.accumulated_core_hours
                    self.logger.info(f"  Core-hours: {self.accumulated_core_hours:.2f}/{self.max_core_hours:.2f} ({used_pct:.1f}% used, {remaining_budget:.2f} remaining)")

                self.logger.info("-" * 70)

        # Final statistics
        self.logger.info("=" * 70)

        if self.budget_exceeded:
            self.logger.info(f"Benchmark stopped: {test_count} tests completed (budget limit reached)")
        else:
            self.logger.info(f"Benchmark completed: {test_count} tests total")

        # Budget statistics
        if self.max_core_hours is not None:
            utilization = (self.accumulated_core_hours / self.max_core_hours * 100) if self.max_core_hours > 0 else 0
            status_msg = "EXCEEDED" if self.budget_exceeded else "OK"
            self.logger.info(
                f"Budget: {self.accumulated_core_hours:.2f} / {self.max_core_hours:.2f} core-hours "
                f"({utilization:.1f}% utilized) [{status_msg}]"
            )

        if self.cache and self.use_cache_reads:
            hit_rate = (self.cache_hits / test_count * 100) if test_count > 0 else 0
            self.logger.info(
                f"Cache statistics: {self.cache_hits} hits, {self.cache_misses} misses ({hit_rate:.1f}% hit rate)"
            )
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
        total_runtime = (benchmark_end_time - benchmark_start_time).total_seconds()

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
        self.logger.info(f"Start time:    {benchmark_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"End time:      {benchmark_end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"Total runtime: {runtime_str}")
        self.logger.info("=" * 70)

        # Save runtime metadata for report generation
        self._save_run_metadata(
            test_count=test_count,
            benchmark_start_time=benchmark_start_time,
            benchmark_end_time=benchmark_end_time
        )

        # Save report config template for easy regeneration
        self._save_report_config_template()

        # Auto-generate report if enabled
        if self.cfg.reporting and self.cfg.reporting.enabled:
            self._generate_report()
            

     
        
            


       
       
        

