
from abc import ABC, abstractmethod
import subprocess
import time
from pathlib import Path
import re

from typing import Tuple

from iops.util.tags import jobManager_Tag


class JobManager:
    """
    Base class for defining how to handle different of job Managers.    
    """

    __name__ = None




    STATUS_COMPLETED = "COMPLETED"
    STATUS_FAILED = "FAILED"
    STATUS_RUNNING = "RUNNING"
    STATUS_PENDING = "PENDING"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_TIMEOUT = "TIMEOUT"
    STATUS_UNKNOWN = "UNKNOWN"
    STATUS_UNDEFINED = "UNDEFINED"
    STATUS_EXIT = "EXIT"
    STATUS_NODE_FAIL = "NODE_FAIL"
    STATUS_PREEMPTED = "PREEMPTED"
    STATUS_SUSPENDED = "SUSPENDED"
    STATUS_OUT_OF_MEMORY = "OUT_OF_MEMORY"
    STATUS_NODE_FAIL = "NODE_FAIL"
    STATUS_DEADLINE = "DEADLINE"
    STATUS_RESV_TIMEOUT = "RESV_TIMEOUT"
    STATUS_SUSPENDED = "SUSPENDED"
    STATUS_TIME_LIMIT = "TIME_LIMIT"
    STATUS_FAILED = "FAILED"
    STATUS_TIMEOUT = "TIMEOUT"
    STATUS_NODE_FAIL = "NODE_FAIL"
    STATUS_PREEMPTED = "PREEMPTED"
    STATUS_SUSPENDED = "SUSPENDED"

    @abstractmethod
    def submit(self, script_file: Path, opt_args: str = "") -> Tuple[str, str]:
        """
        Abstract method to submit a job script to the job manager.
        Parameters:
        - script_file (Path): The path to the script file to be submitted.
        - opt_args (str): Optional arguments for the submission command.
        Returns:
        - str: If successful, the job ID and the output of the submission command. Otherwise, None and the output of the command.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    
    @abstractmethod
    def get_status(self, job_id: str, opt_args: str = "") -> str:
        """
        Abstract method to execute a command to get the status of a job.
        Parameters:
        - job_id (str): The ID of the job to check.
        - opt_args (str): Optional arguments for the status command.
        Returns:
        - str: The return output of the status command.
        """
        raise NotImplementedError("Subclasses must implement this method.")
        
    @abstractmethod
    def cancel(self, job_id: str, opt_args: str = "") -> None:
        """
        Abstract method to cancel a job.
        Parameters:
        - job_id (str): The ID of the job to cancel.
        - opt_args (str): Optional arguments for the cancellation command.
        """
        raise NotImplementedError("Subclasses must implement this method.")
    
    @abstractmethod
    def wait(self, job_id: str, time_delay=5, opt_args: str = "") -> str:
        """
        Abstract method to wait for a job to finish.
        Parameters:
        - job_id (str): The ID of the job to wait for.
        - time_delay (int): The time delay between checks (in seconds).
        - opt_args (str): Optional arguments for the wait command.
        Returns:
        - str: The status of the job after waiting.

        """
        raise NotImplementedError("Subclasses must implement this method.")
    
    @staticmethod
    def factory(job_manager: jobManager_Tag) -> "JobManager":
        """
        Factory method to create an instance of a job manager based on the provided name.
        Parameters:
        - job_manager (str): The name of the job manager to create.
        Returns:
        - JobManager: An instance of the specified job manager.
        """
        # use __name__ to get the class name
        if job_manager == jobManager_Tag.SLURM:
            return SlurmJobManager()
        elif job_manager == jobManager_Tag.MSUB:
            return MsubJobManager()
        elif job_manager == jobManager_Tag.LOCAL:
            return LocalJobManager()
        else:
            raise ValueError(f"Unknown job manager: {job_manager}")
        
    def __str__(self):
        return self.__name__
    
class SlurmJobManager(JobManager):
    """
    Class for handling SLURM job submission and management.
    """
    __name__ = jobManager_Tag.SLURM.name

    def __init__(self):
        """
        Initialize the SLURM job manager.
        """
        super().__init__()

    
    def submit(self, script_file: Path, opt_args: str = "") -> Tuple[str, str]:
        """
        Submit a job script to SLURM.
        Parameters:
        - script_file (Path): The path to the script file to be submitted.
        - opt_args (str): Optional arguments for the submission command.
        Returns:
        - str: If successful, the job ID of the submitted job. Otherwise, None.
        """
        # Implement SLURM submission logic here
        output = subprocess.run(f"sbatch {opt_args} {script_file}", shell=True, capture_output=True)
        job_id = None
        if output.returncode == 0:
            # Extract job ID from the output
            job_id = output.stdout.decode().strip().split()[-1]        
        return job_id, output
    
    import subprocess

    def get_status(self, job_id: str, opt_args: str = "") -> str:
        """
        Get the status of a SLURM job.
        Parameters:
        - job_id (str): The ID of the job to check.
        - opt_args (str): Optional arguments for the status command.
        Returns:
        - str: The job status as a string.
        """
        # First try squeue
        squeue_cmd = f"squeue {opt_args} --job {job_id} --noheader --format='%T'"
        squeue_output = subprocess.run(squeue_cmd, shell=True, capture_output=True, text=True)

        status = squeue_output.stdout.strip()

        if status:
            return status  # Job is still in the queue (e.g., PENDING, RUNNING)       

        return "UNKNOWN"  # If no found. It probably finished, so we can move to the next step

    
    def cancel(self, job_id: str, opt_args: str = "") -> None:
        """
        Cancel a SLURM job.
        Parameters:
        - job_id (str): The ID of the job to cancel.
        - opt_args (str): Optional arguments for the cancellation command.
        """
        # Implement SLURM cancellation logic here
        subprocess.run(f"scancel {opt_args} {job_id}", shell=True)

    def wait(self, job_id: str, time_delay=5, opt_args: str = "") -> None:
        """
        Wait for a SLURM job to finish.
        Parameters:
        - job_id (str): The ID of the job to wait for.
        - time_delay (int): The time delay between checks (in seconds).
        - opt_args (str): Optional arguments for the wait command.
        """
        # Implement SLURM wait logic here
        while True:
            status = self.get_status(job_id, opt_args)
            if status != self.STATUS_RUNNING and status != self.STATUS_PENDING:
                return status
            time.sleep(time_delay)
        
class MsubJobManager(JobManager):
    """
    Class for handling MSUB job submission and management.
    """
    __name__ = jobManager_Tag.MSUB.name

    def __init__(self):
        """
        Initialize the MSUB job manager.
        """
        super().__init__()

    def submit(self, script_file: Path, opt_args: str = "") -> Tuple[str, str]:
        """
        Submit a job script to MSUB.
        Parameters:
        - script_file (Path): The path to the script file to be submitted.
        - opt_args (str): Optional arguments for the submission command.
        Returns:
        - str: If successful, the job ID of the submitted job. Otherwise, None.
        """
        # Implement MSUB submission logic here
        output = subprocess.run(f"ccc_msub {opt_args} {script_file}", shell=True, capture_output=True)
        job_id = None
        if output.returncode == 0:
            # Extract job ID from the output
            str_out = output.stdout.decode().strip()
            job_id = str_out.split()[-1]
            
        return job_id, output
    
    def get_status(self, job_id: str, opt_args: str = "") -> str:
        """
        Get the status of a MSUB job.
        Parameters:
        - job_id (str): The ID of the job to check.
        - opt_args (str): Optional arguments for the status command.
        Returns:
        - str: The return output of the status command.
        """
        # Implement MSUB status retrieval logic here
        output = subprocess.run(f"ccc_mstat -r {job_id}", shell=True, capture_output=True)

        if output.returncode == 0:
            rgex = r"JobState=(\w+)"
            match = re.search(rgex, output.stdout.decode())
            if match:
                status = match.group(1)
                return status
            
        return None
            
    def cancel(self, job_id: str, opt_args: str = "") -> None:
        """
        Cancel a MSUB job.
        Parameters:
        - job_id (str): The ID of the job to cancel.
        - opt_args (str): Optional arguments for the cancellation command.
        """
        # Implement MSUB cancellation logic here
        subprocess.run(f"ccc_mdel {opt_args} {job_id}", shell=True)

    def wait(self, job_id: str, time_delay=129, opt_args: str = "") -> None:
        """
        Wait for a MSUB job to finish.
        Parameters:
        - job_id (str): The ID of the job to wait for.
        - time_delay (int): The time delay between checks (in seconds).
        - opt_args (str): Optional arguments for the wait command.
        """
        # Implement MSUB wait logic here
        while True:
            status = self.get_status(job_id, opt_args)
            if status != self.STATUS_RUNNING and status != self.STATUS_PENDING:
                return status
            time.sleep(time_delay)

class LocalJobManager(JobManager):
    """
    Class for handling local job submission and management.
    """
    __name__ = jobManager_Tag.LOCAL.name

    def __init__(self):
        """
        Initialize the local job manager.
        """
        super().__init__()    


    def submit(self, script_file: Path, opt_args: str = "") -> Tuple[int, str]:
        """
        Submit a job script to the local system.

        Parameters:
        - script_file (Path): The path to the script file to be submitted.
        - opt_args (str): Optional arguments for the submission command.

        Returns:
        - Tuple[int, str]: The PID and the combined stdout/stderr output.
        """
        cmd = f"bash {opt_args} {script_file}"
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pid = process.pid
        comm = process.communicate()

        return pid, comm

        
    def get_status(self, job_id: str, opt_args: str = "") -> str:
        pass
    
    def cancel(self, job_id: str, opt_args: str = "") -> None:     
        pass

    def wait(self, job_id: str, time_delay=5, opt_args: str = "") -> None:
        pass