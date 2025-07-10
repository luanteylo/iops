import sys
import pytest
from unittest.mock import patch

from iops.main import main
from iops.utils.config_loader import ConfigValidationError

import yaml

@pytest.fixture
def config_setup(tmp_path):
    """Creates a valid config file and required folders."""
    cfg_path = tmp_path / "iops_config.yaml"
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (tmp_path / "folder1").mkdir()
    (tmp_path / "folder2").mkdir()
    bash_template = tmp_path / "bash_template.sh"
    bash_template.write_text("#!/bin/bash\necho run")

    import yaml
    cfg = {
        "nodes": {"min_nodes": 2, "max_nodes": 4, "node_step": 2, "processes_per_node": 8, "cores_per_node": 32},
        "storage": {
            "filesystem_dir": str(tmp_path),
            "min_volume": 1024, "max_volume": 2048, "volume_step": 1024,
            "default_stripe": 0,
            "stripe_folders": [{"name": "folder1", "stripe_count": 1}, {"name": "folder2", "stripe_count": 2}]
        },
        "execution": {
            "test_type": "write_only",
            "search_method": "greedy",
            "job_manager": "local",
            "benchmark_tool": "ior",
            "workdir": str(workdir),
            "repetitions": 5,
            "status_check_delay": 10,
            "wall_time": "00:30:00",
            "tests": ["nodes", "volume"],
            "io_pattern": "sequential:shared"
        },
        "template": {"bash_template": str(bash_template)}
    }

    with open(cfg_path, "w") as f:
        yaml.dump(cfg, f)

    import iops.utils.config_loader as cl
    cl.shutil.which = lambda cmd: "/usr/bin/ior"

    return cfg_path


def test_main_generates_setup(tmp_path):
    """Test --generate_setup creates a YAML file."""
    target_path = tmp_path / "my_setup.yaml"
    test_args = ["main", "--generate_setup", str(target_path)]

    with patch.object(sys, "argv", test_args):
        main()

    assert target_path.exists()
    assert "nodes" in target_path.read_text()


def test_main_validates_config(config_setup):
    """Test --check_setup runs validation only."""
    test_args = ["main", str(config_setup), "--check_setup"]

    with patch.object(sys, "argv", test_args):
        main()  # Should run without error


def test_main_runs_execution(config_setup, mocker):
    """Test normal execution calls runner.run()."""
    mock_run = mocker.patch("iops.main.IOPSRunner.run")

    test_args = ["main", str(config_setup)]
    with patch.object(sys, "argv", test_args):
        main()

    mock_run.assert_called_once()


def test_main_missing_file():
    """Test behavior when setup file is missing."""
    test_args = ["main", "nonexistent.yaml"]

    with patch.object(sys, "argv", test_args):
        with pytest.raises(FileNotFoundError):
            main()


def test_main_invalid_config(tmp_path):
    """Test config validation failure with invalid nodes."""
    cfg_path = tmp_path / "invalid.yaml"
    (tmp_path / "folder1").mkdir()
    (tmp_path / "folder2").mkdir()
    (tmp_path / "workdir").mkdir()
    (tmp_path / "bash_template.sh").write_text("bash")

    import yaml
    yaml.dump({
        "nodes": {"min_nodes": -1, "max_nodes": 2, "node_step": 1, "processes_per_node": 4, "cores_per_node": 32},
        "storage": {
            "filesystem_dir": str(tmp_path),
            "min_volume": 1024, "max_volume": 2048, "volume_step": 1024,
            "default_stripe": 0,
            "stripe_folders": [{"name": "folder1", "stripe_count": 1}]
        },
        "execution": {
            "test_type": "write_only", "search_method": "greedy", "job_manager": "local",
            "benchmark_tool": "ior", "workdir": str(tmp_path / "workdir"),
            "repetitions": 5, "status_check_delay": 10, "wall_time": "00:30:00",
            "tests": ["nodes"], "io_pattern": "sequential:shared"
        },
        "template": {"bash_template": str(tmp_path / "bash_template.sh")}
    }, open(cfg_path, "w"))

    import iops.utils.config_loader as cl
    cl.shutil.which = lambda x: "/usr/bin/ior"

    test_args = ["main", str(cfg_path)]

    with patch.object(sys, "argv", test_args):
        main()  # Should print error but not crash


def test_main_invalid_config_verbose(tmp_path):
    """Test config validation failure with --verbose enabled raises exception."""
    cfg_path = tmp_path / "invalid_verbose.yaml"
    (tmp_path / "folder1").mkdir()
    (tmp_path / "bash_template.sh").write_text("#!")

    yaml.dump({
        "nodes": {"min_nodes": -1, "max_nodes": 2, "node_step": 1, "processes_per_node": 4, "cores_per_node": 32},
        "storage": {
            "filesystem_dir": str(tmp_path),
            "min_volume": 1024, "max_volume": 2048, "volume_step": 1024,
            "default_stripe": 0,
            "stripe_folders": [{"name": "folder1", "stripe_count": 1}]
        },
        "execution": {
            "test_type": "write_only", "search_method": "greedy", "job_manager": "local",
            "benchmark_tool": "ior", "workdir": str(tmp_path),
            "repetitions": 5, "status_check_delay": 10, "wall_time": "00:30:00",
            "tests": ["nodes"], "io_pattern": "sequential:shared"
        },
        "template": {"bash_template": str(tmp_path / "bash_template.sh")}
    }, open(cfg_path, "w"))

    import iops.utils.config_loader as cl
    cl.shutil.which = lambda x: "/usr/bin/ior"

    test_args = ["main", str(cfg_path), "--verbose"]

    with patch.object(sys, "argv", test_args):
        with pytest.raises(ConfigValidationError):
            main()
