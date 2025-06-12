from abc import ABC, abstractmethod
from iops.utils.logger import HasLogger
from typing import List, Dict, Any
from iops.utils.config_loader import IOPSConfig
from iops.controller.planner.base_planner import BasePlanner, PhaseResult, Phase

class BenchmarkRunner(ABC, HasLogger):
    """
    Abstract base class for all benchmark implementations.
    Defines the interface required for benchmark execution.
    """

    def __init__(self, config):
        super().__init__()
        self.config = config

    @abstractmethod
    def generate(self, params: dict) -> str:
        """
        Generate the job script or command required to run the benchmark with the given parameters.
        Should return the path to the generated script or command string.
        """
        pass

    @abstractmethod
    def parse_output(self, job_output_path: str) -> dict:
        """
        Parse the output of the benchmark run and return relevant metrics as a dictionary.
        Example: {'bandwidth_avg': 1234.5, 'latency': 4.2}
        """
        pass

    @abstractmethod
    def build_phase(self) -> list:
        """
        Build the phases for the benchmark execution.
        Each phase should define a set of parameters to vary and the expected results.
        Returns a list of Phase objects.
        """
        pass