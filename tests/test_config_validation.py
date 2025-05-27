import pytest
from iops.utils.config_loader import (
    IOPSConfig,
    NodesConfig,
    StorageConfig,
    ExecutionConfig,
    TemplateConfig,
    validate_config,
    ConfigValidationError,
)

# -- Helper: returns a valid config
def make_valid_config():
    return IOPSConfig(
        nodes=NodesConfig(
            min_nodes=2,
            max_nodes=4,
            processes_per_node=8,
            cores_per_node=32,
        ),
        storage=StorageConfig(
            filesystem_dir="/tmp",
            min_volume=1024,
            max_volume=2048,
            volume_step=1024,
            default_stripe=0,
            stripe_folders=["folder1", "folder2"],
        ),
        execution=ExecutionConfig(
            test_type="write_only",
            mode="normal",
            search_method="greedy",
            job_manager="slurm",
            benchmark_tool="ior",
            modules="None",
            workdir="/tmp",
            repetitions=5,
            status_check_delay=10,
            wall_time="00:30:00",
            tests=["filesize", "computing"],
            io_patterns=["sequential:shared"],
            wait_range=[0, 0],
        ),
        template=TemplateConfig(
            bash_template="/template.sh",
            report_template="/report.html",
            ior_2_csv="/ior_2_csv.py",
        )
    )


def test_validate_config_passes_on_valid_config():
    config = make_valid_config()
    # Should not raise anything
    validate_config(config)


def test_validate_config_fails_on_invalid_min_nodes():
    config = make_valid_config()
    config.nodes.min_nodes = -1  # Invalid

    with pytest.raises(ConfigValidationError, match="min_nodes must be greater than 0"):
        validate_config(config)


def test_validate_config_fails_on_non_power_of_two_max_nodes():
    config = make_valid_config()
    config.nodes.max_nodes = 6  # Not a power of 2

    with pytest.raises(ConfigValidationError, match="max_nodes must be a power of 2"):
        validate_config(config)


def test_validate_config_fails_on_empty_stripe_folders():
    config = make_valid_config()
    config.storage.stripe_folders = []

    with pytest.raises(ConfigValidationError, match="At least one stripe folder"):
        validate_config(config)


def test_validate_config_fails_on_invalid_test_type():
    config = make_valid_config()
    config.execution.test_type = "foobar"  # Not allowed

    with pytest.raises(ConfigValidationError, match="Invalid test_type"):
        validate_config(config)
