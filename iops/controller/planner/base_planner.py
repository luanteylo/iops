from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, List


@dataclass
class PhaseResult:
    """
    Holds the result of a completed optimization phase.
    """
    phase_name: str
    best_params: Dict[str, Any]


@dataclass
class Phase:
    """
    Represents a phase of the sweep with a single parameter being optimized.
    """
    name: str
    sweep_param: str
    values: List[Any]
    fixed_params: Dict[str, Any]
    full_param_space: Dict[str, List[Any]]
    criterion: str = "bandwidth_avg"

    def get_parameter_combinations(self):
        """
        Yields full parameter dictionaries for each value in the sweep.
        """
        for value in self.values:
            params = self.fixed_params.copy()
            params[self.sweep_param] = value

            for key, options in self.full_param_space.items():
                if key not in params:
                    params[key] = options[0]  # fallback default

            yield params.copy()

class BasePlanner(ABC):
    @abstractmethod
    def phases(self):
        pass

    @abstractmethod
    def update_for_next_phase(self, result):
        pass
