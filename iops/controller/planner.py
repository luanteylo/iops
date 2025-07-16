from typing import Dict, Any
from iops.utils.config_loader import IOPSConfig
from iops.utils.logger import HasLogger


from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, List, Iterator
import random
from pathlib import Path

@dataclass
class Phase:
    """
    Represents a phase of the sweep with a single parameter being optimized.
    """    
    sweep_param: str # The parameter being swept (e.g., "volume", "nodes")
    values: List[Any] # Possible values for the sweep parameter
    params: Dict[str, Any]  # Fixed parameters (or default values) for the phase
    meta_params: Dict[str, Any] = None  # Metadata parameters used by the IOPS framework
  
    phase_best_param: Dict[str, Any] = None  # Best parameters found in this phase
    phase_best_result: Dict[str, Any] = None  # Best result found in this phase



    

class BasePlanner(ABC):

    def __init__(self, config: IOPSConfig, benchmark):
        self.config = config
        self.benchmark = benchmark
        self.tests = list(config.execution.tests)  # List of parameter names to sweep
        self.phase_index = 0  # Phase index
        self.test_index = 0  # Index for the current combination within the phase

        self.current_phase: Phase | None = None  # Current phase being processed
        self.all_phases: List[Phase] = []  # All phases created during the sweep
        self.current_best: Dict[str, Any] = {}  # Best parameter found so far

        self.current_combinations: Iterator[Dict[str, Any]] = iter([])
        self._next_combo: Dict[str, Any] | None = None

        
    

    def has_next_phase(self) -> bool:
        return self.phase_index < len(self.tests)

    def next_phase(self) -> Phase:
        """
        Creates the next phase of the sweep based on the current index.
        # 
        """

        if self.current_phase is not None:
            self.all_phases.append(self.current_phase)
        

        sweep_param = self.tests[self.phase_index]

        self.current_phase = self.benchmark.build_phase(sweep_param=sweep_param, 
                                           params=self.current_best)
        
        self.logger.debug(f"Current phase: {self.current_phase}")   

        # update meta parameters for the phase
        self.current_phase.meta_params = {
            "__phase_index": self.phase_index,
            "__phase_folder": str(self.config.execution.workdir / f"{self.current_phase.sweep_param}_{self.phase_index}"),
            "__phase_repetitions": self.config.execution.repetitions,
            "__phase_sweep_param": sweep_param,            

            "__test_output": None, 
            "__test_script": None,
            "__test_index": None,       
            "__test_folder": None,  
            "__test_repetition": None, 
        }

        # call the generate_combinations method to generate all combinations for the current phase
        self.current_combinations = self.generate_combinations(self.current_phase)
        self._next_combo = next(self.current_combinations, None)
        
        self.phase_index += 1
        return self.current_phase
    
    def update_phase(self, param: Dict[str, Any], result) -> None:
        """
        Updates the current phase with the best parameters and result found.
        """
        self.current_phase.phase_best_param = param
        self.current_phase.phase_best_result = result
        self.current_best = param
        


    @classmethod   
    def generate_combinations(cls, phase: Phase) -> Iterator[Dict[str, Any]]:
        """
        Generates all test parameter combinations for a phase,
        assigning a test ID.
        This method should be overridden in subclasses.
        """
        raise NotImplementedError("This method should be implemented in subclasses.")
    
    @classmethod
    def next_combination(cls) -> Dict[str, Any]:
        """
        Returns a dictionary with the next parameter combination to test.
        This method should be overridden in subclasses.
        """
        raise NotImplementedError("This method should be implemented in subclasses.")
   


class BruteForce(BasePlanner, HasLogger):
    """
    A brute-force planner that exhaustively searches the parameter space    
    """

    def __init__(self, config: IOPSConfig, benchmark):
        super().__init__(config, benchmark)


    def generate_combinations(self, phase: Phase) -> Iterator[Dict[str, Any]]:
        """
        Generates all test parameter combinations for a phase,
        assigning a test UID and repetition count.
        """
        all_combinations = []
        sweep_param = phase.sweep_param

        for value in phase.values:
            meta_params = phase.meta_params.copy()            
            meta_params["__test_index"] = self.test_index
            #all_params = {**params, **phase.meta_params}  # Merge with meta parameters            
            test_folder = Path(meta_params["__phase_folder"]) / f"test_{self.test_index}"
            meta_params["__test_folder"] = str(test_folder)
            for rep_index in range(meta_params.get("__phase_repetitions")):
                parameters = phase.params.copy()  # Start with fixed parameters
                parameters[sweep_param] = value
                meta_params["__test_output"] = str(test_folder / f"output_{rep_index}.out")
                meta_params["__test_script"] = str(test_folder / f"run_{rep_index}.sh")
                meta_params["__test_repetition"] = rep_index

                all_combinations.append({**parameters, **meta_params})
            
            self.test_index += 1

        random.shuffle(all_combinations)
        return iter(all_combinations)
    
    def __iter__(self):
        while self.has_next_combination():            
            yield self.next_combination()
            
    def next_combination(self) -> Dict[str, Any]:
        """"
        Returns the next parameter combination to test.
        """
        if self._next_combo is None:
            raise StopIteration("No more combinations available.")
        
        next_combo = self._next_combo
        self._next_combo = next(self.current_combinations, None)
        return next_combo
    
    def has_next_combination(self) -> bool:
        """
        Returns True if there are more combinations to test.
        """
        return self._next_combo is not None


    



    


