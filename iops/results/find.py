"""
Find and explore IOPS execution folders.

This module provides functionality for the `iops find` command,
allowing users to discover and filter execution results.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional

# IOPS file constants
INDEX_FILENAME = "__iops_index.json"
PARAMS_FILENAME = "__iops_params.json"
STATUS_FILENAME = "__iops_status.json"
METADATA_FILENAME = "__iops_run_metadata.json"

# Default truncation width for parameter values
DEFAULT_TRUNCATE_WIDTH = 30


def _truncate_value(value: str, max_width: int) -> str:
    """Truncate a value to max_width, showing the end (most relevant part)."""
    if len(value) <= max_width:
        return value
    # Handle edge case where max_width is too small for "..." + content
    if max_width <= 3:
        return "..."[:max_width] if max_width > 0 else ""
    return "..." + value[-(max_width - 3):]


def _read_status(exec_path: Path) -> Dict[str, Any]:
    """
    Read execution status from the status file.

    Args:
        exec_path: Path to the exec_XXXX folder

    Returns:
        Dict with status info, or default values if file doesn't exist
    """
    status_file = exec_path / STATUS_FILENAME
    if status_file.exists():
        try:
            with open(status_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    # Default: no status file means execution hasn't completed or is from old run
    return {"status": "PENDING", "error": None, "end_time": None}


def _read_run_metadata(run_root: Path) -> Dict[str, Any]:
    """
    Read run metadata from the metadata file.

    Args:
        run_root: Path to the run root directory (e.g., workdir/run_001)

    Returns:
        Dict with run metadata, or empty dict if file doesn't exist
    """
    metadata_file = run_root / METADATA_FILENAME
    if metadata_file.exists():
        try:
            with open(metadata_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def find_executions(
    path: Path,
    filters: Optional[List[str]] = None,
    show_command: bool = False,
    show_full: bool = False,
    hide_columns: Optional[set] = None,
    status_filter: Optional[str] = None
) -> None:
    """
    Find and display execution folders in a workdir.

    Args:
        path: Path to workdir (run root) or exec folder
        filters: Optional list of VAR=VALUE filters
        show_command: If True, display the command column
        show_full: If True, show full values without truncation
        hide_columns: Set of column names to hide
        status_filter: Filter by execution status (SUCCEEDED, FAILED, etc.)
    """
    path = path.resolve()
    hide_columns = hide_columns or set()

    # Parse filters into dict
    filter_dict: Dict[str, str] = {}
    if filters:
        for f in filters:
            if '=' not in f:
                print(f"Invalid filter format: {f} (expected VAR=VALUE)")
                return
            key, value = f.split('=', 1)
            filter_dict[key] = value

    # Check if path is an exec folder (has __iops_params.json)
    params_file = path / PARAMS_FILENAME
    if params_file.exists():
        _show_single_execution(path, params_file, show_command, show_full)
        return

    # Check if path is a run root (has __iops_index.json)
    index_file = path / INDEX_FILENAME
    if index_file.exists():
        _show_executions_from_index(
            path, index_file, filter_dict, show_command,
            show_full, hide_columns, status_filter
        )
        return

    # Try to find index in subdirectories (user might point to workdir containing run_XXX or dryrun_XXX)
    run_dirs = sorted(list(path.glob("run_*")) + list(path.glob("dryrun_*")))
    if run_dirs:
        for run_dir in run_dirs:
            index_file = run_dir / INDEX_FILENAME
            if index_file.exists():
                print(f"\n=== {run_dir.name} ===")
                _show_executions_from_index(
                    run_dir, index_file, filter_dict, show_command,
                    show_full, hide_columns, status_filter
                )
        return

    print(f"No IOPS execution data found in: {path}")
    print(f"Expected either {INDEX_FILENAME} (in run root) or {PARAMS_FILENAME} (in exec folder)")


def _show_single_execution(
    exec_dir: Path,
    params_file: Path,
    show_command: bool = False,
    show_full: bool = False
) -> None:
    """Show details for a single execution folder."""
    try:
        with open(params_file, 'r') as f:
            params = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading {params_file}: {e}")
        return

    # Try to read run metadata from parent (run root is 2 levels up: exec_XXXX -> runs -> run_root)
    run_root = exec_dir.parent.parent
    run_metadata = _read_run_metadata(run_root)
    bench_meta = run_metadata.get("benchmark", {})

    # Display run header with metadata
    if bench_meta.get("name"):
        print(f"\nBenchmark: {bench_meta['name']}")
    if bench_meta.get("description"):
        print(f"Description: {bench_meta['description']}")
    if bench_meta.get("hostname"):
        print(f"Host: {bench_meta['hostname']}")
    if bench_meta.get("timestamp"):
        print(f"Executed: {bench_meta['timestamp']}")

    # Read status
    status_info = _read_status(exec_dir)
    status = status_info.get("status", "UNKNOWN")

    print(f"\nStatus: {status}")
    if status_info.get("error"):
        print(f"Error: {status_info['error']}")
    if status_info.get("end_time"):
        print(f"Completed: {status_info['end_time']}")

    print("\nParameters:")
    for key, value in sorted(params.items()):
        val_str = str(value)
        if not show_full:
            val_str = _truncate_value(val_str, DEFAULT_TRUNCATE_WIDTH)
        print(f"  {key}: {val_str}")

    # Count repetition folders
    rep_dirs = sorted(exec_dir.glob("repetition_*"))
    if rep_dirs:
        print(f"\nRepetitions: {len(rep_dirs)}")

    # Show command from index file if requested
    if show_command:
        # Try to find command in parent's index file
        index_file = exec_dir.parent.parent / INDEX_FILENAME
        if index_file.exists():
            try:
                with open(index_file, 'r') as f:
                    index = json.load(f)
                exec_name = exec_dir.name
                if exec_name in index.get("executions", {}):
                    command = index["executions"][exec_name].get("command", "")
                    if command:
                        print(f"\nCommand:\n  {command}")
            except (json.JSONDecodeError, OSError):
                pass


def _show_executions_from_index(
    run_root: Path,
    index_file: Path,
    filter_dict: Dict[str, str],
    show_command: bool = False,
    show_full: bool = False,
    hide_columns: Optional[set] = None,
    status_filter: Optional[str] = None
) -> None:
    """Show executions from the index file, optionally filtered."""
    hide_columns = hide_columns or set()

    try:
        with open(index_file, 'r') as f:
            index = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading {index_file}: {e}")
        return

    benchmark_name = index.get("benchmark", "Unknown")
    executions = index.get("executions", {})

    # Read run metadata for additional info
    run_metadata = _read_run_metadata(run_root)
    bench_meta = run_metadata.get("benchmark", {})

    # Display run header with metadata
    print(f"Benchmark: {benchmark_name}")
    if bench_meta.get("description"):
        print(f"Description: {bench_meta['description']}")
    if bench_meta.get("hostname"):
        print(f"Host: {bench_meta['hostname']}")
    if bench_meta.get("timestamp"):
        print(f"Executed: {bench_meta['timestamp']}")

    if not executions:
        print("No executions found in index.")
        return

    # Get all variable names for header
    all_vars = set()
    for exec_data in executions.values():
        all_vars.update(exec_data.get("params", {}).keys())
    var_names = sorted(all_vars)

    # Remove hidden columns from var_names
    var_names = [v for v in var_names if v not in hide_columns]

    # Determine truncation width
    truncate_width = None if show_full else DEFAULT_TRUNCATE_WIDTH

    # Filter executions and collect status
    matches = []
    for exec_key, exec_data in sorted(executions.items()):
        params = exec_data.get("params", {})
        rel_path = exec_data.get("path", "")
        command = exec_data.get("command", "")

        # Read status from status file
        exec_path = run_root / rel_path
        status_info = _read_status(exec_path)
        status = status_info.get("status", "UNKNOWN")

        # Apply status filter
        if status_filter and status.upper() != status_filter.upper():
            continue

        # Apply parameter filters (partial match - only check specified vars)
        if filter_dict:
            match = True
            for fkey, fval in filter_dict.items():
                if fkey not in params:
                    match = False
                    break
                # Convert both to string for comparison
                if str(params[fkey]) != fval:
                    match = False
                    break
            if not match:
                continue

        matches.append((exec_key, rel_path, params, command, status))

    if not matches:
        filter_desc = []
        if filter_dict:
            filter_desc.append(f"parameters: {filter_dict}")
        if status_filter:
            filter_desc.append(f"status: {status_filter}")
        if filter_desc:
            print(f"No executions match the filter ({', '.join(filter_desc)})")
        else:
            print("No executions found.")
        return

    # Helper to get display value (with optional truncation)
    def display_val(val: str) -> str:
        if truncate_width is None:
            return val
        return _truncate_value(val, truncate_width)

    # Calculate column widths (using truncated values if truncation is enabled)
    col_widths = {}

    # Path column
    if "path" not in hide_columns:
        path_values = [display_val(m[1]) for m in matches]
        col_widths["path"] = max(len("Path"), max(len(v) for v in path_values))

    # Status column
    if "status" not in hide_columns:
        status_values = [m[4] for m in matches]
        col_widths["status"] = max(len("Status"), max(len(v) for v in status_values))

    # Variable columns
    for var in var_names:
        var_values = [display_val(str(m[2].get(var, ""))) for m in matches]
        col_widths[var] = max(len(var), max(len(v) for v in var_values) if var_values else 0)

    # Command column
    if show_command and "command" not in hide_columns:
        cmd_values = [display_val(m[3]) for m in matches]
        col_widths["command"] = max(len("Command"), max(len(v) for v in cmd_values) if cmd_values else 0)

    # Build header
    header_parts = []
    if "path" not in hide_columns:
        header_parts.append("Path".ljust(col_widths["path"]))
    if "status" not in hide_columns:
        header_parts.append("Status".ljust(col_widths["status"]))
    for var in var_names:
        header_parts.append(var.ljust(col_widths[var]))
    if show_command and "command" not in hide_columns:
        header_parts.append("Command")

    header = "  ".join(header_parts)
    print("\n")
    print(header)
    print("-" * len(header))

    # Print rows
    for exec_key, rel_path, params, command, status in matches:
        row_parts = []

        if "path" not in hide_columns:
            row_parts.append(display_val(rel_path).ljust(col_widths["path"]))

        if "status" not in hide_columns:
            row_parts.append(status.ljust(col_widths["status"]))

        for var in var_names:
            val = display_val(str(params.get(var, "")))
            row_parts.append(val.ljust(col_widths[var]))

        if show_command and "command" not in hide_columns:
            row_parts.append(display_val(command))

        print("  ".join(row_parts))
