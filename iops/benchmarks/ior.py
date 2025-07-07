
from abc import ABC, abstractmethod
import csv
from iops.utils.logger import HasLogger
from iops.utils.config_loader import IOPSConfig, StripeFolder, StorageConfig
from iops.controller.planner import Phase
from jinja2 import Environment, FileSystemLoader
from pathlib import Path


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
    
    def _save_script(self, script_content: str, params: dict) -> bool:
        """
        Save the generated script content to a file.
        """
        try:
            script_path = params.get("__script__")            
            script_path.write_text(script_content)
            script_path.chmod(0o755)
            self.logger.info(f"Script saved successfully at {script_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save script: {e}")
            return False
        
    


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
  
    def __init__(self, config : IOPSConfig): 
        super().__init__(config)
        # status file to track job status
        self.status_file: Path = config.execution.workdir / "ior_status.txt"

        
    def get_commands(self, params) -> str: 
        """
        Returns the IOR command based on the configuration.
        """
        commands: str = "ior"

        block_size: int = params.get("volume") / (params.get("processes_per_node") * params.get("nodes"))

        commands += f" -w"
        commands += f" -b {int(block_size)}m"
        commands += f" -t 1m"  
        
        return commands
        
    def generate(self, params: dict) -> Path:
        """
        Generate a script from a Jinja2 template using provided parameters.

        Args:
            params (dict): Parameters to fill into the Jinja2 template.

        Returns:
            Path: Path to the generated script file.
        """
        
        template_path: Path = self.config.template.bash_template

        # Load Jinja2 environment from the template's directory
        env = Environment(loader=FileSystemLoader(template_path.parent))
        template = env.get_template(template_path.name)
      

        # Render the template
        full_params = {
            "nodes": params.get("nodes"),
            "ntasks": params.get("processes_per_node") * params.get("nodes"),
            "ntasks_per_node": params.get("processes_per_node"),
            "chdir": params.get("__path__"),
            "job_name": f"job_name",
            "output_file": f"{params.get('ost_count').name}/test_output.ior",
            "summary_results": params.get("__output__"),
            "status_file": self.status_file,
            "cmd": self.get_commands(params),
        }
        rendered_script = template.render(full_params)

        if not self._save_script(rendered_script, params):
            self.logger.error("Failed to save the generated script.")
            return None       

        return params.get("__script__")

    def parse_output(self, params: dict) -> dict:
        """
        Parses the IOR output CSV file, renames columns, and returns a cleaned-up dictionary.
        """
        output_file = params.get("__output__")
        results = {}

        IOR_CSV_RENAME_MAP = {
            "access": "operation",
            "bw(MiB/s)": "bandwidth",
            "IOPS": "iops",
            "Latency": "latency",
            "block(KiB)": "block_size",
            "xfer(KiB)": "transfer_size",
            "open(s)": "open_time",
            "wr/rd(s)": "operation_time",
            "close(s)": "close_time",
            "total(s)": "total_time",
            "numTasks": "num_tasks",
            "iter": "iteration"
        }

        if output_file.exists():
            with output_file.open("r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    results = {
                        IOR_CSV_RENAME_MAP.get(key.strip(), key.strip()):
                            value.strip() if key.strip() == "access" else float(value)
                        for key, value in row.items()
                    }
                    break  # Only one line expected
        else:
            self.logger.warning(f"Output file not found: {output_file}")

        return results

   
  
    def build_phase(self, sweep_param: str, fixed_params: dict) -> Phase:
        """
        Builds a single Phase based on the sweep_param and current best fixed_params.
        """
        self.logger.debug(f"Building phase for: {sweep_param} with fixed_params: {fixed_params}")

        volume_range = list(range(
            self.config.storage.min_volume,
            self.config.storage.max_volume + 1,
            self.config.storage.volume_step))

        nodes_range = [2**i for i in range(
            self.config.nodes.min_nodes.bit_length() - 1,
            self.config.nodes.max_nodes.bit_length())]

        stripe_folders = self.config.storage.stripe_folders

        # Choose sweep values based on parameter
        if sweep_param == "volume":
            values = volume_range
        elif sweep_param == "nodes":
            values = nodes_range
        elif sweep_param == "ost_count":
            values = stripe_folders
        else:
            raise ValueError(f"Unknown test parameter: {sweep_param}")

        full_param_space = {
            "volume": volume_range,
            "nodes": nodes_range,
            "ost_count": stripe_folders
        }

        # Fill in standard fixed parameters
        full_fixed = {
            "processes_per_node": self.config.nodes.processes_per_node,
            "cores_per_node": self.config.nodes.cores_per_node,
            "io_pattern": self.config.execution.io_pattern,  # string now
            "operation": self.config.execution.test_type,
        }
        full_fixed.update(fixed_params)

        return Phase(
            sweep_param=sweep_param,
            values=values,
            fixed_params=full_fixed,
            full_param_space=full_param_space,
            repetitions=self.config.execution.repetitions
        )

            

            
                        
           

            
