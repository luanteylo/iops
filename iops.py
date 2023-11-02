#!/usr/bin/env python3
import argparse
from argparse import RawTextHelpFormatter
from iops.setup.checkers import Checker
from iops.setup.generator import Generator
from iops.runners.run_test import TestRunner

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
    parser.add_argument('-y', '--yes', help="automatically confirm the setup", action="store_true")


    args = parser.parse_args()



    if args.generate_ini:
        file_name = args.generate_ini if args.generate_ini != True else 'default_config.ini'
        Generator.generate_ini_file(file_name)
        
        return  # Exit after generating the init file

    if args.conf is None:
        console.print("[bold red]Error: Configuration file is required unless --generate_ini is used.")        
        return
    

    if args.check_setup:
        Checker.check_ini_file(args.conf)
        Checker.check_ior_installation()            
        return  # Exit after running setup checks

    runner = TestRunner(args.conf, args.yes)
    runner.run()


if __name__ == "__main__":
    main()

 