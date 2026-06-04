# iops/cache/from_csv.py

"""Build an IOPS execution cache from a CSV file.

Each CSV row becomes one cached execution. The caller specifies which columns
hold parameters and which hold metrics. The resulting database can be reused
by IOPS runs with `--use-cache`, or inspected with `iops cache list|show|stats`.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .execution_cache import ExecutionCache


@dataclass
class CreateFromCsvStats:
    """Statistics from a CSV-to-cache conversion."""

    source_rows: int = 0
    stored_entries: int = 0
    skipped_rows: int = 0
    unique_parameter_sets: int = 0
    param_columns: List[str] = field(default_factory=list)
    metric_columns: List[str] = field(default_factory=list)

    def summary(self) -> str:
        """Return a human-readable summary of the conversion."""
        lines = [
            "Cache Creation Summary",
            "=" * 50,
            f"Source rows:           {self.source_rows}",
            f"Parameter columns:     {', '.join(self.param_columns) or '(none)'}",
            f"Metric columns:        {', '.join(self.metric_columns) or '(none)'}",
            "-" * 50,
            f"Stored entries:        {self.stored_entries}",
            f"Skipped rows:          {self.skipped_rows}",
            f"Unique parameter sets: {self.unique_parameter_sets}",
            "=" * 50,
        ]
        return "\n".join(lines)


def _coerce(value: Optional[str]) -> Any:
    """Best-effort conversion of a CSV string cell to int, float, bool, or str.

    Mirrors how IOPS normalizes parameter values so hashes line up with a real
    benchmark run (e.g. "8" and 8 hash the same).
    """
    if value is None:
        return None
    text = value.strip()
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    low = text.lower()
    if low in ("true", "false"):
        return low == "true"
    return text


def create_cache_from_csv(
    csv_file: Path,
    output_db: Path,
    param_columns: List[str],
    metric_columns: List[str],
    repetition_column: Optional[str] = None,
    delimiter: str = ",",
    logger: Optional[logging.Logger] = None,
) -> CreateFromCsvStats:
    """
    Build an IOPS execution cache from a CSV file.

    Each CSV row becomes one cached execution. Parameter columns form the cache
    key, metric columns are stored as the result metrics. Cell values are
    coerced to int/float/bool where possible so they match how IOPS normalizes
    parameters at run time.

    Args:
        csv_file: Path to the input CSV file (must have a header row).
        output_db: Path for the output cache database (must not exist).
        param_columns: CSV columns to treat as parameters (the cache key).
        metric_columns: CSV columns to treat as metrics.
        repetition_column: CSV column holding the repetition number. If None,
            repetitions are auto-numbered per unique parameter set (from 1).
        delimiter: CSV field delimiter (default: ',').
        logger: Optional logger for progress messages.

    Returns:
        CreateFromCsvStats with statistics about the conversion.

    Raises:
        FileNotFoundError: If csv_file doesn't exist.
        ValueError: If output_db exists, the CSV has no header, or requested
            columns are missing from the header.
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    csv_file = Path(csv_file)
    output_db = Path(output_db)

    if not csv_file.is_file():
        raise FileNotFoundError(f"CSV file not found: {csv_file}")

    if output_db.exists():
        raise ValueError(
            f"Output file already exists: {output_db}. "
            f"Remove it first or choose a different path."
        )

    if not param_columns:
        raise ValueError("At least one parameter column is required (--params)")
    if not metric_columns:
        raise ValueError("At least one metric column is required (--metrics)")

    stats = CreateFromCsvStats(
        param_columns=list(param_columns),
        metric_columns=list(metric_columns),
    )

    logger.info(f"Creating cache from CSV: {csv_file} -> {output_db}")
    logger.info(f"Parameter columns: {param_columns}")
    logger.info(f"Metric columns: {metric_columns}")

    with csv_file.open(newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        if reader.fieldnames is None:
            raise ValueError("CSV file is empty or has no header row")

        header = set(reader.fieldnames)
        wanted = set(param_columns) | set(metric_columns)
        if repetition_column:
            wanted.add(repetition_column)
        missing = wanted - header
        if missing:
            raise ValueError(
                f"Columns not found in CSV header: {sorted(missing)}. "
                f"Available columns: {sorted(header)}"
            )

        cache = ExecutionCache(db_path=output_db)

        # Track per-parameter-set repetition counts for auto-numbering.
        rep_counter: Dict[str, int] = {}

        for line_no, row in enumerate(reader, start=2):  # header is line 1
            stats.source_rows += 1
            params = {col: _coerce(row[col]) for col in param_columns}
            metrics = {col: _coerce(row[col]) for col in metric_columns}

            if repetition_column:
                rep_raw = _coerce(row[repetition_column])
                if not isinstance(rep_raw, int) or isinstance(rep_raw, bool):
                    logger.warning(
                        f"Line {line_no}: repetition value "
                        f"{row[repetition_column]!r} is not an integer; defaulting to 1"
                    )
                    repetition = 1
                else:
                    repetition = rep_raw
            else:
                key = repr(sorted(params.items(), key=lambda kv: kv[0]))
                repetition = rep_counter.get(key, 0) + 1
                rep_counter[key] = repetition

            cache.store_result(
                params=params,
                repetition=repetition,
                metrics=metrics,
                metadata={"status": "SUCCEEDED", "__source": "csv"},
            )
            stats.stored_entries += 1

    cache_stats = cache.get_cache_stats()
    stats.unique_parameter_sets = cache_stats["unique_parameter_sets"]

    logger.info(f"Stored {stats.stored_entries} entries from {stats.source_rows} row(s)")
    logger.info(f"Unique parameter sets: {stats.unique_parameter_sets}")

    return stats
