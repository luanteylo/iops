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

class BasePlanner(ABC):

    def __init__(self, config: IOPSConfig, benchmark):
        self.config = config
        self.benchmark = benchmark
        self.tests = list(config.execution.tests)  # List of parameter names to sweep
        self.index = 0  # Phase index
        self.history: Dict[str, Any] = {}  # Best parameters found so far
        self.current_phase: Phase | None = None
        self.current_combinations: Iterator[Dict[str, Any]] = iter([])
        self._next_combo: Dict[str, Any] | None = None
        self.current_phase_path = None
        self.combinations_path = {} # uses the uid to store the path to the combinations file
    

    def has_next_phase(self) -> bool:
        return self.index < len(self.tests)

    def next_phase(self) -> Phase:
        """
        Creates the next phase of the sweep based on the current index.
        # 
        """
        sweep_param = self.tests[self.index]
        self.logger.info(f"Generating phase for parameter: {sweep_param}")

        self.current_phase_path = self.config.execution.workdir / f"phase{self.index}_{sweep_param}"
        self.current_phase_path.mkdir(parents=True, exist_ok=True)

        self.current_phase = self.benchmark.build_phase(
            sweep_param=sweep_param,
            fixed_params=self.history
        )
        self.current_combinations = self._generate_combinations(self.current_phase)

        self._next_combo = next(self.current_combinations, None)
        self.index += 1
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
        print(combo)
        return combo

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
            test_folder = self.current_phase_path / f"test_{test_uid}"
            test_folder.mkdir(parents=True, exist_ok=True)
            
            base_params["__test_uid__"] = test_uid
            base_params["__phase__"] = phase.sweep_param
            base_params["__path__"] = test_folder

            for rep in range(phase.repetitions):
                combo = base_params.copy()
                combo["__rep__"] = rep            
                combo["__script__"] = test_folder / f"run_{rep}.sh"
                combo["__output__"] = test_folder / f"output_{rep}.csv"
                all_combinations.append(combo)

        random.shuffle(all_combinations)
        return iter(all_combinations)
    
    @abstractmethod
    def update_for_next_phase(self, result: PhaseResult):
        pass

    @abstractmethod 
    def update_for_nex_combination(self, result: PhaseResult):
        pass

class SweepPlanner(BasePlanner, HasLogger):
    """
    Sweep-based planner that iteratively explores parameter spaces
    by sweeping one parameter at a time.
    """

    def __init__(self, config: IOPSConfig, benchmark):
        super().__init__(config, benchmark)

    def update_for_nex_combination(self, result):
        pass

    def update_for_next_phase(self, result: PhaseResult):
        self.logger.info(f"Updating history with best result: {result}")
        self.history.update(result.best_params)



class BayesianPlanner(BasePlanner):
    def __init__(self, config):
        #self.optimizer = Optimizer(
        #    dimensions=[(1, 32), (1024, 8192)],
        #    base_estimator="GP"
        #)
        self.history = []
        #...

    def update_for_nex_combination(self, result):
        pass
    def update_for_next_phase(self, result):
        pass
        