import sys
import pytest
from unittest.mock import patch
from pathlib import Path


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

    # Call the submit method
    job_id = executor.submit(job_script)

    # Assert that job_id is not None after submission
    assert job_id is not None

def test_slurm_executor_wait_and_collect(mocker, tmp_path):
    from iops.controller.executors import SlurmExecutor
    from iops.utils.config_loader import IOPSConfig, StripeFolder, StorageConfig, NodesConfig, ExecutionConfig, TemplateConfig

    # Minimal config
    config = IOPSConfig(
        nodes=NodesConfig(min_nodes=1, max_nodes=1, processes_per_node=1, cores_per_node=1),
        storage=StorageConfig(
            filesystem_dir=tmp_path,
            min_volume=1,
            max_volume=1,
            volume_step=1,
            default_stripe=1,
            stripe_folders=[StripeFolder(name=tmp_path / "folder1", stripe_count=1)]
        ),
        execution=ExecutionConfig(
            test_type="write_only",
            search_method="greedy",
            job_manager="slurm",
            benchmark_tool="ior",
            workdir=tmp_path,
            repetitions=1,
            status_check_delay=1,
            wall_time="00:01:00",
            tests=["nodes"],
            io_pattern="sequential:shared"
        ),
        template=TemplateConfig(
            bash_template=tmp_path / "bash_template.sh"
        )
    )

    executor = SlurmExecutor(config)

    # Mock check_job_status to simulate job completion
    mocker.patch.object(executor, "check_job_status", side_effect=["RUNNING", "COMPLETED"])
    
    # Prepare dummy execution_dir with expected filesiii
    execution_dir = tmp_path / "exec_dir"
    execution_dir.mkdir()
    (execution_dir / "job.start").write_text("2024-01-01T00:00:00")
    (execution_dir / "job.end").write_text("2024-01-01T00:10:00")
    (execution_dir / "job.status").write_text("COMPLETED")

    result = executor.wait_and_collect("12345", execution_dir)

    assert result["job_id"] == "12345"
    assert result["status"] == "COMPLETED"
    assert result["start_time"] == "2024-01-01T00:00:00"
    assert result["end_time"] == "2024-01-01T00:10:00"
    assert result["error"] is None