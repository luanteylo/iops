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
    """Test SlurmExecutor uses default command templates when executor_options not provided."""
    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor_options = None
    config.execution = Mock()

    executor = SlurmExecutor(config)

    assert executor.cmd_submit == "sbatch"
    assert executor.cmd_status == "squeue -j {job_id} --noheader --format=%T"
    assert executor.cmd_info == "scontrol show job {job_id}"
    assert executor.cmd_cancel == "scancel {job_id}"


def test_slurm_executor_custom_commands():
    """Test SlurmExecutor uses custom command templates from executor_options."""
    from iops.config.models import ExecutorOptionsConfig

    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor_options = ExecutorOptionsConfig(
        commands={
            "submit": "lrms-wrapper sbatch",
            "status": "lrms-wrapper -r {job_id} --custom-format",
            "info": "lrms-wrapper info {job_id}",
            "cancel": "lrms-wrapper kill {job_id}"
        }
    )
    config.execution = Mock()

    executor = SlurmExecutor(config)

    assert executor.cmd_submit == "lrms-wrapper sbatch"
    assert executor.cmd_status == "lrms-wrapper -r {job_id} --custom-format"
    assert executor.cmd_info == "lrms-wrapper info {job_id}"
    assert executor.cmd_cancel == "lrms-wrapper kill {job_id}"


def test_slurm_executor_partial_custom_commands():
    """Test SlurmExecutor uses default templates for unspecified commands."""
    from iops.config.models import ExecutorOptionsConfig

    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor_options = ExecutorOptionsConfig(
        commands={
            "status": "custom-squeue -j {job_id}"
        }
    )
    config.execution = Mock()

    executor = SlurmExecutor(config)

    assert executor.cmd_status == "custom-squeue -j {job_id}"
    assert executor.cmd_info == "scontrol show job {job_id}"  # default template
    assert executor.cmd_cancel == "scancel {job_id}"  # default template


def test_slurm_executor_squeue_uses_custom_command(mock_test_instance):
    """Test that _squeue_state uses custom status template and formats it correctly."""
    from iops.config.models import ExecutorOptionsConfig

    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor_options = ExecutorOptionsConfig(
        commands={"status": "wrapper -r {job_id} --custom"}
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

        # Check that the template was formatted correctly
        call_args = mock_run.call_args[0][0]
        assert call_args == ["wrapper", "-r", "12345", "--custom"]


def test_slurm_executor_scontrol_uses_custom_command(mock_test_instance):
    """Test that _scontrol_info uses custom info command template and formats it correctly."""
    from iops.config.models import ExecutorOptionsConfig

    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor_options = ExecutorOptionsConfig(
        commands={"info": "wrapper info {job_id}"}
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

        # Check that the template was formatted correctly
        call_args = mock_run.call_args[0][0]
        assert call_args == ["wrapper", "info", "12345"]


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


def test_local_executor_permission_denied_on_script_file(mock_test_instance):
    """Test LocalExecutor handles permission errors gracefully when checking script file."""
    config = Mock()
    executor = LocalExecutor(config)

    # Mock the _safe_is_file to simulate permission denied
    with patch.object(executor, '_safe_is_file', return_value=False):
        executor.submit(mock_test_instance)

        # Should handle gracefully and mark as error
        assert mock_test_instance.metadata["__executor_status"] == executor.STATUS_ERROR
        assert "__error" in mock_test_instance.metadata
        assert "not set or invalid" in mock_test_instance.metadata["__error"]


def test_local_executor_permission_denied_on_post_script(mock_test_instance, tmp_path):
    """Test LocalExecutor handles permission errors gracefully when checking post-script file."""
    config = Mock()
    executor = LocalExecutor(config)

    # Create a post script path (file exists but we'll simulate permission error)
    mock_test_instance.post_script_file = tmp_path / "post.sh"
    mock_test_instance.post_script_file.write_text("#!/bin/bash\necho 'post'")

    with patch("subprocess.run") as mock_run:
        # Main script succeeds
        mock_run.return_value = Mock(
            returncode=0,
            stdout="main output",
            stderr=""
        )

        # Mock is_file to raise PermissionError on post_script_file check
        original_is_file = Path.is_file

        def mock_is_file(self):
            # Raise permission error for post script file
            if self.name == "post.sh":
                raise PermissionError(f"Permission denied: {self}")
            return original_is_file(self)

        with patch.object(Path, 'is_file', mock_is_file):
            executor.submit(mock_test_instance)

            # Should succeed (main script ran) and skip post-script gracefully
            assert mock_test_instance.metadata["__executor_status"] == executor.STATUS_SUCCEEDED
            # Post script should not have been executed (only one subprocess.run call for main script)
            assert mock_run.call_count == 1
            # Should not have post script return code
            assert "__post_returncode" not in mock_test_instance.metadata


def test_slurm_executor_permission_denied_on_post_script(mock_test_instance, tmp_path):
    """Test SlurmExecutor handles permission errors gracefully when checking post-script file."""
    config = Mock()
    config.execution = Mock()
    config.execution.status_check_delay = 1
    config.benchmark = Mock()
    config.benchmark.executor_options = None

    executor = SlurmExecutor(config)

    # Create a post script path
    mock_test_instance.post_script_file = tmp_path / "post.sh"
    mock_test_instance.post_script_file.write_text("#!/bin/bash\necho 'post'")

    # Setup a succeeded test in wait_and_collect
    mock_test_instance.metadata["__jobid"] = "12345"
    mock_test_instance.metadata["__executor_status"] = executor.STATUS_SUCCEEDED

    # Mock is_file to raise PermissionError on post_script_file check
    original_is_file = Path.is_file

    def mock_is_file(self):
        if self.name == "post.sh":
            raise PermissionError(f"Permission denied: {self}")
        return original_is_file(self)

    with patch.object(Path, 'is_file', mock_is_file):
        with patch.object(executor, '_squeue_state', return_value=None):
            with patch.object(executor, '_scontrol_info', return_value={"state": "COMPLETED", "exitcode": "0:0"}):
                with patch.object(executor, '_try_parse_metrics', return_value=True):
                    executor.wait_and_collect(mock_test_instance)

                    # Should complete successfully without trying to run post script
                    assert mock_test_instance.metadata["__executor_status"] == executor.STATUS_SUCCEEDED
                    # Should not have post script metadata
                    assert "__post_returncode" not in mock_test_instance.metadata


def test_safe_is_file_handles_oserror():
    """Test that _safe_is_file helper handles various OSError scenarios."""
    config = Mock()
    executor = LocalExecutor(config)

    # Test with None
    assert executor._safe_is_file(None) is False

    # Test with valid path that exists
    with patch.object(Path, 'is_file', return_value=True):
        test_path = Path("/some/path")
        assert executor._safe_is_file(test_path) is True

    # Test with PermissionError
    def raise_permission_error():
        raise PermissionError("Permission denied")

    with patch.object(Path, 'is_file', side_effect=raise_permission_error):
        test_path = Path("/restricted/path")
        assert executor._safe_is_file(test_path) is False

    # Test with FileNotFoundError (stale NFS handle scenario)
    def raise_file_not_found():
        raise FileNotFoundError("Stale file handle")

    with patch.object(Path, 'is_file', side_effect=raise_file_not_found):
        test_path = Path("/nfs/stale/path")
        assert executor._safe_is_file(test_path) is False

    # Test with generic OSError
    def raise_os_error():
        raise OSError("I/O error")

    with patch.object(Path, 'is_file', side_effect=raise_os_error):
        test_path = Path("/error/path")
        assert executor._safe_is_file(test_path) is False
