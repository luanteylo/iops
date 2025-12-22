"""
Bayesian Optimization Planner for IOPS benchmarks.

Uses Bayesian optimization to efficiently search the parameter space
and find optimal configurations for a target metric (e.g., maximize bandwidth).

TODO: Add exhaustive_vars support similar to RandomSamplingPlanner:
- Group instances by search point (non-exhaustive variables)
- Optimize over search variables only
- For each suggested point, test all exhaustive variable values
- Aggregate results from exhaustive vars (e.g., mean, max) for GP fitting
"""

from iops.execution.planner import BasePlanner
from iops.config.models import GenericBenchmarkConfig
from iops.execution.matrix import ExecutionInstance, build_execution_matrix
from iops.logger import HasLogger

from typing import List, Dict, Any, Optional
from pathlib import Path
import numpy as np

try:
    from skopt import Optimizer
    from skopt.space import Integer, Real, Categorical
    SKOPT_AVAILABLE = True
except ImportError:
    SKOPT_AVAILABLE = False


@BasePlanner.register("bayesian")
class BayesianPlanner(BasePlanner, HasLogger):
    """
    Bayesian optimization planner that intelligently explores parameter space
    to find optimal configurations for a target metric.

    Configuration (YAML):
        benchmark:
          search_method: "bayesian"
          bayesian_config:
            target_metric: "bwMiB"  # Metric to optimize
            objective: "maximize"    # "maximize" or "minimize"
            n_initial_points: 5      # Random exploration before optimization
            n_iterations: 20         # Total number of evaluations
            acquisition_func: "EI"   # "EI", "PI", or "LCB"
            random_state: 42         # For reproducibility

    The planner will:
    1. Start with random exploration (n_initial_points)
    2. Build a surrogate model from observed results
    3. Use acquisition function to suggest next promising point
    4. Iteratively improve to find optimal parameters
    """

    def __init__(self, cfg: GenericBenchmarkConfig):
        super().__init__(cfg)

        if not SKOPT_AVAILABLE:
            raise ImportError(
                "scikit-optimize is required for Bayesian optimization. "
                "Install it with: pip install scikit-optimize"
            )

        # Get Bayesian config from benchmark config
        self.bayesian_cfg = self._get_bayesian_config()

        # Optimization settings
        self.target_metric = self.bayesian_cfg.get('target_metric', 'bwMiB')
        self.objective = self.bayesian_cfg.get('objective', 'maximize')
        self.n_initial_points = self.bayesian_cfg.get('n_initial_points', 5)
        self.n_iterations = self.bayesian_cfg.get('n_iterations', 20)
        self.acquisition_func = self.bayesian_cfg.get('acquisition_func', 'EI')

        # Validate objective
        if self.objective not in ['maximize', 'minimize']:
            raise ValueError(f"objective must be 'maximize' or 'minimize', got: {self.objective}")

        # Build search space from swept variables
        self.search_space, self.var_names = self._build_search_space()

        if not self.search_space:
            raise ValueError("No swept variables found for Bayesian optimization")

        # Initialize Bayesian optimizer
        self.optimizer = Optimizer(
            dimensions=self.search_space,
            n_initial_points=self.n_initial_points,
            acq_func=self.acquisition_func,
            random_state=self.cfg.benchmark.random_seed,
        )

        # Execution tracking
        self.iteration = 0
        self.completed_tests: List[ExecutionInstance] = []
        self.X_observed: List[List[Any]] = []  # Parameter combinations tried
        self.y_observed: List[float] = []      # Observed metric values

        # Best found so far
        self.best_params: Optional[Dict[str, Any]] = None
        self.best_value: Optional[float] = None

        # Repetitions per configuration
        self.repetitions = cfg.benchmark.repetitions or 1

        # Current test being evaluated
        self.current_test: Optional[ExecutionInstance] = None
        self.current_params: Optional[List[Any]] = None
        self.current_rep = 0

        self.logger.info(
            f"Bayesian planner initialized: target={self.target_metric} "
            f"objective={self.objective} n_iterations={self.n_iterations} "
            f"n_initial={self.n_initial_points}"
        )
        self.logger.info(f"Search space: {len(self.search_space)} dimensions: {self.var_names}")

    def _get_bayesian_config(self) -> Dict[str, Any]:
        """Extract Bayesian optimization config from benchmark config."""
        # Check if bayesian_config exists in benchmark
        if hasattr(self.cfg.benchmark, 'bayesian_config') and self.cfg.benchmark.bayesian_config:
            return self.cfg.benchmark.bayesian_config

        # Fall back to defaults
        return {
            'target_metric': 'bwMiB',
            'objective': 'maximize',
            'n_initial_points': 5,
            'n_iterations': 20,
            'acquisition_func': 'EI',
        }

    def _build_search_space(self):
        """
        Build scikit-optimize search space from swept variables.

        Returns:
            Tuple of (dimensions, var_names)
        """
        dimensions = []
        var_names = []

        for var_name, var_config in self.cfg.vars.items():
            if not var_config.sweep:
                continue  # Skip non-swept variables

            sweep_cfg = var_config.sweep

            if sweep_cfg.mode == "range":
                # Continuous or integer range
                if var_config.type == "int":
                    dim = Integer(
                        low=sweep_cfg.start,
                        high=sweep_cfg.end,
                        name=var_name
                    )
                else:  # float
                    dim = Real(
                        low=float(sweep_cfg.start),
                        high=float(sweep_cfg.end),
                        name=var_name
                    )
                dimensions.append(dim)
                var_names.append(var_name)

            elif sweep_cfg.mode == "list":
                # Categorical or discrete values
                if var_config.type in ["int", "float"]:
                    # Discrete numeric values
                    dim = Categorical(
                        categories=sweep_cfg.values,
                        name=var_name
                    )
                else:
                    # Categorical (string) values
                    dim = Categorical(
                        categories=sweep_cfg.values,
                        name=var_name
                    )
                dimensions.append(dim)
                var_names.append(var_name)

        return dimensions, var_names

    def _params_to_dict(self, params: List[Any]) -> Dict[str, Any]:
        """Convert parameter list to dictionary."""
        return {name: value for name, value in zip(self.var_names, params)}

    def next_test(self) -> Optional[ExecutionInstance]:
        """
        Return the next test to execute.

        Returns:
            ExecutionInstance or None when optimization is complete
        """
        # Check if we've completed all iterations
        if self.iteration >= self.n_iterations:
            self.logger.info("=" * 70)
            self.logger.info("BAYESIAN OPTIMIZATION COMPLETE")
            self.logger.info("=" * 70)
            if self.best_params:
                self.logger.info(f"Best parameters found: {self.best_params}")
                self.logger.info(f"Best {self.target_metric}: {self.best_value:.4f}")
            self.logger.info(f"Total evaluations: {len(self.y_observed)}")
            self.logger.info("=" * 70)
            return None

        # Handle repetitions for current test
        if self.current_test and self.current_rep < self.repetitions:
            # Continue with repetitions of current configuration
            self.current_rep += 1
            test = self._create_test_instance(self.current_params, self.current_rep)
            self.logger.debug(
                f"  [Bayesian] Repetition {self.current_rep}/{self.repetitions} "
                f"of iteration {self.iteration + 1}"
            )
            return test

        # Get next point to evaluate from Bayesian optimizer
        next_params = self.optimizer.ask()
        self.current_params = next_params
        self.current_rep = 1
        self.iteration += 1

        # Create test instance
        test = self._create_test_instance(next_params, self.current_rep)
        self.current_test = test

        params_dict = self._params_to_dict(next_params)
        self.logger.info(
            f"[Bayesian] Iteration {self.iteration}/{self.n_iterations}: "
            f"Testing {params_dict}"
        )

        return test

    def _create_test_instance(self, params: List[Any], repetition: int) -> ExecutionInstance:
        """
        Create an ExecutionInstance from parameters.

        Args:
            params: List of parameter values
            repetition: Repetition number (1-based)

        Returns:
            ExecutionInstance
        """
        # Convert params to variables dict
        vars_dict = self._params_to_dict(params)

        # Build a mini execution matrix with these specific parameters
        # We need to temporarily modify the config to only have these values
        original_vars = {}
        for var_name in self.var_names:
            original_vars[var_name] = self.cfg.vars[var_name].sweep

        try:
            # Temporarily set variables to single values
            for var_name, value in vars_dict.items():
                sweep_cfg = self.cfg.vars[var_name].sweep
                sweep_cfg.mode = "list"
                sweep_cfg.values = [value]

            # Build execution matrix with single point
            matrix = build_execution_matrix(self.cfg)

            if not matrix or len(matrix) == 0:
                raise ValueError(f"Failed to create execution matrix for params: {vars_dict}")

            test = matrix[0]
            test.repetition = repetition
            test.repetitions = self.repetitions
            test.execution_id = self.iteration

            # Prepare execution artifacts (folders and scripts)
            self._prepare_execution_artifacts(test, repetition)

            return test

        finally:
            # Restore original sweep configs
            for var_name, original_sweep in original_vars.items():
                self.cfg.vars[var_name].sweep = original_sweep

    def _prepare_execution_artifacts(self, test: ExecutionInstance, repetition: int) -> None:
        """
        Create folders + scripts for one test execution and one repetition.

        Layout:
        <workdir>/runs/
            └── exec_<execution_id>/
                └── repetition_<rep>/
                    ├── run_<script>.sh
                    └── post_<script>.sh (optional)
        """
        # Set repetition in metadata
        if not hasattr(test, "metadata") or test.metadata is None:
            test.metadata = {}
        test.metadata["repetition"] = repetition

        run_root = Path(self.cfg.benchmark.workdir)
        runs_root = run_root / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)

        # Bayesian planner doesn't use rounds, so directly create exec dir
        exec_dir = runs_root / f"exec_{test.execution_id:04d}" / f"repetition_{repetition:03d}"
        exec_dir.mkdir(parents=True, exist_ok=True)

        # Point to repetition dir (useful for templates like {{ execution_dir }})
        test.execution_dir = exec_dir

        # Write script files inside repetition dir
        test.script_file = exec_dir / f"run_{test.script_name}.sh"
        with open(test.script_file, "w") as f:
            f.write(test.script_text)

        script_info = f"main={test.script_file.name}"

        if getattr(test, "post_script", None):
            test.post_script_file = exec_dir / f"post_{test.script_name}.sh"
            with open(test.post_script_file, "w") as f:
                f.write(test.post_script)
            script_info += f", post={test.post_script_file.name}"

        self.logger.debug(f"  [Bayesian] Scripts written: {script_info}")

    def record_completed_test(self, test: ExecutionInstance):
        """
        Record a completed test and update the Bayesian model.

        Args:
            test: Completed ExecutionInstance with metrics
        """
        self.completed_tests.append(test)

        # Only update optimizer after all repetitions are complete
        if test.repetition == self.repetitions:
            # Extract target metric value
            metrics = test.metadata.get('metrics', {})
            metric_value = metrics.get(self.target_metric)

            if metric_value is None:
                self.logger.warning(
                    f"Target metric '{self.target_metric}' not found in results. "
                    f"Available metrics: {list(metrics.keys())}"
                )
                return

            # Aggregate metric across repetitions (use mean)
            rep_values = []
            for completed_test in self.completed_tests:
                if (completed_test.execution_id == test.execution_id and
                    completed_test.metadata.get('metrics', {}).get(self.target_metric) is not None):
                    rep_values.append(completed_test.metadata['metrics'][self.target_metric])

            if not rep_values:
                return

            aggregated_value = float(np.mean(rep_values))

            # For maximization, negate the value (scikit-optimize minimizes)
            if self.objective == 'maximize':
                y_value = -aggregated_value
            else:
                y_value = aggregated_value

            # Update optimizer with observation
            self.X_observed.append(self.current_params)
            self.y_observed.append(y_value)

            self.optimizer.tell(self.current_params, y_value)

            # Update best found
            if self.best_value is None or aggregated_value > (self.best_value if self.objective == 'maximize' else -self.best_value):
                self.best_params = self._params_to_dict(self.current_params)
                self.best_value = aggregated_value

            self.logger.info(
                f"  [Bayesian] Iteration {self.iteration} complete: "
                f"{self.target_metric}={aggregated_value:.4f} (mean of {len(rep_values)} reps)"
            )
            self.logger.info(
                f"  [Bayesian] Best so far: {self.best_value:.4f} at {self.best_params}"
            )

            # Reset for next iteration
            self.current_test = None
            self.current_params = None
            self.current_rep = 0
