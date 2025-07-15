
from abc import ABC, abstractmethod
import csv
from iops.utils.logger import HasLogger
from iops.utils.config_loader import IOPSConfig
from iops.controller.planner import Phase
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
import time
import json

class BenchmarkRunner(ABC, HasLogger):
    """
    Abstract base class for all benchmark implementations.
    Defines the interface required for benchmark execution.
    """
    _registry = {}
  


    @classmethod
    def register(cls, name):
        def decorator(subclass):
            cls._registry[name.lower()] = subclass
            return subclass
        return decorator

    @classmethod
    def build(cls, name: str, config) -> "BenchmarkRunner":
        benchmark_cls = cls._registry.get(name.lower())
        if benchmark_cls is None:
            raise ValueError(f"Benchmark '{name}' is not registered.")
        return benchmark_cls(config)

    def __init__(self, config):
        super().__init__()
        self.config = config
    
    def _save_script(self, script_content: str, script_path: Path) -> bool:
        """
        Save the generated script content to a file.
        """
        try:            
            script_path.write_text(script_content)
            script_path.chmod(0o755)
            self.logger.info(f"Script saved successfully at {script_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save script: {e}")
            return False
    
    @abstractmethod
    def get_criterion():
        """
        all benchmarks should implement this method to return the criterion for optimization.
        For example, IOR might return 'bandwidth' or 'latency'.
        """
        pass

    @abstractmethod
    def get_operation():
        """
        Returns the operation applied on the criterion value.
        Supported operations are 'mean', median, 'max', 'min'.  
        For example, IOR might return 'mean' for bandwidth or latency.
        """
        pass


    @abstractmethod
    def generate(self, params: dict):
        """
        Generate the job script or command required to run the benchmark with the given parameters.
        This function need to call _save_script at the end to save the generated script content.
        """
        pass

    @abstractmethod
    def parse_output(self, job_output_path: str) -> dict:
        """
        Parse the output of the benchmark run and return relevant metrics as a dictionary.
        Example: {'bandwidth_avg': 1234.5, 'latency': 4.2}
        """
        pass

    @abstractmethod
    def build_phase(self) -> list:
        """
        Build the phases for the benchmark execution.
        Each phase should define a set of parameters to vary and the expected results.
        Returns a list of Phase objects.
        """
        pass

@BenchmarkRunner.register("ior")
class IORBenchmark(BenchmarkRunner):
    """
    IOR benchmark integration.
    Responsible for generating job scripts and parsing benchmark output.
    """
    criterion = "bandwidth"  # Example criterion for IOR
    operation = "mean"  # Example operation for IOR
  
    def __init__(self, config : IOPSConfig): 
        super().__init__(config)
        
    def get_commands(self, params) -> str: 
        """
        Returns the IOR command based on the configuration.
        """

        commands: str = 'ior'

        summary_file = params.get("__test_output")
        output_file = Path(params.get("ost_count")) / "test_output.ior"
        

        block_size: int = params.get("volume") / (params.get("processes_per_node") * params.get("nodes"))

        commands += f' -w'
        commands += f' -b {int(block_size)}m'
        commands += f' -t 1m'  
        commands += f' -O summaryFile="{summary_file}" -O summaryFormat=JSON'
        commands += f' -o "{output_file}"'
        
        return commands
        
    def generate(self, params: dict) -> Path:
        """
        Generate a script from a Jinja2 template using provided parameters.

        Args:
            params (dict): Parameters to fill into the Jinja2 template.

        Returns:
            Path: Path to the generated script file.
        """
        
        template_path: Path = self.config.environment.bash_template
        script_path = Path(params.get("__test_script"))
        

        # Load Jinja2 environment from the template's directory
        env = Environment(loader=FileSystemLoader(template_path.parent))
        template = env.get_template(template_path.name)


        # Render the template
        full_params = {
            "nodes": params.get("nodes"),
            "ntasks": params.get("processes_per_node") * params.get("nodes"),
            "ntasks_per_node": params.get("processes_per_node"),
            "chdir": params.get("__test_folder"),
            "job_name": f"job_name",
            "cmd": self.get_commands(params),
        }
        rendered_script = template.render(full_params)

        if not self._save_script(rendered_script, script_path):
            self.logger.error(f"Failed to save the generated script '{script_path}'")
            return None       

        return script_path

    def __load_json_with_retry(self, output_file: Path, retry_limit: int = 10) -> dict | None:
        """
        Retry loading a JSON file until it exists and is valid, or retry limit is reached.
        
        Args:
            output_file (Path): Path to the JSON file to load.
            logger: Logger to use for messages.
            retry_limit (int): Number of attempts before giving up.

        Returns:
            dict or None: Parsed JSON data or None if loading fails.
        """
        for retry in range(1, retry_limit + 1):
            if output_file.exists():
                try:
                    with output_file.open("r") as f:
                        return json.load(f)
                except json.JSONDecodeError:
                    self.logger.warning(f"Attempt {retry}/{retry_limit}: Invalid JSON in {output_file}")
            else:
                self.logger.warning(f"Attempt {retry}/{retry_limit}: File not found: {output_file}")
            
            sleep_time = retry * 5
            self.logger.info(f"Waiting {sleep_time} seconds before next attempt...")
            time.sleep(sleep_time)

        self.logger.error(f"Failed to load valid JSON after {retry_limit} attempts: {output_file}")
        return None

    def parse_output(self, params: dict) -> dict:
        """
        Parses the IOR JSON summary file and returns a cleaned-up dictionary
        with renamed keys to match expected output format.
        """

        results = {}

        IOR_JSON_RENAME_MAP = {
            "operation": "operation",
            "bwMeanMIB": "bandwidth", # The criterion used for IOR
            "OPsMean": "iops",
            "MeanTime": "total_time",
            "blockSize": "block_size",
            "transferSize": "transfer_size",
            "numTasks": "num_tasks",
        }

        output_file = Path(params.get("__test_output"))
        retry_limit = 10
        data = self.__load_json_with_retry(output_file, retry_limit)

        if data is None:
            return None
        
        # We parse the first 'write' or 'read' summary entry
        for entry in data.get("summary", []):
            result = {
                IOR_JSON_RENAME_MAP.get(key, key): (
                    entry[key] if isinstance(entry[key], str) else float(entry[key])
                )
                for key in IOR_JSON_RENAME_MAP
                if key in entry
            }

            # Optional: add the iteration number if provided
            result["iteration"] = params.get("iteration", 0)

            results = result
            break  # Only parse the first result 

        return results

    def get_criterion(self) -> str:
        """
        Returns the criterion for IOR benchmark.
        """
        return self.criterion
    
    def get_operation(self) -> str:
        """
        Returns the operation applied on the criterion value for IOR benchmark.
        """
        return self.operation
  
    def build_phase(self, sweep_param: str, params: dict) -> Phase:
        """
        Builds a single Phase based on the sweep_param and current best params.
        inputs:
        - sweep_param: The parameter to sweep over (e.g., 'volume', 'nodes', 'ost_count').
        - params: A dictionary of parameters that will be used to fill the parameters of the phase.
        """
        self.logger.debug(f"Building phase for: {sweep_param} with fixed_params: {params}")

        # Choose sweep values based on parameter
        if sweep_param == "volume":
            values = list(range(
                self.config.storage.min_volume,
                self.config.storage.max_volume + 1,
                self.config.storage.volume_step
            ))
        elif sweep_param == "nodes":
            values = list(range(
                self.config.nodes.min_nodes,
                self.config.nodes.max_nodes + 1,
                self.config.nodes.node_step
            ))
        elif sweep_param == "ost_count":
            values = [str(stf) for stf in self.config.storage.stripe_folders]
        else:
            raise ValueError(f"Unknown test parameter: {sweep_param}")

        # Fill in standard fixed parameters
        all_parameters = {
            "processes_per_node": self.config.nodes.processes_per_node,
            "cores_per_node": self.config.nodes.cores_per_node,
            "io_pattern": self.config.execution.io_pattern, 
            "operation": self.config.execution.test_type,
            "ost_count": str(self.config.storage.stripe_folders[0]), # always start with the default values
            "volume": self.config.storage.min_volume, # always start with the default values
            "nodes": self.config.nodes.min_nodes, # always start with the default values
        }
        # Update the phase parameters with the previous sweep parameter values
        all_parameters.update(params)        
        all_parameters.update({sweep_param: None})  # Placeholder for the sweep parameter
        return Phase(sweep_param = sweep_param,
                     values = values,
                     params=all_parameters)


            

            
                        
           

            
