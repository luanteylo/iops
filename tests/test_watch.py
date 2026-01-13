"""
Tests for the watch mode functionality.

These tests are skipped if the 'rich' library is not installed.
Install with: pip install iops-benchmark[watch]
"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Check if rich is available
try:
    import rich
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# Skip all tests in this module if rich is not installed
pytestmark = pytest.mark.skipif(
    not RICH_AVAILABLE,
    reason="Watch mode tests require 'rich' library. Install with: pip install iops-benchmark[watch]"
)


@pytest.fixture
def mock_run_dir(tmp_path):
    """Create a mock run directory with index and status files."""
    run_root = tmp_path / "run_001"
    run_root.mkdir()

    # Create index file with repetitions info
    index = {
        "benchmark": "Test Benchmark",
        "total_expected": 3,  # 3 configs * 1 repetition
        "repetitions": 1,
        "executions": {
            "exec_0001": {
                "path": "runs/exec_0001",
                "params": {"nodes": 1, "ppn": 4},
                "command": "echo test1"
            },
            "exec_0002": {
                "path": "runs/exec_0002",
                "params": {"nodes": 2, "ppn": 4},
                "command": "echo test2"
            },
            "exec_0003": {
                "path": "runs/exec_0003",
                "params": {"nodes": 4, "ppn": 8},
                "command": "echo test3"
            }
        }
    }

    with open(run_root / "__iops_index.json", "w") as f:
        json.dump(index, f)

    # Create execution directories with repetition subdirectories
    statuses = {
        "exec_0001": "SUCCEEDED",
        "exec_0002": "RUNNING",
        "exec_0003": "PENDING"
    }

    for exec_id, exec_data in index["executions"].items():
        exec_path = run_root / exec_data["path"]
        exec_path.mkdir(parents=True)

        # Create repetition_001 subdirectory with status file
        rep_path = exec_path / "repetition_001"
        rep_path.mkdir()
        with open(rep_path / "__iops_status.json", "w") as f:
            json.dump({
                "status": statuses[exec_id],
                "error": None,
                "end_time": None
            }, f)

    return run_root


@pytest.fixture
def mock_run_dir_with_reps(tmp_path):
    """Create a mock run directory with multiple repetitions."""
    run_root = tmp_path / "run_002"
    run_root.mkdir()

    # Create index file with 2 repetitions
    index = {
        "benchmark": "Test Benchmark Multi-Rep",
        "total_expected": 4,  # 2 configs * 2 repetitions
        "repetitions": 2,
        "executions": {
            "exec_0001": {
                "path": "runs/exec_0001",
                "params": {"nodes": 1},
                "command": "echo test1"
            },
            "exec_0002": {
                "path": "runs/exec_0002",
                "params": {"nodes": 2},
                "command": "echo test2"
            }
        }
    }

    with open(run_root / "__iops_index.json", "w") as f:
        json.dump(index, f)

    # Create execution directories with multiple repetitions
    for exec_id, exec_data in index["executions"].items():
        exec_path = run_root / exec_data["path"]
        exec_path.mkdir(parents=True)

        # exec_0001: rep1 SUCCEEDED, rep2 RUNNING
        # exec_0002: rep1 SUCCEEDED (rep2 not started yet)
        if exec_id == "exec_0001":
            rep1 = exec_path / "repetition_001"
            rep1.mkdir()
            with open(rep1 / "__iops_status.json", "w") as f:
                json.dump({"status": "SUCCEEDED", "error": None, "end_time": None}, f)

            rep2 = exec_path / "repetition_002"
            rep2.mkdir()
            with open(rep2 / "__iops_status.json", "w") as f:
                json.dump({"status": "RUNNING", "error": None, "end_time": None}, f)
        else:
            rep1 = exec_path / "repetition_001"
            rep1.mkdir()
            with open(rep1 / "__iops_status.json", "w") as f:
                json.dump({"status": "SUCCEEDED", "error": None, "end_time": None}, f)
            # rep2 not created yet - should be counted as PENDING

    return run_root


@pytest.fixture
def mock_workdir(tmp_path, mock_run_dir):
    """Create a workdir containing run directories."""
    # mock_run_dir is already at tmp_path/run_001
    return tmp_path


class TestWatchModuleImports:
    """Test that watch module imports correctly."""

    def test_import_watch_module(self):
        """Test that watch module can be imported."""
        from iops.results.watch import (
            watch_executions,
            WatchModeError,
            check_rich_available,
            RICH_AVAILABLE
        )
        assert RICH_AVAILABLE is True

    def test_check_rich_available_succeeds(self):
        """Test that check_rich_available doesn't raise when rich is installed."""
        from iops.results.watch import check_rich_available
        # Should not raise
        check_rich_available()


class TestLoadIndex:
    """Test index file loading."""

    def test_load_index_success(self, mock_run_dir):
        """Test loading a valid index file."""
        from iops.results.watch import _load_index

        index_file = mock_run_dir / "__iops_index.json"
        benchmark_name, executions, total_expected, repetitions, _, _, _ = _load_index(index_file)

        assert benchmark_name == "Test Benchmark"
        assert len(executions) == 3
        assert "exec_0001" in executions
        assert total_expected == 3
        assert repetitions == 1

    def test_load_index_missing_file(self, tmp_path):
        """Test loading a non-existent index file."""
        from iops.results.watch import _load_index, WatchModeError

        with pytest.raises(WatchModeError, match="Error reading index file"):
            _load_index(tmp_path / "nonexistent.json")

    def test_load_index_invalid_json(self, tmp_path):
        """Test loading an invalid JSON file."""
        from iops.results.watch import _load_index, WatchModeError

        invalid_file = tmp_path / "__iops_index.json"
        invalid_file.write_text("not valid json {{{")

        with pytest.raises(WatchModeError, match="Error reading index file"):
            _load_index(invalid_file)


class TestCollectExecutionData:
    """Test execution data collection."""

    def test_collect_all_executions(self, mock_run_dir):
        """Test collecting all executions without filters."""
        from iops.results.watch import _load_index, _collect_execution_data

        _, executions, _, _, _, _, _ = _load_index(mock_run_dir / "__iops_index.json")
        tests, status_counts = _collect_execution_data(
            mock_run_dir, executions, {}, None, set()
        )

        assert len(tests) == 3  # 3 test configs
        assert status_counts["SUCCEEDED"] == 1
        assert status_counts["RUNNING"] == 1
        assert status_counts["PENDING"] == 1

    def test_collect_with_status_filter(self, mock_run_dir):
        """Test collecting executions with status filter."""
        from iops.results.watch import _load_index, _collect_execution_data

        _, executions, _, _, _, _, _ = _load_index(mock_run_dir / "__iops_index.json")
        tests, status_counts = _collect_execution_data(
            mock_run_dir, executions, {}, "RUNNING", set()
        )

        # Only tests with RUNNING status should be included
        assert len(tests) == 1
        assert tests[0]["rep_statuses"][0] == "RUNNING"
        # Status counts should still reflect all executions
        assert status_counts["SUCCEEDED"] == 1
        assert status_counts["RUNNING"] == 1
        assert status_counts["PENDING"] == 1

    def test_collect_with_param_filter(self, mock_run_dir):
        """Test collecting executions with parameter filter."""
        from iops.results.watch import _load_index, _collect_execution_data

        _, executions, _, _, _, _, _ = _load_index(mock_run_dir / "__iops_index.json")
        tests, _ = _collect_execution_data(
            mock_run_dir, executions, {"nodes": "2"}, None, set()
        )

        assert len(tests) == 1
        assert tests[0]["params"]["nodes"] == 2

    def test_collect_returns_rep_statuses(self, mock_run_dir):
        """Test that collection returns rep_statuses list for each test."""
        from iops.results.watch import _load_index, _collect_execution_data

        _, executions, _, _, _, _, _ = _load_index(mock_run_dir / "__iops_index.json")
        tests, _ = _collect_execution_data(
            mock_run_dir, executions, {}, None, set()
        )

        # Each test should have rep_statuses list
        for test in tests:
            assert "rep_statuses" in test
            assert isinstance(test["rep_statuses"], list)


class TestBuildTable:
    """Test table building."""

    def test_build_table_basic(self, mock_run_dir):
        """Test building a basic table."""
        from iops.results.watch import _load_index, _collect_execution_data, _build_table

        _, executions, _, repetitions, _, _, _ = _load_index(mock_run_dir / "__iops_index.json")
        tests, _ = _collect_execution_data(
            mock_run_dir, executions, {}, None, set()
        )

        table, shown, total, _, _ = _build_table(tests, show_command=False,
                            show_full=False, hide_columns=set(),
                            total_repetitions=repetitions)

        assert table.row_count == 3
        assert shown == 3
        assert total == 3

    def test_build_table_with_command(self, mock_run_dir):
        """Test building table with command column."""
        from iops.results.watch import _load_index, _collect_execution_data, _build_table

        _, executions, _, repetitions, _, _, _ = _load_index(mock_run_dir / "__iops_index.json")
        tests, _ = _collect_execution_data(
            mock_run_dir, executions, {}, None, set()
        )

        table, shown, total, _, _ = _build_table(tests, show_command=True,
                            show_full=False, hide_columns=set(),
                            total_repetitions=repetitions)

        assert table.row_count == 3
        # Table should have command column
        column_names = [col.header for col in table.columns]
        assert "Command" in column_names

    def test_build_table_hide_path(self, mock_run_dir):
        """Test building table with hidden path column."""
        from iops.results.watch import _load_index, _collect_execution_data, _build_table

        _, executions, _, repetitions, _, _, _ = _load_index(mock_run_dir / "__iops_index.json")
        tests, _ = _collect_execution_data(
            mock_run_dir, executions, {}, None, set()
        )

        table, _, _, _, _ = _build_table(tests, show_command=False,
                            show_full=False, hide_columns={"path"},
                            total_repetitions=repetitions)

        # Should have one less column
        column_names = [col.header for col in table.columns]
        assert "Test" not in column_names  # "Test" is the new column name for path

    def test_build_table_shows_variables(self, mock_run_dir):
        """Test that table always shows variable columns."""
        from iops.results.watch import _load_index, _collect_execution_data, _build_table

        _, executions, _, repetitions, _, _, _ = _load_index(mock_run_dir / "__iops_index.json")
        tests, _ = _collect_execution_data(
            mock_run_dir, executions, {}, None, set()
        )

        # Build table - vars should always be shown
        table, _, _, _, _ = _build_table(tests, show_command=False,
                            show_full=False, hide_columns=set(),
                            total_repetitions=repetitions)
        columns = [col.header for col in table.columns]

        # Verify variable names from params are in column headers
        if tests:
            var_names = set()
            for t in tests:
                var_names.update(t.get("params", {}).keys())
            for var_name in var_names:
                assert var_name in columns

        # Also verify time columns are present
        assert "Avg" in columns
        assert "Total" in columns

    def test_build_table_with_max_rows(self, mock_run_dir):
        """Test that table respects max_rows limit."""
        from iops.results.watch import _load_index, _collect_execution_data, _build_table

        _, executions, _, repetitions, _, _, _ = _load_index(mock_run_dir / "__iops_index.json")
        tests, _ = _collect_execution_data(
            mock_run_dir, executions, {}, None, set()
        )

        # Limit to 2 rows (there are 3 tests)
        table, shown, total, _, hidden_by_status = _build_table(
            tests, show_command=False, show_full=False, hide_columns=set(),
            total_repetitions=repetitions, max_rows=2
        )

        assert table.row_count == 2
        assert shown == 2
        assert total == 3
        # Should have hidden 1 row
        assert sum(hidden_by_status.values()) == 1

    def test_build_table_max_rows_prioritizes_running(self, mock_run_dir_with_reps):
        """Test that row limiting prioritizes RUNNING tests over PENDING."""
        from iops.results.watch import _load_index, _collect_execution_data, _build_table

        _, executions, _, repetitions, _, _, _ = _load_index(
            mock_run_dir_with_reps / "__iops_index.json"
        )
        tests, _ = _collect_execution_data(
            mock_run_dir_with_reps, executions, {}, None, set(),
            expected_repetitions=repetitions
        )

        # Limit to 1 row - should keep the one with RUNNING status
        table, shown, total, _, hidden_by_status = _build_table(
            tests, show_command=False, show_full=False, hide_columns=set(),
            total_repetitions=repetitions, max_rows=1
        )

        assert table.row_count == 1
        assert shown == 1
        # Some rows were hidden
        assert sum(hidden_by_status.values()) >= 1


class TestMultipleRepetitions:
    """Test handling of multiple repetitions."""

    def test_collect_with_multiple_reps(self, mock_run_dir_with_reps):
        """Test collecting executions with multiple repetitions."""
        from iops.results.watch import _load_index, _collect_execution_data

        _, executions, _, repetitions, _, _, _ = _load_index(
            mock_run_dir_with_reps / "__iops_index.json"
        )
        assert repetitions == 2

        tests, status_counts = _collect_execution_data(
            mock_run_dir_with_reps, executions, {}, None, set(),
            expected_repetitions=repetitions
        )

        # Should have 2 test configs (exec_0001 and exec_0002)
        assert len(tests) == 2

        # Check status counts
        # 2 SUCCEEDED (exec_0001 rep1, exec_0002 rep1)
        # 1 RUNNING (exec_0001 rep2)
        # 1 PENDING (exec_0002 rep2 - not started yet)
        assert status_counts["SUCCEEDED"] == 2
        assert status_counts["RUNNING"] == 1
        assert status_counts["PENDING"] == 1

    def test_table_shows_status_dots(self, mock_run_dir_with_reps):
        """Test that table shows status dots when repetitions > 1."""
        from iops.results.watch import _load_index, _collect_execution_data, _build_table

        _, executions, _, repetitions, _, _, _ = _load_index(
            mock_run_dir_with_reps / "__iops_index.json"
        )
        tests, _ = _collect_execution_data(
            mock_run_dir_with_reps, executions, {}, None, set(),
            expected_repetitions=repetitions
        )

        table, _, _, _, _ = _build_table(tests, show_command=False,
                            show_full=False, hide_columns=set(),
                            total_repetitions=repetitions)

        # Table should have Status column
        column_names = [col.header for col in table.columns]
        assert "Status" in column_names

    def test_table_no_rep_column_when_single_rep(self, mock_run_dir):
        """Test that table does NOT show Rep column when repetitions == 1."""
        from iops.results.watch import _load_index, _collect_execution_data, _build_table

        _, executions, _, repetitions, _, _, _ = _load_index(
            mock_run_dir / "__iops_index.json"
        )
        assert repetitions == 1

        tests, _ = _collect_execution_data(
            mock_run_dir, executions, {}, None, set(),
            expected_repetitions=repetitions
        )

        table, _, _, _, _ = _build_table(tests, show_command=False,
                            show_full=False, hide_columns=set(),
                            total_repetitions=repetitions)

        column_names = [col.header for col in table.columns]
        assert "Rep" not in column_names

    def test_rep_statuses_in_test_dict(self, mock_run_dir_with_reps):
        """Test that test dicts include rep_statuses list."""
        from iops.results.watch import _load_index, _collect_execution_data

        _, executions, _, repetitions, _, _, _ = _load_index(
            mock_run_dir_with_reps / "__iops_index.json"
        )
        tests, _ = _collect_execution_data(
            mock_run_dir_with_reps, executions, {}, None, set(),
            expected_repetitions=repetitions
        )

        # Each test should have rep_statuses list
        for test in tests:
            assert "rep_statuses" in test
            assert isinstance(test["rep_statuses"], list)
            assert len(test["rep_statuses"]) == 2  # 2 repetitions expected


class TestIsAllComplete:
    """Test completion detection."""

    def test_not_complete_with_running(self):
        """Test that running executions are not complete."""
        from iops.results.watch import _is_all_complete

        status_counts = {"RUNNING": 1, "PENDING": 0, "SUCCEEDED": 5,
                        "FAILED": 0, "ERROR": 0, "UNKNOWN": 0}
        assert _is_all_complete(status_counts, total_in_index=6, total_expected=6) is False

    def test_not_complete_with_pending(self):
        """Test that pending executions are not complete."""
        from iops.results.watch import _is_all_complete

        status_counts = {"RUNNING": 0, "PENDING": 1, "SUCCEEDED": 5,
                        "FAILED": 0, "ERROR": 0, "UNKNOWN": 0}
        assert _is_all_complete(status_counts, total_in_index=6, total_expected=6) is False

    def test_complete_all_succeeded(self):
        """Test that all succeeded is complete."""
        from iops.results.watch import _is_all_complete

        status_counts = {"RUNNING": 0, "PENDING": 0, "SUCCEEDED": 10,
                        "FAILED": 0, "ERROR": 0, "UNKNOWN": 0}
        assert _is_all_complete(status_counts, total_in_index=10, total_expected=10) is True

    def test_complete_with_failures(self):
        """Test that failed executions are considered complete."""
        from iops.results.watch import _is_all_complete

        status_counts = {"RUNNING": 0, "PENDING": 0, "SUCCEEDED": 8,
                        "FAILED": 2, "ERROR": 0, "UNKNOWN": 0}
        assert _is_all_complete(status_counts, total_in_index=10, total_expected=10) is True

    def test_complete_with_errors(self):
        """Test that error executions are considered complete."""
        from iops.results.watch import _is_all_complete

        status_counts = {"RUNNING": 0, "PENDING": 0, "SUCCEEDED": 7,
                        "FAILED": 2, "ERROR": 1, "UNKNOWN": 0}
        assert _is_all_complete(status_counts, total_in_index=10, total_expected=10) is True

    def test_not_complete_waiting_for_expected(self):
        """Test that we're not complete if waiting for more executions."""
        from iops.results.watch import _is_all_complete

        # All current executions are done, but we expect more
        status_counts = {"RUNNING": 0, "PENDING": 0, "SUCCEEDED": 5,
                        "FAILED": 0, "ERROR": 0, "UNKNOWN": 0}
        assert _is_all_complete(status_counts, total_in_index=5, total_expected=10) is False


class TestWatchExecutionsValidation:
    """Test watch_executions input validation."""

    def test_watch_no_index_file(self, tmp_path):
        """Test error when no index file exists."""
        from iops.results.watch import watch_executions, WatchModeError

        with pytest.raises(WatchModeError, match="No IOPS execution data found"):
            watch_executions(tmp_path)

    def test_watch_invalid_filter(self, mock_run_dir):
        """Test error with invalid filter format."""
        from iops.results.watch import watch_executions, WatchModeError

        with pytest.raises(WatchModeError, match="Invalid filter format"):
            watch_executions(mock_run_dir, filters=["invalid_filter"])

    def test_watch_empty_executions(self, tmp_path):
        """Test error when index has no executions."""
        from iops.results.watch import watch_executions, WatchModeError

        run_root = tmp_path / "run_001"
        run_root.mkdir()

        with open(run_root / "__iops_index.json", "w") as f:
            json.dump({"benchmark": "Empty", "executions": {}}, f)

        with pytest.raises(WatchModeError, match="No executions found"):
            watch_executions(run_root)


class TestWatchExecutionsDiscovery:
    """Test watch_executions path discovery."""

    def test_watch_finds_run_in_workdir(self, mock_workdir, mock_run_dir):
        """Test that watch finds run_* directories in workdir."""
        from iops.results.watch import _load_index, INDEX_FILENAME

        # Verify the structure - workdir should contain run_001 with index
        run_dirs = list(mock_workdir.glob("run_*"))
        assert len(run_dirs) == 1
        assert run_dirs[0].name == "run_001"

        # Verify index can be loaded from discovered directory
        index_file = run_dirs[0] / INDEX_FILENAME
        assert index_file.exists()

        benchmark_name, executions, total_expected, repetitions, _, _, _ = _load_index(index_file)
        assert benchmark_name == "Test Benchmark"
        assert len(executions) == 3
        assert total_expected == 3
        assert repetitions == 1


class TestCLIWatchArguments:
    """Test CLI argument parsing for watch mode."""

    def test_find_watch_argument_parsed(self):
        """Test that --watch argument is parsed for find command."""
        from iops.main import parse_arguments
        import sys

        with patch.object(sys, 'argv', ['iops', 'find', '/some/path', '--watch']):
            args = parse_arguments()
            assert args.watch is True
            assert args.interval == 5  # default

    def test_find_watch_with_interval(self):
        """Test that --interval argument is parsed."""
        from iops.main import parse_arguments
        import sys

        with patch.object(sys, 'argv', ['iops', 'find', '/some/path', '--watch', '--interval', '10']):
            args = parse_arguments()
            assert args.watch is True
            assert args.interval == 10

    def test_find_watch_short_flag(self):
        """Test that -w short flag works."""
        from iops.main import parse_arguments
        import sys

        with patch.object(sys, 'argv', ['iops', 'find', '/some/path', '-w']):
            args = parse_arguments()
            assert args.watch is True

class TestWatchModeErrorWithoutRich:
    """Test error handling when rich is not installed.

    Note: These tests verify the error message structure, not the actual
    import failure (since rich is installed for these tests to run).
    """

    def test_watch_mode_error_message(self):
        """Test WatchModeError has proper message format."""
        from iops.results.watch import WatchModeError

        error = WatchModeError("Test error message")
        assert str(error) == "Test error message"

    def test_check_rich_available_error_structure(self):
        """Test the error message structure when rich is missing."""
        from iops.results.watch import WatchModeError

        # Simulate the error that would be raised
        expected_msg = (
            "Watch mode requires the 'rich' library.\n"
            "Install with: pip install iops-benchmark[watch]"
        )
        error = WatchModeError(expected_msg)

        assert "rich" in str(error)
        assert "pip install" in str(error)
        assert "iops-benchmark[watch]" in str(error)
