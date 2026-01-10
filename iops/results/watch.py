"""
Watch mode for monitoring IOPS execution status in real-time.

This module provides functionality for the `iops find --watch` command,
allowing users to monitor execution progress with live updates.

Requires the 'rich' library: pip install iops-benchmark[watch]
"""

from __future__ import annotations

import json
import time
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# Check for rich availability
try:
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
    from rich.progress import Progress, BarColumn, TextColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# Import constants from find module
from .find import (
    INDEX_FILENAME,
    PARAMS_FILENAME,
    STATUS_FILENAME,
    METADATA_FILENAME,
    DEFAULT_TRUNCATE_WIDTH,
    _truncate_value,
    _read_status,
    _read_run_metadata,
)

# Sysinfo filename constant
SYSINFO_FILENAME = "__iops_sysinfo.json"


class WatchModeError(Exception):
    """Exception raised when watch mode cannot be used."""
    pass


def check_rich_available() -> None:
    """Check if rich is available, raise helpful error if not."""
    if not RICH_AVAILABLE:
        raise WatchModeError(
            "Watch mode requires the 'rich' library.\n"
            "Install with: pip install iops-benchmark[watch]"
        )


# Status display configuration
# All status-related display is centralized here for consistency

STATUS_ORDER = ["RUNNING", "PENDING", "SUCCEEDED", "FAILED", "ERROR", "UNKNOWN"]

# Compact status symbols for repetition display and progress bar
STATUS_SYMBOLS = {
    "SUCCEEDED": ("S", "green bold"),
    "RUNNING": ("R", "yellow bold"),
    "PENDING": ("W", "dim bold"),
    "FAILED": ("F", "red bold"),
    "ERROR": ("E", "red bold"),
    "UNKNOWN": ("?", "dim"),
}

# Short status labels for the Overall column in table
STATUS_LABELS = {
    "SUCCEEDED": ("OK", "green"),
    "RUNNING": ("RUN", "yellow bold"),
    "PENDING": ("WAIT", "dim"),
    "FAILED": ("FAIL", "red"),
    "ERROR": ("ERR", "red bold"),
    "UNKNOWN": ("???", "dim"),
}


def _load_index(index_file: Path) -> Tuple[str, Dict[str, Any], int, int]:
    """
    Load the index file and return benchmark name, executions, expected total, and repetitions.

    Args:
        index_file: Path to __iops_index.json

    Returns:
        Tuple of (benchmark_name, executions_dict, total_expected, repetitions)
    """
    try:
        with open(index_file, 'r') as f:
            index = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise WatchModeError(f"Error reading index file: {e}")

    return (
        index.get("benchmark", "Unknown"),
        index.get("executions", {}),
        index.get("total_expected", 0),
        index.get("repetitions", 1)
    )


def _read_sysinfo(rep_path: Path) -> Optional[Dict[str, Any]]:
    """
    Read sysinfo from a repetition directory.

    Args:
        rep_path: Path to a repetition folder (e.g., exec_0001/repetition_1)

    Returns:
        Dict with sysinfo data, or None if file doesn't exist or can't be read
    """
    sysinfo_file = rep_path / SYSINFO_FILENAME
    if sysinfo_file.exists():
        try:
            with open(sysinfo_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _collect_execution_data(
    run_root: Path,
    executions: Dict[str, Any],
    filter_dict: Dict[str, str],
    status_filter: Optional[str],
    hide_columns: set,
    expected_repetitions: int = 1
) -> Tuple[List[Dict], Dict[str, int]]:
    """
    Collect current execution data from status files.

    Scans repetition subdirectories within each exec_XXXX folder to get
    individual repetition statuses. Returns one entry per test config with
    all repetition statuses grouped together.

    Args:
        run_root: Path to run root directory
        executions: Executions dict from index
        filter_dict: Parameter filters
        status_filter: Status filter (filters tests that have at least one rep matching)
        hide_columns: Columns to hide
        expected_repetitions: Expected number of repetitions per config

    Returns:
        Tuple of (test_list, status_counts)
        test_list contains dicts with: exec_key, rel_path, params, command, rep_statuses, avg_time, total_time
        rep_statuses is a list of status strings for each repetition
        avg_time is the average duration in seconds for successful repetitions (or None)
        total_time is the sum of durations for all successful repetitions (or None)
    """
    # Collect tests and count statuses
    tests = []
    status_counts = {s: 0 for s in STATUS_ORDER}

    for exec_key, exec_data in sorted(executions.items()):
        params = exec_data.get("params", {})
        rel_path = exec_data.get("path", "")
        command = exec_data.get("command", "")

        # Apply parameter filters first
        if filter_dict:
            match = True
            for fkey, fval in filter_dict.items():
                if fkey not in params:
                    match = False
                    break
                if str(params[fkey]) != fval:
                    match = False
                    break
            if not match:
                continue

        # Get the exec_XXXX folder
        exec_path = run_root / rel_path

        # Collect repetition statuses and timing
        rep_statuses = []
        rep_durations = []  # Duration in seconds for successful reps

        # Scan for repetition subdirectories
        rep_dirs = sorted(exec_path.glob("repetition_*"))

        if rep_dirs:
            for rep_dir in rep_dirs:
                status_info = _read_status(rep_dir)
                status = status_info.get("status", "UNKNOWN")
                rep_statuses.append(status)

                # Count statuses
                if status in status_counts:
                    status_counts[status] += 1
                else:
                    status_counts["UNKNOWN"] += 1

                # Collect timing for successful repetitions
                if status == "SUCCEEDED":
                    sysinfo = _read_sysinfo(rep_dir)
                    if sysinfo and "duration_seconds" in sysinfo:
                        try:
                            duration = float(sysinfo["duration_seconds"])
                            rep_durations.append(duration)
                        except (ValueError, TypeError):
                            pass

            # Add pending for missing repetitions
            existing_reps = len(rep_dirs)
            if existing_reps < expected_repetitions:
                pending_count = expected_repetitions - existing_reps
                for _ in range(pending_count):
                    rep_statuses.append("PENDING")
                status_counts["PENDING"] += pending_count
        else:
            # No repetition folders yet - all repetitions are pending
            for _ in range(expected_repetitions):
                rep_statuses.append("PENDING")
            status_counts["PENDING"] += expected_repetitions

        # Calculate average and total time for this test
        avg_time = None
        total_time = None
        if rep_durations:
            total_time = sum(rep_durations)
            avg_time = total_time / len(rep_durations)

        # Apply status filter - include test if any repetition matches
        if status_filter:
            if not any(s.upper() == status_filter.upper() for s in rep_statuses):
                continue

        tests.append({
            "exec_key": exec_key,
            "rel_path": rel_path,
            "params": params,
            "command": command,
            "rep_statuses": rep_statuses,
            "avg_time": avg_time,
            "total_time": total_time,
        })

    # Sort tests numerically by execution ID
    def get_exec_num(test):
        """Extract numeric ID from exec_key like 'exec_0001' -> 1."""
        key = test["exec_key"]
        try:
            return int(key.split("_")[-1])
        except (ValueError, IndexError):
            return 0
    tests.sort(key=get_exec_num)

    return tests, status_counts


def _get_test_overall_status(rep_statuses: List[str]) -> str:
    """
    Determine overall status of a test from its repetition statuses.
    Priority: RUNNING > PENDING > FAILED/ERROR > SUCCEEDED
    """
    if any(s == "RUNNING" for s in rep_statuses):
        return "RUNNING"
    if any(s == "PENDING" for s in rep_statuses):
        return "PENDING"
    if any(s in ("FAILED", "ERROR") for s in rep_statuses):
        return "FAILED"
    if all(s == "SUCCEEDED" for s in rep_statuses):
        return "SUCCEEDED"
    return "UNKNOWN"


def _get_max_symbol_width() -> int:
    """Get the maximum width of all status symbols for alignment."""
    return max(len(sym) for sym, _ in STATUS_SYMBOLS.values())


def _build_rep_status_text(rep_statuses: List[str]) -> Text:
    """
    Build a compact Text display of repetition statuses.

    Each status is displayed using its symbol from STATUS_SYMBOLS,
    padded to consistent width for alignment.
    Example: OK   FAIL WAIT = SUCCEEDED, FAILED, PENDING
    """
    text = Text()
    max_width = _get_max_symbol_width()

    for i, status in enumerate(rep_statuses):
        symbol, style = STATUS_SYMBOLS.get(status, STATUS_SYMBOLS["UNKNOWN"])
        # Pad symbol to max width for alignment
        padded_symbol = symbol.ljust(max_width)
        text.append(padded_symbol, style=style)
        # Add space between symbols (but not after last)
        if i < len(rep_statuses) - 1:
            text.append(" ", style="")
    return text


def _build_table(
    tests: List[Dict],
    show_command: bool,
    show_full: bool,
    hide_columns: set,
    total_repetitions: int = 1,
    show_only_active: bool = False,
    total_expected_configs: int = 0,
    terminal_width: int = 80
) -> Tuple[Table, int, int, int]:
    """
    Build a rich Table from test data.

    Args:
        tests: List of test dicts with exec_key, rel_path, params, command, rep_statuses, avg_time
        show_command: Whether to show command column
        show_full: Whether to show full values
        hide_columns: Columns to hide
        total_repetitions: Total expected repetitions per config
        show_only_active: If True, only show tests that are not fully succeeded
        total_expected_configs: Total expected number of test configs (for queued placeholders)
        terminal_width: Terminal width for auto-fitting variable columns

    Returns:
        Tuple of (table, shown_count, total_count, hidden_vars_count)
    """
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))

    # Collect all variable names - always show vars
    all_var_names = []
    if tests:
        # Get all unique var names from all tests
        var_name_set = set()
        for test in tests:
            var_name_set.update(test.get("params", {}).keys())
        # Sort for consistent ordering, filter out hidden columns
        all_var_names = sorted(n for n in var_name_set if n not in hide_columns)

    # Calculate available width for variable columns
    # Fixed columns: Test (~12), Reps (~reps*2), Status (6), Avg (7), Total (7), Command (~40)
    fixed_width = 12 + 8 + 9 + 9 + 6  # Test + Status + Avg + Total + padding
    if total_repetitions > 1:
        fixed_width += total_repetitions * 2 + 4  # Reps column
    if show_command and "command" not in hide_columns:
        fixed_width += 42  # Command column

    available_width = terminal_width - fixed_width

    # Estimate width per variable column (header + padding + value)
    # Use max of header length and typical value length (~8 chars)
    var_names = []
    hidden_vars_count = 0
    used_width = 0

    for var_name in all_var_names:
        # Estimate column width: header length + 2 padding, min 6
        col_width = max(6, len(var_name) + 2)
        if used_width + col_width <= available_width:
            var_names.append(var_name)
            used_width += col_width
        else:
            hidden_vars_count += 1

    # Add columns
    if "path" not in hide_columns:
        table.add_column("Test", style="cyan", no_wrap=True)

    # Add variable columns
    for var_name in var_names:
        table.add_column(var_name, justify="right")

    # Show repetition symbols when multiple reps
    if total_repetitions > 1:
        table.add_column("Reps", justify="center")
    # Always show overall status
    table.add_column("Status", justify="left", width=6)
    # Time columns: Avg (per repetition) and Total (sum of all reps)
    table.add_column("Avg", justify="right", width=7)
    table.add_column("Total", justify="right", width=7)
    if show_command and "command" not in hide_columns:
        table.add_column("Command", style="dim", max_width=40)

    truncate_width = None if show_full else DEFAULT_TRUNCATE_WIDTH

    def display_val(val: str) -> str:
        if truncate_width is None:
            return val
        return _truncate_value(val, truncate_width)

    # Build a map of existing tests by their numeric ID
    def get_exec_num(exec_key: str) -> int:
        try:
            return int(exec_key.split("_")[-1])
        except (ValueError, IndexError):
            return 0

    tests_by_id = {get_exec_num(t["exec_key"]): t for t in tests}

    # Determine the range of IDs to display
    existing_ids = set(tests_by_id.keys())
    max_id = max(existing_ids) if existing_ids else 0

    # If we know total expected, use that; otherwise use max existing
    if total_expected_configs > 0:
        all_ids = range(1, total_expected_configs + 1)
    else:
        all_ids = sorted(existing_ids)

    # Build combined list: existing tests + queued placeholders, in order
    display_items = []  # List of (id, test_or_none, is_queued)
    for exec_id in all_ids:
        if exec_id in tests_by_id:
            test = tests_by_id[exec_id]
            overall_status = _get_test_overall_status(test["rep_statuses"])
            # Skip completed tests if show_only_active
            if show_only_active and overall_status == "SUCCEEDED":
                continue
            display_items.append((exec_id, test, False))
        else:
            # Queued placeholder - skip if show_only_active (queued are "pending", not active)
            if not show_only_active:
                display_items.append((exec_id, None, True))

    # Add rows
    for exec_id, test, is_queued in display_items:
        row = []

        if is_queued:
            # Queued placeholder row (align with regular exec items)
            # Use same length as "exec_XXXX" (9 chars) for alignment
            if "path" not in hide_columns:
                placeholder_text = Text()
                placeholder_text.append("  ", style="")
                placeholder_text.append(f"wait_{exec_id:04d}", style="dim italic")
                row.append(placeholder_text)

            # Variable columns (show "--" for queued)
            for _ in var_names:
                row.append(Text("--", style="dim"))

            if total_repetitions > 1:
                pending_statuses = ["PENDING"] * total_repetitions
                rep_text = _build_rep_status_text(pending_statuses)
                row.append(rep_text)

            # Overall status for queued (use STATUS_LABELS for consistency)
            label, style = STATUS_LABELS["PENDING"]
            row.append(Text(label, style="dim italic"))

            # Time columns (no time for queued)
            row.append(Text("--", style="dim"))  # Avg
            row.append(Text("--", style="dim"))  # Total

            if show_command and "command" not in hide_columns:
                row.append(Text("--", style="dim"))
        else:
            # Existing test row
            rel_path = test["rel_path"]
            rep_statuses = test["rep_statuses"]
            command = test.get("command", "")
            params = test.get("params", {})
            overall_status = _get_test_overall_status(rep_statuses)

            if "path" not in hide_columns:
                path_display = Path(rel_path).name if rel_path else rel_path
                if overall_status == "RUNNING":
                    path_text = Text()
                    path_text.append("▶ ", style="yellow bold")
                    path_text.append(display_val(path_display), style="cyan")
                    row.append(path_text)
                else:
                    row.append("  " + display_val(path_display))

            # Variable columns
            for var_name in var_names:
                val = params.get(var_name, "")
                row.append(display_val(str(val)))

            # Repetition status symbols (only when multiple reps)
            if total_repetitions > 1:
                rep_text = _build_rep_status_text(rep_statuses)
                row.append(rep_text)

            # Overall status label
            label, style = STATUS_LABELS.get(overall_status, STATUS_LABELS["UNKNOWN"])
            row.append(Text(label, style=style))

            # Average time column
            avg_time = test.get("avg_time")
            if avg_time is not None:
                if avg_time < 60:
                    time_str = f"{avg_time:.1f}s"
                elif avg_time < 3600:
                    time_str = f"{avg_time / 60:.1f}m"
                else:
                    time_str = f"{avg_time / 3600:.1f}h"
                row.append(Text(time_str, style="cyan"))
            else:
                row.append(Text("--", style="dim"))

            # Total time column
            total_time = test.get("total_time")
            if total_time is not None:
                if total_time < 60:
                    time_str = f"{total_time:.1f}s"
                elif total_time < 3600:
                    time_str = f"{total_time / 60:.1f}m"
                else:
                    time_str = f"{total_time / 3600:.1f}h"
                row.append(Text(time_str, style="green"))
            else:
                row.append(Text("--", style="dim"))

            if show_command and "command" not in hide_columns:
                row.append(display_val(command))

        table.add_row(*row)

    total_count = total_expected_configs if total_expected_configs > 0 else len(tests)
    return table, len(display_items), total_count, hidden_vars_count


def _build_progress_bar(
    status_counts: Dict[str, int],
    total_expected: int,
    elapsed_seconds: float = 0,
    terminal_width: int = 80,
    actual_avg_time: Optional[float] = None
) -> Text:
    """
    Build a segmented progress bar with status counts and throughput.

    Args:
        status_counts: Dict of status -> count
        total_expected: Total expected executions
        elapsed_seconds: Elapsed time in seconds (fallback for throughput calculation)
        terminal_width: Terminal width for responsive sizing
        actual_avg_time: Average execution time from sysinfo (more accurate than wall-clock)

    Returns:
        Rich Text object with progress bar and counts
    """
    text = Text()

    total = total_expected if total_expected > 0 else sum(status_counts.values())
    succeeded = status_counts.get("SUCCEEDED", 0)
    failed = status_counts.get("FAILED", 0) + status_counts.get("ERROR", 0)
    running = status_counts.get("RUNNING", 0)
    pending = status_counts.get("PENDING", 0)
    completed = succeeded + failed

    if total > 0:
        pct = (completed / total) * 100
        # Responsive bar width: use ~40% of terminal width, min 20, max 60
        bar_width = max(20, min(60, terminal_width * 2 // 5))

        # Calculate segment widths for the segmented bar
        # Order: succeeded (green) | failed (red) | running (yellow) | pending (dim)
        seg_succeeded = int(bar_width * succeeded / total)
        seg_failed = int(bar_width * failed / total)
        seg_running = int(bar_width * running / total)
        seg_pending = bar_width - seg_succeeded - seg_failed - seg_running

        # Ensure at least 1 char for running if any are running
        if running > 0 and seg_running == 0:
            seg_running = 1
            seg_pending = max(0, seg_pending - 1)

        # Build segmented progress bar
        text.append("▐", style="dim")
        if seg_succeeded > 0:
            text.append("━" * seg_succeeded, style="green")
        if seg_failed > 0:
            text.append("━" * seg_failed, style="red")
        if seg_running > 0:
            text.append("━" * seg_running, style="yellow")
        if seg_pending > 0:
            text.append("─" * seg_pending, style="dim")
        text.append("▌", style="dim")

        # Percentage
        text.append(f" {pct:5.1f}%", style="bold")

        # New line for status counts
        text.append("\n ")

        # ETA info (on same line as percentage continuation)
        # Will be followed by status counts on next line

        # ETA based on average time per test (shows from the start, updates as tests complete)
        if completed > 0:
            # Remaining repetitions
            remaining = total - completed

            if remaining > 0:
                # Use actual execution time from sysinfo when available (more accurate)
                # Falls back to wall-clock time when sysinfo is not available
                if actual_avg_time is not None:
                    avg_time_per_rep = actual_avg_time
                    time_source = "exec"  # Actual execution time from probes
                else:
                    avg_time_per_rep = elapsed_seconds / completed
                    time_source = "wall"  # Wall-clock time (includes queue wait, overhead)

                # Estimate remaining time = remaining reps × average time per rep
                eta_seconds = remaining * avg_time_per_rep

                text.append("", style="dim")
                text.append("AVG: ", style="dim")
                text.append(f"{avg_time_per_rep:.1f}s", style="cyan")
                text.append("/test", style="dim")

                if eta_seconds < 60:
                    text.append(f"  ~{eta_seconds:.0f}s left", style="dim italic")
                elif eta_seconds < 3600:
                    eta_minutes = eta_seconds / 60
                    text.append(f"  ~{eta_minutes:.0f}m left", style="dim italic")
                else:
                    eta_hours = eta_seconds / 3600
                    text.append(f"  ~{eta_hours:.1f}h left", style="dim italic")

        # Status counts with full names on new line
        text.append("\n ")
        text.append("Succeeded: ", style="dim")
        text.append(f"{succeeded}", style="green bold")

        if failed > 0:
            text.append("  Failed: ", style="dim")
            text.append(f"{failed}", style="red bold")

        if running > 0:
            text.append("  Running: ", style="dim")
            text.append(f"{running}", style="yellow bold")

        if pending > 0:
            text.append("  Pending: ", style="dim")
            text.append(f"{pending}", style="dim bold")

    return text


def _is_all_complete(status_counts: Dict[str, int], total_in_index: int, total_expected: int, repetitions: int = 1) -> bool:
    """Check if all executions have reached a terminal state."""
    running = status_counts.get("RUNNING", 0)
    pending = status_counts.get("PENDING", 0)

    # Not complete if there are running or pending executions
    if running > 0 or pending > 0:
        return False

    # Not complete if we haven't seen all expected execution configs yet
    # total_expected is total repetitions, so divide by repetitions to get configs
    if total_expected > 0:
        expected_configs = total_expected // max(1, repetitions)
        if total_in_index < expected_configs:
            return False

    return True


def watch_executions(
    path: Path,
    filters: Optional[List[str]] = None,
    show_command: bool = False,
    show_full: bool = False,
    hide_columns: Optional[set] = None,
    status_filter: Optional[str] = None,
    interval: int = 5,
    exit_on_complete: bool = False
) -> None:
    """
    Watch execution folders with live updates.

    Args:
        path: Path to workdir or run root
        filters: Optional list of VAR=VALUE filters
        show_command: If True, display the command column
        show_full: If True, show full values without truncation
        hide_columns: Set of column names to hide
        status_filter: Filter by execution status
        interval: Refresh interval in seconds
        exit_on_complete: Exit when all executions complete
    """
    check_rich_available()

    path = path.resolve()
    hide_columns = hide_columns or set()

    # Parse filters
    filter_dict: Dict[str, str] = {}
    if filters:
        for f in filters:
            if '=' not in f:
                raise WatchModeError(f"Invalid filter format: {f} (expected VAR=VALUE)")
            key, value = f.split('=', 1)
            filter_dict[key] = value

    # Find index file
    index_file = path / INDEX_FILENAME
    run_root = path

    if not index_file.exists():
        # Try to find in subdirectories
        run_dirs = sorted(list(path.glob("run_*")) + list(path.glob("dryrun_*")))
        if run_dirs:
            # Use the most recent run
            run_root = run_dirs[-1]
            index_file = run_root / INDEX_FILENAME

        if not index_file.exists():
            raise WatchModeError(
                f"No IOPS execution data found in: {path}\n"
                f"Expected {INDEX_FILENAME} in run root directory."
            )

    # Load initial data
    benchmark_name, executions, total_expected, repetitions = _load_index(index_file)
    run_metadata = _read_run_metadata(run_root)
    bench_meta = run_metadata.get("benchmark", {})

    if not executions:
        raise WatchModeError("No executions found in index.")

    console = Console()
    start_time = datetime.now()

    # Set up signal handler for clean exit
    interrupted = False
    def signal_handler(sig, frame):
        nonlocal interrupted
        interrupted = True

    original_handler = signal.signal(signal.SIGINT, signal_handler)

    # Determine if we should show only active tests (when many tests)
    show_only_active = False

    try:
        with Live(console=console, refresh_per_second=1, screen=True) as live:
            while not interrupted:
                # Reload index to pick up new executions
                try:
                    benchmark_name, executions, total_expected, repetitions = _load_index(index_file)
                except WatchModeError:
                    pass  # Keep using previous data if index read fails

                # Collect current data (new format: one entry per test config)
                tests, status_counts = _collect_execution_data(
                    run_root, executions, filter_dict, status_filter, hide_columns,
                    expected_repetitions=repetitions
                )

                total_in_index = len(executions)
                all_complete = _is_all_complete(status_counts, total_in_index, total_expected, repetitions)
                elapsed = datetime.now() - start_time
                elapsed_str = str(elapsed).split('.')[0]  # Remove microseconds

                # Calculate queued tests (expected but not yet created)
                total_expected_configs = total_expected // max(1, repetitions)
                queued_count = max(0, total_expected_configs - total_in_index)

                # Add queued tests to pending count for progress bar
                # (queued_count configs × repetitions = queued attempts)
                if queued_count > 0:
                    status_counts["PENDING"] = status_counts.get("PENDING", 0) + (queued_count * repetitions)

                # Auto-enable show_only_active if many tests and some are complete
                num_tests = len(tests) + queued_count
                num_complete = sum(1 for t in tests if _get_test_overall_status(t["rep_statuses"]) == "SUCCEEDED")
                if num_tests > 20 and num_complete > 0:
                    show_only_active = True

                # Build header panel with clean organization
                header_text = Text()

                # Line 1: Benchmark name and key stats
                header_text.append(f" {benchmark_name}", style="bold white")

                # Line 2: Configuration details
                header_text.append("\n")

                # Executor type with icon
                executor = bench_meta.get("executor", "local")
                executor_icon = "🖥" if executor == "local" else "🔲"
                header_text.append(f" {executor_icon} ", style="")
                executor_style = "magenta" if executor == "slurm" else "blue"
                header_text.append(f"{executor}", style=executor_style)

                # Separator
                header_text.append("    ", style="")

                # Test configuration count × repetitions = total
                header_text.append(f"{total_expected_configs}", style="cyan bold")
                header_text.append(" tests", style="dim")
                if repetitions > 1:
                    header_text.append(" × ", style="dim")
                    header_text.append(f"{repetitions}", style="cyan bold")
                    header_text.append(" reps", style="dim")
                    header_text.append(" = ", style="dim")
                    header_text.append(f"{total_expected}", style="cyan bold")
                    header_text.append(" total", style="dim")

                # Search method (only show if not exhaustive)
                search_method = bench_meta.get("search_method", "exhaustive")
                if search_method and search_method != "exhaustive":
                    header_text.append("    ", style="")
                    header_text.append(f"[{search_method}]", style="yellow")

                # Hostname (if available)
                hostname = bench_meta.get("hostname", "")
                if hostname:
                    header_text.append("    ", style="")
                    header_text.append(f"@{hostname}", style="dim")

                # Line 3: Run status
                header_text.append("\n")
                header_text.append(f" {run_root.name}", style="cyan")
                header_text.append("    ", style="")

                # Elapsed time
                header_text.append("⏱ ", style="dim")
                header_text.append(f"{elapsed_str}", style="")

                # Status info
                if all_complete:
                    header_text.append("    ", style="")
                    header_text.append("✓ COMPLETE", style="green bold")
                else:
                    header_text.append("    ", style="")
                    header_text.append(f"{datetime.now().strftime('%H:%M:%S')}", style="dim")

                # Filter info if any
                if filter_dict or status_filter:
                    header_text.append("\n")
                    header_text.append(" 🔍 ", style="dim")
                    filter_parts = []
                    if filter_dict:
                        filter_parts.append(", ".join(f"{k}={v}" for k, v in filter_dict.items()))
                    if status_filter:
                        filter_parts.append(f"status={status_filter}")
                    header_text.append(f"{', '.join(filter_parts)}", style="italic")

                header = Panel(header_text, border_style="blue", padding=(0, 1))

                # Build table
                terminal_width = console.size.width
                if tests or total_expected_configs > 0:
                    table, shown_count, total_count, hidden_vars = _build_table(
                        tests, show_command, show_full, hide_columns,
                        total_repetitions=repetitions,
                        show_only_active=show_only_active,
                        total_expected_configs=total_expected_configs,
                        terminal_width=terminal_width
                    )

                    # Build note for hidden items
                    notes = []
                    if show_only_active and shown_count < total_count:
                        notes.append(f"{total_count - shown_count} completed tests hidden")
                    if hidden_vars > 0:
                        notes.append(f"+{hidden_vars} vars hidden, use --hide to customize")

                    if notes:
                        table_note = Text()
                        table_note.append(f"  ({'; '.join(notes)})", style="dim italic")
                    else:
                        table_note = None
                else:
                    table = Text("No executions match the current filters.", style="dim italic")
                    table_note = None

                # Build footer with progress bar and legend
                footer_text = Text()
                footer_text.append("\n")

                # Calculate actual average execution time from sysinfo data
                # This is more accurate than wall-clock time as it excludes queue wait, overhead
                actual_times = [t["avg_time"] for t in tests if t.get("avg_time") is not None]
                actual_avg_time = sum(actual_times) / len(actual_times) if actual_times else None

                # Progress bar (with elapsed time for throughput calculation)
                elapsed_seconds = elapsed.total_seconds()
                progress_bar = _build_progress_bar(
                    status_counts, total_expected, elapsed_seconds, terminal_width,
                    actual_avg_time=actual_avg_time
                )
                footer_text.append_text(progress_bar)

                # Completion indicator or help hint
                if all_complete:
                    footer_text.append("\n")
                    succeeded = status_counts.get("SUCCEEDED", 0)
                    failed = status_counts.get("FAILED", 0) + status_counts.get("ERROR", 0)
                    # Responsive completion message based on terminal width
                    if failed == 0:
                        if terminal_width >= 60:
                            footer_text.append(" ✓ ALL TESTS COMPLETED SUCCESSFULLY ", style="bold white on green")
                        elif terminal_width >= 40:
                            footer_text.append(" ✓ COMPLETED ", style="bold white on green")
                        else:
                            footer_text.append(" ✓ DONE ", style="bold white on green")
                    else:
                        if terminal_width >= 50:
                            footer_text.append(f" ⚠ COMPLETED WITH {failed} FAILURES ", style="bold white on red")
                        elif terminal_width >= 35:
                            footer_text.append(f" ⚠ {failed} FAILED ", style="bold white on red")
                        else:
                            footer_text.append(f" ⚠ {failed}F ", style="bold white on red")
                    footer_text.append(f"  {elapsed_str}", style="dim")
                    # Terminal bell to alert user
                    footer_text.append("\a", style="")
                else:
                    footer_text.append("\n ")
                    footer_text.append("Press Ctrl+C to exit", style="dim italic")

                # Combine and display
                from rich.console import Group
                elements = [header, table]
                if table_note:
                    elements.append(table_note)
                elements.append(footer_text)
                live.update(Group(*elements))

                # Check for completion
                if all_complete and exit_on_complete:
                    # Show final state briefly before exiting
                    time.sleep(1)
                    break

                # Wait for next refresh
                for _ in range(interval * 10):  # Check interrupted every 0.1s
                    if interrupted:
                        break
                    time.sleep(0.1)

    finally:
        signal.signal(signal.SIGINT, original_handler)

    # Print exit message
    console.print()
    if all_complete:
        console.print("[green]All executions complete.[/green]")
    else:
        console.print("[yellow]Watch mode exited.[/yellow]")
        console.print(f"To reconnect: [cyan]iops find {run_root} --watch[/cyan]")
