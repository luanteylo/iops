import pytest
from pathlib import Path
from iops.utils.file_utils import FileUtils
from iops.utils.config_loader import IOPSConfig, ConfigValidationError
import shutil
import yaml


@pytest.fixture
def file_utils():
    return FileUtils()


def test_generate_iops_config_creates_yaml_with_expected_keys(tmp_path, file_utils):
    config_path = tmp_path / "test_config"
    file_utils.generate_iops_config(config_path)

    # The file should exist and have .yaml suffix
    yaml_file = config_path.with_suffix(".yaml")
    assert yaml_file.exists()

    # Load and inspect keys
    with open(yaml_file) as f:
        data = yaml.safe_load(f)

    assert "nodes" in data
    assert "storage" in data
    assert "execution" in data
    assert "template" in data
    assert isinstance(data["nodes"]["min_nodes"], int)
    assert data["execution"]["job_manager"] == "slurm"


def test_load_iops_config_success(file_utils, tmp_path):
    config_path = tmp_path / "config.yaml"
    (tmp_path / "folder1").mkdir()
    (tmp_path / "folder2").mkdir()
    (tmp_path / "workdir").mkdir()
    (tmp_path / "bash_template.sh").write_text("#!/bin/bash")

    config_data = {
        "nodes": {
            "min_nodes": 2,
            "max_nodes": 4,
            "node_step": 2,
            "processes_per_node": 8,
            "cores_per_node": 32
        },
        "storage": {
            "filesystem_dir": str(tmp_path),
            "min_volume": 1024,
            "max_volume": 2048,
            "volume_step": 1024,
            "default_stripe": 0,
            "stripe_folders": [
                {"name": "folder1", "stripe_count": 1},
                {"name": "folder2", "stripe_count": 2}
            ]
        },
        "execution": {
            "test_type": "write_only",
            "search_method": "greedy",
            "job_manager": "local",
            "benchmark_tool": "ior",
            "workdir": str(tmp_path / "workdir"),
            "repetitions": 5,
            "status_check_delay": 10,
            "wall_time": "00:30:00",
            "tests": ["nodes", "volume"],
            "io_pattern": "sequential:shared"
        },
        "template": {
            "bash_template": str(tmp_path / "bash_template.sh")
        }
    }

    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    # Patch which
    import iops.utils.config_loader as cl
    cl.shutil.which = lambda x: "/usr/bin/ior"

    config = file_utils.load_iops_config(config_path)
    assert isinstance(config, IOPSConfig)
    assert config.execution.test_type == "write_only"


def test_validate_iops_config_fails_on_invalid_value(file_utils, tmp_path):
    config_path = tmp_path / "bad_config.yaml"
    (tmp_path / "folder1").mkdir()
    (tmp_path / "folder2").mkdir()
    (tmp_path / "workdir").mkdir()
    (tmp_path / "bash_template.sh").write_text("#!/bin/bash")

    config_data = {
        "nodes": {
            "min_nodes": -1,  # Invalid
            "max_nodes": 4,
            "node_step": 2,
            "processes_per_node": 8,
            "cores_per_node": 32
        },
        "storage": {
            "filesystem_dir": str(tmp_path),
            "min_volume": 1024,
            "max_volume": 2048,
            "volume_step": 1024,
            "default_stripe": 0,
            "stripe_folders": [
                {"name": "folder1", "stripe_count": 1},
                {"name": "folder2", "stripe_count": 2}
            ]
        },
        "execution": {
            "test_type": "write_only",
            "search_method": "greedy",
            "job_manager": "local",
            "benchmark_tool": "ior",
            "workdir": str(tmp_path / "workdir"),
            "repetitions": 5,
            "status_check_delay": 10,
            "wall_time": "00:30:00",
            "tests": ["nodes", "volume"],
            "io_pattern": "sequential:shared"
        },
        "template": {
            "bash_template": str(tmp_path / "bash_template.sh")
        }
    }

    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    import iops.utils.config_loader as cl
    cl.shutil.which = lambda x: "/usr/bin/ior"

    config = file_utils.load_iops_config(config_path)
    with pytest.raises(ConfigValidationError, match="min_nodes must be greater than 0"):
        file_utils.validate_iops_config(config)


def test_create_workdir_creates_execution_folder(file_utils, tmp_path):
    config_path = tmp_path / "test_config.yaml"
    workdir = tmp_path / "work"
    workdir.mkdir()
    (tmp_path / "folder1").mkdir()
    (tmp_path / "folder2").mkdir()
    (tmp_path / "bash_template.sh").write_text("# template")

    config_data = {
        "nodes": {"min_nodes": 2, "max_nodes": 4, "node_step": 2, "processes_per_node": 8, "cores_per_node": 32},
        "storage": {
            "filesystem_dir": str(tmp_path),
            "min_volume": 1024, "max_volume": 2048, "volume_step": 1024, "default_stripe": 0,
            "stripe_folders": [{"name": "folder1", "stripe_count": 1}, {"name": "folder2", "stripe_count": 2}]
        },
        "execution": {
            "test_type": "write_only", "search_method": "greedy", "job_manager": "local",
            "benchmark_tool": "ior", "workdir": str(workdir), "repetitions": 5,
            "status_check_delay": 10, "wall_time": "00:30:00",
            "tests": ["nodes", "volume"], "io_pattern": "sequential:shared"
        },
        "template": {"bash_template": str(tmp_path / "bash_template.sh")}
    }

    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    import iops.utils.config_loader as cl
    cl.shutil.which = lambda x: "/usr/bin/ior"

    config = file_utils.load_iops_config(config_path)
    file_utils.validate_iops_config(config)
    file_utils.create_workdir(config)

    assert config.execution.workdir.exists()
    assert "execution_" in config.execution.workdir.name
