
from iops.utils.logger import HasLogger
from iops.utils.generic_config import GenericBenchmarkConfig
from iops.utils.execution_matrix import ExecutionInstance, build_execution_matrix
from typing import List, Any
from abc import ABC, abstractmethod
from pathlib import Path

class BasePlanner(ABC):
    _registry = {}

    def __init__(self, cfg: GenericBenchmarkConfig):
        self.cfg = cfg        
    
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
    

    # get next test to run
    @abstractmethod
    def next_test(self) -> Any:
        pass
    

@BasePlanner.register("exhaustive")
class Exhaustive(BasePlanner, HasLogger):
    """
    A brute-force planner that exhaustively searches the parameter space,
    supports multiple rounds and repetitions.
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

        # Repetitions per test (planner-level)       
        self.current_rep: int = 0  # 0-based repetition index for current test

        # Defaults to be used for the *next* round
        self._defaults_for_next_round: dict[str, Any] = {}

        self.logger.info(
            "Exhaustive planner initialized. "
            "Multiple rounds: %s; rounds=%s",
            self.multiple_rounds,
            self.round_queue if self.round_queue else "single round",            
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
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
            self.current_rep = 0
            self.execution_matrix = None
            self.total_tests = 0

            if not self.round_queue:
                self.logger.info("All rounds have been exhausted. No more tests.")
                return False

            # Take next round from the queue
            self.current_round = self.round_queue.pop(0)
            self.logger.info("Building execution matrix for round: %s", self.current_round)

            # Assumes build_execution_matrix supports a `defaults=` kwarg
            self.execution_matrix = build_execution_matrix(
                self.cfg,
                round_name=self.current_round,
                defaults=self._defaults_for_next_round or None,
            )

            self.total_tests = len(self.execution_matrix)
            self.logger.info(
                "Total tests in execution matrix for round '%s': %d",
                self.current_round,
                self.total_tests,
            )
            return self.total_tests > 0

        # Case 2: single round (no cfg.rounds)
        if self._single_round_built:
            # We already built the single-round matrix once and fully consumed it.
            self.logger.info("Single-round execution matrix already built. No more tests.")
            return False

        self.logger.info("Building execution matrix for single round...")

        # reset per-matrix state
        self.current_index = 0
        self.current_rep = 0
        self.current_round = None

        self.execution_matrix = build_execution_matrix(self.cfg)
        self.total_tests = len(self.execution_matrix)
        self._single_round_built = True  # mark as built

        self.logger.info("Total tests in execution matrix: %d", self.total_tests)
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

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def next_test(self) -> Any:
        """
        Returns the next test to run (including repetitions),
        or None when all tests in all rounds are done.
        """

        while True:
            # Need a matrix (first time) OR we finished the current one -> build next
            if self.execution_matrix is None or self.current_index >= self.total_tests:
                # If we just finished a round in a multi-round setup,
                # pick best_exec and prepare defaults for the next round.
                if (
                    self.multiple_rounds
                    and self.execution_matrix is not None
                    and self.total_tests > 0
                    and self.current_index >= self.total_tests
                ):
                    best_exec = self._select_best_execution()
                    # propagate all vars as defaults for the next round
                    self._defaults_for_next_round = dict(getattr(best_exec, "vars", {}))
                    self.logger.info(
                        "Using vars from best execution as defaults for the next round."
                    )

                # Attempt to build the next matrix (round or single)
                if not self._build_next_execution_matrix():
                    # No more rounds / tests available
                    return None

                # The new matrix might be empty (weird config), so loop again if so
                if self.total_tests == 0:
                    continue

            # At this point we have a valid matrix with remaining tests
            test = self.execution_matrix[self.current_index]

            # Handle repetitions: same test object, multiple times
            rep_idx = self.current_rep
            self.current_rep += 1

            if self.current_rep >= test.repetitions:
                # Move to next test after the last repetition
                self.current_rep = 0
                self.current_index += 1

            # Logging (1-based indices for readability)
            test_idx_for_log = self.current_index + (0 if self.current_rep == 0 else 1)

            if self.current_round:
                self.logger.debug(
                    "Providing test %d/%d, repetition %d/%d from round '%s'",
                    test_idx_for_log,
                    self.total_tests,
                    rep_idx + 1,
                    test.repetitions,
                    self.current_round
                )
            else:
                self.logger.debug(
                    "Providing test %d/%d, repetition %d/%d (single round)",
                    test_idx_for_log,
                    self.total_tests,
                    rep_idx + 1,
                    test.repetitions                    
                )

            # Optional: annotate repetition in test metadata if available
            test.repetition = rep_idx + 1  # 1-based repetition number

            return test



        
 
