from typing import Dict, Any
from iops.utils.config_loader import IOPSConfig
from iops.controller.planner.base_planner import BasePlanner, PhaseResult, Phase
from iops.utils.logger import HasLogger
from iops.benchmarks.base import BenchmarkRunner

class SweepPlanner(BasePlanner, HasLogger):
    """
    Planner that creates one phase at a time and updates based on results.
    """

    def __init__(self, config: IOPSConfig, benchmark: BenchmarkRunner):
        self.config = config
        self.benchmark = benchmark
        self.tests = list(config.execution.tests)
        self.index = 0
        self.history: Dict[str, Any] = {}

    def has_next_phase(self) -> bool:
        return self.index < len(self.tests)

    def next_phase(self) -> Phase:
        sweep_param = self.tests[self.index]
        self.logger.info(f"Generating phase for parameter: {sweep_param}")
        self.index += 1
        return self.benchmark.build_phase(
            sweep_param=sweep_param,
            fixed_params=self.history
        )

    def update_for_next_phase(self, result: PhaseResult):
        self.logger.info(f"Updating history with best result: {result}")
        self.history.update(result.best_params)
