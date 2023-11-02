from rich.progress import Progress
from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.prompt import Prompt
from rich.traceback import install
from rich.traceback import Traceback
import time
import sys
from pathlib import Path
import math
import random
import subprocess

from iops.setup.iops_config import IOPSConfig
from iops.setup.generator import Generator

#install(show_locals=True)
console = Console()


class TestRunner:
    def __init__(self, config_file: str, skip_confirmation: bool=False):
        self.config_file = config_file
        self.skip_confirmation = skip_confirmation

        try:
            # Initialize and load configuration
            self.config = IOPSConfig(config_file)
        except Exception as e:
            console.print("[bold red]Error:[/bold red] {}".format(str(e)))
            sys.exit(1)

        self.__print_config()        

    def __print_config(self):
        # Display startup message with a panel
        console.print(Panel(f"[bold green]Starting test with configuration file {self.config_file}...", expand=False))
        
        # Create a table for node information
        table = Table(show_header=True, header_style="bold blue", box=box.SIMPLE)
        table.add_column("Setting", style="dim", width=30)
        table.add_column("Value")

        table.add_row("Nodes", str(self.config.nodes))
        table.add_row("Max Nodes", str(self.config.max_nodes))
        table.add_row("Max Processes Per Node", str(self.config.max_processes_per_node))

        # Create a table for storage information
        table.add_row("")
        table.add_row("Storage Path", str(self.config.path))
        table.add_row("Max OST", str(self.config.max_ost))
        table.add_row("Default Stripe Count", str(self.config.default_stripe_count))
        table.add_row("Default Stripe Size", str(self.config.default_stripe_size))
        table.add_row("File System", str(self.config.file_system))
        # print max volume in GB
        table.add_row("Max Volume", f"{self.config.max_volume/ 2**30}GB")

        # Create a table for execution information
        table.add_row("")    
        table.add_row("Mode", str(self.config.mode))
        table.add_row("Job Manager", str(self.config.job_manager))
        modules = self.config.modules
        if modules is not None:        
            modules = ", ".join(f"{module}" for module in self.config.modules)
        table.add_row("Modules", str(modules))
        table.add_row("Workdir", str(self.config.workdir))
    
        # Print the tables with section headers and horizontal rules   
        console.print(table)

        if not self.skip_confirmation:
            # Ask for user confirmation
            confirmed = Prompt.ask("Is this setup correct?", choices=["yes", "no"], default="yes")
            
            if confirmed.lower() != "yes":
                console.print("[bold red]Aborting test due to incorrect setup.")
                exit(1)
            
        console.print("\n")
        
        console.print(Panel(f"[bold green]Starting test...", expand=True))

    def __generate_file_cases(self, filesize_folder: Path):        
        start_size = 256 * 2**20  # 256 MiB
        max_size = self.config.max_volume
        cases = []

        # Calculate how many steps are needed
        num_steps = int(math.log(max_size / start_size, 2)) + 1

        # by default the number of nodes for the file_size tests is 4, 
        # except if the max_nodes is less than 4
        # in this case, we will use the max_nodes
        num_nodes = 4
        if num_nodes > self.config.max_nodes:
            num_nodes = self.config.max_nodes
        
        # by defautl the number of processes per node is 8
        # except if the max_processes_per_node is less than 8
        # in this case, we will use the max_processes_per_node
        num_processes_per_node = 8
        if num_processes_per_node > self.config.max_processes_per_node:
            num_processes_per_node = self.config.max_processes_per_node

        total_processes = num_nodes * num_processes_per_node

        panel_text = f"""
        [bold green]Generating {num_steps} file size tests...[/bold green]
        [bold green]Total size: {max_size/2**30:.2f}GB[/bold green]
        [bold green]Total processes: {total_processes}[/bold green]
        [bold green]Total nodes: {num_nodes}[/bold green]
        """

        console.print(Panel(panel_text, title="File Size Tests"))

        for i in range(num_steps):
            current_size = start_size * (2 ** i)
            bytes_per_process = current_size / total_processes

            file_name = f"filesize_{current_size}_{i+1}.sh"
            file_path = filesize_folder / f"{i}"
            file_path.mkdir(exist_ok=True)

            case = template_tags = {
                "job_name": f"filesize_{current_size}_{i+1}",
                #"partition": "The partition to submit the job to",
                "ntasks":total_processes,
                "nodes": num_nodes,                
                "ntasks_per_node": num_processes_per_node,
                "time": "04:00:00",
                "chdir": file_path,
                "constraint": 'bora',
                "modules": self.config.modules,
                "ior_output_path": self.config.path,
                "ior_parameter": f"-w -t 1m -b {bytes_per_process}b"                
            }
            # generate the slurm script            
            Generator.generate_slurm_script(Path("iops/templates/ior_template.sh.j2"), file_path, file_name, case)
            console.print(f"[bold green]Created file:[/bold green] [bold cyan]{file_path/file_name}[/bold cyan]...")

            cases.append(file_path/file_name)        
        
        console.print("\n")        
        
        return cases

    def submit_test_to_slurm(self, all_tests: list, repetitions: int, console: Console, progress: Progress, task_id: int):
        random.shuffle(all_tests)
        for test in all_tests:
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
                    time.sleep(5)  # Adjust sleep time as needed

                console.print(f"Job [bold cyan]{job_id}[/bold cyan] completed.")
            else:
                console.print(f"Failed to submit job: {result.stderr.decode('utf-8')}", style="bold red")

            # Once a job is submitted and finished, advance the progress bar by 1 step
            progress.advance(task_id)
        


    def run(self) -> None:

        try:
            repetitions = 10
            if self.config.mode == "fast":
                repetitions = 5
            
            # First, generate the folder structure
            # Ensure the workdir exists
            self.config.workdir.mkdir(parents=True, exist_ok=True)


            # Create 'filesize' folder and subfolders for each file size step
            filesize_folder = self.config.workdir / 'filesize'
            filesize_folder.mkdir(exist_ok=True)
            #console.print(f"[bold green]Created folder {filesize_folder}[/bold green]")

            # Create 'computing' folder and subfolders for each compute node
            computing_folder = self.config.workdir / 'computing'
            computing_folder.mkdir(exist_ok=True)
            #console.print(f"[bold green]Created folder {computing_folder}[/bold green]")
            

            # Create 'striping' folder
            striping_folder = self.config.workdir / 'striping'
            striping_folder.mkdir(exist_ok=True)
            #console.print(f"[bold green]Created folder {striping_folder}[/bold green]")

            
            # first, let's create the slurm scripts to generate the file size tests
            file_size_tests = self.__generate_file_cases(filesize_folder)
            # then, let's create the slurm scripts to generate the computing tests
            # computing_tests = self.__generate_computing_cases(computing_folder)
            # finally, let's create the slurm scripts to generate the striping tests
            # striping_tests = self.__generate_striping_cases(striping_folder)

            all_tests = file_size_tests #+ computing_tests + striping_tests

            with Progress(console=console, transient=True) as progress:
                # Create task with total count as len(all_tests) * repetitions
                task_id = progress.add_task("[cyan]Submitting...", total=len(all_tests) * repetitions)
                for i in range(repetitions):
                    console.print(f"Repetition [bold green]{i+1}[/bold green] of [bold green]{repetitions}[/bold green]")
                    self.submit_test_to_slurm(all_tests, repetitions, console, progress, task_id)
                    console.print("\n")


            
            console.print("[bold green]All jobs completed successfully.")


        except KeyboardInterrupt:
            console.print("[bold red]Aborting test due to user interruption.")
            exit(1)

        except Exception as e:
            console.print("[bold red]Error:[/bold red] {}".format(str(e)))
            sys.exit(1)