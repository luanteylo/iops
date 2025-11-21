from typing import Dict, Any
from iops.utils.config_loader import IOPSConfig
from iops.utils.logger import HasLogger


from abc import ABC
from dataclasses import dataclass
from typing import Dict, Any, List, Iterator, List, Optional
import random
from pathlib import Path
from itertools import product
from collections import deque
import numpy as np
import os
import re

from smt.surrogate_models import KRG
from scipy.stats import norm





@dataclass
class Phase:
    """
    Represents a phase of the sweep with a single parameter being optimized.
    """    
    sweep_param: str # The parameter being swept (e.g., "volume", "nodes", "all")
    values: List[Any] # Possible values for the sweep parameter
    params: Dict[str, Any]  # Fixed parameters (or default values) for the phase
    meta_params: Dict[str, Any] = None  # Metadata parameters used by the IOPS framework
  
    phase_best_param: Dict[str, Any] = None  # Best parameters found in this phase
    phase_best_result: Dict[str, Any] = None  # Best result found in this phase



    

class BasePlanner(ABC):
    _registry = {}

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


    def next_phase(self) -> Phase:
        raise NotImplementedError("This method should be implemented in subclasses.")
    
    def update_phase(self, param: Dict[str, Any], result) -> None:
        """
        Updates the current phase with the best parameters and result found.
        """
        self.current_phase.phase_best_param = param
        self.current_phase.phase_best_result = result
        self.current_best = param
    
    def record_result(self, param: Dict[str, Any], result: Any) -> None:
        """
        Records the result of a test.
        This method can be overridden in subclasses to implement custom behavior.
        """
        pass


    @classmethod
    def register(cls, name):
        def decorator(subclass):
            cls._registry[name.lower()] = subclass
            return subclass
        return decorator
    
    @classmethod
    def build(cls, name: str, config, benchmark) -> "BasePlanner":
        executor_cls = cls._registry.get(name.lower())
        if executor_cls is None:
            raise ValueError(f"Executor '{name}' is not registered.")
        return executor_cls(config, benchmark)

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
   


@BasePlanner.register("greedy")
class Greedy(BasePlanner, HasLogger):
    """
    A brute-force planner that exhaustively searches the parameter space    
    """

    def __init__(self, config: IOPSConfig, benchmark):
        super().__init__(config, benchmark)


    def has_next_phase(self) -> bool:
        return self.phase_index < len(self.tests)

    def next_phase(self):
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


    

@BasePlanner.register("bayesian")
class BayesianOptimization(BasePlanner, HasLogger):
    """
    Planner that seeds with a 30% random initial sample (>=2 points),
    then uses Bayesian Optimization (KRG + EI) to pick the next candidate.
    Includes early-stopping to minimize the number of tests.
    No fallbacks: BO must be available and trainable.
    """

    # Adjust these if your parameter names differ
    _VOLUME_KEY = "volume"
    _NODES_KEY = "nodes"
    _OST_KEY = "ost_count"  # path like ".../folder<idx>"

    def __init__(self, config: "IOPSConfig", benchmark):
        super().__init__(config, benchmark)

        # Queues/pools
        self.initial_queue: deque[Dict[str, Any]] = deque()
        self.remaining_pool: List[Dict[str, Any]] = []
        self._buffer: Optional[Dict[str, Any]] = None

        # Phase & combinations
        self.current_phase = None
        self.current_combinations: List[Dict[str, Any]] = []

        # BO state
        self.X: Optional[np.ndarray] = None  # (n, d)
        self.y: Optional[np.ndarray] = None  # (n, 1)
        self.model: Optional[KRG] = None
        self._trained = False

        # ---- stopping params (tune or read from config) ----
        self.max_evals = getattr(self.config.execution, "max_iterations", 150)  # hard budget
        self.ei_tol = 1e-3           # EI threshold (absolute)
        self.min_improve = 1e-3      # absolute improvement to reset patience
        self.patience = 5            # no-improve patience

        # ---- tracking ----
        self.n_evals = 0
        self.best_y: Optional[float] = None
        self.no_improve_streak = 0
        self.random_engine = random.Random(42)  # reproducible

    # ------------------ Phase generation ------------------

    def has_next_phase(self) -> bool:
        return self.phase_index == 0  # One phase only for BO

    def next_phase(self):
        sweep_param = "all"
        self.current_phase = self.benchmark.build_phase(
            sweep_param=self.tests,
            params={}
        )

        self.current_phase.meta_params = {
            "__phase_index": self.phase_index,
            "__phase_folder": str(self.config.execution.workdir / f"{sweep_param}_{self.phase_index}"),
            "__phase_repetitions": self.config.execution.repetitions,
            "__phase_sweep_param": sweep_param,
            "__test_output": None,
            "__test_script": None,
            "__test_index": None,
            "__test_folder": None,
            "__test_repetition": None,
        }

        # Generate the full space of tests for this phase
        self.current_combinations = self.generate_combinations(self.current_phase)
        n = len(self.current_combinations)
        if n < 2:
            raise ValueError("BayesianOptimization requires at least 2 total candidates.")

        self.phase_index = None  # only one phase

        # ---- Seed split (>=2 initial points to allow model training) ----
        sample_size = max(2, int(0.2 * n))  # ensure >= 2
        sample_size = min(sample_size, n)   # never exceed n

        all_idx = list(range(n))
        sample_idx = set(self.random_engine.sample(all_idx, sample_size))
        initial_sample = [self.current_combinations[i] for i in sorted(sample_idx)]
        remaining = [self.current_combinations[i] for i in all_idx if i not in sample_idx]

        self.logger.info(f"Initial sample size: {len(initial_sample)}")
        self.logger.info(f"Remaining combinations size: {len(remaining)}")
        self.logger.info(f"Total combinations size: {n}")

        self.logger.debug(f"Initial sample index: {sample_idx}"   )

        self.initial_queue = deque(initial_sample)
        self.remaining_pool = remaining

        # Prime buffer with the first seed item
        self._buffer = self._pop_next()

        return self.current_phase

    def generate_combinations(self, phase) -> List[Dict[str, Any]]:
        """
        Build all test combinations (with repetitions), assigning folders/indexes.
        For each unique parameter combo, __test_index is constant across its repetitions.
        """
        all_combinations: List[Dict[str, Any]] = []

        value_space: Dict[str, list] = phase.values or {}
        sweep_keys = list(value_space.keys())
        sweep_products = product(*(value_space[k] for k in sweep_keys)) if sweep_keys else [()]

        for combo in sweep_products:
            # map sweep values to their keys
            sweep_assignment = dict(zip(sweep_keys, combo))
            parameters = {**phase.params, **sweep_assignment}

            # meta shared across reps
            base_meta = dict(phase.meta_params)
            base_meta["__test_index"] = self.test_index

            test_folder = Path(base_meta["__phase_folder"]) / f"test_{self.test_index}"
            base_meta["__test_folder"] = str(test_folder)

            reps = int(base_meta.get("__phase_repetitions", 1))
            for rep_index in range(reps):
                meta = dict(base_meta)
                meta["__test_repetition"] = rep_index
                meta["__test_output"] = str(test_folder / f"output_{rep_index}.out")
                meta["__test_script"] = str(test_folder / f"run_{rep_index}.sh")
                self.logger.debug(f"Combination: {parameters}, Meta: {meta}")
                all_combinations.append({**parameters, **meta})

            # increment once per unique param combo
            self.test_index += 1

        return all_combinations

    # ------------------ Iteration API ------------------

    def __iter__(self):
        while self.has_next_combination():
            yield self.next_combination()

    def has_next_combination(self) -> bool:
        if self._buffer is not None:
            return True
        if self._should_stop():
            return False
        self._buffer = self._pop_next()
        return self._buffer is not None

    def next_combination(self) -> Dict[str, Any]:
        if not self.has_next_combination():
            raise StopIteration("No more combinations available.")
        next_combo = self._buffer
        self._buffer = None
        return next_combo

    # ------------------ Selection mechanics ------------------

    def _pop_next(self) -> Optional[Dict[str, Any]]:
        """Serve from initial queue first; then let BO choose from the remaining pool."""
        if self.initial_queue:
            return self.initial_queue.popleft()
        if not self.remaining_pool:
            return None
        idx = self._bo_pick_index(self.remaining_pool)  # must be trained already
        if 0 <= idx < len(self.remaining_pool):
            return self.remaining_pool.pop(idx)
        return None

    # ------------------ BO glue ------------------

    def record_result(self, param: Dict[str, Any], result: float) -> None:
        """
        Call this right after executing a test to add the observation.
        `score` should be the objective to maximize (e.g., bandwidth).
        """
        x = self._params_to_vector(param)
        x = np.asarray(x, dtype=int)[None, :]   # (1, d)
        y = np.asarray([[result]], dtype=float)  # (1, 1)

        if self.X is None:
            self.X, self.y = x, y
            self.best_y = float(result)
            self.no_improve_streak = 0
        else:
            self.X = np.vstack((self.X, x))
            self.y = np.vstack((self.y, y))
            if self.best_y is None or float(result) > self.best_y + self.min_improve:
                self.best_y = float(result)
                self.no_improve_streak = 0
            else:
                self.no_improve_streak += 1

        self.n_evals += 1
        self._trained = False  # mark dirty; train lazily on next pick

    def _ensure_model_trained(self) -> None:
        """Train KRG when we have at least 2 points; raise if not trainable."""
        if self._trained:
            return
        if self.X is None or self.y is None or len(self.X) < 2:
            raise RuntimeError("Not enough observations to train the BO model (need >= 2).")

        if self.model is None:
            self.model = KRG(print_global=False)

        self.logger.info("Training KRG model...")
        self.model.set_training_values(self.X, self.y)
        self.model.train()
        self._trained = True
        self.logger.info(f"KRG trained on {len(self.X)} points.")

    def _bo_pick_index(self, pool: List[Dict[str, Any]]) -> int:
        """
        Compute EI over the remaining pool and return the argmax index.
        Requires a trained model; raises if model isn't trainable.
        """
        self._ensure_model_trained()

        Xc = np.vstack([self._params_to_vector(c) for c in pool]).astype(int)
        mean = self.model.predict_values(Xc)       # (n,1)
        var = self.model.predict_variances(Xc)     # (n,1)

        std = np.sqrt(np.maximum(var, 1e-12))
        y_best = float(np.max(self.y))
        ei = self._expected_improvement(mean, std, y_best, xi=0.01).reshape(-1)
    

        if ei.size == 0:
            raise RuntimeError("EI computation returned empty array.")
        return int(np.argmax(ei))

    @staticmethod
    def _expected_improvement(mean: np.ndarray, std: np.ndarray, y_best: float, xi: float = 0.01) -> np.ndarray:
        """
        EI = (μ - y_best - xi) * Φ(Z) + σ * φ(Z),  Z = (μ - y_best - xi) / σ
        """
        mu = mean.reshape(-1)
        s = std.reshape(-1)
        imp = mu - y_best - xi
        z = imp / (s + 1e-12)
        cdf = np.vectorize(norm.cdf)(z)
        pdf = np.vectorize(norm.pdf)(z)
        ei = imp * cdf + s * pdf
        return np.maximum(ei, 0.0)

    # ------------------ Stopping logic ------------------

    def _should_stop(self) -> bool:
        # 1) Budget
        if self.n_evals >= self.max_evals:
            self.logger.info(f"Stopping: reached budget ({self.n_evals}/{self.max_evals}).")
            return True

        # 2) Exhausted everything
        if not self.initial_queue and not self.remaining_pool:
            self.logger.info("Stopping: no candidates left.")
            return True


        return False

    # ------------------ Vectorization helpers ------------------

    def _params_to_vector(self, params: Dict[str, Any]) -> np.ndarray:
        """
        Map a param dict -> numeric vector [volume, nodes, ost_idx].
        """
        try:
            vol = int(params[self._VOLUME_KEY])
            nodes = int(params[self._NODES_KEY])
            ost_idx = self._get_folder_index(params[self._OST_KEY])
            return np.array([vol, nodes, ost_idx], dtype=int)
        except Exception as e:
            self.logger.error(f"Vectorization error for params {params}: {e}")
            raise

    @staticmethod
    def _get_folder_index(path: str) -> int:
        """
        Extract the numeric suffix from a folder name like ".../folder7" -> 7.
        """
        folder_name = os.path.basename(path)
        m = re.search(r'(\d+)$', folder_name)
        if not m:
            raise ValueError(f"No numeric index found in {path}")
        return int(m.group(1))



    

    
    

    


