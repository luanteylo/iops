from pathlib import Path
import configparser

from iops.utils.config_loader import load_config, validate_config, IOPSConfig
from iops.utils.logger import HasLogger


class FileUtils(HasLogger):
    """
    Utility class to handle configuration file generation, loading, and validation for IOPS.
    """

    def generate_iops_config(self, file_name: Path) -> None:
        """
        Generates a default IOPS configuration .ini file.
        """
        config_nodes = configparser.ConfigParser()
        config_storage = configparser.ConfigParser()
        config_execution = configparser.ConfigParser()
        config_template = configparser.ConfigParser()
        config_slurm = configparser.ConfigParser()  # Not used currently

        config_nodes['nodes'] = {
            'min_nodes': '1',
            'max_nodes': '32',
            'processes_per_node': '8',
            'cores_per_node': '32',
        }

        config_storage['storage'] = {
            'filesystem_dir': '/path/to/storage',
            'min_volume': '1024',
            'max_volume': '8192',
            'volume_step': '1024',
            'default_stripe': '0',
            'stripe_folders': "folder1, folder2, folder3, folder4"
        }

        config_execution['execution'] = {
            'test_type': 'write_only',
            'mode': 'normal',
            'search_method': 'greedy',
            'job_manager': 'slurm',
            'benchmark_tool': 'ior',
            'modules': 'None',
            'workdir': '/path/to/workdir',
            'repetitions': '5',
            'status_check_delay': '10',
            'wall_time': '00:30:00',
            'tests': 'filesize, computing, striping',
            'io_patterns': 'sequential:shared, random:shared',
            'wait_range': '0, 0'
        }

        config_template['template'] = {
            'bash_template': '$IOPS_HOME/iops/templates/slurm_template.sh.j2',
            'report_template': '$IOPS_HOME/iops/templates/report_template.html',
            'ior_2_csv': 'tools/ior_2_csv.py'
        }

        with open(file_name, 'w') as config_file:
            config_file.write("# IOPS default configuration\n\n")
            config_nodes.write(config_file)
            config_storage.write(config_file)
            config_execution.write(config_file)
            config_template.write(config_file)
            config_slurm.write(config_file)

        self.logger.info(f"Default IOPS config written to {file_name}")

    def load_iops_config(self, file_path: Path) -> IOPSConfig:
        """
        Loads and parses a configuration file.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"The configuration file {file_path} does not exist.")

        try:
            return load_config(file_path)
        except configparser.Error as e:
            raise configparser.Error(f"Error parsing the configuration file {file_path}: {e}") from e

    def validate_iops_config(self, config: IOPSConfig) -> None:
        """
        Validates a loaded configuration object.
        """
        try:
            validate_config(config)
        except ValueError as e:
            raise ValueError(f"Configuration validation failed: {e}") from e
