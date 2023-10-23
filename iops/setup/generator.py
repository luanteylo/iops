import configparser
import logging


class Generator:
    @staticmethod
    def generate_ini_file(file_name):
        logging.info("Generating default configuration file...")
        config_nodes = configparser.ConfigParser()
        config_storage = configparser.ConfigParser()
    
        config_nodes['nodes'] = {
            'nodes': 'node[1-32]',
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
