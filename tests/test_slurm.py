import sys
import pytest
from unittest.mock import patch
from pathlib import Path


@patch("iops.controller.executors.SlurmExecutor.submit")
def test_slurm_executor_submit(mock_submit, tmp_path):
    from iops.controller.executors import SlurmExecutor
    from iops.utils.config_loader import IOPSConfig

    config = IOPSConfig()
    executor = SlurmExecutor(config)

    # Simulate a job script path
    job_script = tmp_path / "job_script.sh"
    with open(str(job_script), "w") as f:
        f.write("#!/bin/bash\necho 'Running IOR benchmark'")
    # Call the submit method
    job_id = executor.submit(job_script)

    # Check if the mock was called with the correct script
    mock_submit.assert_called_once_with(job_script)
    assert job_id == f"sbatch {job_script}"  # Assuming submit returns the sbatch command



@patch("iops.controller.executors.SlurmExecutor.wait_and_collect")
def test_slurm_executor_wait_and_collect(mock_wait_and_collect, tmp_path):
    #TODO: Implement the test for wait_and_collect
    pass