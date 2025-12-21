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


def test_slurm_executor_default_commands():
    """Test SlurmExecutor uses default commands when executor_options not provided."""
    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor_options = None
    config.execution = Mock()

    executor = SlurmExecutor(config)

    assert executor.cmd_submit == "sbatch"
    assert executor.cmd_status == "squeue"
    assert executor.cmd_info == "scontrol"
    assert executor.cmd_cancel == "scancel"


def test_slurm_executor_custom_commands():
    """Test SlurmExecutor uses custom commands from executor_options."""
    from iops.config.models import ExecutorOptionsConfig

    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor_options = ExecutorOptionsConfig(
        commands={
            "submit": "lrms-wrapper sbatch",
            "status": "lrms-wrapper squeue",
            "info": "lrms-wrapper scontrol",
            "cancel": "lrms-wrapper scancel"
        }
    )
    config.execution = Mock()

    executor = SlurmExecutor(config)

    assert executor.cmd_submit == "lrms-wrapper sbatch"
    assert executor.cmd_status == "lrms-wrapper squeue"
    assert executor.cmd_info == "lrms-wrapper scontrol"
    assert executor.cmd_cancel == "lrms-wrapper scancel"


def test_slurm_executor_partial_custom_commands():
    """Test SlurmExecutor uses defaults for unspecified commands."""
    from iops.config.models import ExecutorOptionsConfig

    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor_options = ExecutorOptionsConfig(
        commands={
            "status": "custom-squeue"
        }
    )
    config.execution = Mock()

    executor = SlurmExecutor(config)

    assert executor.cmd_status == "custom-squeue"
    assert executor.cmd_info == "scontrol"  # default
    assert executor.cmd_cancel == "scancel"  # default


def test_slurm_executor_squeue_uses_custom_command(mock_test_instance):
    """Test that _squeue_state uses custom status command."""
    from iops.config.models import ExecutorOptionsConfig

    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor_options = ExecutorOptionsConfig(
        commands={"status": "wrapper squeue"}
    )
    config.execution = Mock()

    executor = SlurmExecutor(config)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(
            returncode=0,
            stdout="RUNNING",
            stderr=""
        )

        state = executor._squeue_state("12345")

        # Check that the custom command was used
        call_args = mock_run.call_args[0][0]
        assert call_args[0:2] == ["wrapper", "squeue"]
        assert "-j" in call_args
        assert "12345" in call_args


def test_slurm_executor_scontrol_uses_custom_command(mock_test_instance):
    """Test that _scontrol_info uses custom info command."""
    from iops.config.models import ExecutorOptionsConfig

    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor_options = ExecutorOptionsConfig(
        commands={"info": "wrapper scontrol"}
    )
    config.execution = Mock()

    executor = SlurmExecutor(config)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(
            returncode=0,
            stdout="JobState=COMPLETED ExitCode=0:0",
            stderr=""
        )

        info = executor._scontrol_info("12345")

        # Check that the custom command was used
        call_args = mock_run.call_args[0][0]
        assert call_args[0:2] == ["wrapper", "scontrol"]
        assert "show" in call_args
        assert "job" in call_args
        assert "12345" in call_args


def test_slurm_executor_uses_default_submit_when_not_specified(mock_test_instance):
    """Test that executor uses default submit command when test.submit_cmd is empty."""
    from iops.config.models import ExecutorOptionsConfig

    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor_options = ExecutorOptionsConfig(
        commands={"submit": "custom-sbatch"}
    )
    config.execution = Mock()

    # Test instance with empty submit_cmd
    mock_test_instance.submit_cmd = ""

    executor = SlurmExecutor(config)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(
            returncode=0,
            stdout="Submitted batch job 12345",
            stderr=""
        )

        executor.submit(mock_test_instance)

        # Check that the default submit command was used
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "custom-sbatch"
        assert str(mock_test_instance.script_file) in call_args


def test_slurm_executor_script_submit_overrides_default(mock_test_instance):
    """Test that script-specific submit command overrides executor default."""
    from iops.config.models import ExecutorOptionsConfig

    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor_options = ExecutorOptionsConfig(
        commands={"submit": "default-sbatch"}
    )
    config.execution = Mock()

    # Test instance with specific submit_cmd
    mock_test_instance.submit_cmd = "script-specific-sbatch --parsable"

    executor = SlurmExecutor(config)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(
            returncode=0,
            stdout="12345;cluster",
            stderr=""
        )

        executor.submit(mock_test_instance)

        # Check that the script-specific submit command was used (not the default)
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "script-specific-sbatch"
        assert "--parsable" in call_args
