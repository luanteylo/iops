
from iops.logger import HasLogger
from iops.execution.planner import BasePlanner
from iops.execution.executors import BaseExecutor
from iops.execution.cache import ExecutionCache
from iops.config.models import GenericBenchmarkConfig
from iops.results.writer import save_test_execution

from typing import Optional, List
from pathlib import Path
from jinja2 import Template
from datetime import datetime
import json

class IOPSRunner(HasLogger):
    def __init__(self, cfg: GenericBenchmarkConfig, args):
        super().__init__()
        self.cfg = cfg
        self.args = args
        self.planner = BasePlanner.build(cfg=self.cfg)
        self.executor = BaseExecutor.build(cfg=self.cfg)

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
        if hasattr(args, 'estimated_time') and args.estimated_time is not None:
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

    def _get_expected_metrics(self) -> set:
        """Get set of expected metric names from configuration."""
        expected = set()
        for script in self.cfg.scripts:
            if script.parser and script.parser.metrics:
                for metric in script.parser.metrics:
                    expected.add(metric.name)
        return expected

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

    def _save_run_metadata(self, test_count: int = 0):
        """Save runtime metadata for report generation."""
        try:
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
                }
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

            # Save to file
            metadata_path = self.cfg.benchmark.workdir / "run_metadata.json"
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)

            self.logger.debug(f"Saved runtime metadata to: {metadata_path}")

        except Exception as e:
            self.logger.warning(f"Failed to save runtime metadata: {e}")

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
        self.logger.info("=" * 70)
        self.logger.info(f"Starting IOPS Runner: {self.cfg.benchmark.name}")
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

                if core_hours_used > 0:
                    cores = self._compute_cores(test)
                    remaining = self.max_core_hours - self.accumulated_core_hours
                    self.logger.debug(
                        f"  [Budget] Used {core_hours_used:.4f} core-hours ({cores} cores) | "
                        f"Total: {self.accumulated_core_hours:.2f}/{self.max_core_hours:.2f} | "
                        f"Remaining: {remaining:.2f}"
                    )

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

        # Save runtime metadata for report generation
        self._save_run_metadata(test_count=test_count)
            

     
        
            


       
       
        

