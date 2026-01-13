"""Filtering logic for partial archive creation.

This module provides functions to filter executions and result files
for creating partial archives from running or completed benchmark campaigns.
"""

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

# Import constants from find module
from iops.results.find import (
    INDEX_FILENAME,
    STATUS_FILENAME,
    _read_status,
)


def filter_executions(
    run_root: Path,
    status_filter: Optional[str] = None,
    cached_filter: Optional[bool] = None,
    param_filters: Optional[Dict[str, str]] = None,
) -> Tuple[Set[str], int]:
    """
    Filter executions based on criteria.

    Args:
        run_root: Path to the run directory containing __iops_index.json
        status_filter: Filter by status (e.g., "SUCCEEDED", "FAILED")
        cached_filter: Filter by cache status (True=cached only, False=non-cached only)
        param_filters: Filter by parameter values (e.g., {"nodes": "4"})

    Returns:
        Tuple of (set of execution_ids matching filters, total execution count)

    Raises:
        FileNotFoundError: If index file doesn't exist
        ValueError: If no executions match the filters
    """
    index_file = run_root / INDEX_FILENAME
    if not index_file.exists():
        raise FileNotFoundError(f"Index file not found: {index_file}")

    with open(index_file, "r") as f:
        index_data = json.load(f)

    executions = index_data.get("executions", {})
    total_count = len(executions)
    matching_ids: Set[str] = set()

    for exec_id, exec_info in executions.items():
        exec_path = run_root / exec_info.get("path", exec_id)
        params = exec_info.get("params", {})

        # Read status
        status_info = _read_status(exec_path)
        status = status_info.get("status", "UNKNOWN")
        cached = status_info.get("cached", False)

        # Apply status filter
        if status_filter and status.upper() != status_filter.upper():
            continue

        # Apply cache filter
        if cached_filter is not None:
            if cached_filter and not cached:
                continue
            if not cached_filter and cached:
                continue

        # Apply parameter filters
        if param_filters:
            match = True
            for key, value in param_filters.items():
                if key not in params:
                    match = False
                    break
                if str(params[key]) != str(value):
                    match = False
                    break
            if not match:
                continue

        matching_ids.add(exec_id)

    return matching_ids, total_count


def create_filtered_index(
    original_index: Dict[str, Any],
    execution_ids: Set[str],
) -> Dict[str, Any]:
    """
    Create a filtered copy of __iops_index.json content.

    Args:
        original_index: Original index data
        execution_ids: Set of execution IDs to include

    Returns:
        Filtered index data with only matching executions
    """
    filtered = original_index.copy()
    original_executions = original_index.get("executions", {})

    filtered["executions"] = {
        exec_id: exec_info
        for exec_id, exec_info in original_executions.items()
        if exec_id in execution_ids
    }

    return filtered


def filter_result_file(
    source_path: Path,
    output_path: Path,
    execution_ids: Set[int],
) -> bool:
    """
    Create a filtered copy of a result file.

    Supports CSV, Parquet, and SQLite formats.
    Sanitizes the file (removes broken rows) and filters by execution_id.

    Args:
        source_path: Path to the source result file
        output_path: Path for the filtered output file
        execution_ids: Set of execution IDs (as integers) to include

    Returns:
        True if file was created with data, False if empty or failed
    """
    if not source_path.exists():
        return False

    suffix = source_path.suffix.lower()

    if suffix == ".csv":
        return _filter_csv(source_path, output_path, execution_ids)
    elif suffix == ".parquet":
        return _filter_parquet(source_path, output_path, execution_ids)
    elif suffix in (".db", ".sqlite", ".sqlite3"):
        return _filter_sqlite(source_path, output_path, execution_ids)
    else:
        # Unknown format - just copy the file
        shutil.copy2(source_path, output_path)
        return True


def _filter_csv(
    source_path: Path,
    output_path: Path,
    execution_ids: Set[int],
) -> bool:
    """Filter a CSV result file."""
    try:
        # Read with error handling for broken rows
        df = pd.read_csv(source_path, on_bad_lines="skip")
    except pd.errors.EmptyDataError:
        return False
    except Exception:
        return False

    if df.empty:
        return False

    # Filter by execution_id if column exists
    exec_col = "execution.execution_id"
    if exec_col in df.columns:
        # Convert to int for comparison
        df = df[df[exec_col].astype(int).isin(execution_ids)]

    if df.empty:
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return True


def _filter_parquet(
    source_path: Path,
    output_path: Path,
    execution_ids: Set[int],
) -> bool:
    """Filter a Parquet result file."""
    try:
        df = pd.read_parquet(source_path)
    except Exception:
        return False

    if df.empty:
        return False

    # Filter by execution_id if column exists
    exec_col = "execution.execution_id"
    if exec_col in df.columns:
        df = df[df[exec_col].astype(int).isin(execution_ids)]

    if df.empty:
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
    return True


def _filter_sqlite(
    source_path: Path,
    output_path: Path,
    execution_ids: Set[int],
    table: str = "results",
) -> bool:
    """Filter a SQLite result file."""
    try:
        # Copy the database first
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, output_path)

        with sqlite3.connect(output_path) as conn:
            # Check if table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
            if not cursor.fetchone():
                return False

            # Get column names
            cursor = conn.execute(f'PRAGMA table_info("{table}")')
            columns = [row[1] for row in cursor.fetchall()]

            exec_col = "execution.execution_id"
            if exec_col in columns:
                # Delete rows not in execution_ids
                placeholders = ",".join("?" * len(execution_ids))
                conn.execute(
                    f'DELETE FROM "{table}" WHERE "{exec_col}" NOT IN ({placeholders})',
                    list(execution_ids),
                )

            # Check if any rows remain
            cursor = conn.execute(f'SELECT COUNT(*) FROM "{table}"')
            count = cursor.fetchone()[0]

            if count == 0:
                output_path.unlink()
                return False

            conn.execute("VACUUM")

        return True
    except Exception:
        if output_path.exists():
            output_path.unlink()
        return False


def get_result_file_paths(run_root: Path) -> List[Path]:
    """
    Find result file paths in a run directory.

    Looks for common result file patterns: results.csv, results.parquet, results.db

    Args:
        run_root: Path to the run directory

    Returns:
        List of paths to result files found
    """
    result_patterns = [
        "*.csv",
        "*.parquet",
        "*.db",
        "*.sqlite",
        "*.sqlite3",
    ]

    result_files = []
    for pattern in result_patterns:
        for f in run_root.glob(pattern):
            # Skip IOPS metadata files
            if not f.name.startswith("__iops_"):
                result_files.append(f)

    return result_files
