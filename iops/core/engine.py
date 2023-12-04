from rich.progress import BarColumn, TextColumn
from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.prompt import Prompt
import time
import sys
import shutil

from typing import List, Optional

from iops.core.config import IOPSConfig
from iops.core.search_methods import SearchMethod, Test
from iops.reports.report import Report
from iops.util.tags import TestType


# This class is the main engine of the application. It is responsible for:
# 1. Loading the configuration file
# 2. Displaying the configuration to the user
# 3. Cleaning the working directoryfrom typing import List
# 4. Running the benchmark
# 5. Reporting the results


 
#install(show_locals=True)
console = Console()       
            
                
custom_columns = [
    TextColumn("[bold blue]{task.description}"),
    BarColumn(),
    TextColumn("{task.completed}/{task.total} ({task.percentage:.2f}%)"),
]


class Engine:
    
    def __init__(self, config_file: str, skip_confirmation: bool=False):
        self.config_file = config_file
        self.skip_confirmation = skip_confirmation        
        self.clean_workdir = 'yes'
        self.reports = []

        try:
            # Initialize and load configuration
            self.config = IOPSConfig(config_file)
            # Initialize search method
            self.search_method = SearchMethod.create(self.config.search_method, self.config)

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
        table.add_row("File System Dir:", str(self.config.filesystem_dir))                
        # print max volume in GB
        table.add_row("Max Volume", f"{self.config.max_volume/ 2**30}GB")
        stripe_folders = self.config.stripe_folders
        if stripe_folders is not None:        
            stripe_folders = ", ".join(f"{stripe}" for stripe in self.config.stripe_folders)
        table.add_row("Stripe Folders", str(stripe_folders))


        # Create a table for execution information
        table.add_row("")    
        table.add_row("Mode", str(self.config.mode))
        table.add_row("Search Method", str(self.config.search_method))
        table.add_row("Job Manager", str(self.config.job_manager))
        table.add_row("Benchmark Tool", str(self.config.benchmark_tool))
        modules = self.config.modules
        if modules is not None:        
            modules = ", ".join(f"{module}" for module in self.config.modules)
        table.add_row("Modules", str(modules))        
        table.add_row("Workdir", str(self.config.workdir))
        table.add_row("Repetitions", str(self.config.repetitions))

        table.add_row("")  
        table.add_row("Slurm Template", str(self.config.slurm_template))
        table.add_row("Report Template", str(self.config.report_template))
        table.add_row("ior_2_csv script", str(self.config.ior_2_csv))

        table.add_row("")
        slurm_constraint = self.config.slurm_constraint
        if slurm_constraint is not None:
            slurm_constraint = ", ".join(f"{constraint}" for constraint in self.config.slurm_constraint)
        table.add_row("Slurm Constraint", str(slurm_constraint))
        table.add_row("Slurm Partition", str(self.config.slurm_partition))
        table.add_row("Slurm Time", str(self.config.slurm_time))
        table.add_row("")

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

    def __execute_rounds(self, rounds: List[List[Test]]) -> None:
        for test in rounds:
            print(test)
    
    def __build_report(self,  report_id: int, round: List[Test]) -> Report:
        report = Report(self.config, report_id=report_id, description="a report")
        
        for test in round:
            report.add_test(test)          
        
        return report
            

         
    
    def __process_report(self, report: Report) -> Optional[int]:
        # TODO: process the report and return the value for the next round
        if report.testtype == TestType.FILESIZE:
            # return 32GB (in bytes)
            return 32 * 2**30
        elif report.testtype == TestType.COMPUTING:
            # return 32
            return 32
        elif report.testtype == TestType.STRIPING:
            return None
    

    def run(self) -> None:

        start_time = time.time()
        error = False
        run = True
        # config = IOPSConfig("/home/luan/Devel/io-ps/default_config.ini")     
        value_nround = None

        round_counter = 0

        try:

            while run:
                # Build the next round
                round = self.search_method.build_round(value=value_nround)
                if round not in (None, []):
                    status = self.__execute_rounds(round)
                    
                    if status == False:
                        raise Exception(f"Error executing round {round_counter}")
                    
                    report = self.__build_report(round)
                    value_nround = self.__process_report(report)

                    # add report to the list
                    self.reports.append(report)

                    round_counter += 1

                else:
                    self.build_html_report()
                    run = False
                
 
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



# let's test the engine

engine = Engine(config_file="/home/luan/Devel/io-ps/default_config.ini", skip_confirmation=True)


engine.run()