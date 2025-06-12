from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, List
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
        Yields full parameter dictionaries for each value in the sweep,
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
    def next_phase(self):
        pass

    @abstractmethod
    def has_next_phase(self) -> bool:
        pass

    @abstractmethod
    def update_for_next_phase(self, result):
        pass
