from typing import List, Dict, Any
from dataclasses import dataclass

from iops.utils.config_loader import IOPSConfig
from iops.controller.planner.base_planner import BasePlanner, PhaseResult, Phase
from iops.utils.logger import HasLogger
from iops.benchmarks.base import BenchmarkRunner

class SweepPlanner(BasePlanner, HasLogger):
    """
    Planner that executes a sequence of parameter sweeps.
    Each phase varies one parameter while fixing others,
    recording the best value per phase.
    """

    def __init__(self, config: IOPSConfig, benchmark: BenchmarkRunner):
        self.config = config
        self.history: Dict[str, Any] = {}
        self.benchmark = benchmark
        self._phases = self.benchmark.build_phases()
        
    
    def phases(self) -> List[Phase]:
        """
        Returns the list of phases to execute.
        """
        self.logger.debug(f"Available phases: {[phase.sweep_param for phase in self._phases]}")
        return self._phases

    def update_for_next_phase(self, result: PhaseResult):
        """
        Updates all remaining phases with the best parameters
        found in the last completed phase.
        """
        self.logger.debug(f"Updating planner with result: {result}")
        self.logger.debug(f"Current history before update: {self.history}") 
        self.history.update(result.best_params)
        for phase in self._phases:
            self.logger.debug(f"Updating phase '{phase.sweep_param}' with history: {self.history}")
            phase.fixed_params.update(self.history)
        
        self.logger.debug(f"History after update: {self.history}")
