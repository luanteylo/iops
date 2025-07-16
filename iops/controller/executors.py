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
    JOB_STATUS_FILE = "job.status"
    JOB_START_FILE = "job.start"
    JOB_END_FILE = "job.end"

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
    def _wait_and_collect(self, job_id: str, execution_dir : Path) -> dict:
        """
        Wait for the job to finish and collect execution results.
        Returns a dictionary with metrics like bandwidth and latency.
        """
        pass
    
    def __clean_up_temp_files(self, execution_dir: Path) -> None:
        """        
        This method is called after job completion to remove temporary files.
        """
        self.logger.debug(f"Cleaning up temporary files in {execution_dir}")
        try:
            for file in [self.JOB_END_FILE, self.JOB_START_FILE, self.JOB_STATUS_FILE]:
                file_path = execution_dir / file
                if file_path.exists():
                    self.logger.debug(f"Removing temporary file: {file_path}")
                    file_path.unlink(missing_ok=True)
                else:
                    self.logger.warning(f"Temporary file not found, skipping: {file_path}")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")

    def wait_and_collect(self, job_id: str, execution_dir: Path) -> dict:
        """
        Wrapper method that ensures cleanup after wait_and_collect.
        """
        try:
            return self._wait_and_collect(job_id, execution_dir)
        finally:
            self.__clean_up_temp_files(execution_dir)

    def _default_execution_summary(self) -> dict:
        """
        Returns a default dictionary for recording execution metadata.
        """
        return {
            "__jobid": None,
            "__status": None,
            "__executor_status": None,
            "__start": None,
            "__end": None,
            "__error": None
        }
    
   







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
            self.logger.debug(f"Process completed with return code {result.returncode}")
            self.logger.debug(f"stdout:\n{result.stdout}")
            self.logger.debug(f"stderr:\n{result.stderr}")

            if result.returncode != 0:
                raise RuntimeError(f"Script failed with code {result.returncode}: {result.stderr}")

            return "local"

        except Exception as e:
            self.logger.error(f"Error running script {script}: {e}")
            raise

    def _wait_and_collect(self, job_id: str, execution_dir: Path = None) -> dict:
        """
        Collect metrics from a local job that has already been executed (we don't actually wait here).
        
        Args:
            job_id (str): The PID of the local process as a string.
            execution_dir (Path, optional): Path to the job's execution directory. Not used in local execution.
        
        Returns:
            dict: A dictionary containing the job status and exit code.
        """   
        self.logger.debug(f"Waiting for process with PID {job_id} to complete.")

        execution_summary = self._default_execution_summary()
        execution_summary['__jobid'] = job_id
        try:           
             # Define expected file paths
            job_start_path = execution_dir / self.JOB_START_FILE
            job_end_path = execution_dir / self.JOB_END_FILE
            job_status_path = execution_dir / self.JOB_STATUS_FILE

            # Read contents of the files
            execution_summary["__start"] = job_start_path.read_text().strip() if job_start_path.exists() else None
            execution_summary["__end"] = job_end_path.read_text().strip() if job_end_path.exists() else None
            execution_summary["__status"] = job_status_path.read_text().strip() if job_status_path.exists() else None            
        
        except Exception as e:
            self.logger.error(f"Error while collecting status for job {job_id}: {e}")
            execution_summary["__status"] = "ERROR"
            execution_summary["__error"] = str(e)
        
        return execution_summary

@BaseExecutor.register("slurm")
class SlurmExecutor(BaseExecutor, HasLogger):
    """
    Executor for submitting and managing jobs via SLURM.
    """
    SLURM_FINISHED = "FINISHED"
    SLURM_PENDING = "PENDING"
    SLURM_RUNNING = "RUNNING"

    def submit(self, script: Path) -> str:
        """
        Simulates SLURM job submission.
        In practice, would use `sbatch` and capture the job ID.
        """
        self.logger.debug(f"Submitting SLURM job script: {script}")
        try:
            result = subprocess.run(
                ["sbatch", f"--time={self.config.execution.wall_time}",  str(script)],
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
        
    
    def __check_job_status(self, job_id: str) -> str:
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
        

    def _wait_and_collect(self, job_id: str, execution_dir: Path) -> dict:
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
        execution_summary = self._default_execution_summary()
        execution_summary["__jobid"] = job_id

        try:
            while self.__check_job_status(job_id) in [self.SLURM_PENDING, self.SLURM_RUNNING]:
                time.sleep(poll_interval)

            self.logger.info(f"SLURM job {job_id} completed with status: {self.last_status}")

            # Define expected file paths
            job_start_path = execution_dir / self.JOB_START_FILE
            job_end_path = execution_dir / self.JOB_END_FILE
            job_status_path = execution_dir / self.JOB_STATUS_FILE      

            # Read contents of the files
            execution_summary["__start"] = job_start_path.read_text().strip() if job_start_path.exists() else None
            execution_summary["__end"] = job_end_path.read_text().strip() if job_end_path.exists() else None
            execution_summary["__status"] = job_status_path.read_text().strip() if job_status_path.exists() else "UNKNOWN"
            execution_summary["__executor_status"] = self.last_status                        

        except Exception as e:
            self.logger.error(f"Error while waiting for SLURM job {job_id}: {e}")
            execution_summary["__status"] = "ERROR"
            execution_summary["__error"] = str(e)
        
        return execution_summary