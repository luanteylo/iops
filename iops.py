#!/usr/bin/env python3
import argparse
from argparse import RawTextHelpFormatter
from iops.setup.checkers import Checker
from iops.setup.generator import Generator
from iops.setup.iops_config import IOPSConfig

from rich.progress import Progress
from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.prompt import Prompt
import time


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



console = Console()

def start_test(config_file, skip_confirmation=False):
    # Display startup message with a panel
    console.print(Panel(f"[bold green]Starting test with configuration file {config_file}...", 
                        expand=False))

    # Initialize and load configuration
    config = IOPSConfig(config_file)
    
    # Create a table for node information
    table = Table(show_header=True, header_style="bold blue", box=box.SIMPLE)
    table.add_column("Setting", style="dim", width=30)
    table.add_column("Value")

    table.add_row("Nodes", str(config.nodes))
    table.add_row("Max Nodes", str(config.max_nodes))
    table.add_row("Max Processes Per Node", str(config.max_processes_per_node))

    # Create a table for storage information
    table.add_row("")
    table.add_row("Storage Path", str(config.path))
    table.add_row("Max OST", str(config.max_ost))
    table.add_row("Default Stripe Count", str(config.default_stripe_count))
    table.add_row("Default Stripe Size", str(config.default_stripe_size))
    table.add_row("File System", str(config.file_system))

    # Create a table for execution information
    table.add_row("")    
    table.add_row("Mode", str(config.mode))

    # Print the tables with section headers and horizontal rules   
    console.print(table)

    if not skip_confirmation:
        # Ask for user confirmation
        confirmed = Prompt.ask("Is this setup correct?", choices=["yes", "no"], default="yes")
        
        if confirmed.lower() != "yes":
            console.print("[bold red]Aborting test due to incorrect setup.")
            exit(1)
        
    console.print("\n")
    

    total_rounds = 10

    with Progress() as progress:

        task1 = progress.add_task("[cyan]Running tests...\n", total=total_rounds)
        
        for round_num in range(1, total_rounds + 1):        
            # Update the progress bar
            progress.update(task1, advance=1)
            progress.print(f"[bold green]Completed Round {round_num} of {total_rounds}...\n")

            # wait for some time to simulate work            
            time.sleep(5)


    

    
    

def main():
    parser = argparse.ArgumentParser(formatter_class=RawTextHelpFormatter, description=app_description)

    parser.add_argument('conf', help="full path to the .ini file", type=str, nargs='?')
    parser.add_argument('--check_setup', help="check if all dependencies are correctly installed", action="store_true")
    parser.add_argument('--generate_ini', nargs='?', const='default_config.ini', default=None,
                    help="generate a default .ini configuration file. Optionally, specify the file name and path.")
    parser.add_argument('-y', '--yes', help="automatically confirm the setup", action="store_true")


    args = parser.parse_args()



    if args.check_setup:
        Checker.check_ior_installation()            
        return  # Exit after running setup checks

    if args.generate_ini:
        file_name = args.generate_ini if args.generate_ini != True else 'default_config.ini'
        Generator.generate_ini_file(file_name)
        
        return  # Exit after generating the init file

    if args.conf is None:
        print("Error: Configuration file is required unless --check_setup or --generate_init is used.")
        return

    start_test(args.conf, skip_confirmation=args.yes)


if __name__ == "__main__":
    main()

 