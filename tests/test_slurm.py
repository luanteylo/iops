import sys
import pytest
from unittest.mock import patch
from pathlib import Path



@patch("iops.controller.executors.SlurmExecutor.submit")
def test_slurm_executor_submit(mock_submit, tmp_path):
    from iops.controller.executors import SlurmExecutor
    from iops.utils.config_loader import IOPSConfig, StripeFolder, StorageConfig, NodesConfig, ExecutionConfig, TemplateConfig

    config = IOPSConfig(
        nodes=NodesConfig(min_nodes=2, max_nodes=4, processes_per_node=4, cores_per_node=32),
        storage=StorageConfig(
            filesystem_dir=tmp_path / "fs",
            min_volume=1,
            max_volume=10,
            volume_step=1,
            default_stripe=1,
            stripe_folders=[StripeFolder(name=tmp_path / "folder1", stripe_count=1)]
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
            bash_template=tmp_path / "bash_template.sh" 
        )
    )
    
    executor = SlurmExecutor(config)

    # Simulate a job script path
    job_script = tmp_path / "job_script.sh"
    with open(str(job_script), "w") as f:
        f.write("#!/bin/bash\necho 'Running IOR benchmark'")
    mock_submit.return_value = "12345"
    # Call the submit method
    job_id = executor.submit(job_script)

    # Check if the mock was called with the correct script
    mock_submit.assert_called_once_with(job_script)
    assert job_id is not None

# @patch("iops.controller.executors.SlurmExecutor.submit")
def test_slurm_executor_submit(tmp_path):
    from iops.controller.executors import SlurmExecutor
    from iops.utils.config_loader import IOPSConfig, StripeFolder, StorageConfig, NodesConfig, ExecutionConfig, TemplateConfig

    config = IOPSConfig(
        nodes=NodesConfig(min_nodes=2, max_nodes=4, processes_per_node=4, cores_per_node=32),
        storage=StorageConfig(
            filesystem_dir=tmp_path / "fs",
            min_volume=1,
            max_volume=10,
            volume_step=1,
            default_stripe=1,
            stripe_folders=[StripeFolder(name=tmp_path / "folder1", stripe_count=1)]
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
            bash_template=tmp_path / "bash_template.sh" 
        )
    )
    
    executor = SlurmExecutor(config)

    # Simulate a job script path
    job_script = tmp_path / "job_script.sh"
    with open(str(job_script), "w") as f:
        f.write("#!/bin/bash\necho 'Running IOR benchmark'")
    # mock_submit.return_value = "12345"
    # Call the submit method
    job_id = executor.submit(job_script)

    # Check if the mock was called with the correct script
    # mock_submit.assert_called_once_with(job_script)
    assert job_id is not None



@patch("iops.controller.executors.SlurmExecutor.wait_and_collect")
def test_slurm_executor_wait_and_collect(mock_wait_and_collect, tmp_path):
    #TODO: Implement the test for wait_and_collect
    pass