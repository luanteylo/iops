#!/usr/bin/env python3
import argparse
from argparse import RawTextHelpFormatter

from rich.console import Console
from iops.util.checkers import Checker
from iops.util.generator import Generator
from iops.util.tags import TestType, jobManager

from iops.core.runner import Runner, Round
from iops.core.config import IOPSConfig

from iops.reports.report import Report


console = Console()   

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
    config = IOPSConfig(config_path=args.conf)
    config.print_config(skip_confirmation=args.yes)

    # Create a round object with static parameters
    round_volume = Round(volume=1073741824, 
                         folder_index=0, 
                         computing=1, 
                         config=config, 
                         test_type=TestType.FILESIZE)
    
    round_computing = Round(volume=1073741824, 
                            folder_index=0, 
                            computing=1, 
                            config=config, 
                            test_type=TestType.COMPUTING)
    
    round_striping = Round(volume=1073741824, 
                           folder_index=0, 
                           computing=1, 
                           config=config, 
                           test_type=TestType.STRIPING)    

    report = Report(config, 1, "IOPS Report")                     
    
    for round in (round_volume, round_computing, round_striping):
        if round.config.job_manager == jobManager.LOCAL:
            if round.test_type == TestType.FILESIZE:
                Runner.run(round)
                report.add_round(round)
        elif round.config.job_manager == jobManager.SLURM:
            Runner.run(round)
            report.add_round(round)


    
    # generating the reports
    report.generate_report()
    console.print("[bold green]Exiting...")


if __name__ == "__main__":
    main()

 