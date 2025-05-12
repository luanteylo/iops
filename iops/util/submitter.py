import time
import subprocess
from pathlib import Path
import random

from iops.util.tags import jobManager_Tag

def __get_jobid(cc_return: str):
    """"""

def __cc_mstat_wait(jobid: int):
    pass

class Submitter:

    @staticmethod
    def __slurm(test: Path):
        return f"sbatch --wait {test}"
    
    @staticmethod
    def __msub(test: Path):
        return f"msub {test}"
    
    @staticmethod
    def __local(test: Path) -> str:
        return f"bash {test}"

    @staticmethod
    def submit(test: Path, job_manager: jobManager_Tag) -> subprocess.CompletedProcess:

        if job_manager == jobManager_Tag.SLURM:
            submit_command = Submitter.__slurm(test)
            result = subprocess.run(submit_command, shell=True, capture_output=True)
        elif job_manager == jobManager_Tag.MSUB:
            submit_command == Submitter.__msub(test)
            result = subprocess.run(submit_command, shell=True, capture_output=True)
            # get job_id and wait for it

        elif job_manager == jobManager_Tag.LOCAL:
            submit_command = Submitter.__local(test)
            result = subprocess.run(submit_command, shell=True, capture_output=True)
        
             
        return result

    @staticmethod
    def stop_slurm():
        result = subprocess.run("scancel -u $USER", shell=True, capture_output=True)
        return result
    
    @staticmethod
    def wait(start_time: int, end_time: int) -> int:
        wait_time = start_time
        if start_time !=  end_time:
             wait_time =  random.randrange(start_time, end_time)                            
        
        time.sleep(wait_time)
        return wait_time

    
            

        