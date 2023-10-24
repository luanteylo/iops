import configparser
import logging


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
            'file_system': 'lustre | beegfs # Select the parallel file system',
        }

        config_execution['execution'] = {
            'mode': 'fast | complete # Select the mode of execution',
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
