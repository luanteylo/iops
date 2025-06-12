from iops.benchmarks.base import BenchmarkRunner
from iops.controller.planner.base_planner import Phase
from iops.utils.config_loader import IOPSConfig
from typing import List


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
    
    def build_phases(self) -> List[Phase]:
        """
        Builds the phases for the IOR benchmark execution.
        Each phase defines a set of parameters to vary and the expected results.
        Returns a list of Phase objects.
        """
        self.logger.debug("Building IOR benchmark phases")
        # with IOR we need to define thre parameters range for the sweep
        volume_range = list(range(
                self.config.storage.min_volume,
                self.config.storage.max_volume + 1,
                self.config.storage.volume_step))
        
        nodes_range = [2**i for i in range(
            self.config.nodes.min_nodes.bit_length() - 1,
            self.config.nodes.max_nodes.bit_length())]

        stripe_folders = self.config.storage.stripe_folders

        phases = []
        
        fixed_params = {
            "processes_per_node": self.config.nodes.processes_per_node,
            "cores_per_node": self.config.nodes.cores_per_node,                        
            "io_pattern": self.config.execution.io_pattern,
            "operation": self.config.execution.test_type,
        }
        full_param_space = {
            "volume": volume_range,
            "nodes": nodes_range,
            "ost_count": stripe_folders
        }        

        
        # for each test_type we will create a phase
        for test in self.config.execution.tests:
            # if test is  file_size
            self.logger.debug(f"Creating phase for test: {test}")

            if test == "volume":                
                values = volume_range
                self.logger.debug(f"Setting up phase for filesize with values: {values}")
            elif test == "nodes":                
                values = nodes_range
                self.logger.debug(f"Setting up phase for computing with values: {values}")
            elif test == "ost_count":                
                values = stripe_folders
                self.logger.debug(f"Setting up phase for striping with values: {values}")
            else:
                self.logger.error(f"Unknown test type: {test}")
                raise ValueError(f"Unknown test type: {test}")

            phases.append(Phase(sweep_param=test,
                                values=values,
                                fixed_params=fixed_params.copy(),
                                full_param_space=full_param_space,                                
                                repetitions=self.config.execution.repetitions))
        
        return phases
            

            
                        
            

            
