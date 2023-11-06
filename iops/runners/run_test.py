from rich.progress import Progress, BarColumn, TextColumn
from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.prompt import Prompt
import time
import sys
from pathlib import Path
import math
import subprocess
import shutil
import uuid
import random

from iops.setup.iops_config import IOPSConfig
from iops.setup.generator import Generator
from iops.reports.report import Report
from iops.setup.tags import TestType


#install(show_locals=True)
console = Console()

# Custom Progress Bar
custom_columns = [
    TextColumn("[bold blue]{task.description}"),
    BarColumn(),
    TextColumn("{task.completed}/{task.total} ({task.percentage:.2f}%)"),
]


class TestRunner:
    
    def __init__(self, config_file: str, skip_confirmation: bool=False):
        self.config_file = config_file
        self.skip_confirmation = skip_confirmation        
        self.clean_workdir = 'yes'

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
        table.add_row("Max Nodes", str(self.config.max_nodes))
        table.add_row("Processes Per Node", str(self.config.processes_per_node))

        # Create a table for storage information
        table.add_row("")
        table.add_row("Benchmark Output", str(self.config.benchmark_output))        
        table.add_row("File System", str(self.config.file_system))
        # print max volume in GB
        table.add_row("Max Volume", f"{self.config.max_volume/ 2**30}GB")
        stripe_folders = self.config.stripe_folders
        if stripe_folders is not None:        
            stripe_folders = ", ".join(f"{stripe}" for stripe in self.config.stripe_folders)
        table.add_row("Stripe Folders", str(stripe_folders))


        # Create a table for execution information
        table.add_row("")    
        table.add_row("Mode", str(self.config.mode))
        table.add_row("Job Manager", str(self.config.job_manager))
        modules = self.config.modules
        if modules is not None:        
            modules = ", ".join(f"{module}" for module in self.config.modules)
        table.add_row("Modules", str(modules))
        slurm_constraint = self.config.slurm_constraint
        if slurm_constraint is not None:
            slurm_constraint = ", ".join(f"{constraint}" for constraint in self.config.slurm_constraint)
        table.add_row("Slurm Constraint", str(slurm_constraint))
        table.add_row("Workdir", str(self.config.workdir))
        table.add_row("Repetitions", str(self.config.repetitions))

        table.add_row("")  
        table.add_row("Slurm Template", str(self.config.slurm_template))
        table.add_row("Report Template", str(self.config.report_template))
        table.add_row("ior_2_csv script", str(self.config.ior_2_csv))

        table.add_row("")
        # Print the tables with section headers and horizontal rules   
        console.print(table)

        console.print("[bold yellow]Warning:[/bold yellow] You may need to adapt the template file for your system. Check the options in 'iops/templates/'\n")


        if not self.skip_confirmation:
            # Ask for user confirmation
            confirmed = Prompt.ask("Is this setup correct?", choices=["yes", "no"], default="yes")
            
            if confirmed.lower() != "yes":
                console.print("[bold red]Aborting test due to incorrect setup.")
                exit(1)
            
            # Ask for user confirmation to clean workdir
            self.clean_workdir = Prompt.ask("[bold cyan]Do you want to clean the working directory?[/bold cyan]", choices=["yes", "no"], default="yes")
        
        if self.clean_workdir.lower() == "yes":            
            console.print("[bold green]Cleaning the working directory...[/bold green]")
            self.__clean_workdir()
        else:
            console.print("[bold yellow]Preserving the working directory.[/bold yellow]")
            
        console.print("\n")
        
        console.print(Panel(f"[bold green]Starting test...", expand=True))

    def __generate_file_cases(self, benchmark_output: Path, test_folder: Path, dict_info = None):        
        cases = []
        start_size = 256 * 2**20  # 256 MiB
        max_size = self.config.max_volume
        
        # Calculate how many steps are needed
        num_steps = int(math.log(max_size / start_size, 2)) + 1

        # by default the number of nodes for the file_size tests is 4, 
        # except if the max_nodes is less than 4
        # in this case, we will use the max_nodes
        num_nodes = 4
        if num_nodes > self.config.max_nodes:
            num_nodes = self.config.max_nodes

        total_processes = num_nodes * self.config.processes_per_node

        panel_text = f"""        
        [bold green]Total size: {max_size/2**30:.2f}GB[/bold green]
        [bold green]Total processes: {total_processes}[/bold green]
        [bold green]Total nodes: {num_nodes}[/bold green]
        """

        console.print(Panel(panel_text, title="File Size Test", expand=True))

        for i in range(num_steps):
            current_size = start_size * (2 ** i)
            bytes_per_process = current_size / total_processes

            file_name = f"filesize_{current_size}_{i}.sh"
            file_path = test_folder / f"{i}"
            file_path.mkdir(exist_ok=True)

            case = {
                "job_name": f"iops_filesize_{current_size}_{i+1}",
                #"partition": "The partition to submit the job to",
                "ntasks":total_processes,
                "nodes": num_nodes,                
                "ntasks_per_node": self.config.processes_per_node,
                "time": "04:00:00",
                "chdir": file_path,
                "constraint": self.config.slurm_constraint,
                "modules": self.config.modules,
                "ior_output_path": benchmark_output,
                "ior_parameter": f"-w -t 1m -b {bytes_per_process}b -k"                
            }
            # generate the slurm script            
            Generator.slurm_script(self.config.slurm_template, file_path, file_name, case)
            console.print(f"[bold green]Created file:[/bold green] [bold cyan]{file_path/file_name}[/bold cyan]...")

            cases.append(file_path/file_name)        
        
        console.print("\n")        
        
        return cases
    
    def __generate_striping_cases(self, test_folder : Path, dict_info = None):        
        cases = []
        file_size = 32 * 2**30
        num_computing_nodes = 4

                
        panel_text = f"""
        [bold green]Computing nodes {num_computing_nodes}[/bold green]
        [bold green]File size: {file_size/2**30}GB[/bold green]        
        [bold green]Striping folder: {self.config.stripe_folders}[/bold green]  
        """

        console.print(Panel(panel_text, title="Striping Tests", expand=True))
        
        i = 0
        for stripe_folder in self.config.stripe_folders:            
            total_processes = num_computing_nodes * self.config.processes_per_node
            bytes_per_process = file_size / total_processes

            file_name = f"striping_{stripe_folder}_{i}.sh"
            file_path = test_folder / f"{i}"
            file_path.mkdir(exist_ok=True)
      
            case = {
                "job_name": f"iops_striping_{i+1}",
                #"partition": "The partition to submit the job to",
                "ntasks":total_processes,
                "nodes": num_computing_nodes,                
                "ntasks_per_node": self.config.processes_per_node,
                "time": "04:00:00",
                "chdir": file_path,
                "constraint": self.config.slurm_constraint,
                "modules": self.config.modules,
                "ior_output_path": self.config.benchmark_output / stripe_folder,
                "ior_parameter": f"-w -t 1m -b {bytes_per_process}b -k"                
            }
            # generate the slurm script            
            Generator.slurm_script(self.config.slurm_template, file_path, file_name, case)
            console.print(f"[bold green]Created file:[/bold green] [bold cyan]{file_path/file_name}[/bold cyan]...")
            cases.append(file_path/file_name)        

            i += 1
        
        console.print("\n")        
        
        return cases

    def __generate_computing_cases(self, benchmark_output : Path, test_folder: Path, dict_info = None):        
        cases = []
        current_nodes = 1
        max_nodes = self.config.max_nodes
        file_size = 32 * 2**30 # 32 GB hardcoded

               
        panel_text = f"""
        [bold green]Max nodes {max_nodes}[/bold green]
        [bold green]File size: {file_size/2**30}GB[/bold green]        
        [bold green]Processes per Node: {self.config.processes_per_node}
        """

        console.print(Panel(panel_text, title="Computing Nodes Tests"))
        i = 0
        while current_nodes <= max_nodes:
            total_processes = current_nodes * self.config.processes_per_node
            bytes_per_process = file_size / total_processes

            file_name = f"computing_{current_nodes}_{i}.sh"
            file_path = test_folder / f"{i}"
            file_path.mkdir(exist_ok=True)

            case = {
                "job_name": f"iops_computing_{current_nodes}_{i+1}",
                #"partition": "The partition to submit the job to",
                "ntasks":total_processes,
                "nodes": current_nodes,                
                "ntasks_per_node": self.config.processes_per_node,
                "time": "04:00:00",
                "chdir": file_path,
                "constraint": self.config.slurm_constraint,
                "modules": self.config.modules,
                "ior_output_path": benchmark_output,
                "ior_parameter": f"-w -t 1m -b {bytes_per_process}b -k"                
            }
            # generate the slurm script            
            Generator.slurm_script(self.config.slurm_template, file_path, file_name, case)
            console.print(f"[bold green]Created file:[/bold green] [bold cyan]{file_path/file_name}[/bold cyan]...")
            cases.append(file_path/file_name)        

            current_nodes = current_nodes * 2
            i += 1
        
        console.print("\n")        
        
        return cases

    def submit_test_to_slurm(self, test: Path):
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
   
    def __clean_workdir(self):
        try:
            # Clean everything inside the working directory
            for item in self.config.workdir.iterdir():
                if item.is_file() or item.is_symlink():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
        except Exception as e:
            console.print("[bold red]Error:[/bold red] {}".format(str(e)))
            sys.exit(1)

    def __format_time(self, seconds: float) -> str:
        hours, remainder = divmod(int(seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours} hours, {minutes} minutes, and {seconds} seconds"

    def run(self) -> None:

        start_time = time.time()
        error = False

        reports = []
        all_tests = []

        try:
            # First, generate the folder structure
            # Create 'filesize' folder and subfolders for each file size step
            
            for round in (0, 1):

                report = Report(self.config, report_id=round, description=f"Test report {round}")          
                    

                benchmark_output = self.config.benchmark_output

                if round == 1:
                    benchmark_output = benchmark_output / "ior_8"
                    striping_folder = None
                else:
                     # Create 'striping' folder
                    striping_folder = self.config.workdir / f'striping_{round}'
                    report.add_test(striping_folder, test_id= uuid.uuid4(), type=TestType.STRIPING)
                    striping_folder.mkdir(exist_ok=True)
                    # let's create the slurm scripts to generate the striping tests
                    all_tests.extend(self.__generate_striping_cases(striping_folder))

                filesize_folder = self.config.workdir / f'filesize_{round}'
                filesize_folder.mkdir(exist_ok=True)
                report.add_test(filesize_folder,test_id= uuid.uuid4(), type=TestType.FILESIZE)                
                # Then, let's create the slurm scripts to generate the file size tests
                all_tests.extend(self.__generate_file_cases(benchmark_output, filesize_folder))

                  
                # Create 'computing' folder and subfolders for each compute node
                computing_folder = self.config.workdir / f'computing_{round}'
                computing_folder.mkdir(exist_ok=True)
                report.add_test(computing_folder, test_id= uuid.uuid4(), type=TestType.COMPUTING)               
                # Finally, let's create the slurm scripts to generate the computing tests
                all_tests.extend(self.__generate_computing_cases(benchmark_output, computing_folder))

                reports.append(report)  
            
            with Progress(*custom_columns, console=console, transient=True) as progress:
                total_tests = len(all_tests) * self.config.repetitions
                task_id = progress.add_task("[cyan]Submitting...", total=total_tests)
                
                for i in range(self.config.repetitions):
                    console.print(f"Repetition [bold green]{i+1}[/bold green] of [bold green]{self.config.repetitions}[/bold green]")
                    random.shuffle(all_tests)
                    
                    for test in all_tests:
                        self.submit_test_to_slurm(test)
                        progress.advance(task_id)            

            
            console.print("[bold green]All jobs completed successfully.")            
            console.print(Panel("Generating Report", expand=True))            
                    
            Generator.report(reports, self.config.reportdir / "report.html", self.config)
            
                
           

        except KeyboardInterrupt:
            # Check if job is still in queue
            console.print("[bold red]Aborting test due to user interruption.")
            console.print("[bold yellow]Warning:[/bold yellow] You may have an ongoing job in the job manager.")
            error = True

        except Exception as e:
            console.print("[bold red]Error:[/bold red] {}".format(str(e)))
            error = True
        
        end_time = time.time()  # Record the end time
        execution_time = end_time - start_time  # Compute the execution time
        formatted_time = self.__format_time(execution_time)
        console.print(f"[bold green]Execution Time:[/bold green] {formatted_time}")

        if error:
            sys.exit(1)