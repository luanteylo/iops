from pathlib import Path
from iops.utils.logger import HasLogger
from abc import ABC, abstractmethod
import subprocess
import psutil
import time
from pathlib import Path
import datetime

from enum import Enum

class JobStatus(Enum):
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    UNKNOWN = "UNKNOWN"

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



@BaseExecutor.register("local")
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
        self.logger.debug(f"Submitting local job script: {script}")
        if not script or not script.exists():
            raise ValueError(f"Script not found: {script}")

        command = f"bash {script}"  # or use `sh` depending on your shell
        self.logger.debug(f"Executing local script with command: {command}")

        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
                "exit_code": proc.wait(),
                "error": None
            }
        except psutil.NoSuchProcess:
            self.logger.warning(f"No process found with PID {pid}")
            return {
                "job_id": job_id,
                "status": "not_found",
                "exit_code": None,
                "error": "Process not found"
            }
        except Exception as e:
            self.logger.error(f"Error while waiting for PID {pid}: {e}")
            return {
                "job_id": job_id,
                "status": "error",
                "exit_code": None,
                "error": str(e)
            }

@BaseExecutor.register("slurm")
class SlurmExecutor(BaseExecutor, HasLogger):
    """
    Executor for submitting and managing jobs via SLURM.
    """
    def submit(self, test: Path) -> str:
        """
        Simulates SLURM job submission.
        In practice, would use `sbatch` and capture the job ID.
        """
        self.logger.debug(f"Submitting SLURM job script: {test}")
        try:
            result = subprocess.run(
                ["sbatch", str(test)],
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

            if output == JobStatus.CANCELLED.value:
                self.logger.info(f"SLURM job {job_id} was cancelled.")
                return JobStatus.CANCELLED.value
            elif output == JobStatus.COMPLETED.value or output == "":
                # Assuming an empty output means the job has completed successfully
                self.logger.info(f"SLURM job {job_id} completed successfully.")
                return JobStatus.COMPLETED.value
            else:
                self.logger.warning(f"Unknown job status for job {job_id}: {output}")
                return JobStatus.UNKNOWN.value
    
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to check SLURM job status: {e}")
            raise RuntimeError("SLURM job status check failed") from e
        

    def wait_and_collect(self, job_id: str) -> dict:
        """
        Wait for the SLURM job to complete and collect metrics.
        Args:
            job_id (str): The SLURM job ID to wait for.
        Returns:
            dict: A dictionary containing job ID, status, exit code, and metrics.
        """
        self.logger.debug(f"Waiting for SLURM job to complete: {job_id}")
        
        poll_interval = self.config.execution.status_check_delay  # seconds to wait between status checks
        if not poll_interval:
            poll_interval = 10
        # Parse wall_time in HH:MM:SS format to seconds
        wall_time_str = self.config.execution.wall_time  # e.g., "00:30:00"
        if wall_time_str:
            h, m, s = map(int, wall_time_str.split(":"))
            timeout = h * 3600 + m * 60 + s
        else:
            timeout = None
        if not timeout:
            timeout = 15
        start_time = datetime.datetime.now()
        timeout = float(timeout)  # Ensure timeout is a float for comparison
        try:
            while True:
                status = self.check_job_status(job_id)
                if status == JobStatus.COMPLETED.value:
                    # Job completed successfully
                    self.logger.info(f"SLURM job {job_id} completed successfully.")
                    break
                elapsed = (datetime.datetime.now() - start_time).total_seconds()
                if elapsed > timeout:
                    self.logger.error(f"SLURM job {job_id} timed out after {timeout} seconds")
                    return {
                        "job_id": job_id,
                        "status": "timeout",
                        "exit_code": None,
                        "error": "Job timed out"
                    }
                time.sleep(poll_interval)
            self.logger.info(f"SLURM job {job_id} completed with status: {status}")
            return {
                "job_id": job_id,
                "status": status,
                "exit_code": 0,  # Assuming job completed successfully
            }
        except Exception as e:
            self.logger.error(f"Error while waiting for SLURM job {job_id}: {e}")
            return {
                "job_id": job_id,
                "status": "error",
                "exit_code": None,
                "error": str(e)
            }
    # def collect_metrics(self, job_id: str) -> dict:
    #     """
    #     Collect metrics from the SLURM job output files.
    #     This is a placeholder for actual metric collection logic.
        
    #     Args:
    #         job_id (str): The SLURM job ID to collect metrics for.
        
    #     Returns:
    #         dict: A dictionary containing collected metrics.
    #     """
    #     self.logger.debug(f"Collecting metrics for SLURM job: {job_id}")
    #     output_dir = self.config.get("slurm_output_dir", ".")
    #     output_files = list(Path(output_dir).glob(f"*{job_id}*"))
    #     if not output_files:
    #         self.logger.warning(f"No output files found for SLURM job {job_id} in {output_dir}")
    #         return {"job_id": job_id, "output_files": [], "outputs": {}}

    #     outputs = {}
    #     for file in output_files:
    #         try:
    #             with open(file, "r") as f:
    #                 outputs[str(file)] = f.read()
    #         except Exception as e:
    #             self.logger.error(f"Failed to read output file {file}: {e}")
    #             outputs[str(file)] = f"Error reading file: {e}"

    #     return {
    #         "job_id": job_id,
    #         "output_files": [str(f) for f in output_files],
    #         "outputs": outputs
    #     }
