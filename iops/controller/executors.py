from pathlib import Path
from iops.utils.logger import HasLogger
from abc import ABC, abstractmethod
import subprocess
import psutil
import time
from pathlib import Path
import datetime

from enum import Enum



class BaseExecutor(ABC):
    """
    Abstract base class for all execution environments (e.g., SLURM, local).
    """

    _registry = {}

    @classmethod
    def register(cls, name):
        def decorator(subclass):
            cls._registry[name.lower()] = subclass
            return subclass
        return decorator

    @classmethod
    def build(cls, name: str, config) -> "BaseExecutor":
        executor_cls = cls._registry.get(name.lower())
        if executor_cls is None:
            raise ValueError(f"Executor '{name}' is not registered.")
        return executor_cls(config)

    def __init__(self, config):
        """
        Initialize executor with configuration.
        """
        self.config = config
        self.last_status = None

    @abstractmethod
    def submit(self, script : Path) -> str:
        """
        Submit a job with the given parameters.
        Returns a job identifier.
        """
        pass

    @abstractmethod
    def wait_and_collect(self, job_id: str, execution_dir : Path) -> dict:
        """
        Wait for the job to finish and collect execution results.
        Returns a dictionary with metrics like bandwidth and latency.
        """
        pass



@BaseExecutor.register("local")
class LocalExecutor(BaseExecutor, HasLogger):
    """
    Executor for simulating local benchmark jobs.
    """

    
    def submit(self, script: Path) -> str:
        """
        Execute the script locally and wait for it to finish.
        Returns "local" when completed.
        """
        self.logger.debug(f"Submitting local job script: {script}")
        if not script or not script.exists():
            raise ValueError(f"Script not found: {script}")

        command = f"bash {script}"
        self.logger.debug(f"Executing local script with command: {command}")

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=script.parent  # Ensures relative files are created in the right place
            )
            self.logger.info(f"Process completed with return code {result.returncode}")
            self.logger.debug(f"stdout:\n{result.stdout}")
            self.logger.debug(f"stderr:\n{result.stderr}")

            if result.returncode != 0:
                raise RuntimeError(f"Script failed with code {result.returncode}: {result.stderr}")

            return "local"

        except Exception as e:
            self.logger.error(f"Error running script {script}: {e}")
            raise

    def wait_and_collect(self, job_id: str, execution_dir: Path = None) -> dict:
        """
        Collect metrics from a local job that has already been executed (we don't actually wait here).
        
        Args:
            job_id (str): The PID of the local process as a string.
            execution_dir (Path, optional): Path to the job's execution directory. Not used in local execution.
        
        Returns:
            dict: A dictionary containing the job status and exit code.
        """
        pid = str(job_id)
        self.logger.debug(f"Waiting for process with PID {pid} to complete.")

        try:           
             # Define expected file paths
            job_start_path = execution_dir / "job.start"
            job_end_path = execution_dir / "job.end"
            job_status_path = execution_dir / "job.status"

            # Read contents of the files
            start_time = job_start_path.read_text().strip() if job_start_path.exists() else None
            end_time = job_end_path.read_text().strip() if job_end_path.exists() else None
            final_status = job_status_path.read_text().strip() if job_status_path.exists() else "UNKNOWN"

            return {
                "job_id": job_id,
                "status": final_status,
                "slurm_status": None,
                "start_time": start_time,
                "end_time": end_time,
                "error": None
            }
        
        except Exception as e:
            self.logger.error(f"Error while waiting for PID {pid}: {e}")
            return {
                "job_id": job_id,
                "status": "ERROR",
                "slurm_status": self.last_status,
                "start_time": None,
                "end_time": None,
                "error": str(e)
            }

@BaseExecutor.register("slurm")
class SlurmExecutor(BaseExecutor, HasLogger):
    """
    Executor for submitting and managing jobs via SLURM.
    """
    SLURM_FINISHED = "FINISHED"
    SLURM_PENDING = "PENDING"
    SLURM_RUNNING = "RUNNING"

    def submit(self, test: Path) -> str:
        """
        Simulates SLURM job submission.
        In practice, would use `sbatch` and capture the job ID.
        """
        self.logger.debug(f"Submitting SLURM job script: {test}")
        try:
            result = subprocess.run(
                ["sbatch", f"--time={self.config.execution.wall_time}",  str(test)],
                capture_output=True,
                text=True,
                check=True
            )
            job_id = result.stdout.strip().split()[-1]
            self.logger.info(f"SLURM job submitted with ID: {job_id}")
            # return the job ID
            return job_id
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to submit SLURM job: {e}")
            raise RuntimeError("SLURM job submission failed") from e
        
    
    def check_job_status(self, job_id: str) -> str:
        """
        Check the status of a SLURM job.
        In practice, would use `squeue` or `sacct` to get job status.
        """
        
        try:
            result = subprocess.run(
            ["squeue", "-j", job_id, "--noheader", "--format=%T"],  # %T gives only the state
                capture_output=True,
                text=True,
                check=True,
            )
            output = result.stdout.strip()
            self.logger.info(f"SLURM job {job_id}: {output}")

            if output == "":
                output = self.SLURM_FINISHED
            self.last_status = output
            return output
    
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to check SLURM job status: {e}")
            raise RuntimeError("SLURM job status check failed") from e
        

 
    def wait_and_collect(self, job_id: str, execution_dir: Path) -> dict:
        """
        Wait for the SLURM job to complete and collect metrics.
        Args:
            job_id (str): The SLURM job ID to wait for.
            execution_dir (Path): Path to the job's execution directory.
        Returns:
            dict: A dictionary containing job ID, status, start time, end time, and any error message.
        """
        self.logger.debug(f"Waiting for SLURM job to complete: {job_id}")
        poll_interval = self.config.execution.status_check_delay

        try:
            while self.check_job_status(job_id) in [self.SLURM_PENDING, self.SLURM_RUNNING]:
                time.sleep(poll_interval)

            self.logger.info(f"SLURM job {job_id} completed with status: {self.last_status}")

            # Define expected file paths
            job_start_path = execution_dir / "job.start"
            job_end_path = execution_dir / "job.end"
            job_status_path = execution_dir / "job.status"

            # Read contents of the files
            start_time = job_start_path.read_text().strip() if job_start_path.exists() else None
            end_time = job_end_path.read_text().strip() if job_end_path.exists() else None
            final_status = job_status_path.read_text().strip() if job_status_path.exists() else "UNKNOWN"

            return {
                "job_id": job_id,
                "status": final_status,
                "slurm_status": self.last_status,
                "start_time": start_time,
                "end_time": end_time,
                "error": None
            }

        except Exception as e:
            self.logger.error(f"Error while waiting for SLURM job {job_id}: {e}")
            return {
                "job_id": job_id,
                "status": "ERROR",
                "slurm_status": self.last_status,
                "start_time": None,
                "end_time": None,
                "error": str(e)
            }

  