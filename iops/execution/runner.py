
from iops.logger import HasLogger
from iops.execution.planner import BasePlanner
from iops.execution.executors import BaseExecutor
from iops.execution.cache import ExecutionCache
from iops.config.models import GenericBenchmarkConfig
from iops.results.writer import save_test_execution

from typing import Optional
from pathlib import Path
from jinja2 import Template
from datetime import datetime

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
            

     
        
            


       
       
        

