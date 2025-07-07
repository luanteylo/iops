from typing import Dict, Any, List
from iops.utils.logger import HasLogger
from collections import defaultdict
import statistics
from pathlib import Path
import yaml
import csv


class MetricsAnalyzer(HasLogger):
    """
    Analyzes benchmark results across phases to select the best parameter configuration
    according to a specified performance criterion.
    """

    METRIC_KEYS = {"bandwidth", "latency"}

    def __init__(self):
        self.logger.debug("Initializing MetricsAnalyzer")
        self.results: List[Dict[str, Any]] = []

    def record(self, result: Dict[str, Any], params: Dict[str, Any]):
        """
        Store a benchmark result together with the parameters used.
        """
        self.logger.debug("Recording benchmark result")        
        combined = {**params, **result}
        self.logger.debug(f"\t Nodes: {combined.get('nodes')}, Volume: {combined.get('volume')}, OST Count: {combined.get('ost_count').name}.")
        self.logger.debug(f"\t Bandwidth: {combined.get('bandwidth', 'N/A')} MB/s, Latency: {combined.get('latency', 'N/A')} ms")
        self.results.append(combined) 

    def save_record_csv(self, file_path: Path):
        """
        Save benchmark results to a flat CSV file with readable structure.
        """
        if not self.results:
            self.logger.warning("No results to save")
            return

        def flatten(record):
            flat = {}
            for key, value in record.items():
                if isinstance(value, Path):
                    flat[key] = str(value)
                elif isinstance(value, dict):  # flatten one level
                    for sub_key, sub_val in value.items():
                        flat[f"{key}_{sub_key}"] = str(sub_val)
                else:
                    flat[key] = value
            return flat

        flat_results = [flatten(r) for r in self.results]
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
 
    def select_best(self, criterion: str) -> Dict[str, Any]:
        """
        Select the best parameter configuration based on the average of the given criterion,
        grouped by the test UID.
        """
        if not self.results:
            raise ValueError("No results recorded")

        # Group results by test UID
        grouped = defaultdict(list)
        for result in self.results:
            uid = result.get("__test_uid__")
            if uid is not None:
                grouped[uid].append(result)
            else:
                self.logger.warning(f"Missing __test_uid__ in result: {result}")

        best_avg = float("-inf")
        best_params = None

        for uid, group in grouped.items():
            values = [r.get(criterion, 0) for r in group if criterion in r]
            avg_value = statistics.mean(values) if values else float("-inf")
            std = statistics.stdev(values) if len(values) > 1 else 0

            self.logger.info(f"Test UID {uid}: avg {criterion} = {avg_value}  ± {std}, , group size = {len(group)}")

            if avg_value > best_avg:
                best_avg = avg_value
                # Pick one param config as representative (all should be the same except __rep__)
                base = group[0]
                input_keys = {k for k in base if k not in self.METRIC_KEYS and not k.startswith("__")}
                best_params = {k: base[k] for k in input_keys}
                best_params[criterion] = avg_value

        if best_params is None:
            raise ValueError(f"No valid groups found for criterion '{criterion}'")
     
        return best_params
    
    def clean(self):
        """
        Clear all recorded results.
        """
        self.logger.debug("Clearing recorded results")
        self.results.clear()

