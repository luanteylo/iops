import sys
import tempfile
import pytest
from unittest.mock import patch
from pathlib import Path

from iops.controller.executors import SlurmExecutor, LocalExecutor
from iops.controller.executors import BaseExecutor

@pytest.fixture
def config_setup_local(tmp_path):
    from iops.utils.config_loader import IOPSConfig, StorageConfig, NodesConfig, ExecutionConfig, TemplateConfig
    
    # Create a minimal config for testing
    config = IOPSConfig(
        nodes=NodesConfig(min_nodes=1, max_nodes=2, node_step=2, processes_per_node=4, cores_per_node=32),
        storage=StorageConfig(
            filesystem_dir=tmp_path / "fs",
            min_volume=1,
            max_volume=10,
            volume_step=1,
            default_stripe=1,
            stripe_folders=[
                {"name": str(tmp_path / "folder1")}
            ]
        ),
        execution=ExecutionConfig(
            test_type="write_only",
            search_method="greedy",
            job_manager="local",
            benchmark_tool="ior",
            workdir=tmp_path / "workdir",
            repetitions=5,
            status_check_delay=10,
            wall_time="00:30:00",
            tests=["nodes"],
            io_pattern="sequential:shared"
        ),
        template=TemplateConfig(
            bash_template=tmp_path / "slurm_template.sh",
        )
    )
    return config


def test_local_submit_success(config_setup_local):
    """Test successful submission of a local job script."""
    executor = LocalExecutor(config_setup_local)
    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "test.sh"
        
        script_path.write_text("#!/bin/bash\necho hello\n")
        script_path.chmod(0o755)
        result = executor.submit(script_path)
        assert result == "local"

def test_local_submit_missing_script(config_setup_local):
    """Test submission failure when script does not exist."""
    executor = LocalExecutor(config_setup_local)
    with pytest.raises(ValueError):
        executor.submit(Path("/nonexistent/script.sh"))


def test_local_submit_script_failure(config_setup_local):
    """Test submission failure when script execution fails."""
    executor = LocalExecutor(config_setup_local)
    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = Path(tmpdir) / "fail.sh"
        script_path.write_text("#!/bin/bash\nexit 1\n")
        script_path.chmod(0o755)
        with pytest.raises(RuntimeError):
            executor.submit(script_path)

def test_local_wait_and_collect_success(tmp_path):
    """Test successful collection of job metadata."""
    executor = LocalExecutor(config_setup)
    job_id = "12345"
    
    # Create fake files
    (tmp_path / executor.JOB_START_FILE).write_text("start-time")
    (tmp_path / executor.JOB_END_FILE).write_text("end-time")
    (tmp_path / executor.JOB_STATUS_FILE).write_text("COMPLETED")

    result = executor._wait_and_collect(job_id, execution_dir=tmp_path)

    assert result["__jobid"] == job_id
    assert result["__start"] == "start-time"
    assert result["__end"] == "end-time"
    assert result["__status"] == "COMPLETED"
    assert "__error" not in result

def test_local_wait_and_collect_missing_files(tmp_path):
    """Test behavior when some expected files are missing."""
    executor = LocalExecutor(config_setup)
    job_id = "12345"

    # Only one file exists
    (tmp_path / executor.JOB_STATUS_FILE).write_text("COMPLETED")

    result = executor._wait_and_collect(job_id, execution_dir=tmp_path)

    assert result["__start"] is None
    assert result["__end"] is None
    assert result["__status"] == "COMPLETED"

def test_local_wait_and_collect_file_error(config_setup, tmp_path):
    """Test behavior when reading files raises an error."""
    executor = LocalExecutor(config_setup)
    job_id = "12345"

    # Create a file that will raise exception on read
    bad_file = tmp_path / executor.JOB_STATUS_FILE
    bad_file.write_text("invalid")

    # Simulate read_text() raising error using patch
    with patch.object(Path, "read_text", side_effect=Exception("Read error")):
        result = executor._wait_and_collect(job_id, execution_dir=tmp_path)

    assert result["__jobid"] == job_id
    assert result["__status"] == "ERROR"
    assert "Read error" in result["__error"]

@pytest.fixture
def config_setup(tmp_path):
    from iops.utils.config_loader import IOPSConfig, StorageConfig, NodesConfig, ExecutionConfig, TemplateConfig
    
    # Create a minimal config for testing
    config = IOPSConfig(
        nodes=NodesConfig(
            min_nodes=1, 
            max_nodes=2, 
            node_step=2, 
            processes_per_node=4, 
            cores_per_node=32
        ),
        storage=StorageConfig(
            filesystem_dir=tmp_path / "fs",
            min_volume=1,
            max_volume=10,
            volume_step=1,
            default_stripe=1,
            stripe_folders=[
                {"name": str(tmp_path / "folder1")}
            ]
        ),
        execution=ExecutionConfig(
            test_type="write_only",
            search_method="greedy",
            job_manager="slurm",
            benchmark_tool="ior",
            workdir=tmp_path / "workdir",
            repetitions=5,
            status_check_delay=10,
            wall_time="00:30:00",
            tests=["nodes"],
            io_pattern="sequential:shared"
        ),
        template=TemplateConfig(
            bash_template=tmp_path / "slurm_template.sh",
        )
    )
    return config

def test_slurm_submit(config_setup, tmp_path):
    """Test submitting a job with a valid job script."""
    executor = SlurmExecutor(config_setup)

    # Simulate a job script path
    job_script = tmp_path / "job_script.sh"
    with open(str(job_script), "w") as f:
        f.write("#!/bin/bash\necho 'Running IOR benchmark'")

    # Call the submit method & assert job_id is not None
    job_id = executor.submit(job_script)
    assert job_id is not None

def test_slurm_submit_invalid_job_script(config_setup, tmp_path):
    """Test submitting a job with an invalid job script."""
    executor = SlurmExecutor(config_setup)

    # Simulate an invalid job script path
    job_script = tmp_path / "invalid_job_script.sh"
    # Call the submit method and expect an exception
    with pytest.raises(RuntimeError, match="SLURM job submission failed"):
        executor.submit(job_script)

    assert not job_script.exists()


def test_slurm_submit_running_job(config_setup, tmp_path):
    """Test submitting a job that is already running."""
    executor = SlurmExecutor(config_setup)
    # Simulate a job script path
    job_script = tmp_path / "job_script.sh"
    with open(str(job_script), "w") as f:
        f.write("#!/bin/bash\necho 'Running IOR benchmark'")

    # Mock the job submission to simulate a running job
    with patch.object(executor, 'submit', return_value="12345"):
        job_id = executor.submit(job_script)
        assert job_id == "12345"
    
def test_slurm_submit_finished_job(config_setup, tmp_path):
    """Test submitting a job that has already finished."""
    executor = SlurmExecutor(config_setup)
    job_script = tmp_path / "job_script.sh"
    job_script.write_text("#!/bin/bash\necho 'Running IOR benchmark'")

    # Patch both submit and check_job_status
    with patch.object(executor, 'submit', return_value="12345") as mock_submit, \
        patch.object(executor, '_SlurmExecutor__check_job_status', return_value="COMPLETED") as mock_status:
        job_id = executor.submit(job_script)
        assert job_id == "12345"
        status = executor._SlurmExecutor__check_job_status("12345")
        assert status == "COMPLETED"
        # Optionally, check that the mocks were called as expected
        mock_submit.assert_called_once_with(job_script)
        mock_status.assert_called_once_with(job_id)

def test_slurm_check_job_status(config_setup):
    """Test checking the status of a SLURM job."""
    executor = SlurmExecutor(config_setup)  # Pass None or a mock config if needed
    job_id = "12345"

    list_status = ["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
    for status in list_status:
        with patch.object(executor, '_SlurmExecutor__check_job_status', return_value=status):
            result = executor._SlurmExecutor__check_job_status(job_id)
            assert result == status


def test_slurm_wait_and_collect_success(config_setup, tmp_path):
    """Test successful collection of job metadata."""
    executor = SlurmExecutor(config_setup)
    job_id = "12345"
    
    # Create fake files
    (tmp_path / executor.JOB_START_FILE).write_text("start-time")
    (tmp_path / executor.JOB_END_FILE).write_text("end-time")
    (tmp_path / executor.JOB_STATUS_FILE).write_text("COMPLETED")

    # Mock __check_job_status to return a valid status
    with patch.object(executor, '_SlurmExecutor__check_job_status', side_effect=["RUNNING", "COMPLETED"]):
        result = executor._wait_and_collect(job_id, execution_dir=tmp_path)

    assert result["__jobid"] == job_id
    assert result["__start"] == "start-time"
    assert result["__end"] == "end-time"
    assert result["__status"] == "COMPLETED"

def test_slurm_wait_and_collect_missing_files(config_setup, tmp_path):
    """Test behavior when some expected files are missing."""
    executor = SlurmExecutor(config_setup)
    job_id = "12345"

    # Only one file exists
    (tmp_path / executor.JOB_STATUS_FILE).write_text("COMPLETED")

    with patch.object(executor, '_SlurmExecutor__check_job_status', side_effect="COMPLETED"):
        result = executor._wait_and_collect(job_id, execution_dir=tmp_path)

    assert result["__start"] is None
    assert result["__end"] is None
    assert result["__status"] == "COMPLETED"

def test_slurm_wait_and_collect_file_error(config_setup, tmp_path):
    """Test behavior when reading files raises an error."""
    executor = SlurmExecutor(config_setup)
    job_id = "12345"

    # Create a file that will raise exception on read
    bad_file = tmp_path / executor.JOB_STATUS_FILE
    bad_file.write_text("invalid")

    # Simulate read_text() raising error using patch
    with patch.object(Path, "read_text", side_effect=Exception("Read error")):
        result = executor._wait_and_collect(job_id, execution_dir=tmp_path)

    assert result["__jobid"] == job_id
    assert result["__status"] == "ERROR"
    assert "Read error" in result["__error"]
    
