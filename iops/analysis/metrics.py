from typing import Dict, Any, List
from iops.utils.logger import HasLogger





class MetricsAnalyzer(HasLogger):
    """
    Analyzes benchmark results across phases to select the best parameter configuration
    according to a specified performance criterion.
    """

    METRIC_KEYS = {"bandwidth_avg", "latency", "throughput"}

    def __init__(self):
        self.logger.debug("Initializing MetricsAnalyzer")
        self.results: List[Dict[str, Any]] = []

    def record(self, result: Dict[str, Any], params: Dict[str, Any]):
        """
        Store a benchmark result together with the parameters used.
        """
        combined = {**params, **result}
        self.results.append(combined)
        self.logger.debug(f"Recorded result: {combined}")
        

    def select_best(self, criterion: str) -> Dict[str, Any]:
        """
        Select the best parameter configuration based on the given criterion.
        Returns only the parameter keys (excluding metrics).
        """
        if not self.results:
            raise ValueError("No results recorded")

        sorted_results = sorted(self.results, key=lambda x: x.get(criterion, 0), reverse=True)
        best_result = sorted_results[0]

        input_keys = {k for k in best_result if k not in self.METRIC_KEYS}
        self.logger.debug(f"Selecting best result based on criterion '{criterion}': {best_result}")
        self.logger.debug(f"Input keys for best result: {input_keys}")

        return {k: best_result[k] for k in input_keys}

    def clear(self):
        """
        Reset the stored results.
        """
        self.logger.debug("Clearing stored results")
        self.results = []
