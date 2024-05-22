#!/usr/bin/env python3
import argparse
from argparse import RawTextHelpFormatter
from rich.console import Console
import sys

from iops.util.checkers import Checker
from iops.util.generator import Generator
from iops.util.tags import TestType, jobManager, ExecutionMode
from iops.core.runner import Runner, Round
from iops.core.config import IOPSConfig
from iops.reports.report import Report

from version import __version__

from typing import List
console = Console()   


app_name = "IOPS"
app_description = f"""
    {app_name} version {__version__}  

    
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


def run(config: IOPSConfig) ->  Report:
    """
    build the next round based on the previous round results
    :param config:
    :param round_parameters:
    :return:
    """
    report = Report(config, 1, "IOPS Report") 
    parameters = {"volume": 1024, "folder_index": 0, "computing": 1}
    
    current_round = None    

    for io_pattern, file_mode in config.io_patterns:
        console.print(f"[bold]Running tests for {io_pattern.name}:{file_mode.name}[/bold]")        
        for test_type in config.tests:
            # build the round
            if current_round is not None:
                # update the parameters based on the previous round results        
                if test_type == TestType.FILESIZE:
                    # get filesize from previous round
                    parameters["volume"] = current_round.get_volume()                
                elif test_type == TestType.COMPUTING:
                    # get computing nodes from previous round
                    parameters["computing"] = current_round.get_computing_nodes()
                elif test_type == TestType.STRIPING:
                    # get ost folder from previous round
                    parameters["folder_index"] = current_round.get_folder_index()
                
            current_round = Round(pattern=io_pattern, file_mode=file_mode, config=config, test_type=test_type, round_parameters=parameters)
            Runner.run(current_round)
            report.add_round(current_round)
        
    return report

def main():
    parser = argparse.ArgumentParser(formatter_class=RawTextHelpFormatter, description=app_description)

    parser.add_argument('conf', help="full path to the .ini file", type=str, nargs='?')
    parser.add_argument('--check_setup', help="check if all dependencies are correctly installed", action="store_true")
    parser.add_argument('--generate_ini', nargs='?', const='default_config.ini', default=None, help="generate a default .ini configuration file. Optionally, specify the file name and path.")
    parser.add_argument('-y', '--yes', help="automatically confirm the setup (Attention: the workdir directory will be cleaned without asking for confirmation)", action="store_true")   
    
    args = parser.parse_args()

    if args.generate_ini:
        file_name = args.generate_ini if args.generate_ini != True else 'default_config.ini'
        Generator.ini_file(file_name)
        console.print(f"[bold green]Configuration file {file_name} generated successfully.")        
        sys.exit(0)  # Exit after generating the init file

    if args.conf is None:
        console.print("[bold red]Error: Configuration file is required unless --generate_ini is used.")        
        sys.exit(1)
    

    if args.check_setup:        
        r1 = Checker.check_ini_file(args.conf)            
        r2 = Checker.check_ior_installation()   
        r3 = Checker.check_mpi()         
        sys.exit(0 if r1 and r2 and r3 else 1)  # Exit after running setup checks
    
    try:
        # Initialize and load configuration
        config = IOPSConfig(config_path=args.conf)   
        config.print_config(skip_confirmation=args.yes)              
        report = run(config)
        report.generate_report()        
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] [white]{e}[/white]")
        #raise e


if __name__ == "__main__":
    main()

 