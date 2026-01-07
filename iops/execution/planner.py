"""
Planners for IOPS benchmark execution.

This module contains all planner implementations:
- BasePlanner: Abstract base class with registry pattern
- ExhaustivePlanner: Brute-force search of entire parameter space
- RandomSamplingPlanner: Random sampling of parameter space
- BayesianPlanner: Bayesian optimization for intelligent search
"""

from iops.logger import HasLogger
from iops.config.models import GenericBenchmarkConfig
from iops.execution.matrix import ExecutionInstance, build_execution_matrix, create_execution_instance
from iops.constraints.evaluator import check_constraints_for_vars

from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
from pathlib import Path
from collections import defaultdict
import random
import warnings

# Optional imports for Bayesian optimization
try:
    from skopt import Optimizer
    from skopt.space import Integer, Real, Categorical
    import numpy as np
    SKOPT_AVAILABLE = True
    # Suppress skopt warning about duplicate points - it handles this by using random points
    warnings.filterwarnings('ignore', message='.*objective has been evaluated at point.*', category=UserWarning)
except ImportError:
    SKOPT_AVAILABLE = False


# ============================================================================ #
# Base Planner
# ============================================================================ #

class BasePlanner(ABC, HasLogger):
    """
    Abstract base class for all planners.

    Uses a registry pattern to allow dynamic selection of planners by name.
    """

    _registry = {}

    def __init__(self, cfg: GenericBenchmarkConfig):
        self.cfg = cfg
        # create a random generator with a fixed seed for reproducibility
        self.random = random.Random(cfg.benchmark.random_seed)
        self.logger.info("Planner initialized with benchmark config: %s", cfg.benchmark)
        self.logger.info("Using random seed: %s", cfg.benchmark.random_seed)

    @classmethod
    def register(cls, name):
        def decorator(subclass):
            cls._registry[name.lower()] = subclass
            return subclass
        return decorator

    @classmethod
    def build(cls, cfg) -> "BasePlanner":
        name = cfg.benchmark.search_method
        executor_cls = cls._registry.get(name.lower())
        if executor_cls is None:
            raise ValueError(f"Executor '{name}' is not registered.")
        return executor_cls(cfg)

    def random_sample(self, items: List[ExecutionInstance]) -> List[ExecutionInstance]:
        # randomly sample all items of the list
        sample_size = len(items)
        if sample_size > 0:
            self.logger.debug(f"  [Planner] Shuffling execution order ({sample_size} tests)")
            items = self.random.sample(items, sample_size)
        return items

    @abstractmethod
    def next_test(self) -> Any:
        pass

    @abstractmethod
    def record_completed_test(self, test: Any) -> None:
        pass

    def get_progress(self) -> dict:
        """
        Get current execution progress information.

        Returns:
            Dictionary with progress metrics:
            - completed: Number of tests completed
            - total: Total number of tests expected
            - percentage: Completion percentage (0-100)
            - remaining: Number of tests remaining
        """
        # Use attributes that subclasses should have
        attempt_count = getattr(self, '_attempt_count', 0)
        attempt_total = getattr(self, '_attempt_total', 0)

        return {
            'completed': attempt_count,
            'total': attempt_total,
            'percentage': (attempt_count / attempt_total * 100) if attempt_total > 0 else 0,
            'remaining': attempt_total - attempt_count
        }

    def _prepare_execution_artifacts(self, test: Any, repetition: int) -> None:
        """
        Create folders + scripts for one test execution and one repetition.

        This method is shared by all planners. It:
        - Creates the execution directory structure
        - Sets test.repetition and metadata["repetition"]
        - Writes the main script file
        - Writes the post script file (if present)

        Layout:
        <workdir>/runs/
            └── exec_0001/
                └── repetition_001/
                    ├── run_<script>.sh
                    └── post_<script>.sh (optional)

        Args:
            test: ExecutionInstance to prepare
            repetition: 1-based repetition number
        """
        # Set repetition
        test.repetition = repetition
        if not hasattr(test, "metadata") or test.metadata is None:
            test.metadata = {}
        test.metadata["repetition"] = repetition

        run_root = Path(self.cfg.benchmark.workdir)
        runs_root = run_root / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)

        # Create execution dir
        exec_dir = (
            runs_root
            / f"exec_{test.execution_id:04d}"
            / f"repetition_{repetition:03d}"
        )
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

        self.logger.debug(f"  [Prepare] Scripts written: {script_info}")


# ============================================================================ #
# Exhaustive Planner
# ============================================================================ #

@BasePlanner.register("exhaustive")
class ExhaustivePlanner(BasePlanner, HasLogger):
    """
    A brute-force planner that exhaustively searches the parameter space.

    Uses random interleaving of repetitions within the execution matrix.
    """

    def __init__(self, cfg: GenericBenchmarkConfig):
        super().__init__(cfg)

        self.execution_matrix: list[Any] | None = None
        self.current_index: int = 0
        self.total_tests: int = 0

        # Control flag to ensure we only build the matrix once
        self._matrix_built: bool = False

        # State for random interleaving of repetitions
        self._active_indices: list[int] = []          # tests with reps remaining
        self._next_rep_by_idx: dict[int, int] = {}    # next rep (0-based) per test index
        self._total_reps_by_idx: dict[int, int] = {}  # total reps per test index
        self._attempt_count: int = 0                  # attempts emitted in current matrix
        self._attempt_total: int = 0                  # sum(repetitions) in current matrix

        self.logger.info("Exhaustive planner initialized.")

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _init_interleaving_state(self) -> None:
        """
        Initialize the bookkeeping for the current execution_matrix.
        """
        assert self.execution_matrix is not None

        self._active_indices = []
        self._next_rep_by_idx = {}
        self._total_reps_by_idx = {}
        self._attempt_count = 0
        self._attempt_total = 0

        for i, t in enumerate(self.execution_matrix):
            reps = int(getattr(t, "repetitions", 1) or 1)
            if reps < 1:
                reps = 1
            self._next_rep_by_idx[i] = 0
            self._total_reps_by_idx[i] = reps
            self._attempt_total += reps
            self._active_indices.append(i)

        self.logger.debug(
            f"  [Matrix] Built: {self.total_tests} unique parameter combinations, "
            f"{self._attempt_total} total attempts (with repetitions)"
        )

    def _build_execution_matrix(self) -> bool:
        """
        Build the execution matrix.

        Returns:
            True if a new matrix with at least one test was built.
            False if the matrix was already built (no more tests).
        """
        if self._matrix_built:
            self.logger.info("Execution matrix already built. No more tests.")
            return False

        self.logger.info("Building execution matrix...")

        # Reset per-matrix state
        self.current_index = 0

        self.execution_matrix = self.random_sample(build_execution_matrix(self.cfg))
        self.total_tests = len(self.execution_matrix)

        self._matrix_built = True  # mark as built

        self.logger.info("Total tests in execution matrix: %d", self.total_tests)

        if self.total_tests > 0:
            self._init_interleaving_state()

        return self.total_tests > 0

    def record_completed_test(self, test: Any) -> None:
        """
        Record a completed test.

        For the Exhaustive planner, this is a no-op since we don't need to track
        completed tests (no optimization/search happening).
        """
        pass

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def next_test(self) -> Any:
        """
        Returns the next test to run (including repetitions),
        or None when all tests are done.

        Uses random interleaving of repetitions.
        """
        while True:
            matrix_finished = (
                self.execution_matrix is not None
                and self.total_tests > 0
                and len(self._active_indices) == 0
            )

            # Need a matrix (first time) OR we finished the current one
            if self.execution_matrix is None or matrix_finished:
                # Attempt to build the matrix
                if not self._build_execution_matrix():
                    return None

                # The new matrix might be empty (weird config), so loop again if so
                if self.total_tests == 0:
                    continue

            # At this point we have a valid matrix with remaining attempts
            assert self.execution_matrix is not None, "Execution matrix should be populated"
            idx = self.random.choice(self._active_indices)
            test = self.execution_matrix[idx]

            rep_idx = self._next_rep_by_idx[idx]
            self._next_rep_by_idx[idx] += 1
            self._attempt_count += 1

            # If this test is done, remove it from the active pool
            if self._next_rep_by_idx[idx] >= self._total_reps_by_idx[idx]:
                # remove by value (list is small; fine)
                self._active_indices.remove(idx)

            # Logging: attempt-oriented
            self.logger.debug(
                f"  [Planner] Selected test (attempt {self._attempt_count}/{self._attempt_total}): "
                f"exec_id={getattr(test, 'execution_id', '?')} "
                f"rep={rep_idx + 1}/{getattr(test, 'repetitions', 1)}"
            )

            # Prepare filesystem artifacts (dirs + scripts) for this test+repetition
            # rep_idx is 0-based, _prepare_execution_artifacts expects 1-based
            self._prepare_execution_artifacts(test, rep_idx + 1)
            return test


# ============================================================================ #
# Random Sampling Planner
# ============================================================================ #

@BasePlanner.register("random")
class RandomSamplingPlanner(ExhaustivePlanner):
    """
    Random sampling planner that randomly samples N configurations from the
    full parameter space.

    Inherits from ExhaustivePlanner and overrides _build_execution_matrix to
    add random sampling before the standard matrix processing.

    Configuration (YAML):
        benchmark:
          search_method: "random"
          random_config:
            # Option 1: Explicit number of samples
            n_samples: 20

            # Option 2: Percentage of total space (mutually exclusive with n_samples)
            # percentage: 0.1  # 10% of parameter space

            # Optional: behavior when n_samples >= total_space
            fallback_to_exhaustive: true  # default: true

    Features:
    - Random sampling without replacement
    - Repetition interleaving for statistical robustness (inherited)
    - Reproducible sampling with random_seed
    - Two sampling modes: explicit n_samples or percentage
    """

    def __init__(self, cfg: GenericBenchmarkConfig):
        # Call parent __init__ first (sets up execution_matrix, interleaving state, etc.)
        super().__init__(cfg)

        # Sampling configuration (already validated by loader)
        rc = cfg.benchmark.random_config
        self.n_samples: Optional[int] = rc.n_samples
        self.percentage: Optional[float] = rc.percentage
        self.fallback_to_exhaustive: bool = rc.fallback_to_exhaustive

        # Random-specific attributes
        self.total_space_size: int = 0  # Full parameter space size
        self.sampled_size: int = 0  # Actual sample size used

        # Log sampling mode
        sampling_mode = f"n_samples={self.n_samples}" if self.n_samples is not None else f"percentage={self.percentage}"
        self.logger.info("Random sampling mode: %s", sampling_mode)

    def _compute_sample_size(self, total_space: int) -> int:
        """
        Compute the actual sample size based on configuration.

        Args:
            total_space: Total size of parameter space

        Returns:
            Sample size (clamped to valid range [1, total_space])
        """
        if self.n_samples is not None:
            # Explicit number of samples
            if self.n_samples >= total_space:
                if self.fallback_to_exhaustive:
                    self.logger.warning(
                        f"Requested n_samples={self.n_samples} >= total_space={total_space}. "
                        f"Using full exhaustive search."
                    )
                    return total_space
                else:
                    self.logger.warning(
                        f"Requested n_samples={self.n_samples} >= total_space={total_space}. "
                        f"Clamping to total_space."
                    )
                    return total_space
            return self.n_samples

        else:
            # Percentage-based sampling
            sample_size = max(1, int(total_space * self.percentage))
            self.logger.info(
                f"Sampling {self.percentage*100:.1f}% of parameter space: "
                f"{sample_size}/{total_space} configurations"
            )
            return sample_size

    def _sample_execution_matrix(self, full_matrix: list[Any]) -> list[Any]:
        """
        Randomly sample configurations from the full execution matrix.

        If exhaustive_vars is configured, groups instances by search point
        and samples search points (not individual instances), then returns
        all instances from selected search points.

        Args:
            full_matrix: Full execution matrix (all parameter combinations)

        Returns:
            Sampled subset of execution matrix
        """
        if not full_matrix:
            return full_matrix

        # Check if exhaustive_vars is being used
        has_exhaustive_vars = bool(full_matrix[0].exhaustive_var_names)

        if has_exhaustive_vars:
            # Group instances by search point
            search_point_groups = defaultdict(list)

            for instance in full_matrix:
                search_point = instance.get_search_point()
                search_point_groups[search_point].append(instance)

            # Total space size is the number of unique search points
            self.total_space_size = len(search_point_groups)
            self.sampled_size = self._compute_sample_size(self.total_space_size)

            if self.sampled_size >= self.total_space_size:
                # Use all search points (exhaustive)
                self.logger.info(
                    f"Using all {self.total_space_size} search points "
                    f"(each expanded with {len(full_matrix[0].exhaustive_var_names)} exhaustive vars)"
                )
                return full_matrix

            # Sample random search points
            search_points = list(search_point_groups.keys())
            sampled_search_points = self.random.sample(search_points, self.sampled_size)

            # Collect all instances from sampled search points
            sampled_matrix = []
            for sp in sampled_search_points:
                sampled_matrix.extend(search_point_groups[sp])

            exhaustive_count = len(search_point_groups[sampled_search_points[0]])
            self.logger.info(
                f"Randomly sampled {self.sampled_size}/{self.total_space_size} search points "
                f"({self.sampled_size/self.total_space_size*100:.1f}%), "
                f"each with {exhaustive_count} exhaustive var combinations. "
                f"Total instances: {len(sampled_matrix)}"
            )

            return sampled_matrix

        else:
            # Original behavior: no exhaustive vars, sample individual instances
            self.total_space_size = len(full_matrix)
            self.sampled_size = self._compute_sample_size(self.total_space_size)

            if self.sampled_size >= self.total_space_size:
                # Use full matrix (exhaustive)
                self.logger.info(
                    f"Using full parameter space: {self.total_space_size} configurations"
                )
                return full_matrix

            # Random sampling without replacement
            sampled_matrix = self.random.sample(full_matrix, self.sampled_size)

            self.logger.info(
                f"Randomly sampled {self.sampled_size}/{self.total_space_size} configurations "
                f"({self.sampled_size/self.total_space_size*100:.1f}%)"
            )

            return sampled_matrix

    def _build_execution_matrix(self) -> bool:
        """
        Build the execution matrix with random sampling.

        Returns:
            True if a new matrix with at least one test was built.
            False if the matrix was already built (no more tests).
        """
        if self._matrix_built:
            self.logger.info("Execution matrix already built. No more tests.")
            return False

        self.logger.info("Building execution matrix...")

        # Reset per-matrix state
        self.current_index = 0

        # Build full matrix, then sample
        full_matrix = build_execution_matrix(self.cfg)
        sampled_matrix = self._sample_execution_matrix(full_matrix)
        self.execution_matrix = self.random_sample(sampled_matrix)

        self.total_tests = len(self.execution_matrix)

        self._matrix_built = True  # mark as built

        self.logger.info(
            "Total tests in execution matrix: %d (sampled from %d)",
            self.total_tests,
            self.total_space_size,
        )

        if self.total_tests > 0:
            self._init_interleaving_state()

        return self.total_tests > 0


# ============================================================================ #
# Bayesian Optimization Planner
# ============================================================================ #

@BasePlanner.register("bayesian")
class BayesianPlanner(BasePlanner, HasLogger):
    """
    Bayesian optimization planner that intelligently explores parameter space
    to find optimal configurations for a target metric.

    Configuration (YAML):
        benchmark:
          search_method: "bayesian"
          bayesian_config:
            objective_metric: "metric"  # REQUIRED: Metric to optimize (must match parser metric)
            objective: "minimize"        # "minimize" (default) or "maximize"
            n_iterations: 20             # Total configurations to evaluate (default: 20)
            n_initial_points: 5          # Random exploration before optimization (default: 5)
            acquisition_func: "EI"       # "EI" (default), "PI", or "LCB"
            base_estimator: "RF"         # Surrogate model: "RF" (default), "GP", "ET", or "GBRT"
            xi: 0.01                     # Exploration-exploitation for EI/PI (higher = more exploration)
            kappa: 1.96                  # Exploration parameter for LCB (higher = more exploration)

    Surrogate Models (base_estimator):
        - "RF": Random Forest (default) - Best for categorical/mixed spaces
        - "GP": Gaussian Process - Best for continuous spaces, struggles with categoricals
        - "ET": Extra Trees - Similar to RF, slightly different tree building
        - "GBRT": Gradient Boosted Regression Trees

    Acquisition Functions:
        - "EI": Expected Improvement (default) - Balanced exploration/exploitation
        - "PI": Probability of Improvement - More exploitative, faster convergence
        - "LCB": Lower Confidence Bound - More explorative, controlled by kappa

    Numeric List Handling:
        For variables with list mode and numeric types (int/float), uses ordinal
        encoding instead of categorical. This allows the model to learn that
        higher indices correlate with higher/lower metric values.

    The planner will:
    1. Start with random exploration (n_initial_points)
    2. Build a surrogate model (Random Forest by default) from observed results
    3. Use acquisition function to suggest next promising point
    4. Iteratively improve to find optimal parameters

    Requires scikit-optimize: pip install scikit-optimize
    """

    def __init__(self, cfg: GenericBenchmarkConfig):
        super().__init__(cfg)

        if not SKOPT_AVAILABLE:
            raise ImportError(
                "scikit-optimize is required for Bayesian optimization. "
                "Install it with: pip install scikit-optimize"
            )

        # Bayesian config is guaranteed by loader to be set when search_method is "bayesian"
        self.bayesian_cfg = self.cfg.benchmark.bayesian_config

        # Optimization settings from BayesianConfig dataclass
        self.target_metric = self.bayesian_cfg.objective_metric
        self.objective = self.bayesian_cfg.objective
        self.n_initial_points = self.bayesian_cfg.n_initial_points
        self.n_iterations = self.bayesian_cfg.n_iterations
        self.acquisition_func = self.bayesian_cfg.acquisition_func
        self.xi = self.bayesian_cfg.xi
        self.kappa = self.bayesian_cfg.kappa
        self.base_estimator = self.bayesian_cfg.base_estimator

        # Build search space from swept variables
        # This also populates self.ordinal_mappings for index-to-value conversion
        self.ordinal_mappings: Dict[str, List[Any]] = {}  # var_name -> list of valid values
        self.search_space, self.var_names = self._build_search_space()

        if not self.search_space:
            raise ValueError("No swept variables found for Bayesian optimization")

        # Build acquisition function kwargs
        acq_func_kwargs = {}
        if self.acquisition_func in ['EI', 'PI']:
            acq_func_kwargs['xi'] = self.xi
        elif self.acquisition_func == 'LCB':
            acq_func_kwargs['kappa'] = self.kappa

        # Initialize Bayesian optimizer with Random Forest (better for categorical/mixed spaces)
        self.optimizer = Optimizer(
            dimensions=self.search_space,
            base_estimator=self.base_estimator,
            n_initial_points=self.n_initial_points,
            acq_func=self.acquisition_func,
            acq_func_kwargs=acq_func_kwargs,
            random_state=self.cfg.benchmark.random_seed,
        )

        # Execution tracking
        self.iteration = 0
        self.completed_tests: List[ExecutionInstance] = []
        self.X_observed: List[List[Any]] = []  # Parameter combinations tried
        self.y_observed: List[float] = []      # Observed metric values

        # Progress tracking for get_progress()
        self._attempt_count: int = 0
        self._attempt_total: int = self.n_iterations * (cfg.benchmark.repetitions or 1)

        # Total search space size (for comparison with exhaustive search)
        self.total_space_size = self._compute_total_space_size()

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
            f"n_initial={self.n_initial_points} estimator={self.base_estimator}"
        )
        self.logger.info(f"Search space: {len(self.search_space)} dimensions: {self.var_names}")
        if self.ordinal_mappings:
            self.logger.info(f"Using ordinal encoding for: {list(self.ordinal_mappings.keys())}")

        # Log search space coverage
        if self.total_space_size > 0:
            coverage_pct = (self.n_iterations / self.total_space_size) * 100
            savings_pct = 100 - coverage_pct
            self.logger.info(
                f"Total search space: {self.total_space_size} configurations. "
                f"Bayesian will explore {self.n_iterations} ({coverage_pct:.1f}%), "
                f"saving {savings_pct:.1f}% vs exhaustive search."
            )

    def _compute_total_space_size(self) -> int:
        """
        Compute the total number of configurations in the search space.

        Uses build_execution_matrix to get the exact count of all possible
        parameter combinations.

        Returns:
            Total number of possible configurations
        """
        full_matrix = build_execution_matrix(self.cfg, start_execution_id=0)
        return len(full_matrix)

    def _build_search_space(self):
        """
        Build scikit-optimize search space from swept variables.

        For numeric list variables, uses ordinal encoding (index-based) instead of
        Categorical to allow the surrogate model to interpolate between values.
        This is crucial for Random Forest to learn patterns like "higher values = better".

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
                values = sweep_cfg.values

                if var_config.type in ["int", "float"]:
                    # Numeric list: use ordinal encoding (index-based Integer dimension)
                    # This allows the model to interpolate: index 0 < index 1 < index 2
                    # Sort values to ensure ordering makes sense
                    sorted_values = sorted(values)
                    self.ordinal_mappings[var_name] = sorted_values

                    dim = Integer(
                        low=0,
                        high=len(sorted_values) - 1,
                        name=f"{var_name}_idx"
                    )
                    self.logger.debug(
                        f"  [Bayesian] Variable '{var_name}': ordinal encoding "
                        f"{sorted_values} -> indices [0, {len(sorted_values) - 1}]"
                    )
                else:
                    # Categorical (string) values - keep as Categorical
                    dim = Categorical(
                        categories=values,
                        name=var_name
                    )

                dimensions.append(dim)
                var_names.append(var_name)

        return dimensions, var_names

    def _params_to_dict(self, params: List[Any]) -> Dict[str, Any]:
        """
        Convert parameter list to dictionary, converting numpy types to native Python.

        For ordinal-encoded variables (numeric lists), converts the index back to
        the actual value from the sorted list.
        """
        result = {}
        for name, value in zip(self.var_names, params):
            # Convert numpy types to native Python types
            if hasattr(value, 'item'):
                # numpy scalar (np.int64, np.float64, etc.)
                value = value.item()

            # Convert ordinal index back to actual value
            if name in self.ordinal_mappings:
                idx = int(value)
                # Clamp to valid range (shouldn't be needed, but safety check)
                idx = max(0, min(idx, len(self.ordinal_mappings[name]) - 1))
                value = self.ordinal_mappings[name][idx]

            result[name] = value
        return result

    def _check_constraints(self, params: List[Any]) -> bool:
        """
        Check if parameters satisfy all constraints.

        Args:
            params: List of parameter values

        Returns:
            True if all constraints pass (or only have "warn" policy)
        """
        if not self.cfg.constraints:
            return True

        vars_dict = self._params_to_dict(params)
        is_valid, violations = check_constraints_for_vars(vars_dict, self.cfg.constraints)

        if violations:
            for constraint, msg in violations:
                if constraint.violation_policy == "warn":
                    self.logger.warning(f"  [Bayesian] {msg} (proceeding anyway)")
                else:
                    self.logger.debug(f"  [Bayesian] Constraint violated: {msg}")

        return is_valid

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
            self._attempt_count += 1
            test = self._create_test_instance(self.current_params, self.current_rep)
            self.logger.debug(
                f"  [Bayesian] Repetition {self.current_rep}/{self.repetitions} "
                f"of iteration {self.iteration + 1}"
            )
            return test

        # Get next point from optimizer, checking constraints
        max_constraint_retries = 100  # Avoid infinite loop if space is heavily constrained
        for retry in range(max_constraint_retries):
            next_params = self.optimizer.ask()

            if self._check_constraints(next_params):
                break

            # Constraint violated - tell optimizer this is a bad point
            self.logger.debug(
                f"  [Bayesian] Suggested point violates constraints, asking for another "
                f"(retry {retry + 1}/{max_constraint_retries})"
            )
            # Tell optimizer this point is infeasible with a large penalty
            # Note: scikit-optimize always minimizes internally, so inf is always "worst"
            # (for maximization, actual values are negated before telling the optimizer)
            self.optimizer.tell(next_params, float('inf'))
        else:
            self.logger.warning(
                f"  [Bayesian] Could not find valid point after {max_constraint_retries} retries. "
                f"Using last suggested point anyway."
            )

        self.current_params = next_params
        self.current_rep = 1
        self.iteration += 1
        self._attempt_count += 1

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

        Uses create_execution_instance from matrix.py for clean instance creation.

        Args:
            params: List of parameter values
            repetition: Repetition number (1-based)

        Returns:
            ExecutionInstance
        """
        vars_dict = self._params_to_dict(params)

        # Create instance directly using the matrix helper
        test = create_execution_instance(
            cfg=self.cfg,
            base_vars=vars_dict,
            execution_id=self.iteration,
            script_index=0,  # Use first script
            search_var_names=self.var_names,
        )

        test.repetition = repetition
        test.repetitions = self.repetitions

        # Prepare execution artifacts (folders and scripts)
        self._prepare_execution_artifacts(test, repetition)

        return test

    def record_completed_test(self, test: ExecutionInstance) -> None:
        """
        Record a completed test and update the Bayesian model.

        This is essential for Bayesian optimization - the optimizer needs
        to learn from completed tests to suggest better parameters.

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


# Backwards compatibility alias
Exhaustive = ExhaustivePlanner
