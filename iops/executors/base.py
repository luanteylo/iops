from abc import ABC, abstractmethod


class BaseExecutor(ABC):
    """
    Abstract base class for all execution environments (e.g., SLURM, local).
    """

    def __init__(self, config):
        """
        Initialize executor with configuration.
        """
        self.config = config

    @abstractmethod
    def submit(self, params: dict) -> str:
        """
        Submit a job with the given parameters.
        Returns a job identifier.
        """
        pass

    @abstractmethod
    def wait_and_collect(self, job_id: str) -> dict:
        """
        Wait for the job to finish and collect execution results.
        Returns a dictionary with metrics like bandwidth and latency.
        """
        pass
