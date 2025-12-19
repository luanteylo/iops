
from iops.logger import HasLogger
from iops.execution.planner import BasePlanner
from iops.execution.executors import BaseExecutor
from iops.execution.cache import ExecutionCache
from iops.config.models import GenericBenchmarkConfig
from iops.results.writer import save_test_execution

from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path
import json

class IOPSRunner(HasLogger):
    def __init__(self, cfg: GenericBenchmarkConfig, args):
        super().__init__()
        self.cfg = cfg
        self.args = args
        self.planner = BasePlanner.build(cfg=self.cfg)
        self.executor = BaseExecutor.build(cfg=self.cfg)

        # Initialize cache if use_cache is enabled and sqlite_db is configured
        self.cache: Optional[ExecutionCache] = None
        if args.use_cache:
            if cfg.benchmark.sqlite_db:
                self.cache = ExecutionCache(cfg.benchmark.sqlite_db)
                stats = self.cache.get_cache_stats()
                self.logger.info(
                    f"Cache enabled: {stats['total_entries']} entries, "
                    f"{stats['unique_parameter_sets']} unique parameter sets"
                )
            else:
                self.logger.warning(
                    "Cache requested (--use_cache) but benchmark.sqlite_db not configured. "
                    "Cache disabled."
                )

        # Statistics
        self.cache_hits = 0
        self.cache_misses = 0

    def run(self):
        self.logger.info("Starting IOPS Runner...")

        test_count = 0

        while True:
            test = self.planner.next_test()
            if test is None:
                break

            test_count += 1

            # Check cache if enabled
            used_cache = False
            if self.cache:
                cached_result = self.cache.get_cached_result(
                    params=test.vars,
                    repetition=test.repetition,
                    round_name=test.round_name,
                )

                if cached_result:
                    # Use cached result
                    self.cache_hits += 1
                    used_cache = True

                    self.logger.info(
                        f"Test {test.execution_id} (repetition {test.repetition}): "
                        f"Using CACHED result from {cached_result['cached_at']}"
                    )

                    # Populate test with cached data
                    test.metadata.update(cached_result['metadata'])
                    test.metadata['metrics'] = cached_result['metrics']
                    test.metadata['__cached'] = True
                    test.metadata['__cached_at'] = cached_result['cached_at']

                else:
                    self.cache_misses += 1

            # Execute if not using cache
            if not used_cache:
                self.executor.submit(test)
                self.executor.wait_and_collect(test)

                # Store in cache if enabled and execution succeeded
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

            # Log test details
            if self.args.log_level.upper() == 'DEBUG':
                self.logger.debug(test.describe())
            else:
                self.logger.info(test)

            # Check the status
            status = test.metadata.get("__executor_status", "UNKNOWN")
            cache_status = " [CACHED]" if used_cache else ""
            self.logger.info(f"Test {test.execution_id} status: {status}{cache_status}")

            # Add test to output file
            save_test_execution(test)

        # Final statistics
        self.logger.info("All tests have been planned. Total tests: %d", test_count)

        if self.cache:
            self.logger.info(
                f"Cache statistics: {self.cache_hits} hits, {self.cache_misses} misses "
                f"({self.cache_hits / test_count * 100:.1f}% hit rate)"
            )

        self.logger.info(f"Results saved to: {self.cfg.output.sink.path}")
        self.logger.info("IOPS Runner finished.")
            

     
        
            


       
       
        

