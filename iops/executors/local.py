from iops.executors.base import BaseExecutor
from iops.utils.logger import HasLogger


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

