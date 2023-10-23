#!/usr/bin/env python3

import argparse
from argparse import RawTextHelpFormatter
import logging
import subprocess
import configparser
from iops.setup.checkers import Checker

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


class ColoredFormatter(logging.Formatter):
    COLORS = {
        'WARNING': '\033[0m \033[1;33m',
        'INFO': '\033[0m \033[1;32m',
        'DEBUG': '\033[0m \033[1;34m',
        'CRITICAL': '\033[0m \033[1;41m',
        'ERROR': '\033[0m \033[1;31m'
    }

    def format(self, record):
        log_message = super(ColoredFormatter, self).format(record)
        return f"{self.COLORS.get(record.levelname)}{record.levelname}\033[0m - {log_message}"

def configure_logging(verbose):
    log_format = "%(message)s"
    
    formatter = ColoredFormatter(log_format)

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    logger = logging.getLogger()
    logger.addHandler(handler)
    
    if verbose:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)




def generate_ini_file(file_name='default_config.ini'):
    logging.info("Generating default configuration file...")
    config_nodes = configparser.ConfigParser()
    config_storage = configparser.ConfigParser()
   
    config_nodes['nodes'] = {
        'nodes': 'bora[1-32]',
        'max_cpu_per_node': '32',
        'max_processes': '64',
    }

    
    config_storage['storage'] = {
        'path': '/path/to/storage',
    }
    
    with open(file_name, 'w') as config_file:
        config_file.write("#This is a default configuration file for IOPS. You can edit it to suit your needs.\n")        
        config_file.write("#Nodes configuration\n")
        config_nodes.write(config_file)

        config_file.write("#Storage configuration\n")    
        config_storage.write(config_file)

    
    logging.info(f"Default configuration file generated as {file_name}")

def start_test(config_file):
    logging.info(f"Starting test with configuration file {config_file}...")
    

def main():
    parser = argparse.ArgumentParser(formatter_class=RawTextHelpFormatter, description=app_description)

    parser.add_argument('conf', help="full path to the .ini file", type=str, nargs='?')
    parser.add_argument('-v', '--verbose', help="increase output verbosity", action="store_true")
    parser.add_argument('--check_setup', help="check if all dependencies are correctly installed", action="store_true")
    parser.add_argument('--generate_ini', nargs='?', const='default_config.ini', default=None,
                    help="generate a default .ini configuration file. Optionally, specify the file name and path.")


    args = parser.parse_args()

    configure_logging(args.verbose)

    if args.check_setup:
        Checker.check_ior_installation()            
        return  # Exit after running setup checks

    if args.generate_ini:
        file_name = args.generate_ini if args.generate_ini != True else 'default_config.ini'
        generate_ini_file(file_name)
        return  # Exit after generating the init file

    if args.conf is None:
        print("Error: Configuration file is required unless --check_setup or --generate_init is used.")
        return

    start_test(args.conf)


if __name__ == "__main__":
    main()

 