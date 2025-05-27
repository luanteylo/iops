from iops.executors.base import BaseExecutor
from iops.utils.logger import HasLogger


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
