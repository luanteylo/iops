from rich.console import Console
import subprocess

from pathlib import Path
import time

console = Console()



class Slurm:

    @staticmethod
    def submit(test: Path):
        # Submit the job to SLURM        
        console.print(f"Submitting job: [bold cyan]{test}[/bold cyan]...")                     
        submit_command = f"sbatch {test}"
        result = subprocess.run(submit_command, shell=True, capture_output=True)
        # Extract job ID from sbatch output
        if result.returncode == 0:
            output = result.stdout.decode("utf-8")
            job_id = output.split()[-1]  # Assumes sbatch returns "Submitted batch job <job_id>"
            console.print(f"Job [bold cyan]{job_id}[/bold cyan] submitted successfully.")
            # Wait for job to finish
            while True:
                # Check if job is still in queue
                check_job_command = f"squeue -j {job_id}"
                job_status = subprocess.run(check_job_command, shell=True, capture_output=True)
                if job_status.returncode == 0 and job_id.encode() not in job_status.stdout:
                    break
                time.sleep(5)  
            console.print(f"Job [bold cyan]{job_id}[/bold cyan] completed.")
        else:
            console.print(f"Failed to submit job: {result.stderr.decode('utf-8')}", style="bold red")

        
