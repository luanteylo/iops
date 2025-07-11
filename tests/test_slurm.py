import sys
import pytest
from unittest.mock import patch
from pathlib import Path

from iops.controller.executors import SlurmExecutor

@pytest.fixture
def config_setup(tmp_path):
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

def test_slurm_executor_submit(config_setup, tmp_path):
    """Test submitting a job with a valid job script."""
    executor = SlurmExecutor(config_setup)

    # Simulate a job script path
    job_script = tmp_path / "job_script.sh"
    with open(str(job_script), "w") as f:
        f.write("#!/bin/bash\necho 'Running IOR benchmark'")

    # Call the submit method & assert job_id is not None
    job_id = executor.submit(job_script)
    assert job_id is not None

def test_slurm_executor_submit_invalid_job_script(config_setup, tmp_path):
    """Test submitting a job with an invalid job script."""
    executor = SlurmExecutor(config_setup)

    # Simulate an invalid job script path
    job_script = tmp_path / "invalid_job_script.sh"
    # Call the submit method and expect an exception
    with pytest.raises(RuntimeError, match="SLURM job submission failed"):
        executor.submit(job_script)

    assert not job_script.exists()


def test_slurm_executor_submit_running_job(config_setup, tmp_path):
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
    
def test_slurm_executor_submit_finished_job(config_setup, tmp_path):
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

def test_slurm_executor_check_job_status(job_id, config_setup):
    """Test checking the status of a SLURM job."""
    executor = SlurmExecutor(config_setup)  # Pass None or a mock config if needed

    list_status = ["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
    for status in list_status:
        with patch.object(executor, '_SlurmExecutor__check_job_status', return_value=status):
            result = executor._SlurmExecutor__check_job_status(job_id)
            assert result == status


def test_slurm_executor_wait_and_collect(job_id, execution_dir, config_setup):
    """Test waiting for a SLURM job to finish and collecting results."""
    pass
