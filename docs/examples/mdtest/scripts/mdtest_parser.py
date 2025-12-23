"""
mdtest output parser for IOPS.

Parses mdtest output and extracts performance metrics from the SUMMARY section.
"""

import re


def parse(file_path: str) -> dict:
    """
    Parse mdtest output file and extract performance metrics.

    mdtest outputs a SUMMARY rate table with the following format:

    SUMMARY rate: (of N iterations)
       Operation                     Max            Min           Mean        Std Dev
       ---------                     ---            ---           ----        -------
       File creation               36079.411      36079.411      36079.411          0.000
       File stat                  329691.957     329691.957     329691.957          0.000
       ...

    Args:
        file_path: Path to the mdtest output file

    Returns:
        dict: Metrics dictionary with operation rates (ops/sec)
              Keys: file_creation_rate, file_stat_rate, file_read_rate,
                    file_removal_rate, tree_creation_rate, tree_removal_rate
              Values: Mean operation rate from the SUMMARY section
    """
    with open(file_path, "r") as f:
        content = f.read()

    metrics = {}

    # Find the SUMMARY rate section
    summary_match = re.search(
        r"SUMMARY rate:.*?\n.*?Operation.*?Max.*?Min.*?Mean.*?Std Dev.*?\n.*?-+.*?\n(.*?)(?:\n\n|--\s+finished|\Z)",
        content,
        re.DOTALL | re.IGNORECASE,
    )

    if not summary_match:
        # If no summary section found, return None for all metrics
        return {
            "file_creation_rate": None,
            "file_stat_rate": None,
            "file_read_rate": None,
            "file_removal_rate": None,
            "tree_creation_rate": None,
            "tree_removal_rate": None,
        }

    summary_section = summary_match.group(1)

    # Parse each operation line
    # Format: "   Operation_name    max_val   min_val   mean_val   stddev_val"
    operation_lines = summary_section.strip().split("\n")

    for line in operation_lines:
        line = line.strip()
        if not line:
            continue

        # Split on whitespace and extract operation name and mean value
        parts = line.split()
        if len(parts) < 4:
            continue

        # Operation name can be multiple words, values are the last 4 numbers
        # Extract operation name (everything except last 4 numbers)
        operation_name = " ".join(parts[:-4]).lower()

        try:
            # Mean is the 3rd number from the end (Max, Min, Mean, StdDev)
            mean_value = float(parts[-2])
        except (ValueError, IndexError):
            continue

        # Map operation names to metric keys
        if "file creation" in operation_name:
            metrics["file_creation_rate"] = mean_value
        elif "file stat" in operation_name:
            metrics["file_stat_rate"] = mean_value
        elif "file read" in operation_name:
            metrics["file_read_rate"] = mean_value if mean_value > 0 else None
        elif "file removal" in operation_name:
            metrics["file_removal_rate"] = mean_value
        elif "tree creation" in operation_name:
            metrics["tree_creation_rate"] = mean_value if mean_value > 0 else None
        elif "tree removal" in operation_name:
            metrics["tree_removal_rate"] = mean_value if mean_value > 0 else None

    # Ensure all expected metrics are present (set to None if not found)
    for key in [
        "file_creation_rate",
        "file_stat_rate",
        "file_read_rate",
        "file_removal_rate",
        "tree_creation_rate",
        "tree_removal_rate",
    ]:
        if key not in metrics:
            metrics[key] = None

    return metrics
