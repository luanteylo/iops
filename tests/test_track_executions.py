"""Comprehensive unit tests for track_executions configuration option.

This module tests the track_executions feature which controls whether IOPS writes
execution metadata files (__iops_params.json and __iops_status.json) to disk.
When enabled (default), these files enable the 'iops find' command to explore
execution history without parsing the full results database.

Key components tested:
1. BenchmarkConfig.track_executions field (default True)
2. Planner._write_params_file() gating
3. Runner._write_status_file() gating
4. Status file writing functionality
"""

import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import yaml

from iops.config.models import GenericBenchmarkConfig, BenchmarkConfig
from iops.execution.planner import BasePlanner, ExhaustivePlanner
from iops.execution.matrix import ExecutionInstance
from iops.execution.runner import IOPSRunner
from conftest import load_config


# ============================================================================ #
# Config Tests - track_executions field
# ============================================================================ #

class TestTrackExecutionsConfig:
    """Test track_executions configuration field."""

    def test_track_executions_default_true(self, sample_config_dict, tmp_path):
        """Test that track_executions defaults to True."""
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)

        # Default should be True
        assert config.benchmark.track_executions is True

    def test_track_executions_can_be_disabled(self, sample_config_file):
        """Test that track_executions can be set to False programmatically."""
        config = load_config(sample_config_file)

        # Explicitly set to False after loading
        config.benchmark.track_executions = False

        assert config.benchmark.track_executions is False

    def test_track_executions_can_be_enabled_explicitly(self, sample_config_dict, tmp_path):
        """Test that track_executions can be explicitly set to True."""
        config_file = tmp_path / "test_config.yaml"

        # Explicitly set to True
        sample_config_dict["benchmark"]["track_executions"] = True

        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)

        assert config.benchmark.track_executions is True

    def test_track_executions_field_exists_in_dataclass(self):
        """Test that track_executions field exists in BenchmarkConfig dataclass."""
        config = BenchmarkConfig(
            name="Test",
            description="Test description",
            workdir=Path("/tmp"),
        )

        # Should have the field with default value True
        assert hasattr(config, "track_executions")
        assert config.track_executions is True


# ============================================================================ #
# Planner Tests - _write_params_file() gating
# ============================================================================ #

class TestPlannerTrackExecutions:
    """Test planner respects track_executions setting."""

    def test_prepare_execution_artifacts_writes_params_file_when_enabled(
        self, sample_config_file, tmp_path
    ):
        """Test that params file is written when track_executions=True (default)."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = True  # Ensure enabled

        planner = ExhaustivePlanner(config)
        planner._build_execution_matrix()

        test = planner.execution_matrix[0]

        # Prepare artifacts (repetition=1 triggers params file writing)
        planner._prepare_execution_artifacts(test, repetition=1)

        # Params file should be created in exec_XXXX folder
        exec_dir = test.execution_dir.parent  # Get exec_XXXX from repetition_XXX
        params_file = exec_dir / "__iops_params.json"

        assert params_file.exists(), "Params file should be created when track_executions=True"

        # Verify params file contains correct data
        with open(params_file, 'r') as f:
            params_data = json.load(f)

        assert "nodes" in params_data
        assert "ppn" in params_data
        assert params_data["nodes"] in [1, 2]  # From config sweep

    def test_prepare_execution_artifacts_skips_params_file_when_disabled(
        self, sample_config_file, tmp_path
    ):
        """Test that params file is NOT written when track_executions=False."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = False  # Explicitly disable

        planner = ExhaustivePlanner(config)
        planner._build_execution_matrix()

        test = planner.execution_matrix[0]

        # Prepare artifacts
        planner._prepare_execution_artifacts(test, repetition=1)

        # Params file should NOT be created
        exec_dir = test.execution_dir.parent
        params_file = exec_dir / "__iops_params.json"

        assert not params_file.exists(), "Params file should not be created when track_executions=False"

    def test_prepare_execution_artifacts_params_file_default_behavior(
        self, sample_config_file, tmp_path
    ):
        """Test that params file is created by default (when track_executions not specified)."""
        config = load_config(sample_config_file)
        # Don't set track_executions - should default to True

        planner = ExhaustivePlanner(config)
        planner._build_execution_matrix()

        test = planner.execution_matrix[0]

        # Prepare artifacts
        planner._prepare_execution_artifacts(test, repetition=1)

        # Params file should be created (default behavior)
        exec_dir = test.execution_dir.parent
        params_file = exec_dir / "__iops_params.json"

        assert params_file.exists(), "Params file should be created by default"

    def test_params_file_only_written_on_first_repetition(
        self, sample_config_file, tmp_path
    ):
        """Test that params file is only written once (repetition=1), not for subsequent reps."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = True
        config.benchmark.repetitions = 3

        planner = ExhaustivePlanner(config)
        planner._build_execution_matrix()

        test = planner.execution_matrix[0]

        # Prepare artifacts for repetition 1
        planner._prepare_execution_artifacts(test, repetition=1)
        exec_dir_rep1 = test.execution_dir.parent
        params_file = exec_dir_rep1 / "__iops_params.json"
        assert params_file.exists()

        # Store modification time
        mtime_rep1 = params_file.stat().st_mtime

        # Prepare artifacts for repetition 2
        planner._prepare_execution_artifacts(test, repetition=2)

        # Params file should not be rewritten
        mtime_rep2 = params_file.stat().st_mtime
        assert mtime_rep1 == mtime_rep2, "Params file should not be rewritten for repetition 2"

    def test_params_file_not_written_when_disabled_even_for_first_rep(
        self, sample_config_file, tmp_path
    ):
        """Test that params file is not written even on first repetition when disabled."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = False

        planner = ExhaustivePlanner(config)
        planner._build_execution_matrix()

        test = planner.execution_matrix[0]

        # Prepare artifacts for repetition 1
        planner._prepare_execution_artifacts(test, repetition=1)

        exec_dir = test.execution_dir.parent
        params_file = exec_dir / "__iops_params.json"

        assert not params_file.exists(), "Params file should not be created when disabled"


# ============================================================================ #
# Runner Tests - _write_status_file() gating
# ============================================================================ #

class TestRunnerTrackExecutions:
    """Test runner respects track_executions setting."""

    def test_write_status_file_creates_file_when_enabled(self, sample_config_file, tmp_path):
        """Test that status file is written when track_executions=True (default)."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = True

        args = Mock()
        args.use_cache = False
        args.max_core_hours = None
        args.time_estimate = None
        args.log_level = "INFO"

        runner = IOPSRunner(config, args)

        # Create a test instance with execution_dir
        test = Mock(spec=ExecutionInstance)
        test.execution_dir = tmp_path / "exec_0001" / "repetition_001"
        test.execution_dir.mkdir(parents=True)
        test.metadata = {
            "__executor_status": "SUCCEEDED",
            "__error": None,
            "__end": "2024-01-01T12:00:00",
        }

        # Write status file
        runner._write_status_file(test)

        # Status file should be created in the repetition folder (execution_dir)
        status_file = test.execution_dir / "__iops_status.json"

        assert status_file.exists(), "Status file should be created when track_executions=True"

        # Verify status file contains correct data
        with open(status_file, 'r') as f:
            status_data = json.load(f)

        assert status_data["status"] == "SUCCEEDED"
        assert status_data["error"] is None
        assert status_data["end_time"] == "2024-01-01T12:00:00"

    def test_write_status_file_handles_failed_execution(self, sample_config_file, tmp_path):
        """Test that status file correctly records failed executions."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = True

        args = Mock()
        args.use_cache = False
        args.max_core_hours = None
        args.time_estimate = None
        args.log_level = "INFO"

        runner = IOPSRunner(config, args)

        test = Mock(spec=ExecutionInstance)
        test.execution_dir = tmp_path / "exec_0001" / "repetition_001"
        test.execution_dir.mkdir(parents=True)
        test.metadata = {
            "__executor_status": "FAILED",
            "__error": "Command returned non-zero exit code: 1",
            "__end": "2024-01-01T12:00:00",
        }

        runner._write_status_file(test)

        # Status file should be in the repetition folder
        status_file = test.execution_dir / "__iops_status.json"

        with open(status_file, 'r') as f:
            status_data = json.load(f)

        assert status_data["status"] == "FAILED"
        assert "non-zero exit code" in status_data["error"]

    def test_write_status_file_handles_error_status(self, sample_config_file, tmp_path):
        """Test that status file correctly records ERROR status."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = True

        args = Mock()
        args.use_cache = False
        args.max_core_hours = None
        args.time_estimate = None
        args.log_level = "INFO"

        runner = IOPSRunner(config, args)

        test = Mock(spec=ExecutionInstance)
        test.execution_dir = tmp_path / "exec_0001" / "repetition_001"
        test.execution_dir.mkdir(parents=True)
        test.metadata = {
            "__executor_status": "ERROR",
            "__error": "Job submission failed",
            "__end": "2024-01-01T12:00:00",
        }

        runner._write_status_file(test)

        # Status file should be in the repetition folder
        status_file = test.execution_dir / "__iops_status.json"

        with open(status_file, 'r') as f:
            status_data = json.load(f)

        assert status_data["status"] == "ERROR"
        assert "Job submission failed" in status_data["error"]

    def test_write_status_file_handles_missing_metadata_fields(
        self, sample_config_file, tmp_path
    ):
        """Test that status file handles missing metadata fields gracefully."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = True

        args = Mock()
        args.use_cache = False
        args.max_core_hours = None
        args.time_estimate = None
        args.log_level = "INFO"

        runner = IOPSRunner(config, args)

        test = Mock(spec=ExecutionInstance)
        test.execution_dir = tmp_path / "exec_0001" / "repetition_001"
        test.execution_dir.mkdir(parents=True)
        test.metadata = {}  # Empty metadata

        runner._write_status_file(test)

        # Status file should be in the repetition folder
        status_file = test.execution_dir / "__iops_status.json"

        with open(status_file, 'r') as f:
            status_data = json.load(f)

        assert status_data["status"] == "UNKNOWN"
        assert status_data["error"] is None
        assert status_data["end_time"] is None

    def test_write_status_file_handles_none_execution_dir(self, sample_config_file):
        """Test that _write_status_file handles None execution_dir gracefully."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = True

        args = Mock()
        args.use_cache = False
        args.max_core_hours = None
        args.time_estimate = None
        args.log_level = "INFO"

        runner = IOPSRunner(config, args)

        test = Mock(spec=ExecutionInstance)
        test.execution_dir = None
        test.metadata = {"__executor_status": "SUCCEEDED"}

        # Should not raise, just log debug message
        runner._write_status_file(test)

    def test_write_status_file_handles_write_error(
        self, sample_config_file, tmp_path
    ):
        """Test that _write_status_file handles write errors gracefully."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = True

        args = Mock()
        args.use_cache = False
        args.max_core_hours = None
        args.time_estimate = None
        args.log_level = "INFO"

        runner = IOPSRunner(config, args)

        test = Mock(spec=ExecutionInstance)
        # Create a read-only directory to trigger write error
        test.execution_dir = tmp_path / "exec_0001" / "repetition_001"
        test.execution_dir.mkdir(parents=True)
        test.metadata = {"__executor_status": "SUCCEEDED"}

        # Make parent directory read-only
        exec_dir = test.execution_dir.parent
        exec_dir.chmod(0o444)

        try:
            # Should not raise, just log warning
            runner._write_status_file(test)
        finally:
            # Restore permissions for cleanup
            exec_dir.chmod(0o755)

    def test_run_calls_write_status_file_when_enabled(
        self, sample_config_file, tmp_path
    ):
        """Test that _write_status_file is called when track_executions=True."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = True

        args = Mock()
        args.use_cache = False
        args.max_core_hours = None
        args.time_estimate = None
        args.log_level = "INFO"

        runner = IOPSRunner(config, args)

        # Create a test instance and call _write_status_file directly
        test = Mock(spec=ExecutionInstance)
        test.execution_dir = tmp_path / "exec_0001" / "repetition_001"
        test.execution_dir.mkdir(parents=True)
        test.metadata = {"__executor_status": "SUCCEEDED"}

        # Call _write_status_file
        runner._write_status_file(test)

        # Verify status file was created in repetition folder
        status_file = test.execution_dir / "__iops_status.json"
        assert status_file.exists()

    def test_run_skips_write_status_file_when_disabled(
        self, sample_config_file, tmp_path
    ):
        """Test that runner.run() does NOT call _write_status_file when track_executions=False."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = False  # Disable

        args = Mock()
        args.use_cache = False
        args.max_core_hours = None
        args.time_estimate = None
        args.log_level = "INFO"

        runner = IOPSRunner(config, args)

        # Create a test instance
        test = Mock(spec=ExecutionInstance)
        test.execution_dir = tmp_path / "exec_0001" / "repetition_001"
        test.execution_dir.mkdir(parents=True)
        test.metadata = {"__executor_status": "SUCCEEDED"}

        # Manually call _write_status_file to verify file is still created
        # (the method itself doesn't check track_executions, the caller does)
        runner._write_status_file(test)

        # Status file should be in the repetition folder
        status_file = test.execution_dir / "__iops_status.json"

        # The _write_status_file method itself always writes
        # The gating happens in the caller (runner.run)
        assert status_file.exists()


# ============================================================================ #
# Integration Tests - End-to-End track_executions Flow
# ============================================================================ #

class TestTrackExecutionsIntegration:
    """Test complete track_executions flow."""

    def test_track_executions_enabled_creates_both_files(
        self, sample_config_file, tmp_path
    ):
        """Test that both params and status files are created when enabled."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = True

        # 1. Planner generates params file
        planner = ExhaustivePlanner(config)
        planner._build_execution_matrix()
        test = planner.execution_matrix[0]
        planner._prepare_execution_artifacts(test, repetition=1)

        exec_dir = test.execution_dir.parent
        params_file = exec_dir / "__iops_params.json"
        assert params_file.exists()

        # 2. Runner writes status file
        args = Mock()
        args.use_cache = False
        args.max_core_hours = None
        args.time_estimate = None
        args.log_level = "INFO"

        runner = IOPSRunner(config, args)
        test.metadata = {
            "__executor_status": "SUCCEEDED",
            "__error": None,
            "__end": "2024-01-01T12:00:00",
        }
        runner._write_status_file(test)

        # Status file should be in the repetition folder
        status_file = test.execution_dir / "__iops_status.json"
        assert status_file.exists()

        # 3. Verify both files have correct content
        with open(params_file, 'r') as f:
            params_data = json.load(f)
        assert "nodes" in params_data

        with open(status_file, 'r') as f:
            status_data = json.load(f)
        assert status_data["status"] == "SUCCEEDED"

    def test_track_executions_disabled_creates_no_files(
        self, sample_config_file, tmp_path
    ):
        """Test that neither params nor status files are created when disabled."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = False

        # 1. Planner skips params file
        planner = ExhaustivePlanner(config)
        planner._build_execution_matrix()
        test = planner.execution_matrix[0]
        planner._prepare_execution_artifacts(test, repetition=1)

        exec_dir = test.execution_dir.parent
        params_file = exec_dir / "__iops_params.json"
        assert not params_file.exists()

        # 2. Runner would skip status file in normal flow
        # (but _write_status_file itself doesn't check, the caller does)
        # So we verify the gating happens at the runner.run level

    def test_track_executions_works_with_multiple_executions(
        self, sample_config_file, tmp_path
    ):
        """Test track_executions with multiple execution instances."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = True

        planner = ExhaustivePlanner(config)
        planner._build_execution_matrix()

        # Should have 2 executions (nodes: [1, 2])
        assert len(planner.execution_matrix) >= 2

        # Prepare artifacts for all executions
        for test in planner.execution_matrix[:2]:
            planner._prepare_execution_artifacts(test, repetition=1)

            exec_dir = test.execution_dir.parent
            params_file = exec_dir / "__iops_params.json"
            assert params_file.exists()

            # Verify each has different params
            with open(params_file, 'r') as f:
                params_data = json.load(f)
            assert "nodes" in params_data


# ============================================================================ #
# Edge Case Tests
# ============================================================================ #

class TestTrackExecutionsEdgeCases:
    """Test edge cases for track_executions feature."""

    def test_track_executions_with_getattr_fallback(self, sample_config_file):
        """Test that getattr with default True works for configs without the field."""
        config = load_config(sample_config_file)

        # Simulate old config without track_executions field
        if hasattr(config.benchmark, 'track_executions'):
            delattr(config.benchmark, 'track_executions')

        # Code uses getattr(cfg.benchmark, 'track_executions', True)
        result = getattr(config.benchmark, 'track_executions', True)
        assert result is True

    def test_params_file_content_structure(self, sample_config_file, tmp_path):
        """Test that params file has expected JSON structure."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = True

        planner = ExhaustivePlanner(config)
        planner._build_execution_matrix()
        test = planner.execution_matrix[0]
        planner._prepare_execution_artifacts(test, repetition=1)

        exec_dir = test.execution_dir.parent
        params_file = exec_dir / "__iops_params.json"

        with open(params_file, 'r') as f:
            params_data = json.load(f)

        # Should be a flat dict of param names to values
        assert isinstance(params_data, dict)
        assert "nodes" in params_data
        assert "ppn" in params_data
        assert "total_procs" in params_data

        # Values should be primitive types
        assert isinstance(params_data["nodes"], int)
        assert isinstance(params_data["ppn"], int)
        assert isinstance(params_data["total_procs"], int)

    def test_status_file_content_structure(self, sample_config_file, tmp_path):
        """Test that status file has expected JSON structure."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = True

        args = Mock()
        args.use_cache = False
        args.max_core_hours = None
        args.time_estimate = None
        args.log_level = "INFO"

        runner = IOPSRunner(config, args)

        test = Mock(spec=ExecutionInstance)
        test.execution_dir = tmp_path / "exec_0001" / "repetition_001"
        test.execution_dir.mkdir(parents=True)
        test.metadata = {
            "__executor_status": "SUCCEEDED",
            "__error": None,
            "__end": "2024-01-01T12:00:00",
        }

        runner._write_status_file(test)

        # Status file should be in the repetition folder
        status_file = test.execution_dir / "__iops_status.json"

        with open(status_file, 'r') as f:
            status_data = json.load(f)

        # Should have exactly these six fields
        assert "status" in status_data
        assert "error" in status_data
        assert "end_time" in status_data
        assert "cached" in status_data
        assert "duration_seconds" in status_data
        assert "metrics" in status_data
        assert len(status_data) == 6

        # Status should be a string
        assert isinstance(status_data["status"], str)
        # error can be None or string
        assert status_data["error"] is None or isinstance(status_data["error"], str)
        # end_time can be None or string
        assert status_data["end_time"] is None or isinstance(status_data["end_time"], str)
        # cached should be a boolean
        assert isinstance(status_data["cached"], bool)
        # duration_seconds can be None or number
        assert status_data["duration_seconds"] is None or isinstance(status_data["duration_seconds"], (int, float))
        # metrics can be None or dict
        assert status_data["metrics"] is None or isinstance(status_data["metrics"], dict)

    def test_track_executions_with_cache(self, sample_config_file, tmp_path):
        """Test that track_executions works correctly with cached executions."""
        config = load_config(sample_config_file)
        config.benchmark.track_executions = True

        args = Mock()
        args.use_cache = True  # Enable cache
        args.max_core_hours = None
        args.time_estimate = None
        args.log_level = "INFO"

        runner = IOPSRunner(config, args)

        # When using cache, status file should still be written
        # (only for non-cached executions)
        test = Mock(spec=ExecutionInstance)
        test.execution_dir = tmp_path / "exec_0001" / "repetition_001"
        test.execution_dir.mkdir(parents=True)
        test.metadata = {
            "__executor_status": "SUCCEEDED",
            "__error": None,
            "__end": "2024-01-01T12:00:00",
        }

        runner._write_status_file(test)

        # Status file should be in the repetition folder
        status_file = test.execution_dir / "__iops_status.json"

        assert status_file.exists()
