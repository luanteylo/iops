from iops.controller.executors import SlurmExecutor, LocalExecutor
from iops.analysis.metrics import MetricsAnalyzer
from iops.benchmarks.ior import IORBenchmark
from iops.utils.logger import HasLogger
from iops.controller.planner import SweepPlanner
from iops.controller.planner import PhaseResult
from iops.utils.config_loader import IOPSConfig
from iops.utils.file_utils import FileUtils 

class IOPSRunner(HasLogger):
    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        self.logger.info("Starting IOPS benchmarking process")

        benchmark = IORBenchmark(self.config)
        planner = SweepPlanner(self.config, benchmark)
        analyzer = MetricsAnalyzer()
        #executor = SlurmExecutor(self.config)  # or LocalExecutor depending on config
        executor = LocalExecutor(self.config)  # For local testing, replace with SlurmExecutor for actual cluster runs
        

        
        
        while planner.has_next_phase():
            phase = planner.next_phase()
            self.logger.info(f"Running phase: {phase.sweep_param}")

            last_result = None

            while planner.has_next_combination():
                params = planner.next_combination(last_result=last_result)

                self.logger.info(f"Submitting Test {params.get('__test_uid__')} - Repetition: {params.get('__rep__')}. Parameters:")
                self.logger.info(f"\tnodes: {params.get('nodes')}, volume: {params.get('volume')}, ost_count: {params.get('ost_count').name}")
                self.logger.info(f"\tPattern: {params.get('io_pattern')}, Operation: {params.get('operation')}")

                try:
                    job_script = benchmark.generate(params=params)
                    job_id = executor.submit(script=job_script)  # Replace with actual job submission logic
                    output_data = executor.wait_and_collect(job_id)                    
                    # result = benchmark.parse_output(output_data["output_path"])

                    #self.logger.info(f"\tBandwidth: {result.get('bandwidth', 'N/A')} MB/s, Latency: {result.get('latency', 'N/A')} ms")

                    #analyzer.record(result, params)
                    #last_result = {"params": params, "result": result}
                    self.logger.info(f"Simulating test execution for parameters: {params}")

                except Exception as e:
                    self.logger.error(f"Error during test execution: {e}")
                    raise

            #best = analyzer.select_best(phase.criterion)
            #self.logger.info(f"Best parameters for phase '{phase.sweep_param}':")
            #self.logger.info(f"\tnodes: {best.get('nodes')}, volume: {best.get('volume')}, ost_count: {best.get('ost_count').name}")
            #self.logger.info(f"\tBest {phase.criterion}: {best.get(phase.criterion)}")

            #planner.update_for_next_phase(PhaseResult(phase.sweep_param, best))
            #analyzer.clean()
        
        self.logger.info("All benchmarking phases completed.")
