"""Tests for executor implementations."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import subprocess

from iops.execution.executors import BaseExecutor, LocalExecutor, SlurmExecutor
from iops.execution.matrix import ExecutionInstance
from conftest import load_config


@pytest.fixture
def mock_test_instance(tmp_path):
    """Create a mock ExecutionInstance for testing."""
    test = Mock(spec=ExecutionInstance)
    test.execution_id = 1
    test.repetition = 1
    test.repetitions = 1
    test.execution_dir = tmp_path / "exec_001"
    test.execution_dir.mkdir(parents=True, exist_ok=True)
    test.script_file = test.execution_dir / "test.sh"
    test.script_file.write_text("#!/bin/bash\necho 'test'")
    test.post_script_file = None
    test.metadata = {}
    test.parser = Mock()
    test.parser.metrics = []
    return test


def test_executor_registry():
    """Test that executors are properly registered."""
    assert "local" in BaseExecutor._registry
    assert "slurm" in BaseExecutor._registry
    assert BaseExecutor._registry["local"] == LocalExecutor
    assert BaseExecutor._registry["slurm"] == SlurmExecutor


def test_executor_build(sample_config_file):
    """Test building executor from config."""
    config = load_config(sample_config_file)
    executor = BaseExecutor.build(config)

    assert isinstance(executor, LocalExecutor)


def test_local_executor_submit_success(mock_test_instance):
    """Test LocalExecutor successful submission."""
    config = Mock()
    executor = LocalExecutor(config)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(
            returncode=0,
            stdout="output",
            stderr=""
        )

        executor.submit(mock_test_instance)

        assert mock_test_instance.metadata["__executor_status"] == executor.STATUS_SUCCEEDED
        assert mock_test_instance.metadata["__jobid"] == "local"
        mock_run.assert_called_once()


def test_local_executor_submit_failure(mock_test_instance):
    """Test LocalExecutor failed submission."""
    config = Mock()
    executor = LocalExecutor(config)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="error message"
        )

        executor.submit(mock_test_instance)

        assert mock_test_instance.metadata["__executor_status"] == executor.STATUS_FAILED
        assert "__error" in mock_test_instance.metadata


def test_local_executor_post_script_success(mock_test_instance, tmp_path):
    """Test LocalExecutor with successful post script."""
    config = Mock()
    executor = LocalExecutor(config)

    # Create post script
    mock_test_instance.post_script_file = tmp_path / "post.sh"
    mock_test_instance.post_script_file.write_text("#!/bin/bash\necho 'post'")

    with patch("subprocess.run") as mock_run:
        # Mock both main and post script calls
        mock_run.side_effect = [
            Mock(returncode=0, stdout="main output", stderr=""),  # Main script
            Mock(returncode=0, stdout="post output", stderr=""),  # Post script
        ]

        executor.submit(mock_test_instance)

        assert mock_test_instance.metadata["__executor_status"] == executor.STATUS_SUCCEEDED
        assert "__post_returncode" in mock_test_instance.metadata
        assert mock_test_instance.metadata["__post_returncode"] == 0


def test_local_executor_post_script_failure(mock_test_instance, tmp_path):
    """Test LocalExecutor with failed post script."""
    config = Mock()
    executor = LocalExecutor(config)

    # Create post script
    mock_test_instance.post_script_file = tmp_path / "post.sh"
    mock_test_instance.post_script_file.write_text("#!/bin/bash\nexit 1")

    with patch("subprocess.run") as mock_run:
        # Mock both main and post script calls
        mock_run.side_effect = [
            Mock(returncode=0, stdout="main output", stderr=""),  # Main script succeeds
            Mock(returncode=1, stdout="", stderr="error"),  # Post script fails
        ]

        executor.submit(mock_test_instance)

        # Should mark entire test as failed
        assert mock_test_instance.metadata["__executor_status"] == executor.STATUS_FAILED
        assert "__error" in mock_test_instance.metadata


def test_local_executor_wait_and_collect(mock_test_instance):
    """Test LocalExecutor wait_and_collect."""
    config = Mock()
    executor = LocalExecutor(config)

    # Setup successful execution
    mock_test_instance.metadata["__executor_status"] = executor.STATUS_SUCCEEDED

    # Create a proper mock metric object
    mock_metric = Mock()
    mock_metric.name = "metric1"
    mock_test_instance.parser.metrics = [mock_metric]

    with patch("iops.execution.executors.local.parse_metrics_from_execution") as mock_parse:
        mock_parse.return_value = {"metrics": {"metric1": 100.5}}

        executor.wait_and_collect(mock_test_instance)

        assert "metrics" in mock_test_instance.metadata
        assert mock_test_instance.metadata["metrics"]["metric1"] == 100.5


def test_slurm_executor_submit_success(mock_test_instance):
    """Test SlurmExecutor successful submission."""
    config = Mock()
    config.execution = Mock()
    config.execution.status_check_delay = 1

    mock_test_instance.submit_cmd = "sbatch test.sh"

    executor = SlurmExecutor(config)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(
            returncode=0,
            stdout="Submitted batch job 12345",
            stderr=""
        )

        executor.submit(mock_test_instance)

        assert mock_test_instance.metadata["__executor_status"] == executor.STATUS_PENDING
        assert mock_test_instance.metadata["__jobid"] == "12345"


def test_slurm_executor_parse_jobid_standard():
    """Test SLURM job ID parsing from standard sbatch output."""
    config = Mock()
    config.execution = Mock()
    executor = SlurmExecutor(config)

    jobid = executor._parse_jobid("Submitted batch job 12345")
    assert jobid == "12345"


def test_slurm_executor_parse_jobid_parsable():
    """Test SLURM job ID parsing from parsable output."""
    config = Mock()
    config.execution = Mock()
    executor = SlurmExecutor(config)

    jobid = executor._parse_jobid("12345;cluster")
    assert jobid == "12345"


def test_executor_init_metadata(mock_test_instance):
    """Test that _init_execution_metadata sets standard keys."""
    config = Mock()
    executor = LocalExecutor(config)

    executor._init_execution_metadata(mock_test_instance)

    assert "__jobid" in mock_test_instance.metadata
    assert "__executor_status" in mock_test_instance.metadata
    assert "__start" in mock_test_instance.metadata
    assert "__end" in mock_test_instance.metadata
    assert "__error" in mock_test_instance.metadata


def test_executor_truncate_output():
    """Test output truncation helper."""
    config = Mock()
    executor = LocalExecutor(config)

    # Short output
    short = "line1\nline2\nline3"
    truncated = executor._truncate_output(short, max_lines=10)
    assert truncated == short

    # Long output
    long = "\n".join([f"line{i}" for i in range(20)])
    truncated = executor._truncate_output(long, max_lines=10)
    assert "line0" in truncated  # First line
    assert "line19" in truncated  # Last line
    assert "omitted" in truncated  # Truncation marker
