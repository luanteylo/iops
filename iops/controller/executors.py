from iops.utils.logger import HasLogger
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




class LocalExecutor(BaseExecutor, HasLogger):
    """
    Executor for simulating local benchmark jobs.
    """

    def submit(self, params: dict) -> str:
        """
        Simulates local job submission.
        """
        self.logger.info(f"Simulating local job with parameters: {params}")
        # TODO: Implement actual local execution logic if needed
        return "local-job-123"

    def wait_and_collect(self, job_id: str) -> dict:
        """
        Simulates waiting for a local job to complete and collecting results.
        """
        self.logger.info(f"Simulating wait for job completion: {job_id}")
        # TODO: Replace with actual metrics collection if applicable
        return {
            "output_path": f"/path/to/slurm/output/{job_id}.out",            
        }




class SlurmExecutor(BaseExecutor, HasLogger):
    """
    Executor for submitting and managing jobs via SLURM.
    """

    def submit(self, job_script_path: str) -> str:
        """
        Simulates SLURM job submission.
        In practice, would use `sbatch` and capture the job ID.
        """
        self.logger.debug(f"Submitting SLURM job script: {job_script_path}")
        # TODO: Use subprocess to call `sbatch` and parse the output for job ID
        return "slurm-job-456"  # Placeholder job ID

    def wait_and_collect(self, job_id: str) -> dict:
        """
        Simulates waiting for a SLURM job and collecting results.
        In practice, would monitor job status and parse SLURM output files.
        """
        self.logger.debug(f"Waiting for SLURM job to complete: {job_id}")
        # TODO: Poll SLURM (e.g., `squeue`, `sacct`) and read output files
        return {
            "output_path": f"/path/to/slurm/output/{job_id}.out",            
        }
