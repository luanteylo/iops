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
    SKIPPED_MARKER_FILENAME,
    _read_status,
)


def _count_completed_repetitions(exec_path: Path) -> Tuple[int, int, Set[int]]:
    """
    Count completed repetitions for an execution.

    A repetition is considered "completed" if it has SUCCEEDED or FAILED status
    (i.e., it finished running, regardless of outcome).

    Args:
        exec_path: Path to the execution directory

    Returns:
        Tuple of (completed_count, total_count, set of completed repetition indices)
    """
    rep_dirs = sorted(exec_path.glob("repetition_*"))

    if not rep_dirs:
        # No repetition folders - check for skipped marker
        skipped_marker = exec_path / SKIPPED_MARKER_FILENAME
        if skipped_marker.exists():
            # Skipped tests count as 0 completed
            return 0, 0, set()
        # No marker and no reps - pending
        return 0, 1, set()

    completed_count = 0
    completed_indices: Set[int] = set()

    for rep_dir in rep_dirs:
        # Extract repetition index from folder name (e.g., "repetition_001" -> 0)
        try:
            rep_idx = int(rep_dir.name.split("_")[1]) - 1
        except (IndexError, ValueError):
            rep_idx = 0

        status_file = rep_dir / STATUS_FILENAME
        if status_file.exists():
            try:
                with open(status_file, "r") as f:
                    status_data = json.load(f)
                    status = status_data.get("status", "UNKNOWN")
                    if status in ("SUCCEEDED", "FAILED"):
                        completed_count += 1
                        completed_indices.add(rep_idx)
            except (json.JSONDecodeError, OSError):
                pass

    return completed_count, len(rep_dirs), completed_indices


def filter_executions(
    run_root: Path,
    status_filter: Optional[str] = None,
    cached_filter: Optional[bool] = None,
    param_filters: Optional[Dict[str, str]] = None,
    min_completed_reps: Optional[int] = None,
) -> Tuple[Set[str], int, Dict[str, Set[int]]]:
    """
    Filter executions based on criteria.

    Args:
        run_root: Path to the run directory containing __iops_index.json
        status_filter: Filter by status (e.g., "SUCCEEDED", "FAILED")
        cached_filter: Filter by cache status (True=cached only, False=non-cached only)
        param_filters: Filter by parameter values (e.g., {"nodes": "4"})
        min_completed_reps: Minimum number of completed repetitions required

    Returns:
        Tuple of (set of execution_ids matching filters, total execution count,
                  dict mapping exec_id to set of completed repetition indices)

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
    completed_reps_map: Dict[str, Set[int]] = {}

    for exec_id, exec_info in executions.items():
        exec_path = run_root / exec_info.get("path", exec_id)
        params = exec_info.get("params", {})

        # Count completed repetitions
        completed_count, total_reps, completed_indices = _count_completed_repetitions(exec_path)

        # Apply min_completed_reps filter
        if min_completed_reps is not None:
            if completed_count < min_completed_reps:
                continue
        else:
            # If no min_completed_reps specified, use status filter logic
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
        completed_reps_map[exec_id] = completed_indices

    return matching_ids, total_count, completed_reps_map


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
    completed_reps_map: Optional[Dict[int, Set[int]]] = None,
) -> bool:
    """
    Create a filtered copy of a result file.

    Supports CSV, Parquet, and SQLite formats.
    Sanitizes the file (removes broken rows) and filters by execution_id
    and optionally by repetition index.

    Args:
        source_path: Path to the source result file
        output_path: Path for the filtered output file
        execution_ids: Set of execution IDs (as integers) to include
        completed_reps_map: Optional dict mapping exec_id to set of completed
                           repetition indices. If provided, also filters by repetition.

    Returns:
        True if file was created with data, False if empty or failed
    """
    if not source_path.exists():
        return False

    suffix = source_path.suffix.lower()

    if suffix == ".csv":
        return _filter_csv(source_path, output_path, execution_ids, completed_reps_map)
    elif suffix == ".parquet":
        return _filter_parquet(source_path, output_path, execution_ids, completed_reps_map)
    elif suffix in (".db", ".sqlite", ".sqlite3"):
        return _filter_sqlite(source_path, output_path, execution_ids, completed_reps_map)
    else:
        # Unknown format - just copy the file
        shutil.copy2(source_path, output_path)
        return True


def _filter_dataframe(
    df: pd.DataFrame,
    execution_ids: Set[int],
    completed_reps_map: Optional[Dict[int, Set[int]]] = None,
) -> pd.DataFrame:
    """
    Filter a DataFrame by execution_id and optionally by repetition.

    Args:
        df: DataFrame to filter
        execution_ids: Set of execution IDs to include
        completed_reps_map: Optional dict mapping exec_id to completed rep indices

    Returns:
        Filtered DataFrame
    """
    exec_col = "execution.execution_id"
    rep_col = "execution.repetition"

    if exec_col not in df.columns:
        return df

    # Filter by execution_id
    df = df[df[exec_col].astype(int).isin(execution_ids)]

    # Filter by repetition if map provided
    if completed_reps_map is not None and rep_col in df.columns:
        mask = df.apply(
            lambda row: int(row[rep_col]) in completed_reps_map.get(int(row[exec_col]), set()),
            axis=1
        )
        df = df[mask]

    return df


def _filter_csv(
    source_path: Path,
    output_path: Path,
    execution_ids: Set[int],
    completed_reps_map: Optional[Dict[int, Set[int]]] = None,
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

    # Filter by execution_id and optionally by repetition
    df = _filter_dataframe(df, execution_ids, completed_reps_map)

    if df.empty:
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return True


def _filter_parquet(
    source_path: Path,
    output_path: Path,
    execution_ids: Set[int],
    completed_reps_map: Optional[Dict[int, Set[int]]] = None,
) -> bool:
    """Filter a Parquet result file."""
    try:
        df = pd.read_parquet(source_path)
    except Exception:
        return False

    if df.empty:
        return False

    # Filter by execution_id and optionally by repetition
    df = _filter_dataframe(df, execution_ids, completed_reps_map)

    if df.empty:
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
    return True


def _filter_sqlite(
    source_path: Path,
    output_path: Path,
    execution_ids: Set[int],
    completed_reps_map: Optional[Dict[int, Set[int]]] = None,
    table: str = "results",
) -> bool:
    """Filter a SQLite result file."""
    try:
        # For SQLite, read into DataFrame, filter, and write back
        # This is simpler than complex SQL for repetition filtering
        with sqlite3.connect(source_path) as conn:
            # Check if table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
            if not cursor.fetchone():
                return False

            df = pd.read_sql(f'SELECT * FROM "{table}"', conn)

        if df.empty:
            return False

        # Filter by execution_id and optionally by repetition
        df = _filter_dataframe(df, execution_ids, completed_reps_map)

        if df.empty:
            return False

        # Write filtered data to new database
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(output_path) as conn:
            df.to_sql(table, conn, if_exists="replace", index=False)

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
