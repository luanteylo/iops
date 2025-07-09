from typing import Dict, Any, List
from iops.utils.logger import HasLogger
from collections import defaultdict
from pathlib import Path
import statistics
import yaml
import csv


class MetricsAnalyzer(HasLogger):
    """
    Analyzes benchmark results across phases to select the best parameter configuration
    according to a specified performance criterion and statistical operation.
    """

    def __init__(self):        
        self.results: List[Dict[str, Any]] = []
        self.history: Dict[str, Dict[str, Any]] = {}  # stepN -> {parameters, results}

    def record(self, result: Dict[str, Any], params: Dict[str, Any]):
        """
        Store a benchmark result together with the parameters used.
        """
        self.logger.debug("Recording benchmark result")
        combined = {"__parameters": params, "__results": result}

        self.logger.debug(f"Parameters: {params}")
        self.logger.debug(f"Results: {result}")
        

        self.results.append(combined)

    def save_record_csv(self, file_path: Path):
        """
        Save benchmark results to a flat CSV file with readable structure.
        """
        if not self.results:
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

        flat_results = [flatten(e) for e in self.results]
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
        if not self.history:
            self.logger.warning("No history to save")
            return

        try:
            with file_path.open("w") as f:
                yaml.dump(self.history, f, default_flow_style=False, sort_keys=False)
            self.logger.info(f"History saved to {file_path}")
        except Exception as e:
            self.logger.error(f"Failed to save history: {e}")

    def select_best(self, criterion: str, operation: str = "mean") -> Dict[str, Any]:
        """
        Select the best parameter configuration based on the given criterion using the specified operation.
        Supported operations: mean, median, max, min
        The criterion must be a key in the results' __results__ dictionary.
        """
        if not self.results:
            raise ValueError("No results recorded")

        grouped = defaultdict(list)
        for entry in self.results:
            uid = entry["__parameters"].get("__test_index")
            if uid is not None:
                grouped[uid].append(entry)
            else:
                self.logger.warning(f"Missing __test_index in parameters: {entry}")

        op_func = {
            "mean": statistics.mean,
            "median": statistics.median,
            "max": max,
            "min": min
        }.get(operation)

        if op_func is None:
            raise ValueError(f"Unsupported operation '{operation}'. Choose from mean, median, max, min")

        best_score = float("-inf")
        best_entry = None

        for uid, group in grouped.items():
            values = [e["__results"].get(criterion) for e in group if criterion in e["__results"]]
            if not values:
                continue
            try:
                score = op_func(values)
            except Exception as e:
                self.logger.warning(f"Failed to compute {operation} for {uid}: {e}")
                continue

            self.logger.info(f"Test {uid}: {operation} {criterion} = {score}, group size = {len(group)}")

            if score > best_score:
                best_score = score
                base = group[0]
                parameters = base["__parameters"]
                results = base["__results"].copy()
                results[criterion] = score  # explicitly store selected criterion value
                best_entry = {"parameters": parameters, "results": results}

        if best_entry is None:
            raise ValueError(f"No valid groups found for criterion '{criterion}'")

        phase_name = f"phase_{len(self.history)}"
        self.history[phase_name] = best_entry

        return best_entry

    def clean(self):
        """
        Clear all recorded results.
        """
        self.logger.debug("Clearing recorded results")
        self.results.clear()
