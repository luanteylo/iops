from pathlib import Path
from ruamel.yaml import YAML
from iops.utils.config_loader import load_config, validate_config, IOPSConfig
from iops.utils.logger import HasLogger
from ruamel.yaml.parser import ParserError

class FileUtils(HasLogger):
    """
    Utility class to handle configuration file generation, loading, and validation for IOPS.
    """

    from pathlib import Path
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from iops.utils.config_loader import load_config, validate_config, IOPSConfig
from iops.utils.logger import HasLogger
from ruamel.yaml.parser import ParserError


class FileUtils(HasLogger):
    """
    Utility class to handle configuration file generation, loading, and validation for IOPS.
    """

    def generate_iops_config(self, file_name: Path) -> None:
        """
        Generates a default IOPS configuration YAML file with comments.
        """
        yaml = YAML()
        yaml.indent(mapping=2, sequence=4, offset=2)
        yaml.preserve_quotes = True

        data = CommentedMap()

        # --- Nodes ---
        nodes = data["nodes"] = CommentedMap()
        nodes["min_nodes"] = 1
        nodes.yaml_add_eol_comment("Minimum number of nodes to use", "min_nodes")
        nodes["max_nodes"] = 32        
        nodes.yaml_add_eol_comment("Maximum number of nodes to use", "max_nodes")
        nodes["node_step"] = 1
        nodes.yaml_add_eol_comment("Step size to increase nodes per test", "node_step")
        nodes["processes_per_node"] = 8
        nodes.yaml_add_eol_comment("Number of processes per node", "processes_per_node")
        nodes["cores_per_node"] = 32
        nodes.yaml_add_eol_comment("Number of physical cores per node", "cores_per_node")

        # --- Storage ---
        storage = data["storage"] = CommentedMap()
        storage["filesystem_dir"] = "/path/to/storage"
        storage.yaml_add_eol_comment("Root path of the storage filesystem", "filesystem_dir")
        storage["min_volume"] = 1024
        storage.yaml_add_eol_comment("Minimum data volume in MB", "min_volume")
        storage["max_volume"] = 8192
        storage.yaml_add_eol_comment("Maximum data volume in MB", "max_volume")
        storage["volume_step"] = 1024
        storage.yaml_add_eol_comment("Step size (MB) to increase volume per test", "volume_step")
        storage["default_stripe"] = 0
        storage.yaml_add_eol_comment("Default stripe count to apply", "default_stripe")
        storage["stripe_folders"] = ["folder1", "folder2", "folder3"]
        storage.yaml_set_comment_before_after_key("stripe_folders",before="Folders under filesystem_dir to apply striping")

        # --- Execution ---
        execution = data["execution"] = CommentedMap()
        execution["test_type"] = "write_only"
        execution.yaml_add_eol_comment("write_only or write_read", "test_type")
        execution["search_method"] = "greedy"
        execution.yaml_add_eol_comment("Search method for test generation", "search_method")
        execution["job_manager"] = "slurm"
        execution.yaml_add_eol_comment("Job scheduler to use", "job_manager")
        execution["benchmark_tool"] = "ior"
        execution.yaml_add_eol_comment("Benchmark tool to run", "benchmark_tool")
        execution["workdir"] = "/path/to/workdir"
        execution.yaml_add_eol_comment("Where test jobs and results are written", "workdir")
        execution["repetitions"] = 5
        execution.yaml_add_eol_comment("Repetitions per test case", "repetitions")
        execution["status_check_delay"] = 10
        execution.yaml_add_eol_comment("Delay (s) between job status checks", "status_check_delay")
        execution["wall_time"] = "00:30:00"
        execution.yaml_add_eol_comment("Max walltime for each job (hh:mm:ss)", "wall_time")
        execution["tests"] = ["volume", "nodes", "ost_count"]
        execution.yaml_add_eol_comment("Test dimensions (matrix axes)", "tests")
        execution["io_pattern"] = "sequential:shared"
        execution.yaml_add_eol_comment("I/O access patterns (e.g., sequential:shared or random:shared)", "io_pattern")
        

        # --- Template ---
        template = data["template"] = CommentedMap()
        
        template["bash_template"] = "$IOPS_HOME/iops/templates/slurm_template.sh.j2"
        template.yaml_add_eol_comment("Path to job submission script template", "bash_template")

        # --- Dump to file ---
        file_name = file_name.with_suffix('.yaml')
        with open(file_name, 'w') as f:
            yaml.dump(data, f)

        self.logger.info(f"Default IOPS config written to {file_name}")

    def load_iops_config(self, file_path: Path) -> IOPSConfig:
        """
        Loads and parses a configuration YAML file.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"The configuration file {file_path} does not exist.")

        try:
            return load_config(file_path)
        except (ParserError, ValueError) as e:
            raise ValueError(f"Error parsing the configuration file {file_path}: {e}") from e
 
    def validate_iops_config(self, config: IOPSConfig) -> None:
        """
        Validates a loaded configuration object.
        """
        try:
            validate_config(config)
        except Exception as e:
            raise e  # Can wrap with more context if desired
    
    def create_workdir(self, config: IOPSConfig) -> None:
        """
        Creates a new execution directory inside the configured work directory.
        If the base work directory does not exist, it will be created.
        Then, a subdirectory named 'execution_<id>' is created, where <id> is the next available integer.
        """
        base_workdir = config.execution.workdir

        # Ensure the base work directory exists
        if not base_workdir.exists():
            base_workdir.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"Created base work directory: {base_workdir}")
        else:
            self.logger.info(f"Base work directory already exists: {base_workdir}")

        # Find all existing execution directories
        execution_dirs = [
            d for d in base_workdir.iterdir()
            if d.is_dir() and d.name.startswith("execution_") and d.name.split('_')[1].isdigit()
        ]

        # Determine the next execution ID
        next_id = (
            max(int(d.name.split('_')[1]) for d in execution_dirs) + 1
            if execution_dirs else 1
        )

        # Create the new execution directory
        new_execution_dir = base_workdir / f"execution_{next_id}"
        new_execution_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Created new execution directory: {new_execution_dir}")

        # Update the config to point to the new execution directory
        config.execution.workdir = new_execution_dir

        