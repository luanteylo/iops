from iops.controller.executors import SlurmExecutor, LocalExecutor, BaseExecutor
from iops.analysis.metrics import MetricsAnalyzer
from iops.benchmarks.ior import IORBenchmark, BenchmarkRunner
from iops.utils.logger import HasLogger
from iops.controller.planner import SweepPlanner
from iops.controller.planner import PhaseResult
from iops.utils.config_loader import IOPSConfig
from iops.utils.file_utils import FileUtils 

class IOPSRunner(HasLogger):
    def __init__(self, config: IOPSConfig):
        super().__init__()
        self.config = config

    def run(self):
        self.logger.info("Starting IOPS benchmarking process")

        benchmark = BenchmarkRunner.build(name=self.config.execution.benchmark_tool, 
                                          config=self.config)
        
        executor = BaseExecutor.build(name=self.config.execution.job_manager, 
                                      config=self.config)
    
        planner = SweepPlanner(self.config, benchmark)
        analyzer = MetricsAnalyzer()        
        
                
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
                    job_id = executor.submit(job_script)  # Replace with actual job submission logic
                    output_data = executor.wait_and_collect(job_id)      
                    self.logger.debug(f"Job {job_id} completed. Output data: {output_data}")              

                    # check if output_data is valid
                    if output_data.get('status') == 'completed':
                        # call parse_output to extract metrics
                        result = benchmark.parse_output(params=params)                    
                        self.logger.debug(f"Parsed result: {result}")
                        analyzer.record(result, params)
                    else:
                        self.logger.error(f"Job {job_id} failed or did not complete successfully. Output: {output_data}")
                    
                    #last_result = {"params": params, "result": result}
                    #self.logger.info(f"Simulating test execution for parameters: {params}")

                except Exception as e:
                    self.logger.error(f"Error during test execution: {e}")
                    raise

            best = analyzer.select_best(phase.criterion)
            self.logger.info(f"Best parameters for phase '{phase.sweep_param}':")
            self.logger.info(f"\tnodes: {best.get('nodes')}, volume: {best.get('volume')}, ost_count: {best.get('ost_count').name}")
            self.logger.info(f"\tBest {phase.criterion}: {best.get(phase.criterion)}")
            analyzer.save_record_csv(planner.current_phase_path / f"results_{phase.sweep_param}.")

            planner.update_for_next_phase(PhaseResult(phase.sweep_param, best))

            analyzer.clean()
        
        self.logger.info("All benchmarking phases completed.")
