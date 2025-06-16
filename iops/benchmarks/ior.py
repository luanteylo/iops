
from abc import ABC, abstractmethod
from iops.utils.logger import HasLogger
from iops.utils.config_loader import IOPSConfig
from iops.controller.planner import Phase


class BenchmarkRunner(ABC, HasLogger):
    """
    Abstract base class for all benchmark implementations.
    Defines the interface required for benchmark execution.
    """

    def __init__(self, config):
        super().__init__()
        self.config = config

    @abstractmethod
    def generate(self, params: dict) -> str:
        """
        Generate the job script or command required to run the benchmark with the given parameters.
        Should return the path to the generated script or command string.
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

class IORBenchmark(BenchmarkRunner):
    """
    IOR benchmark integration.
    Responsible for generating job scripts and parsing benchmark output.
    """
    def __init__(self, config : IOPSConfig): 
        super().__init__(config)

    def generate(self, params: dict) -> str:
        """
        Generates a placeholder IOR job script path for the given parameters.
        In the full version, this would render a script template and save it.
        """
        self.logger.debug(f"Generating IOR job script with parameters: {params}")
        # TODO: implement script file generation based on params
        return f"/tmp/ior-job-script-{hash(frozenset(params.items()))}.sh"  # Simulated script path

    def parse_output(self, job_output_path: str) -> dict:
        """
        Parses a simulated IOR output file.
        In a real implementation, it would extract bandwidth, latency, etc.
        """
        # random generated bandwidth and latency for demonstration
        import random
        bw = random.uniform(300, 900)  # Simulated bandwidth in MB/s
        latency = random.uniform(3, 5)

        self.logger.debug(f"Parsing IOR output from: {job_output_path}")
        # TODO: parse actual IOR output file
        return {
            "bandwidth": bw,
            "latency": latency
        }
    
  
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

            

            
                        
            

            
