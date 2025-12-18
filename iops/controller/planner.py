from iops.utils.logger import HasLogger
from iops.utils.generic_config import GenericBenchmarkConfig
from iops.utils.execution_matrix import ExecutionInstance, build_execution_matrix

from typing import List, Any
from abc import ABC, abstractmethod
from pathlib import Path
import random


class BasePlanner(ABC, HasLogger):
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
            self.logger.debug(
                "Randomly sampling %d items from %d total items.",
                sample_size,
                len(items),
            )
            items = self.random.sample(items, sample_size)
        else:
            self.logger.debug("No items to sample from.")
        return items

    @abstractmethod
    def next_test(self) -> Any:
        pass


@BasePlanner.register("exhaustive")
class Exhaustive(BasePlanner, HasLogger):
    """
    A brute-force planner that exhaustively searches the parameter space,
    supports multiple rounds and repetitions.

    Idea B (implemented): random interleaving of repetitions within each execution_matrix.
    """

    def __init__(self, cfg: GenericBenchmarkConfig):
        super().__init__(cfg)

        # Queue of round names (empty list if no rounds were defined)
        self.round_queue: list[str] = [r.name for r in cfg.rounds] if cfg.rounds else []
        self.multiple_rounds: bool = len(self.round_queue) > 0

        self.current_round: str | None = None
        self.execution_matrix: list[Any] | None = None
        self.current_index: int = 0
        self.total_tests: int = 0

        # Single-round control flag
        self._single_round_built: bool = False

        # Defaults to be used for the *next* round
        self._defaults_for_next_round: dict[str, Any] = {}

        # ------------------------------------------------------------------
        # Idea B state (per execution_matrix): random interleaving of reps
        # ------------------------------------------------------------------
        self._active_indices: list[int] = []          # tests with reps remaining
        self._next_rep_by_idx: dict[int, int] = {}    # next rep (0-based) per test index
        self._total_reps_by_idx: dict[int, int] = {}  # total reps per test index
        self._attempt_count: int = 0                  # attempts emitted in current matrix
        self._attempt_total: int = 0                  # sum(repetitions) in current matrix

        self.logger.info(
            "Exhaustive planner initialized. "
            "Multiple rounds: %s; rounds=%s",
            self.multiple_rounds,
            self.round_queue if self.round_queue else "single round",
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
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

        self.logger.info(
            "Built matrix: %d tests, %d total attempts (random interleaving enabled).",
            self.total_tests,
            self._attempt_total,
        )

    def _build_next_execution_matrix(self) -> bool:
        """
        Build the next execution_matrix.

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

            if not self.round_queue:
                self.logger.info("All rounds have been exhausted. No more tests.")
                return False

            # Take next round from the queue
            self.current_round = self.round_queue.pop(0)
            self.logger.info("Building execution matrix for round: %s", self.current_round)

            # Assumes build_execution_matrix supports a `defaults=` kwarg
            self.execution_matrix = self.random_sample(
                build_execution_matrix(
                    self.cfg,
                    round_name=self.current_round,
                    defaults=self._defaults_for_next_round or None,
                )
            )

            self.total_tests = len(self.execution_matrix)

            self.logger.info(
                "Total tests in execution matrix for round '%s': %d",
                self.current_round,
                self.total_tests,
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

        self.execution_matrix = self.random_sample(build_execution_matrix(self.cfg))
        self.total_tests = len(self.execution_matrix)

        self._single_round_built = True  # mark as built

        self.logger.info("Total tests in execution matrix: %d", self.total_tests)

        if self.total_tests > 0:
            self._init_interleaving_state()

        return self.total_tests > 0

    def _select_best_execution(self) -> Any:
        """
        Select the best execution from the *previous* round.

        For now, as requested, this simply returns the last test.
        Later, you can upgrade this to use a metric stored in the test.
        """
        assert self.execution_matrix, "No executions to select from."
        best_exec = self.execution_matrix[-1]
        self.logger.info("Selected best execution (placeholder = last in round): %s", best_exec)
        return best_exec

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
        self.logger.debug(
            "Written script file for test %d: %s",
            test_idx_for_log,
            test.script_file,
        )

        if getattr(test, "post_script", None):
            test.post_script_file = exec_dir / f"post_{test.script_name}.sh"
            with open(test.post_script_file, "w") as f:
                f.write(test.post_script)
            self.logger.debug(
                "Written post-processing script file for test %d: %s",
                test_idx_for_log,
                test.post_script_file,
            )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def next_test(self) -> Any:
        """
        Returns the next test to run (including repetitions),
        or None when all tests in all rounds are done.

        Idea B: random interleaving of repetitions.
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
                    self._defaults_for_next_round = dict(getattr(best_exec, "vars", {}))
                    self.logger.info(
                        "Using vars from best execution as defaults for the next round."
                    )

                # Attempt to build the next matrix (round or single)
                if not self._build_next_execution_matrix():
                    return None

                # The new matrix might be empty (weird config), so loop again if so
                if self.total_tests == 0:
                    continue

            # At this point we have a valid matrix with remaining attempts
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
            if self.current_round:
                self.logger.debug(
                    "Providing attempt %d/%d: exec_id=%s (matrix idx=%d), repetition %d/%d from round '%s'",
                    self._attempt_count,
                    self._attempt_total,
                    getattr(test, "execution_id", "?"),
                    idx,
                    rep_idx + 1,
                    getattr(test, "repetitions", 1),
                    self.current_round,
                )
            else:
                self.logger.debug(
                    "Providing attempt %d/%d: exec_id=%s (matrix idx=%d), repetition %d/%d (single round)",
                    self._attempt_count,
                    self._attempt_total,
                    getattr(test, "execution_id", "?"),
                    idx,
                    rep_idx + 1,
                    getattr(test, "repetitions", 1),
                )

            # Prepare filesystem artifacts (dirs + scripts) for this test+repetition
            # test_idx_for_log is informational; we keep idx+1 as "matrix position"
            self._prepare_execution_artifacts(test, rep_idx, test_idx_for_log=idx + 1)
            return test
