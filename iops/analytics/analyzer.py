from typing import Dict, Any, List
from iops.utils.logger import HasLogger
from pathlib import Path
import statistics
import yaml
import csv


class MetricsAnalyzer(HasLogger):
    """
    Analyzes benchmark results across phases to select the best parameter configuration
    according to a specified performance criterion and statistical operation.
    """

    def __init__(self, criterion: str, operation: str):        
        self.logger.debug(f"MetricsAnalyzer initialized with criterion '{criterion}' and operation '{operation}'")
        self.current_records: Dict[str, Dict[str, Any]] = {}  # List of all recorded results grouped by test index
        self.best_per_phase: Dict[str, Dict[str, Any]] = {}  # stepN -> {parameters, results}
        self.all_records: List[Dict[str, Any]] = []  # History of all entries for all phases
        self.criterion = criterion
        self.operation = operation     
        self.op_func = {
            "mean": statistics.mean,
            "median": statistics.median,
            "max": max,
            "min": min
        }.get(self.operation)

        if self.op_func is None:
            raise ValueError(f"Unsupported operation '{operation}'. Choose from mean, median, max, min")
    
    def record(self, result: Dict[str, Any], params: Dict[str, Any]):
        """
        Store a benchmark result together with the parameters used.
        """
        self.logger.debug("Recording benchmark result")
        
        # check if criterion is in results
        if self.criterion not in result:
            self.logger.error(f"Criterion '{self.criterion}' not found in results: {result}")
            raise ValueError(f"Criterion '{self.criterion}' not found in results")
        
        # check if __test_index is in parameters
        if "__test_index" not in params:
            self.logger.error(f"Missing '__test_index' in parameters: {params}")
            raise ValueError("Missing '__test_index' in parameters")
    
        
        combined = {"__parameters": params, "__results": result}

        self.logger.debug(f"__parameters: {params}")
        self.logger.debug(f"__results: {result}")
        
        
        test_index = params["__test_index"]
        if test_index not in self.current_records:
            self.current_records[test_index] = []        
        self.current_records[test_index].append(combined)
        self.all_records.append(combined)

    def save_csv(self, file_path: Path):
        """
        Save all recorded results to a CSV file.
        """
        if not self.all_records:
            self.logger.warning("No results to save")
            return

        def flatten(entry):
            flat = {}
            for group_key in ("__parameters", "__results"):
                for key, value in entry.get(group_key, {}).items():
                    if isinstance(value, Path):
                        flat[f"{group_key[2:-2]}_{key}"] = str(value)
                    elif isinstance(value, dict):
                        for sub_key, sub_val in value.items():
                            flat[f"{group_key[2:-2]}_{key}_{sub_key}"] = str(sub_val)
                    else:
                        flat[f"{group_key[2:-2]}_{key}"] = value
            return flat

        flat_results = [flatten(e) for e in self.all_records]
        fieldnames = sorted({k for r in flat_results for k in r.keys()})

        try:
            with file_path.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in flat_results:
                    writer.writerow(row)
            self.logger.info(f"CSV results saved to {file_path}")
        except Exception as e:
            self.logger.error(f"Failed to save CSV results: {e}")

    def save_history_yaml(self, file_path: Path):
        """
        Save the history of best parameters to a YAML file.
        """
        if not self.best_per_phase:
            self.logger.warning("No history to save")
            return

        try:
            with file_path.open("w") as f:
                yaml.dump(self.best_per_phase, f, default_flow_style=False, sort_keys=False)
            self.logger.info(f"History saved to {file_path}")
        except Exception as e:
            self.logger.error(f"Failed to save history: {e}")

    def __compare_score(self, score: Any, best_score: Any) -> bool:
        """
        Compare the current score with the best score found so far.
        Returns True if the current score is better than the best score.
        """
        if best_score is None:
            return True
        if self.operation in ["max", "mean", "median"]:
            return score > best_score
        elif self.operation in ["min"]:
            return score < best_score

    def select_best(self) -> Dict[str, Any]:
        """
        Select the best parameter configuration based on the given criterion using the specified operation.
        Supported operations: mean, median, max, min
        The criterion must be a key in the results' __results dictionary.
        """
        if not self.current_records:
            raise ValueError("No results recorded")

        best_score = None
        best_entry = None

        for test_index, entries in self.current_records.items():
            self.logger.debug(f"Processing test index {test_index} with {len(entries)} entries")
            score = self.op_func([e["__results"].get(self.criterion) for e in entries])
            self.logger.info(f"Computed score for test index {test_index}: {score}")
            if self.__compare_score(score, best_score):
                best_score = score
                best_entry = {
                    "__parameters": entries[0]["__parameters"],
                    "__results": {self.criterion: score}                    
                }
                self.logger.debug(f"New best score found: {best_score} for test index {test_index}")        
        
        self.best_per_phase[f"phase_{len(self.best_per_phase)}"] = best_entry

        # clear current records after selection
        self.current_records = {}

        return best_entry

        
