"""Random sampling planner for IOPS.

This module implements a random sampling planner that randomly samples N configurations
from the full parameter space. Supports multi-round optimization with best-result
propagation, following the exhaustive planner's proven patterns.
"""

import copy
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Optional

from iops.config.models import GenericBenchmarkConfig
from iops.execution.matrix import build_execution_matrix
from iops.execution.planner import BasePlanner
from iops.logger import HasLogger


@BasePlanner.register("random")
class RandomSamplingPlanner(BasePlanner, HasLogger):
    """
    Random sampling planner that randomly samples N configurations from the
    full parameter space.

    Supports multi-round optimization with best-result propagation between rounds.
    Uses the same repetition interleaving strategy as the exhaustive planner for
    statistical robustness.

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
    - Multi-round optimization with best-result propagation
    - Repetition interleaving for statistical robustness
    - Reproducible sampling with random_seed
    - Two sampling modes: explicit n_samples or percentage
    """

    def __init__(self, cfg: GenericBenchmarkConfig):
        super().__init__(cfg)

        # Get random sampling configuration
        self.random_cfg = self._get_random_config()

        # Sampling configuration
        self.n_samples: Optional[int] = self.random_cfg.get('n_samples')
        self.percentage: Optional[float] = self.random_cfg.get('percentage')
        self.fallback_to_exhaustive: bool = self.random_cfg.get('fallback_to_exhaustive', True)

        # Validate configuration
        self._validate_config()

        # Queue of round names (empty list if no rounds were defined)
        self.round_queue: list[str] = [r.name for r in cfg.rounds] if cfg.rounds else []
        self.multiple_rounds: bool = len(self.round_queue) > 0

        self.current_round: str | None = None
        self.execution_matrix: list[Any] | None = None
        self.current_index: int = 0
        self.total_tests: int = 0
        self.total_space_size: int = 0  # Full parameter space size
        self.sampled_size: int = 0  # Actual sample size used

        # Single-round control flag
        self._single_round_built: bool = False

        # Defaults to be used for the *next* round
        self._defaults_for_next_round: dict[str, Any] = {}

        # Track completed tests for search (includes all repetitions)
        self._completed_tests: list[Any] = []

        # Repetition interleaving state (Idea B from exhaustive)
        self._active_indices: list[int] = []  # tests with reps remaining
        self._next_rep_by_idx: dict[int, int] = {}  # next rep (0-based) per test index
        self._total_reps_by_idx: dict[int, int] = {}  # total reps per test index
        self._attempt_count: int = 0  # attempts emitted in current matrix
        self._attempt_total: int = 0  # sum(repetitions) in current matrix

        # Log initialization
        sampling_mode = f"n_samples={self.n_samples}" if self.n_samples is not None else f"percentage={self.percentage}"
        self.logger.info(
            "Random sampling planner initialized. "
            "Sampling mode: %s; Multiple rounds: %s; rounds=%s",
            sampling_mode,
            self.multiple_rounds,
            self.round_queue if self.round_queue else "single round",
        )

    def _get_random_config(self) -> Dict[str, Any]:
        """
        Extract random sampling config from benchmark config.

        Returns:
            Dictionary with random sampling configuration.
        """
        if hasattr(self.cfg.benchmark, 'random_config') and self.cfg.benchmark.random_config:
            return self.cfg.benchmark.random_config

        # Return empty dict if not specified (will be caught by validation)
        return {}

    def _validate_config(self):
        """Validate random sampling configuration."""
        # Must have exactly one of n_samples or percentage
        if self.n_samples is not None and self.percentage is not None:
            raise ValueError(
                "random_config: cannot specify both 'n_samples' and 'percentage'. "
                "Choose one."
            )

        if self.n_samples is None and self.percentage is None:
            raise ValueError(
                "random_config: must specify either 'n_samples' or 'percentage'"
            )

        # Validate n_samples
        if self.n_samples is not None:
            if not isinstance(self.n_samples, int) or self.n_samples < 1:
                raise ValueError(
                    f"random_config.n_samples must be a positive integer, got: {self.n_samples}"
                )

        # Validate percentage
        if self.percentage is not None:
            if not isinstance(self.percentage, (int, float)) or self.percentage <= 0:
                raise ValueError(
                    f"random_config.percentage must be positive, got: {self.percentage}"
                )
            if self.percentage > 1.0:
                self.logger.warning(
                    f"random_config.percentage > 1.0 ({self.percentage}), clamping to 1.0"
                )
                self.percentage = 1.0

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
            from collections import defaultdict
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

    # ------------------------------------------------------------------ #
    # Internal helpers (from exhaustive planner)
    # ------------------------------------------------------------------ #

    def _init_interleaving_state(self) -> None:
        """
        Initialize the Idea B bookkeeping for the current execution_matrix.
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

    def _build_next_execution_matrix(self) -> bool:
        """
        Build the next execution_matrix with random sampling.

        Returns:
            True if a new matrix with at least one test was built.
            False if there are no more matrices (no more rounds / tests).
        """

        # Case 1: multiple rounds
        if self.multiple_rounds:
            # reset per-matrix state
            self.current_index = 0
            self.execution_matrix = None
            self.total_tests = 0
            self._completed_tests = []  # Clear completed tests for new round

            if not self.round_queue:
                self.logger.info("All rounds have been exhausted. No more tests.")
                return False

            # Take next round from the queue
            self.current_round = self.round_queue.pop(0)
            self.logger.info("Building execution matrix for round: %s", self.current_round)

            # Build full matrix, then sample
            full_matrix = build_execution_matrix(
                self.cfg,
                round_name=self.current_round,
                defaults=self._defaults_for_next_round or None,
            )

            # Sample from full matrix and shuffle
            sampled_matrix = self._sample_execution_matrix(full_matrix)
            self.execution_matrix = self.random_sample(sampled_matrix)

            self.total_tests = len(self.execution_matrix)

            self.logger.info(
                "Total tests in execution matrix for round '%s': %d (sampled from %d)",
                self.current_round,
                self.total_tests,
                self.total_space_size,
            )

            if self.total_tests > 0:
                self._init_interleaving_state()

            return self.total_tests > 0

        # Case 2: single round (no cfg.rounds)
        if self._single_round_built:
            self.logger.info("Single-round execution matrix already built. No more tests.")
            return False

        self.logger.info("Building execution matrix for single round...")

        # reset per-matrix state
        self.current_index = 0
        self.current_round = None

        # Build full matrix, then sample
        full_matrix = build_execution_matrix(self.cfg)
        sampled_matrix = self._sample_execution_matrix(full_matrix)
        self.execution_matrix = self.random_sample(sampled_matrix)

        self.total_tests = len(self.execution_matrix)

        self._single_round_built = True  # mark as built

        self.logger.info(
            "Total tests in execution matrix: %d (sampled from %d)",
            self.total_tests,
            self.total_space_size,
        )

        if self.total_tests > 0:
            self._init_interleaving_state()

        return self.total_tests > 0

    def record_completed_test(self, test: Any) -> None:
        """
        Record a completed test for later search.

        This captures the test state after execution, including all metrics.
        We need to make a copy because the test object gets reused for different repetitions.
        """
        # Deep copy to preserve metrics and metadata from this specific execution
        test_snapshot = copy.deepcopy(test)
        self._completed_tests.append(test_snapshot)

    def _select_best_execution(self) -> Any:
        """
        Select the best execution from the *previous* round based on search metric.

        When repetitions > 1, groups tests by parameter combination and computes
        average metric values across repetitions before selecting the best.

        The search configuration is stored in each test:
        - test.search_metric: metric name to optimize
        - test.search_objective: "max" or "min"

        Returns one test from the parameter group with the best average metric.
        """
        if not self._completed_tests:
            self.logger.warning("No completed tests to select from. Using last from matrix as fallback.")
            assert self.execution_matrix, "No executions to select from."
            return self.execution_matrix[-1]

        # Get search config from first test (all tests in round share same config)
        first_test = self._completed_tests[0]
        metric_name = getattr(first_test, "search_metric", None)
        objective = getattr(first_test, "search_objective", None)

        if not metric_name or not objective:
            self.logger.warning(
                "No search configuration found for round. Using last completed test as default."
            )
            return self._completed_tests[-1]

        self.logger.info(
            f"Searching for best execution: {objective} {metric_name}"
        )

        # Group tests by parameter combination (base_vars = params without repetition)
        # Map: param_signature -> [(test, metric_value), ...]
        param_groups = defaultdict(list)

        for test in self._completed_tests:
            metrics = test.metadata.get("metrics", {})
            if metric_name in metrics:
                try:
                    metric_value = float(metrics[metric_name])

                    # Create unique signature from base_vars (excludes repetition)
                    base_vars = getattr(test, "base_vars", {})
                    param_sig = json.dumps(base_vars, sort_keys=True, default=str)

                    param_groups[param_sig].append((test, metric_value))
                except (ValueError, TypeError):
                    self.logger.warning(
                        f"  [Search] Skipping test {test.execution_id}: "
                        f"invalid metric '{metric_name}'={metrics[metric_name]}"
                    )
            else:
                self.logger.debug(
                    f"  [Search] Skipping test {test.execution_id}: metric '{metric_name}' not found"
                )

        if not param_groups:
            self.logger.warning(
                f"No tests with valid '{metric_name}' metric found. Using last completed test as fallback."
            )
            return self._completed_tests[-1]

        # Compute average metric for each parameter combination
        group_averages = []
        for param_sig, tests_and_values in param_groups.items():
            values = [v for _, v in tests_and_values]
            avg_value = sum(values) / len(values)
            representative_test = tests_and_values[0][0]  # Use first test as representative

            group_averages.append((representative_test, avg_value, len(values)))

        # Find best group based on objective
        if objective == "max":
            best_test, best_avg, num_reps = max(group_averages, key=lambda x: x[1])
        elif objective == "min":
            best_test, best_avg, num_reps = min(group_averages, key=lambda x: x[1])
        else:
            self.logger.warning(
                f"Unknown objective '{objective}'. Using last completed test as fallback."
            )
            return self._completed_tests[-1]

        self.logger.info(
            f"Selected best parameter combination: execution_id={best_test.execution_id} "
            f"with {metric_name}_avg={best_avg:.4f} (averaged over {num_reps} repetitions, "
            f"from {len(group_averages)} unique parameter combinations)"
        )

        return best_test

    def _prepare_execution_artifacts(
        self,
        test: Any,
        rep_idx: int,
        test_idx_for_log: int,
    ) -> None:
        """
        Create folders + scripts for one test execution and one repetition.

        Layout:
        <workdir>/runs/
            ├── round_01_<round_name>/           (if rounds)
            │   └── exec_0001/
            │       └── repetition_001/
            │           ├── run_<script>.sh
            │           └── post_<script>.sh (optional)
            └── exec_0001/                       (if no rounds)
                └── repetition_001/
        """
        # 1-based repetition number
        test.repetition = rep_idx + 1
        if not hasattr(test, "metadata") or test.metadata is None:
            test.metadata = {}
        test.metadata["repetition"] = test.repetition

        run_root = Path(self.cfg.benchmark.workdir)
        runs_root = run_root / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)

        # ---- round dir ----
        if self.current_round:
            round_idx = getattr(test, "round_index", None)
            if round_idx is None:
                round_idx = next(
                    (i for i, r in enumerate(self.cfg.rounds) if r.name == self.current_round),
                    0,
                )
            round_dir = runs_root / f"round_{round_idx + 1:02d}_{self.current_round}"
        else:
            round_dir = runs_root

        round_dir.mkdir(parents=True, exist_ok=True)

        # ---- execution dir ----
        exec_dir = (
            round_dir
            / f"exec_{test.execution_id:04d}"
            / f"repetition_{test.repetition:03d}"
        )
        exec_dir.mkdir(parents=True, exist_ok=True)

        # Point to repetition dir (useful for templates like {{ execution_dir }})
        test.execution_dir = exec_dir

        # ---- script files live inside repetition dir ----
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

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def next_test(self) -> Any:
        """
        Returns the next test to run (including repetitions),
        or None when all tests in all rounds are done.

        Uses random interleaving of repetitions (Idea B from exhaustive planner).
        """
        while True:
            matrix_finished = (
                self.execution_matrix is not None
                and self.total_tests > 0
                and len(self._active_indices) == 0
            )

            # Need a matrix (first time) OR we finished the current one -> build next
            if self.execution_matrix is None or matrix_finished:
                # If we just finished a round in a multi-round setup,
                # pick best_exec and prepare defaults for the next round.
                if self.multiple_rounds and matrix_finished:
                    best_exec = self._select_best_execution()
                    best_vars = getattr(best_exec, "vars", {}) or {}
                    self._defaults_for_next_round = dict(best_vars)

                    # Log propagated values for visibility
                    if self._defaults_for_next_round:
                        propagated_str = ", ".join(
                            f"{k}={v}" for k, v in sorted(self._defaults_for_next_round.items())
                        )
                        self.logger.info(
                            f"Round '{self.current_round}' completed. "
                            f"Propagating {len(self._defaults_for_next_round)} values to next round: {propagated_str}"
                        )
                    else:
                        self.logger.warning(f"Round '{self.current_round}' completed but no variables to propagate")

                # Attempt to build the next matrix (round or single)
                if not self._build_next_execution_matrix():
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

            # Logging: attempt-oriented (more meaningful now)
            round_tag = f" [{self.current_round}]" if self.current_round else ""
            self.logger.debug(
                f"  [Planner] Selected test (attempt {self._attempt_count}/{self._attempt_total}): "
                f"exec_id={getattr(test, 'execution_id', '?')} "
                f"rep={rep_idx + 1}/{getattr(test, 'repetitions', 1)}{round_tag}"
            )

            # Prepare filesystem artifacts (dirs + scripts) for this test+repetition
            # test_idx_for_log is informational; we keep idx+1 as "matrix position"
            self._prepare_execution_artifacts(test, rep_idx, test_idx_for_log=idx + 1)
            return test
