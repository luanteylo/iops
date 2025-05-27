
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
        Execute the full benchmarking workflow.
        - Plan benchmark phases
        - Select executor (Slurm or Local)
        - Generate and submit jobs
        - Analyze results and select best parameters
        """
        self.logger.info("Starting IOPS benchmarking process")

        planner = SweepPlanner(self.config)
        analyzer = MetricsAnalyzer()
        benchmark = IORBenchmark(self.config)

        job_manager = self.config.execution.job_manager.lower()
        if job_manager == "slurm":
            executor = SlurmExecutor(self.config)
        elif job_manager == "local":
            executor = LocalExecutor(self.config)
        else:
            raise ValueError(f"Unsupported job manager: {self.config.execution.job_manager}")

        for phase in planner.phases():
            self.logger.info(f"Running phase: {phase.name}")

            for params in phase.get_parameter_combinations():
                self.logger.info(f"Submitting job with parameters: {params}")
                job_script = benchmark.generate(params)
                job_id = executor.submit(job_script)
                output_data = executor.wait_and_collect(job_id)
                result = benchmark.parse_output(output_data["output_path"])

                self.logger.info(f"Received result for job {job_id}: {result}")
                analyzer.record(result, params)

            best = analyzer.select_best(phase.criterion)
            self.logger.info(f"Best parameters for phase '{phase.name}': {best}")

            planner.update_for_next_phase(PhaseResult(phase.name, best))

        self.logger.info("All benchmarking phases completed.")
