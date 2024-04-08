#!/usr/bin/env python3
import argparse
from argparse import RawTextHelpFormatter

import sys
import shutil

from iops.util.checkers import Checker
from iops.util.generator import Generator
from iops.util.tags import TestType

from iops.core.runner import Runner, Round
from iops.core.config import IOPSConfig


from rich.progress import BarColumn, TextColumn
from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.prompt import Prompt

console = Console()       
            
                
custom_columns = [
    TextColumn("[bold blue]{task.description}"),
    BarColumn(),
    TextColumn("{task.completed}/{task.total} ({task.percentage:.2f}%)"),
]



app_version = "1.0"
app_name = "IOPS"
app_description = f"""
    {app_name} version {app_version}  

    
    IOPS (I/O Performance Evaluation benchmark Suite) is an automated utility designed to 
    help you fine-tune the I/O performance of your Parallel File System (PFS). 
    Rather than acting as a standalone benchmarking tool, IOPS leverages existing open-source benchmarks, 
    such as IOR, to perform a comprehensive search across multiple parameters:

    - Number of compute nodes and I/O processes
    - Data volume and file size
    - I/O access patterns
    - Striping configurations

    The tool conducts these tests automatically, processes the results, and generates performance graphs to provide
    actionable insights.

    Usage:
    iops config.ini

    
    For a complete list of options and more detailed information, visit https://gitlab.inria.fr/lgouveia/iops


     
    Authors:     
    Luan Teylo (2023)
    
    """
def clean_workdir(config : IOPSConfig) -> None:
    try:
        # Clean everything inside the working directory
        for item in config.workdir.iterdir():
            if item.is_file() or item.is_symlink():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
    except Exception as e:
        console.print("[bold red]Error:[/bold red] {}".format(str(e)))
        sys.exit(1)



def print_config(config: IOPSConfig, skip_confirmation: bool):
    # Display startup message with a panel
    console.print(Panel(f"[bold green]Starting test with configuration file {config.config_path}...", expand=False))
    
    # Create a table for node information
    table = Table(show_header=True, header_style="bold blue", box=box.SIMPLE)
    table.add_column("Setting", style="dim", width=30)
    table.add_column("Value")
    table.add_row("Max Nodes", str(config.max_nodes))
    table.add_row("Processes Per Node", str(config.processes_per_node))

    # Create a table for storage information
    table.add_row("")
    table.add_row("File System Dir:", str(config.filesystem_dir))                
    # print max volume in GB
    table.add_row("Max Volume", f"{config.max_volume/ 2**30}GB")
    stripe_folders = config.stripe_folders
    if stripe_folders is not None:        
        stripe_folders = ", ".join(f"{stripe}" for stripe in config.stripe_folders)
    table.add_row("Stripe Folders", str(stripe_folders))


    # Create a table for execution information
    table.add_row("")    
    table.add_row("Mode", str(config.mode))    
    table.add_row("Job Manager", str(config.job_manager))
    
    
    modules = config.modules
    if modules is not None:        
        modules = ", ".join(f"{module}" for module in config.modules)
    table.add_row("Modules", str(modules))        
    table.add_row("Workdir", str(config.workdir))
    table.add_row("Repetitions", str(config.repetitions))

    table.add_row("")  
    table.add_row("Slurm Template", str(config.slurm_template))
    table.add_row("Report Template", str(config.report_template))
    table.add_row("ior_2_csv script", str(config.ior_2_csv))

    table.add_row("")
    slurm_constraint = config.slurm_constraint
    if slurm_constraint is not None:
        slurm_constraint = ", ".join(f"{constraint}" for constraint in config.slurm_constraint)
    table.add_row("Slurm Constraint", str(slurm_constraint))
    table.add_row("Slurm Partition", str(config.slurm_partition))
    table.add_row("Slurm Time", str(config.slurm_time))
    table.add_row("")

    table.add_row("")
    # Print the tables with section headers and horizontal rules   
    console.print(table)

    console.print("[bold yellow]Warning:[/bold yellow] You may need to adapt the template file for your system. Check the options in 'iops/templates/'\n")


    if not skip_confirmation:
        # Ask for user confirmation
        confirmed = Prompt.ask("Is this setup correct?", choices=["yes", "no"], default="yes")
        
        if confirmed.lower() != "yes":
            console.print("[bold red]Aborting test due to incorrect setup.")
            exit(1)
        
    # Ask for user confirmation to clean workdir
    confirmed = Prompt.ask("[bold cyan]Do you want to clean the working directory?[/bold cyan]", choices=["yes", "no"], default="yes")

    if confirmed.lower() == "yes":            
        console.print("[bold green]Cleaning the working directory...[/bold green]")
        clean_workdir(config)
    else:
        console.print("[bold yellow]Preserving the working directory.[/bold yellow]")
        
    console.print("\n")
    
    console.print(Panel(f"[bold green]Starting test...", expand=True))




def main():
    parser = argparse.ArgumentParser(formatter_class=RawTextHelpFormatter, description=app_description)

    parser.add_argument('conf', help="full path to the .ini file", type=str, nargs='?')
    parser.add_argument('--check_setup', help="check if all dependencies are correctly installed", action="store_true")
    parser.add_argument('--generate_ini', nargs='?', const='default_config.ini', default=None,
                    help="generate a default .ini configuration file. Optionally, specify the file name and path.")
    parser.add_argument('-y', '--yes', help="automatically confirm the setup (Attention: the workdir directory will be cleaned without asking for confirmation)", action="store_true")


    args = parser.parse_args()



    if args.generate_ini:
        file_name = args.generate_ini if args.generate_ini != True else 'default_config.ini'
        Generator.ini_file(file_name)

        console.print(f"[bold green]Configuration file {file_name} generated successfully.")
        
        return  # Exit after generating the init file

    if args.conf is None:
        console.print("[bold red]Error: Configuration file is required unless --generate_ini is used.")        
        return
    

    if args.check_setup:
        Checker.check_ini_file(args.conf)
        Checker.check_ior_installation()            
        return  # Exit after running setup checks
    
    
    # Initialize and load configuration
    config = IOPSConfig(args.conf)
    print_config(config, args.yes)

    parameters = {
        'volume_mb': 1,
        'storage_folder': config.stripe_folders[0],
        'computing_nodes': 1
        }

    round = Round(parameters=parameters, test_type=TestType.COMPUTING)
    Runner.run(round)


if __name__ == "__main__":
    main()

 