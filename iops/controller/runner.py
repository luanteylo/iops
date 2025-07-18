from iops.controller.executors import BaseExecutor
from iops.analytics.analyzer import MetricsAnalyzer
from iops.analytics.storage import MetricsStorage, Tests
from iops.benchmarks.ior import  BenchmarkRunner
from iops.utils.logger import HasLogger
from iops.controller.planner import BruteForce
from iops.utils.config_loader import IOPSConfig

from typing import Dict, Any
from datetime import datetime
from pathlib import Path
import json

class IOPSRunner(HasLogger):
    def __init__(self, config: IOPSConfig, args, 
                 benchmark=None, executor=None, planner=None, analyzer=None, storage = None):
        super().__init__()
        self.config = config
        self.args = args

        self.benchmark = benchmark or self._build_benchmark()
        self.executor = executor or self._build_executor()
        self.planner = planner or self._build_planner()
        self.analyzer = analyzer or self._build_analyzer()
        self.storage = storage or self._build_storage()

    def _build_benchmark(self):
        return BenchmarkRunner.build(name=self.config.execution.benchmark_tool, config=self.config)

    def _build_executor(self):
        return BaseExecutor.build(name=self.config.execution.job_manager, config=self.config)

    def _build_planner(self):
        return BruteForce(self.config, self.benchmark)

    def _build_analyzer(self):
        return MetricsAnalyzer(
            criterion=self.benchmark.get_criterion(),
            operation=self.benchmark.get_operation()
        )
    
    def _build_storage(self):

        return MetricsStorage(
            db_path=self.config.environment.sqlite_db,
            read_only=False
        )
   
    def _run_test(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run a single test with the given parameters.
        This method creates a test folder, submits the job to the executor,
        and waits for the job to complete, collecting the results.
        """
        # create the test folder 
        test_folder = Path(params.get("__test_folder"))
        test_index = params.get("__test_index")
        test_repetition = params.get("__test_repetition")
        test_folder.mkdir(parents=True, exist_ok=True)              
         
        self.logger.info(f"Submitting Test: {test_index}, Repetition: {test_repetition}, folder: {test_folder}")  

        job_script = self.benchmark.generate(params=params)
        job_id = self.executor.submit(script=job_script)
        return  self.executor.wait_and_collect(job_id=job_id,
                                               execution_dir=test_folder)

    def _parse_datetime(self, value, fmt="%Y-%m-%d %H:%M:%S"):
        if isinstance(value, str):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                return None
        return value


    def _log_params(self, params: dict):        
        for k, v in params.items():
            if not k.startswith("__"):
                self.logger.info(f"{k}: {v}")
                
        
    
    def run(self):
        
        # Initialize Storage

        start_time = datetime.now()                    
        criterion_key = self.benchmark.get_criterion()

        ## Start couters
        cache_hits = 0
        total_tests = 0
        

        
        while self.planner.has_next_phase():
            phase = self.planner.next_phase()
            phase_folder = Path(phase.meta_params.get("__phase_folder"))
            phase_folder.mkdir(parents=True, exist_ok=True)

            self.logger.info(f"Running phase: {phase.sweep_param}")            

            for params in self.planner:
                total_tests += 1
                test_index = params.get("__test_index")
                test_repetition = params.get("__test_repetition")

                # each parameter + repeition we check if 
                cached_test = self.storage.get_test(
                    param=params,
                    repetition=test_repetition
                )
                
                self.logger.info(msg=f"Phase: {phase.sweep_param}, Test: {test_index} Repetition: {test_repetition}. Status: {cached_test.status if cached_test else 'PENDING'}")
                self._log_params(params)

                if self.args.use_cache and (cached_test and cached_test.status == "SUCCESS"): 
                    result = json.loads(cached_test.result_json)
                    self.analyzer.record(result=result,
                                         params=params)
                                                           
                    self.logger.info(f"Result (CACHED): {criterion_key}: {result.get(criterion_key)}")                    
                    cache_hits += 1 
                    continue
                else:
                    # save the test                    
                    cached_test = self.storage.save_test(params=params,
                                                         status="PENDING")

                execution_summary = self._run_test(params)
                self.logger.debug(f"Execution_summary: {execution_summary}")

                job_start = self._parse_datetime(execution_summary.get("__start"))
                job_end = self._parse_datetime(execution_summary.get("__end"))
                job_status = execution_summary.get("__status")
                duration = job_end - job_start if job_start and job_end else "unknown"

                self.logger.info(f"Job Status: {job_status}. Start: {job_start} End: {job_end}. Duration: {duration}")

                result = None
                if job_status == "SUCCESS" and (result := self.benchmark.parse_output(params=params)):
                    self.logger.info(f"Result (EXECUTED): {self.benchmark.get_criterion()}: {result.get(self.benchmark.get_criterion())}")
                    self.analyzer.record(result, params)
                else:
                    self.logger.error(
                        "Job succeeded, but output could not be parsed."
                        if job_status == "SUCCESS"
                        else f"Job failed or did not complete successfully. Status: {job_status}"
                    )

                self.storage.update_test(test=cached_test, status=job_status, result=result)

                


               

            best = self.analyzer.select_best()            
          
            self.logger.info(f"Best parameters for phase '{phase.sweep_param}':")
            self._log_params(best.get("__parameters"))
            
            self.logger.info(f"Best results for phase '{phase.sweep_param}': {best.get('__results')}")
                             
            
            self.planner.update_phase(param=best.get("__parameters"), 
                                 result=best.get("__results"))            
        
        self.logger.info("All benchmarking phases completed.")
        self.analyzer.save_csv(self.config.execution.workdir / "results.csv")
        self.analyzer.save_history_yaml(self.config.execution.workdir / "history.yaml")
        self.logger.info(f"Execution completed in {datetime.now() - start_time}. Results saved to {self.config.execution.workdir}")
        self.logger.info(f"Total tests: {total_tests}. Cache hit ratio: {cache_hits / total_tests if total_tests > 0 else 0:.2%} ({cache_hits})")

