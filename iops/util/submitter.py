import time
import subprocess
from pathlib import Path
import random

from iops.util.tags import jobManager

class Submitter:

    @staticmethod
    def __slurm(test: Path):
        return f"sbatch --wait {test}"
    
    @staticmethod
    def __local(test: Path) -> str:
        return f"bash {test}"

    @staticmethod
    def submit(test: Path, job_manager: jobManager) -> subprocess.CompletedProcess:

        if job_manager == jobManager.SLURM:
            submit_command = Submitter.__slurm(test)
        elif job_manager == jobManager.LOCAL:
            submit_command = Submitter.__local(test)
        
        result = subprocess.run(submit_command, shell=True, capture_output=True)     
        return result

    @staticmethod
    def stop_slurm():
        result = subprocess.run("scancel -u $USER", shell=True, capture_output=True)
        return result
    
    def wait(start_time: int, end_time: int) -> int:
        wait_time = start_time
        if start_time !=  end_time:
             wait_time =  random.randrange(start_time, end_time)                            
        
        time.sleep(wait_time)
        return wait_time

    
            

        