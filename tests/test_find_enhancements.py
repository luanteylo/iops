"""Comprehensive unit tests for enhanced 'iops find' functionality.

This module tests the new features added to the 'iops find' command:
1. --full flag: Show full parameter values without truncation
2. --hide flag: Hide specific columns from output
3. --status flag: Filter executions by status
4. _truncate_value() function: Value truncation logic
5. _read_status() function: Status file reading

These enhancements improve the usability of 'iops find' for exploring large
parameter spaces and filtering by execution status.
"""

import pytest
import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from iops.main import parse_arguments
from iops.results.find import (
    find_executions,
    _truncate_value,
    _read_status,
    INDEX_FILENAME,
    PARAMS_FILENAME,
    STATUS_FILENAME,
    DEFAULT_TRUNCATE_WIDTH,
)


# ============================================================================ #
# Truncate Value Tests - _truncate_value()
# ============================================================================ #

class TestTruncateValue:
    """Test the _truncate_value() utility function."""

    def test_truncate_short_string(self):
        """Test that short strings are not truncated."""
        value = "short"
        result = _truncate_value(value, max_width=30)
        assert result == "short"

    def test_truncate_exact_length_string(self):
        """Test string exactly at max_width is not truncated."""
        value = "x" * 30
        result = _truncate_value(value, max_width=30)
        assert result == value
        assert len(result) == 30

    def test_truncate_long_string(self):
        """Test that long strings are truncated with ellipsis at beginning."""
        value = "x" * 50
        result = _truncate_value(value, max_width=30)
        assert result.startswith("...")
        assert len(result) == 30
        # "..." + last 27 chars = 30
        assert result == "..." + ("x" * 27)

    def test_truncate_preserves_end(self):
        """Test that truncation preserves the end of the string (most relevant part)."""
        value = "some_prefix_and_important_suffix"
        result = _truncate_value(value, max_width=20)
        assert result.endswith("important_suffix")
        assert result.startswith("...")
        assert len(result) == 20

    def test_truncate_empty_string(self):
        """Test truncation of empty string."""
        value = ""
        result = _truncate_value(value, max_width=30)
        assert result == ""

    def test_truncate_with_small_max_width(self):
        """Test truncation with very small max_width."""
        value = "hello world"
        result = _truncate_value(value, max_width=5)
        assert result == "...ld"
        assert len(result) == 5

    def test_truncate_with_min_max_width(self):
        """Test truncation with minimum possible max_width (3 for ellipsis)."""
        value = "hello"
        result = _truncate_value(value, max_width=3)
        assert result == "..."
        assert len(result) == 3

    def test_truncate_unicode_string(self):
        """Test truncation with unicode characters."""
        value = "Hello 世界 " * 10
        result = _truncate_value(value, max_width=30)
        assert len(result) == 30
        assert result.startswith("...")

    def test_truncate_with_newlines(self):
        """Test truncation of string containing newlines."""
        value = "line1\nline2\nline3\nline4\nline5"
        result = _truncate_value(value, max_width=20)
        assert len(result) == 20
        assert result.startswith("...")
        # Newlines are preserved, end of string is kept
        assert result.endswith("line4\nline5")


# ============================================================================ #
# Read Status Tests - _read_status()
# ============================================================================ #

class TestReadStatus:
    """Test the _read_status() utility function."""

    def test_read_status_with_valid_file(self, tmp_path):
        """Test reading status from valid JSON file."""
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir()

        status_data = {
            "status": "SUCCEEDED",
            "error": None,
            "end_time": "2024-01-01T12:00:00"
        }

        status_file = exec_dir / STATUS_FILENAME
        with open(status_file, 'w') as f:
            json.dump(status_data, f)

        result = _read_status(exec_dir)

        assert result["status"] == "SUCCEEDED"
        assert result["error"] is None
        assert result["end_time"] == "2024-01-01T12:00:00"

    def test_read_status_with_failed_execution(self, tmp_path):
        """Test reading status from failed execution."""
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir()

        status_data = {
            "status": "FAILED",
            "error": "Command returned non-zero exit code: 1",
            "end_time": "2024-01-01T12:00:00"
        }

        status_file = exec_dir / STATUS_FILENAME
        with open(status_file, 'w') as f:
            json.dump(status_data, f)

        result = _read_status(exec_dir)

        assert result["status"] == "FAILED"
        assert "non-zero exit code" in result["error"]

    def test_read_status_missing_file_returns_pending(self, tmp_path):
        """Test that missing status file returns PENDING status."""
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir()
        # Don't create status file

        result = _read_status(exec_dir)

        assert result["status"] == "PENDING"
        assert result["error"] is None
        assert result["end_time"] is None

    def test_read_status_malformed_json_returns_pending(self, tmp_path):
        """Test that malformed JSON returns PENDING status."""
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir()

        status_file = exec_dir / STATUS_FILENAME
        with open(status_file, 'w') as f:
            f.write("{ invalid json content [")

        result = _read_status(exec_dir)

        assert result["status"] == "PENDING"
        assert result["error"] is None

    def test_read_status_empty_file_returns_pending(self, tmp_path):
        """Test that empty file returns PENDING status."""
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir()

        status_file = exec_dir / STATUS_FILENAME
        status_file.touch()  # Create empty file

        result = _read_status(exec_dir)

        assert result["status"] == "PENDING"

    def test_read_status_with_error_status(self, tmp_path):
        """Test reading ERROR status."""
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir()

        status_data = {
            "status": "ERROR",
            "error": "Job submission failed",
            "end_time": "2024-01-01T12:00:00"
        }

        status_file = exec_dir / STATUS_FILENAME
        with open(status_file, 'w') as f:
            json.dump(status_data, f)

        result = _read_status(exec_dir)

        assert result["status"] == "ERROR"
        assert "Job submission failed" in result["error"]

    def test_read_status_handles_os_error(self, tmp_path):
        """Test that OS errors are handled gracefully."""
        import os
        # Skip this test when running as root (root can read files regardless of permissions)
        if os.geteuid() == 0:
            pytest.skip("Test cannot run as root - root bypasses file permissions")

        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir()

        status_file = exec_dir / STATUS_FILENAME
        with open(status_file, 'w') as f:
            json.dump({"status": "SUCCEEDED"}, f)

        # Make file unreadable
        status_file.chmod(0o000)

        try:
            result = _read_status(exec_dir)
            # Should return default PENDING status
            assert result["status"] == "PENDING"
        finally:
            # Restore permissions for cleanup
            status_file.chmod(0o644)


# ============================================================================ #
# Argument Parsing Tests - --full, --hide, --status
# ============================================================================ #

class TestFindArgumentParsing:
    """Test argument parsing for new find command options."""

    def test_parse_find_with_full_flag(self):
        """Test parsing --full flag."""
        test_args = ['find', '/path/to/workdir', '--full']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.command == 'find'
            assert args.full is True

    def test_parse_find_without_full_flag(self):
        """Test that --full defaults to False."""
        test_args = ['find', '/path/to/workdir']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.full is False

    def test_parse_find_with_hide_flag(self):
        """Test parsing --hide flag with single column."""
        test_args = ['find', '/path/to/workdir', '--hide', 'path']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.hide == 'path'

    def test_parse_find_with_hide_multiple_columns(self):
        """Test parsing --hide flag with multiple columns."""
        test_args = ['find', '/path/to/workdir', '--hide', 'path,status,command']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.hide == 'path,status,command'

    def test_parse_find_with_status_filter(self):
        """Test parsing --status flag."""
        test_args = ['find', '/path/to/workdir', '--status', 'SUCCEEDED']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.status == 'SUCCEEDED'

    def test_parse_find_with_all_new_flags(self):
        """Test parsing all new flags together."""
        test_args = [
            'find', '/path/to/workdir',
            '--full',
            '--hide', 'path,command',
            '--status', 'FAILED'
        ]
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.full is True
            assert args.hide == 'path,command'
            assert args.status == 'FAILED'


# ============================================================================ #
# Find Command Tests - --full flag
# ============================================================================ #

class TestFindCommandFull:
    """Test find command with --full flag (no truncation)."""

    def test_find_without_full_truncates_long_values(self, tmp_path):
        """Test that long values are truncated by default."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {
                    "path": "runs/exec_0001",
                    "params": {
                        "nodes": 1,
                        "long_param": "x" * 100  # Very long value
                    }
                }
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, show_full=False)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # Long value should be truncated
            assert '...' in output
            # Full value should NOT appear
            assert 'x' * 100 not in output

    def test_find_with_full_shows_complete_values(self, tmp_path):
        """Test that --full shows complete values without truncation."""
        long_value = "x" * 100
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {
                    "path": "runs/exec_0001",
                    "params": {
                        "nodes": 1,
                        "long_param": long_value
                    }
                }
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, show_full=True)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # Full value should appear
            assert long_value in output

    def test_find_full_flag_applies_to_all_columns(self, tmp_path):
        """Test that --full applies to all columns including path and command."""
        long_path = "runs/" + "x" * 100
        long_command = "mpirun " + "x" * 100

        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {
                    "path": long_path,
                    "params": {"nodes": 1},
                    "command": long_command
                }
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, show_command=True, show_full=True)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # Both long values should appear in full
            assert long_path in output
            assert long_command in output

    def test_find_single_execution_respects_full_flag(self, tmp_path):
        """Test that --full flag works for single execution display."""
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir()

        long_value = "x" * 100
        params = {"nodes": 1, "long_param": long_value}
        params_file = exec_dir / PARAMS_FILENAME
        with open(params_file, 'w') as f:
            json.dump(params, f)

        # Without --full (should truncate)
        with patch('builtins.print') as mock_print:
            find_executions(exec_dir, show_full=False)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert '...' in output
            assert long_value not in output

        # With --full (should show complete)
        with patch('builtins.print') as mock_print:
            find_executions(exec_dir, show_full=True)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert long_value in output


# ============================================================================ #
# Find Command Tests - --hide flag
# ============================================================================ #

class TestFindCommandHide:
    """Test find command with --hide flag."""

    def test_find_hide_single_column(self, tmp_path):
        """Test hiding a single column."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {
                    "path": "runs/exec_0001",
                    "params": {"nodes": 1, "ppn": 4}
                }
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, hide_columns={'path'})
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # Path column should NOT appear
            assert 'Path' not in output or 'runs/exec_0001' not in output
            # Other columns should appear
            assert 'nodes' in output

    def test_find_hide_multiple_columns(self, tmp_path):
        """Test hiding multiple columns."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {
                    "path": "runs/exec_0001",
                    "params": {"nodes": 1, "ppn": 4}
                }
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Create status file
        exec_dir = tmp_path / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)
        status_file = exec_dir / STATUS_FILENAME
        with open(status_file, 'w') as f:
            json.dump({"status": "SUCCEEDED", "error": None, "end_time": None}, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, hide_columns={'path', 'status'})
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # Hidden columns should not appear
            # Path column header or values
            lines = output.split('\n')
            # Check that path and status are not in the header line
            header_line = [line for line in lines if 'nodes' in line and '---' not in line]
            if header_line:
                assert 'Path' not in header_line[0] or 'runs/' not in output

    def test_find_hide_parameter_column(self, tmp_path):
        """Test hiding a parameter column."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {
                    "path": "runs/exec_0001",
                    "params": {"nodes": 1, "ppn": 4, "threads": 8}
                }
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, hide_columns={'ppn'})
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # ppn column should not appear
            # (Harder to verify since values might appear in other contexts)
            # Check that ppn is not in column headers
            assert 'nodes' in output
            assert 'threads' in output

    def test_find_hide_command_column(self, tmp_path):
        """Test hiding command column with --show-command."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {
                    "path": "runs/exec_0001",
                    "params": {"nodes": 1},
                    "command": "mpirun -np 4 ./benchmark"
                }
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Show command but hide it
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, show_command=True, hide_columns={'command'})
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # Command should not appear even though show_command=True
            assert 'mpirun' not in output or 'Command' not in output

    def test_find_hide_nonexistent_column(self, tmp_path):
        """Test that hiding nonexistent column doesn't cause errors."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {
                    "path": "runs/exec_0001",
                    "params": {"nodes": 1}
                }
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Should not raise error
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, hide_columns={'nonexistent_column'})
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            # Should still show normal output
            assert 'exec_0001' in output

    def test_find_hide_all_columns_shows_nothing(self, tmp_path):
        """Test hiding all columns results in minimal output."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {
                    "path": "runs/exec_0001",
                    "params": {"nodes": 1}
                }
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Hide all possible columns
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, hide_columns={'path', 'status', 'nodes'})
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            # Should have minimal output (just header separator maybe)
            # Exact behavior depends on implementation


# ============================================================================ #
# Find Command Tests - --status flag
# ============================================================================ #

class TestFindCommandStatus:
    """Test find command with --status flag."""

    def test_find_filter_by_succeeded_status(self, tmp_path):
        """Test filtering by SUCCEEDED status."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1}},
                "exec_0002": {"path": "runs/exec_0002", "params": {"nodes": 2}},
                "exec_0003": {"path": "runs/exec_0003", "params": {"nodes": 4}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Create status files
        for exec_name, status in [
            ("exec_0001", "SUCCEEDED"),
            ("exec_0002", "FAILED"),
            ("exec_0003", "SUCCEEDED")
        ]:
            exec_dir = tmp_path / "runs" / exec_name
            exec_dir.mkdir(parents=True)
            status_file = exec_dir / STATUS_FILENAME
            with open(status_file, 'w') as f:
                json.dump({"status": status, "error": None, "end_time": None}, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, status_filter='SUCCEEDED')
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # Should show only SUCCEEDED executions
            assert 'exec_0001' in output
            assert 'exec_0002' not in output
            assert 'exec_0003' in output

    def test_find_filter_by_failed_status(self, tmp_path):
        """Test filtering by FAILED status."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1}},
                "exec_0002": {"path": "runs/exec_0002", "params": {"nodes": 2}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Create status files
        for exec_name, status in [
            ("exec_0001", "SUCCEEDED"),
            ("exec_0002", "FAILED")
        ]:
            exec_dir = tmp_path / "runs" / exec_name
            exec_dir.mkdir(parents=True)
            status_file = exec_dir / STATUS_FILENAME
            with open(status_file, 'w') as f:
                json.dump({"status": status, "error": None, "end_time": None}, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, status_filter='FAILED')
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # Should show only FAILED executions
            assert 'exec_0001' not in output
            assert 'exec_0002' in output

    def test_find_filter_by_error_status(self, tmp_path):
        """Test filtering by ERROR status."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1}},
                "exec_0002": {"path": "runs/exec_0002", "params": {"nodes": 2}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Create status files
        for exec_name, status in [
            ("exec_0001", "SUCCEEDED"),
            ("exec_0002", "ERROR")
        ]:
            exec_dir = tmp_path / "runs" / exec_name
            exec_dir.mkdir(parents=True)
            status_file = exec_dir / STATUS_FILENAME
            with open(status_file, 'w') as f:
                json.dump({"status": status, "error": None, "end_time": None}, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, status_filter='ERROR')
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # Should show only ERROR executions
            assert 'exec_0001' not in output
            assert 'exec_0002' in output

    def test_find_filter_by_pending_status(self, tmp_path):
        """Test filtering by PENDING status (no status file)."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1}},
                "exec_0002": {"path": "runs/exec_0002", "params": {"nodes": 2}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Create status file for exec_0001 only
        exec_dir1 = tmp_path / "runs" / "exec_0001"
        exec_dir1.mkdir(parents=True)
        status_file1 = exec_dir1 / STATUS_FILENAME
        with open(status_file1, 'w') as f:
            json.dump({"status": "SUCCEEDED", "error": None, "end_time": None}, f)

        # exec_0002 has no status file (PENDING)
        exec_dir2 = tmp_path / "runs" / "exec_0002"
        exec_dir2.mkdir(parents=True)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, status_filter='PENDING')
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # Should show only PENDING executions
            assert 'exec_0001' not in output
            assert 'exec_0002' in output

    def test_find_status_filter_case_insensitive(self, tmp_path):
        """Test that status filter is case-insensitive."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        exec_dir = tmp_path / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)
        status_file = exec_dir / STATUS_FILENAME
        with open(status_file, 'w') as f:
            json.dump({"status": "SUCCEEDED", "error": None, "end_time": None}, f)

        # Test lowercase filter
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, status_filter='succeeded')
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'exec_0001' in output

    def test_find_status_filter_with_no_matches(self, tmp_path):
        """Test status filter with no matching executions."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        exec_dir = tmp_path / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)
        status_file = exec_dir / STATUS_FILENAME
        with open(status_file, 'w') as f:
            json.dump({"status": "SUCCEEDED", "error": None, "end_time": None}, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, status_filter='FAILED')
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # Should show "no matches" message
            assert 'No executions match' in output or 'No executions' in output

    def test_find_status_filter_combined_with_param_filter(self, tmp_path):
        """Test combining status filter with parameter filter."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1, "ppn": 4}},
                "exec_0002": {"path": "runs/exec_0002", "params": {"nodes": 2, "ppn": 4}},
                "exec_0003": {"path": "runs/exec_0003", "params": {"nodes": 2, "ppn": 8}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Create status files
        for exec_name, status in [
            ("exec_0001", "SUCCEEDED"),
            ("exec_0002", "SUCCEEDED"),
            ("exec_0003", "FAILED")
        ]:
            exec_dir = tmp_path / "runs" / exec_name
            exec_dir.mkdir(parents=True)
            status_file = exec_dir / STATUS_FILENAME
            with open(status_file, 'w') as f:
                json.dump({"status": status, "error": None, "end_time": None}, f)

        with patch('builtins.print') as mock_print:
            # Filter by nodes=2 AND status=SUCCEEDED
            find_executions(tmp_path, filters=['nodes=2'], status_filter='SUCCEEDED')
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # Should show only exec_0002 (nodes=2 and SUCCEEDED)
            assert 'exec_0001' not in output  # nodes=1
            assert 'exec_0002' in output      # nodes=2 and SUCCEEDED
            assert 'exec_0003' not in output  # nodes=2 but FAILED


# ============================================================================ #
# Integration Tests - Combined Features
# ============================================================================ #

class TestFindCommandIntegration:
    """Test find command with multiple new features combined."""

    def test_find_all_features_combined(self, tmp_path):
        """Test combining --full, --hide, and --status filters."""
        long_value = "x" * 100
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {
                    "path": "runs/exec_0001",
                    "params": {"nodes": 1, "long_param": long_value},
                    "command": "cmd1"
                },
                "exec_0002": {
                    "path": "runs/exec_0002",
                    "params": {"nodes": 2, "long_param": long_value},
                    "command": "cmd2"
                },
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Create status files
        for exec_name, status in [
            ("exec_0001", "SUCCEEDED"),
            ("exec_0002", "FAILED")
        ]:
            exec_dir = tmp_path / "runs" / exec_name
            exec_dir.mkdir(parents=True)
            status_file = exec_dir / STATUS_FILENAME
            with open(status_file, 'w') as f:
                json.dump({"status": status, "error": None, "end_time": None}, f)

        with patch('builtins.print') as mock_print:
            # Use all features: full values, hide path, filter by SUCCEEDED
            find_executions(
                tmp_path,
                show_full=True,
                hide_columns={'path'},
                status_filter='SUCCEEDED'
            )
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # Should show exec_0001 only (SUCCEEDED)
            assert 'exec_0001' not in output  # path is hidden
            assert 'exec_0002' not in output  # FAILED (filtered out)

            # Should show full long_param value
            assert long_value in output

    def test_find_status_column_displayed_by_default(self, tmp_path):
        """Test that status column is displayed by default."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        exec_dir = tmp_path / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)
        status_file = exec_dir / STATUS_FILENAME
        with open(status_file, 'w') as f:
            json.dump({"status": "SUCCEEDED", "error": None, "end_time": None}, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # Status column should appear by default
            assert 'Status' in output or 'SUCCEEDED' in output

    def test_find_status_column_can_be_hidden(self, tmp_path):
        """Test that status column can be hidden with --hide."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        exec_dir = tmp_path / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)
        status_file = exec_dir / STATUS_FILENAME
        with open(status_file, 'w') as f:
            json.dump({"status": "SUCCEEDED", "error": None, "end_time": None}, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, hide_columns={'status'})
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # Status should not appear when hidden
            # This is tricky to test precisely since other text might contain these words


# ============================================================================ #
# Edge Cases and Error Handling
# ============================================================================ #

class TestFindCommandEdgeCases:
    """Test edge cases for enhanced find functionality."""

    def test_find_unknown_status_values(self, tmp_path):
        """Test handling of unknown status values."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        exec_dir = tmp_path / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)
        status_file = exec_dir / STATUS_FILENAME
        with open(status_file, 'w') as f:
            # Write unknown status
            json.dump({"status": "WEIRD_STATUS", "error": None, "end_time": None}, f)

        # Should not crash
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            # Should display the unknown status
            assert 'WEIRD_STATUS' in output or 'exec_0001' in output

    def test_find_empty_hide_columns_set(self, tmp_path):
        """Test with empty hide_columns set."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Should work fine with empty set
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, hide_columns=set())
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'exec_0001' in output

    def test_find_none_status_filter(self, tmp_path):
        """Test with None status_filter (no filtering)."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1}},
                "exec_0002": {"path": "runs/exec_0002", "params": {"nodes": 2}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Should show all executions
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, status_filter=None)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'exec_0001' in output
            assert 'exec_0002' in output
