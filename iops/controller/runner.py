from iops.controller.executors import BaseExecutor
from iops.analysis.metrics import MetricsAnalyzer
from iops.benchmarks.ior import  BenchmarkRunner
from iops.utils.logger import HasLogger
from iops.controller.planner import BruteForce
from iops.utils.config_loader import IOPSConfig


from pathlib import Path

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
    
        planner = BruteForce(self.config, benchmark)
        analyzer = MetricsAnalyzer()        
        
                
        while planner.has_next_phase():
            phase = planner.next_phase()
            phase_folder = Path(phase.meta_params.get("__phase_folder"))
            phase_folder.mkdir(parents=True, exist_ok=True)

            self.logger.info(f"Running phase: {phase.sweep_param}")

            while planner.has_next_combination():
                params = planner.next_combination()
                test_folder = Path(params.get("__test_folder"))
                test_index = params.get("__test_index")
                test_repetition = params.get("__test_repetition")

                # create the test folder 
                test_folder.mkdir(parents=True, exist_ok=True)                

                self.logger.info(f"Submitting Test: {test_index}, Repetition: {test_repetition}")
                self.logger.info(f"Execution directory: {test_folder}")
                self.logger.info(f"Parameters:")
                # Print only parameters that are not metadata "__test_id__", "__repetition__", "__path__", "__script__"                
                self.logger.info(params)                
                
                try:                    
                    job_script = benchmark.generate(params=params)
                    job_id = executor.submit(job_script)  # Replace with actual job submission logic
                    output_data = executor.wait_and_collect(job_id, test_folder)
                    self.logger.info(f"Job {job_id} completed. Status: {output_data.get('status')}")              

                    # check if output_data is valid
                    if output_data and output_data.get('status') == 'SUCCESS':
                        # call parse_output to extract metrics
                        result = benchmark.parse_output(params=params)                    
                        self.logger.info(f"Parsed result: {result}")
                        analyzer.record(result, params)
                    else:
                        self.logger.error(f"Job {job_id} failed or did not complete successfully. Output: {output_data}")
                    
                    #last_result = {"params": params, "result": result}
                    #self.logger.info(f"Simulating test execution for parameters: {params}")

                except Exception as e:
                    self.logger.error(f"Error during test execution: {e}")
                    raise

            best = analyzer.select_best(criterion=benchmark.get_criterion(),
                                        operation=benchmark.get_operation())
            

            
            self.logger.info(f"Best parameters for phase '{phase.sweep_param}':")
            self.logger.info(best)
            #self.logger.info(f"\tBest {phase.criterion}: {best.get(phase.criterion)}")
            analyzer.save_record_csv(phase_folder / f"results_{phase.sweep_param}.csv")

            planner.update_phase(param=best.get("parameters"), result=best.get("results"))

            analyzer.clean()
        
        self.logger.info("All benchmarking phases completed.")
        analyzer.save_history_yaml(self.config.execution.workdir / "history.yaml")
