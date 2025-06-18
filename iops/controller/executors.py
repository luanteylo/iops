from iops.utils.logger import HasLogger
from abc import ABC, abstractmethod
import subprocess
import psutil
import time
from pathlib import Path

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
    def submit(self, script : Path) -> str:
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

    def submit(self, script: Path) -> str:
        """
        Execute the script locally.
        Gets the process PID and returns it.

        Args:
            script (Path): The path to the script to execute.

        Returns:
            str: The process PID as a string.
        """
        if not script or not script.exists():
            raise ValueError(f"Script not found: {script}")

        command = f"bash {script}"  # or use `sh` depending on your shell
        self.logger.debug(f"Executing local script with command: {command}")

        process = subprocess.Popen(command, shell=True)
        self.logger.info(f"Started process with PID: {process.pid}")

        return str(process.pid)




    def wait_and_collect(self, job_id: str) -> dict:
        """
        Wait for the local job to complete and collect .
        
        Args:
            job_id (str): The PID of the local process as a string.
        
        Returns:
            dict: A dictionary containing the job status and exit code.
        """
        pid = int(job_id)
        self.logger.debug(f"Waiting for process with PID {pid} to complete.")

        try:
            proc = psutil.Process(pid)
            while proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                time.sleep(1)
            return {
                "job_id": job_id,
                "status": "completed",
                "exit_code": proc.wait()
            }
        except psutil.NoSuchProcess:
            self.logger.warning(f"No process found with PID {pid}")
            return {
                "job_id": job_id,
                "status": "not_found",
                "exit_code": None
            }
        except Exception as e:
            self.logger.error(f"Error while waiting for PID {pid}: {e}")
            return {
                "job_id": job_id,
                "status": "error",
                "exit_code": None,
                "error": str(e)
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
