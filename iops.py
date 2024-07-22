#!/usr/bin/env python3
import argparse
from argparse import RawTextHelpFormatter
from rich.console import Console


import sys
from datetime import datetime

from iops.util.checkers import Checker
from iops.util.generator import Generator
from iops.util.tags import TestType
from iops.core.runner import Runner
from iops.core.round import Round
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
    Francieli Boito (2024-)
    Mahamat Abdraman (2024-)   
    
    """


def run(config: IOPSConfig) ->  Report:
    """
    build the next round based on the previous round results
    :param config:
    :param round_parameters:
    :return:
    """
    report = Report(config, 1, "IOPS Report") 

    
    
    for io_pattern, file_mode in config.io_patterns:
        parameters = {TestType.FILESIZE: config.min_volume, TestType.STRIPING: config.get_stripe_folder(config.default_stripe), TestType.COMPUTING: config.min_nodes}        
        for test_type in config.tests:
            current_round = Round.factory(pattern=io_pattern,
                                          file_mode=file_mode, 
                                          config=config, 
                                          test_type=test_type, 
                                          initial_parameters=parameters)
            Runner.run(current_round)
            report.add_round(current_round)
            # build the round
            parameters[test_type] = current_round.get_best_parameter()
            console.print(f"[bold green]Round {current_round.round_id} completed successfully.")
            console.print(f"[bold green]Best parameter for {test_type.name}: {parameters[test_type]}")

    console.print(f"[bold green]All rounds completed successfully.")
    return report


def main():
    parser = argparse.ArgumentParser(formatter_class=RawTextHelpFormatter, description=app_description)

    parser.add_argument('conf', help="full path to the .ini file", type=str, nargs='?')
    parser.add_argument('--check_setup', help="check if all dependencies are correctly installed", action="store_true")
    parser.add_argument('--generate_ini', nargs='?', const='default_config.ini', default=None, help="generate a default .ini configuration file. Optionally, specify the file name and path.")
    parser.add_argument('-y', '--yes', help="automatically confirm the setup (Attention: the workdir directory will be cleaned without asking for confirmation)", action="store_true")   
    # add verbose mode to print errors
    parser.add_argument('-v', '--verbose', help="print the full error traceback", action="store_true")
    
    args = parser.parse_args()

    start_time = datetime.now()

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
        report.generate_html()        
        report.generate_txt(run_time=datetime.now() - start_time)

    except Exception as e:
        console.print(f"[bold white]{e}[/ bold white]")
        if args.verbose:
            raise e
        else:
            console.print(f"[bold red]Run with --verbose to see the full error traceback.")
            sys.exit(1)
        
    console.print(f"[bold green]Execution completed successfully in {datetime.now() - start_time}.")


if __name__ == "__main__":
    main()

 