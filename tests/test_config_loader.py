import pytest
from pathlib import Path
from iops.utils.config_loader import load_config, validate_config, ConfigValidationError

sample_yaml_content = """
nodes:
  min_nodes: 2
  max_nodes: 4
  node_step: 2
  processes_per_node: 8
  cores_per_node: 32

storage:
  filesystem_dir: {fs_dir}
  min_volume: 1024
  max_volume: 2048
  volume_step: 1024
  default_stripe: 0
  stripe_folders:
    - name: folder1
      stripe_count: 1
    - name: folder2
      stripe_count: 2

execution:
  test_type: write_only
  search_method: greedy
  job_manager: local
  benchmark_tool: ior
  workdir: {workdir}
  repetitions: 5
  status_check_delay: 10
  wall_time: "00:30:00"
  tests: [nodes, volume]
  io_pattern: sequential:shared

template:
  bash_template: {bash_template}
"""

@pytest.fixture
def valid_config_file(tmp_path):
    # Setup directory structure
    fs_dir = tmp_path
    (fs_dir / "folder1").mkdir()
    (fs_dir / "folder2").mkdir()
    workdir = fs_dir / "work"
    workdir.mkdir()
    bash_template = fs_dir / "bash_template.sh"
    bash_template.write_text("#!/bin/bash\necho Hello")

    # Format and write config
    yaml_text = sample_yaml_content.format(
        fs_dir=fs_dir,
        workdir=workdir,
        bash_template=bash_template
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml_text)

    # Patch shutil.which to simulate 'ior' in PATH
    import iops.utils.config_loader as cl
    cl.shutil.which = lambda cmd: "/usr/bin/ior" if cmd == "ior" else None

    return config_path


def test_load_config_parses_yaml_correctly(valid_config_file):
    config = load_config(valid_config_file)

    assert config.nodes.min_nodes == 2
    assert config.nodes.max_nodes == 4
    assert config.storage.min_volume == 1024
    assert config.execution.test_type == "write_only"
    assert config.execution.io_pattern == "sequential:shared"
    assert len(config.storage.stripe_folders) == 2
    assert config.template.bash_template.exists()


def test_validate_config_accepts_valid_config(valid_config_file):
    config = load_config(valid_config_file)
    validate_config(config)  # Should not raise


def test_validate_config_raises_on_invalid_nodes(tmp_path):
    config_path = tmp_path / "bad_config.yaml"
    config_path.write_text(sample_yaml_content.format(
        fs_dir=tmp_path,
        workdir=tmp_path,
        bash_template=tmp_path / "bash_template.sh"
    ).replace("min_nodes: 2", "min_nodes: -1"))

    (tmp_path / "folder1").mkdir()
    (tmp_path / "folder2").mkdir()
    (tmp_path / "bash_template.sh").write_text("echo test")

    import iops.utils.config_loader as cl
    cl.shutil.which = lambda cmd: "/usr/bin/ior"

    config = load_config(config_path)
    with pytest.raises(ConfigValidationError, match="min_nodes must be greater than 0"):
        validate_config(config)


def test_validate_config_raises_on_invalid_test_type(tmp_path):
    config_path = tmp_path / "bad_config.yaml"
    config_text = sample_yaml_content.replace("test_type: write_only", "test_type: invalid_type").format(
        fs_dir=tmp_path,
        workdir=tmp_path,
        bash_template=tmp_path / "bash_template.sh"
    )
    config_path.write_text(config_text)
    (tmp_path / "folder1").mkdir()
    (tmp_path / "folder2").mkdir()
    (tmp_path / "bash_template.sh").write_text("echo test")

    import iops.utils.config_loader as cl
    cl.shutil.which = lambda cmd: "/usr/bin/ior"

    config = load_config(config_path)
    with pytest.raises(ConfigValidationError, match="Invalid test_type"):
        validate_config(config)
