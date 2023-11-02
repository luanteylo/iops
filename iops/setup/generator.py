import configparser
import logging
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

from iops.setup.iops_config import IOPSConfig

from typing import List

class Generator:
    @staticmethod
    def generate_ini_file(file_name):
        logging.info("Generating default configuration file...")
        config_nodes = configparser.ConfigParser()
        config_storage = configparser.ConfigParser()
        config_execution = configparser.ConfigParser()
    
        config_nodes['nodes'] = {
            'nodes': 'node[1-32]',
            'max_nodes': '32',
            'max_processes_per_node': '64',
        }

        
        config_storage['storage'] = {
            'path': '/path/to/storage',            
            'max_ost': '8',
            'default_stripe_count': '4',
            'default_stripe_size': '1048576 # In bytes', 
            'file_system': 'lustre | beegfs | local # Select the file system',
            'max_volume':  '34359738368 # max volume size in bytes (to limit the size of the benchmarked file size)',
        }

        config_execution['execution'] = {
            'mode': 'fast | complete # Select the mode of execution',
            'job_manager': 'slurm | None # Specify the job manager. If "None" is provided, it will execute the benchmark locally',
            'modules': 'mpi, some_other_module | None # Specify the list of modules to load using "module add <module>". If "None" is provided, no module is loaded',
            'workdir': '/path/to/workdir # Specify the working directory, i.e., where the benchmark will be executed',
        }

        
        with open(file_name, 'w') as config_file:
            config_file.write("# This is a default configuration file for IOPS.\n")        
            config_file.write("# Edit it to suit your needs.\n\n")
            config_nodes.write(config_file)

            config_storage.write(config_file)

            config_file.write("# Execution mode\n")
            config_file.write("# - fast: Run the benchmark with a reduced number of repetitions (less accurate)\n")
            config_file.write("# - complete: Run the benchmark with the full number of repetitions (more accurate)\n")
            config_execution.write(config_file)

        
        logging.info(f"Default configuration file generated as {file_name}")
    
    @staticmethod
    def generate_slurm_script(template_path: Path, output_path: str, file_name: str, case: dict) -> None:
        '''
        Generates a bash script for a given case.
        The bash script is generated using the template file in template_path and is saved in the output_path directory.
        '''
        # create the Jinja2 environment and load the template
        env = Environment(loader=FileSystemLoader(str(template_path.parent)))
        template = env.get_template(template_path.name)

        # generate the script
        bash_script = template.render(**case)
        # write the script to a file
        script_filename = Path(output_path, file_name)
        with open(script_filename, 'w') as f:
            f.write(bash_script)

   

        


