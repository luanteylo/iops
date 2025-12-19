
from iops.logger import HasLogger
from iops.execution.planner import BasePlanner
from iops.execution.executors import BaseExecutor
from iops.execution.cache import ExecutionCache
from iops.config.models import GenericBenchmarkConfig
from iops.results.writer import save_test_execution

from typing import Optional
from pathlib import Path
from jinja2 import Template

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

    def run(self):
        self.logger.info("=" * 70)
        self.logger.info(f"Starting IOPS Runner: {self.cfg.benchmark.name}")
        self.logger.info("=" * 70)

        test_count = 0

        while True:
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

        # Final statistics
        self.logger.info("=" * 70)
        self.logger.info(f"Benchmark completed: {test_count} tests total")

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
            

     
        
            


       
       
        

