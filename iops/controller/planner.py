from typing import Dict, Any
from iops.utils.config_loader import IOPSConfig
from iops.utils.logger import HasLogger

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, List, Iterator
import random
import uuid

@dataclass
class PhaseResult:
    """
    Holds the result of a completed optimization phase.
    """
    sweep_param: str
    best_params: Dict[str, Any]

@dataclass
class Phase:
    """
    Represents a phase of the sweep with a single parameter being optimized.
    """    
    sweep_param: str
    values: List[Any]
    fixed_params: Dict[str, Any]
    full_param_space: Dict[str, List[Any]]
    criterion: str = "bandwidth"
    repetitions: int = 1


    
    def get_parameter_combinations(self):
        """
        Yields full parameter dictionaries for each value in the sweep,a
        with support for repetitions and randomization.
        """       
        all_combinations = []        

        for value in self.values:
            params = self.fixed_params.copy()
            params[self.sweep_param] = value

            for key, options in self.full_param_space.items():
                if key not in params:
                    params[key] = options[0]  # fallback default
            
            # Generate a unique identifier for this combination
            test_uid = str(uuid.uuid4())
            for rep in range(self.repetitions):
                combo = params.copy()
                combo["__rep__"] = rep
                combo["__test_uid__"] = test_uid
                all_combinations.append(combo)

        random.shuffle(all_combinations)

        for combo in all_combinations:
            yield combo

class BasePlanner(ABC):
    @abstractmethod
    def next_phase(self) -> Phase:
        pass

    @abstractmethod
    def has_next_phase(self) -> bool:
        pass

    @abstractmethod
    def update_for_next_phase(self, result: PhaseResult):
        pass

    @abstractmethod
    def has_next_combination(self) -> bool:
        pass

    @abstractmethod
    def next_combination(self, last_result: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Returns the next parameter combination to test.
        Optionally takes in the result of the previous test to inform adaptive logic.
        """
        pass

class SweepPlanner(BasePlanner, HasLogger):
    """
    Sweep-based planner that iteratively explores parameter spaces
    by sweeping one parameter at a time.
    """

    def __init__(self, config: IOPSConfig, benchmark):
        super().__init__()
        self.config = config
        self.benchmark = benchmark
        self.tests = list(config.execution.tests)  # List of parameter names to sweep
        self.index = 0  # Phase index
        self.history: Dict[str, Any] = {}  # Best parameters found so far
        self.current_phase: Phase | None = None
        self.current_combinations: Iterator[Dict[str, Any]] = iter([])
        self._next_combo: Dict[str, Any] | None = None

    def has_next_phase(self) -> bool:
        return self.index < len(self.tests)

    def next_phase(self) -> Phase:
        sweep_param = self.tests[self.index]
        self.logger.info(f"Generating phase for parameter: {sweep_param}")
        self.index += 1

        self.current_phase = self.benchmark.build_phase(
            sweep_param=sweep_param,
            fixed_params=self.history
        )
        self.current_combinations = self._generate_combinations(self.current_phase)
        self._next_combo = next(self.current_combinations, None)
        return self.current_phase

    def has_next_combination(self) -> bool:
        return self._next_combo is not None

    def next_combination(self, last_result: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Returns the next parameter combination to test.
        Optionally uses last_result (not used in sweep mode).
        """
        if not self.has_next_combination():
            raise StopIteration("No more combinations.")
        combo = self._next_combo
        try:
            self._next_combo = next(self.current_combinations)
        except StopIteration:
            self._next_combo = None
        return combo

    def update_for_next_phase(self, result: PhaseResult):
        self.logger.info(f"Updating history with best result: {result}")
        self.history.update(result.best_params)

    def _generate_combinations(self, phase: Phase) -> Iterator[Dict[str, Any]]:
        """
        Generates all test parameter combinations for a phase,
        assigning a test UID and repetition count.
        """
        all_combinations = []
        sweep_param = phase.sweep_param

        for value in phase.values:
            base_params = phase.fixed_params.copy()
            base_params[sweep_param] = value

            # Fill in default values for other parameters not swept in this phase
            for key, options in phase.full_param_space.items():
                if key not in base_params:
                    base_params[key] = options[0]

            test_uid = str(uuid.uuid4())
            for rep in range(phase.repetitions):
                combo = base_params.copy()
                combo["__rep__"] = rep
                combo["__test_uid__"] = test_uid
                all_combinations.append(combo)

        random.shuffle(all_combinations)
        return iter(all_combinations)

class BayesianPlanner(BasePlanner):
    def __init__(self, config):
        #self.optimizer = Optimizer(
        #    dimensions=[(1, 32), (1024, 8192)],
        #    base_estimator="GP"
        #)
        self.history = []
        #...

    def phases(self):
        yield {"min_nodes": 2, "volume": 4096}  # Just an example

    def update_for_next_phase(self, result):
        self.optimizer.tell(list(result.values()), result["bandwidth_avg"])
