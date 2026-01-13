"""
Find and explore IOPS execution folders.

This module provides functionality for the `iops find` command,
allowing users to discover and filter execution results.

Supports both filesystem paths and tar archives.
"""

import json
import tarfile
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
    Read execution status from status files.

    First checks for test-level status (SKIPPED) in exec_XXXX folder.
    Then checks repetition folders for execution status.

    Args:
        exec_path: Path to the exec_XXXX folder

    Returns:
        Dict with status info, or default values if file doesn't exist.
        Includes 'cached' field: True if all reps are cached, False if none,
        'partial' if some are cached.
        Includes 'metrics' field: Dict of metric_name -> average value across
        successful repetitions, or None if no metrics available.
    """
    # First check for test-level status (SKIPPED, PENDING, COMPLETE)
    test_status_file = exec_path / STATUS_FILENAME
    if test_status_file.exists():
        try:
            with open(test_status_file, 'r') as f:
                test_status = json.load(f)
                # If test is SKIPPED, return that directly
                if test_status.get("status") == "SKIPPED":
                    return test_status
        except (json.JSONDecodeError, OSError):
            pass

    # Check repetition folders for execution status
    rep_dirs = sorted(exec_path.glob("repetition_*"))
    if rep_dirs:
        # Aggregate status from repetitions
        statuses = []
        cached_flags = []
        error = None
        end_time = None
        # Collect metrics from all successful repetitions for averaging
        all_metrics: Dict[str, list] = {}

        for rep_dir in rep_dirs:
            rep_status_file = rep_dir / STATUS_FILENAME
            if rep_status_file.exists():
                try:
                    with open(rep_status_file, 'r') as f:
                        rep_status = json.load(f)
                        statuses.append(rep_status.get("status", "UNKNOWN"))
                        cached_flags.append(rep_status.get("cached", False))
                        if rep_status.get("error"):
                            error = rep_status.get("error")
                        if rep_status.get("end_time"):
                            end_time = rep_status.get("end_time")
                        # Collect metrics for averaging
                        rep_metrics = rep_status.get("metrics")
                        if rep_metrics:
                            for metric_name, metric_value in rep_metrics.items():
                                if metric_value is not None:
                                    if metric_name not in all_metrics:
                                        all_metrics[metric_name] = []
                                    all_metrics[metric_name].append(metric_value)
                except (json.JSONDecodeError, OSError):
                    statuses.append("UNKNOWN")
                    cached_flags.append(False)
            else:
                statuses.append("PENDING")
                cached_flags.append(False)

        # Determine overall status
        if any(s == "RUNNING" for s in statuses):
            overall = "RUNNING"
        elif any(s == "PENDING" for s in statuses):
            overall = "PENDING"
        elif any(s in ("FAILED", "ERROR") for s in statuses):
            overall = "FAILED"
        elif all(s == "SUCCEEDED" for s in statuses):
            overall = "SUCCEEDED"
        else:
            overall = "UNKNOWN"

        # Determine cache status: True if all cached, False if none, "partial" if mixed
        if all(cached_flags):
            cached = True
        elif any(cached_flags):
            cached = "partial"
        else:
            cached = False

        # Calculate average metrics (only for numeric values)
        avg_metrics = None
        if all_metrics:
            avg_metrics = {}
            for metric_name, values in all_metrics.items():
                try:
                    # Try to calculate average for numeric values
                    numeric_values = [float(v) for v in values if isinstance(v, (int, float))]
                    if numeric_values:
                        avg_metrics[metric_name] = sum(numeric_values) / len(numeric_values)
                except (ValueError, TypeError):
                    pass
            if not avg_metrics:
                avg_metrics = None

        return {
            "status": overall,
            "error": error,
            "end_time": end_time,
            "cached": cached,
            "metrics": avg_metrics,
        }

    # No repetition folders yet - check test-level status or default to PENDING
    if test_status_file.exists():
        try:
            with open(test_status_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    return {"status": "PENDING", "error": None, "end_time": None, "cached": False, "metrics": None}


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


def _is_archive(path: Path) -> bool:
    """Check if path is a tar archive."""
    if not path.is_file():
        return False
    return tarfile.is_tarfile(path)


def find_executions(
    path: Path,
    filters: Optional[List[str]] = None,
    show_command: bool = False,
    show_full: bool = False,
    hide_columns: Optional[set] = None,
    status_filter: Optional[str] = None,
    cached_filter: Optional[bool] = None
) -> None:
    """
    Find and display execution folders in a workdir or archive.

    Args:
        path: Path to workdir (run root), exec folder, or tar archive
        filters: Optional list of VAR=VALUE filters
        show_command: If True, display the command column
        show_full: If True, show full values without truncation
        hide_columns: Set of column names to hide
        status_filter: Filter by execution status (SUCCEEDED, FAILED, etc.)
        cached_filter: Filter by cache status (True=only cached, False=only executed)
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

    # Check if path is a tar archive
    if _is_archive(path):
        _find_executions_in_archive(
            path, filter_dict, show_command, show_full,
            hide_columns, status_filter, cached_filter
        )
        return

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
            show_full, hide_columns, status_filter, cached_filter
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
                    show_full, hide_columns, status_filter, cached_filter
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
    if status == "SKIPPED" and status_info.get("reason"):
        print(f"Skip Reason: {status_info['reason']}")
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
    status_filter: Optional[str] = None,
    cached_filter: Optional[bool] = None
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

    # Remove hidden columns from var_names
    var_names = sorted(v for v in all_vars if v not in hide_columns)

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

        # Get cache status
        cached = status_info.get("cached", False)

        # Apply cached filter
        if cached_filter is not None:
            # cached_filter=True means only show cached
            # cached_filter=False means only show executed (not cached)
            if cached_filter and not cached:
                continue
            if not cached_filter and cached:
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

        skip_reason = status_info.get("reason") if status == "SKIPPED" else None
        matches.append((exec_key, rel_path, params, command, status, skip_reason, cached))

    if not matches:
        filter_desc = []
        if filter_dict:
            filter_desc.append(f"parameters: {filter_dict}")
        if status_filter:
            filter_desc.append(f"status: {status_filter}")
        if cached_filter is not None:
            filter_desc.append(f"cached: {cached_filter}")
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

    # Status column (include skip reason and cache indicator in width calculation)
    if "status" not in hide_columns:
        def format_status(status, skip_reason, cached):
            result = status
            if status == "SKIPPED" and skip_reason:
                result = f"{status}:{skip_reason}"
            if cached is True:
                result += " [C]"
            elif cached == "partial":
                result += " [C*]"
            return result
        status_values = [format_status(m[4], m[5], m[6]) for m in matches]
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
    for exec_key, rel_path, params, command, status, skip_reason, cached in matches:
        row_parts = []

        if "path" not in hide_columns:
            row_parts.append(display_val(rel_path).ljust(col_widths["path"]))

        if "status" not in hide_columns:
            status_display = format_status(status, skip_reason, cached)
            row_parts.append(status_display.ljust(col_widths["status"]))

        for var in var_names:
            val = display_val(str(params.get(var, "")))
            row_parts.append(val.ljust(col_widths[var]))

        if show_command and "command" not in hide_columns:
            row_parts.append(display_val(command))

        print("  ".join(row_parts))


def _find_executions_in_archive(
    archive_path: Path,
    filter_dict: Dict[str, str],
    show_command: bool = False,
    show_full: bool = False,
    hide_columns: Optional[set] = None,
    status_filter: Optional[str] = None,
    cached_filter: Optional[bool] = None
) -> None:
    """
    Find and display executions from a tar archive.

    Args:
        archive_path: Path to the tar archive
        filter_dict: Dict of parameter filters
        show_command: If True, display the command column
        show_full: If True, show full values without truncation
        hide_columns: Set of column names to hide
        status_filter: Filter by execution status
        cached_filter: Filter by cache status
    """
    from iops.archive import ArchiveReader

    hide_columns = hide_columns or set()

    try:
        reader = ArchiveReader(archive_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error reading archive: {e}")
        return

    manifest = reader.get_manifest()
    if not manifest:
        print(f"No IOPS manifest found in archive: {archive_path}")
        return

    # Print archive header with metadata
    print(f"Archive: {archive_path.name}")
    print("-" * 40)
    print(f"IOPS Version:     {manifest.iops_version}")
    print(f"Created:          {manifest.created_at}")
    print(f"Source Host:      {manifest.source_hostname}")
    print(f"Archive Type:     {manifest.archive_type}")
    print(f"Original Path:    {manifest.original_path}")
    print(f"Total Executions: {manifest.total_executions}")
    print(f"Checksums:        {len(manifest.checksums)} files")
    print()
    print("Runs:")
    for run in manifest.runs:
        print(f"  - {run.name}: \"{run.benchmark_name}\" ({run.execution_count} executions)")

    # Get executions with filters
    executions = reader.list_executions(
        filters=filter_dict if filter_dict else None,
        status_filter=status_filter,
        cached_filter=cached_filter,
    )

    if not executions:
        filter_desc = []
        if filter_dict:
            filter_desc.append(f"parameters: {filter_dict}")
        if status_filter:
            filter_desc.append(f"status: {status_filter}")
        if cached_filter is not None:
            filter_desc.append(f"cached: {cached_filter}")
        if filter_desc:
            print(f"No executions match the filter ({', '.join(filter_desc)})")
        else:
            print("No executions found in archive.")
        return

    # Show by run for workdir archives
    if manifest.archive_type == "workdir":
        runs_shown = set()
        for run in manifest.runs:
            run_executions = [e for e in executions if e["run"] == run.name]
            if not run_executions:
                continue

            if run.name not in runs_shown:
                runs_shown.add(run.name)
                print(f"\n=== {run.name} ===")

            _display_archive_executions(
                run_executions, show_command, show_full, hide_columns
            )
    else:
        # Single run archive - metadata already shown in header
        _display_archive_executions(
            executions, show_command, show_full, hide_columns
        )

    print(f"\nFound {len(executions)} execution(s)")


def _display_archive_executions(
    executions: List[dict],
    show_command: bool = False,
    show_full: bool = False,
    hide_columns: Optional[set] = None
) -> None:
    """Display executions from archive in table format."""
    hide_columns = hide_columns or set()

    if not executions:
        return

    # Get all variable names
    all_vars = set()
    for exec_data in executions:
        all_vars.update(exec_data.get("params", {}).keys())

    var_names = sorted(v for v in all_vars if v not in hide_columns)

    # Determine truncation width
    truncate_width = None if show_full else DEFAULT_TRUNCATE_WIDTH

    def display_val(val: str) -> str:
        if truncate_width is None:
            return val
        return _truncate_value(val, truncate_width)

    def format_status(status, skip_reason, cached):
        result = status
        if status == "SKIPPED" and skip_reason:
            result = f"{status}:{skip_reason}"
        if cached is True:
            result += " [C]"
        elif cached == "partial":
            result += " [C*]"
        return result

    # Calculate column widths
    col_widths = {}

    if "path" not in hide_columns:
        path_values = [display_val(e["path"]) for e in executions]
        col_widths["path"] = max(len("Path"), max(len(v) for v in path_values))

    if "status" not in hide_columns:
        status_values = [format_status(e["status"], e.get("skip_reason"), e["cached"]) for e in executions]
        col_widths["status"] = max(len("Status"), max(len(v) for v in status_values))

    for var in var_names:
        var_values = [display_val(str(e["params"].get(var, ""))) for e in executions]
        col_widths[var] = max(len(var), max(len(v) for v in var_values) if var_values else 0)

    if show_command and "command" not in hide_columns:
        cmd_values = [display_val(e["command"]) for e in executions]
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
    for exec_data in executions:
        row_parts = []

        if "path" not in hide_columns:
            row_parts.append(display_val(exec_data["path"]).ljust(col_widths["path"]))

        if "status" not in hide_columns:
            status_display = format_status(exec_data["status"], exec_data.get("skip_reason"), exec_data["cached"])
            row_parts.append(status_display.ljust(col_widths["status"]))

        for var in var_names:
            val = display_val(str(exec_data["params"].get(var, "")))
            row_parts.append(val.ljust(col_widths[var]))

        if show_command and "command" not in hide_columns:
            row_parts.append(display_val(exec_data["command"]))

        print("  ".join(row_parts))
