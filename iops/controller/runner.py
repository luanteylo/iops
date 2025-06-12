
from iops.executors.slurm import SlurmExecutor
from iops.executors.local import LocalExecutor
from iops.analysis.metrics import MetricsAnalyzer
from iops.benchmarks.ior import IORBenchmark
from iops.utils.logger import HasLogger

from iops.controller.planner.sweep import SweepPlanner
from iops.controller.planner.base_planner import PhaseResult


class IOPSRunner(HasLogger):
    """
    Main runner class for the IOPS benchmarking framework.
    Orchestrates planning, execution, and result analysis.
    """

    def __init__(self, config):
        """
        Initialize the runner with a configuration object.
        """
        super().__init__()
        self.config = config

    def run(self):
        """
        Execute the full benchmarking workflow with phase repetition and randomization.
            - Plan benchmark phases
            - Select executor (Slurm or Local)
            - Generate and submit jobs
            - Analyze results and select best parameters
        """
        self.logger.info("Starting IOPS benchmarking process")
        benchmark = IORBenchmark(self.config)
        planner = SweepPlanner(self.config, benchmark)
        analyzer = MetricsAnalyzer()
        executor = SlurmExecutor(self.config)
     

        for phase in planner.phases():
            self.logger.info(f"Running phase: {phase.sweep_param}")

            all_combinations = list(phase.get_parameter_combinations())

            for params in all_combinations:
                self.logger.info(f"Submitting Test {params.get('__test_uid__')} - Repetition: {params.get('__rep__')}. Parameters:")
                self.logger.info(f"\tnodes: {params.get('nodes')}, volume: {params.get('volume')}, ost_count: {params.get('ost_count').name}")  
                self.logger.info(f"\tPattern: {params.get('io_pattern')}, Operation: {params.get('operation')}")

                
                job_script = benchmark.generate(params)
                job_id = executor.submit(job_script)                
                output_data = executor.wait_and_collect(job_id)
                result = benchmark.parse_output(output_data["output_path"])
                self.logger.info(f"\tBandwidth: {result.get('bandwidth', 'N/A')} MB/s, {result.get('latency', 'N/A')} ms")              
                analyzer.record(result, params)

            best = analyzer.select_best(phase.criterion)
            self.logger.info(f"Best parameters for phase '{phase.sweep_param}': ")
            self.logger.info(f"\t nodes: {best.get('nodes')}, volume: {best.get('volume')}, ost_count: {best.get('ost_count').name}")            
            self.logger.info(f"\t Best {phase.criterion}: {best.get(phase.criterion)}")

            planner.update_for_next_phase(PhaseResult(phase.sweep_param, best))
            analyzer.clean() # Clear results for next phase

        self.logger.info("All benchmarking phases completed.")


