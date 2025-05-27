import configparser
import pytest
from pathlib import Path
from iops.utils.file_utils import FileUtils


def test_generate_setup_file(tmp_path):
    utils = FileUtils()
    config_path = tmp_path / "test_config.ini"

    utils.generate_iops_config(config_path)

    assert config_path.exists(), "INI file should be created"

    config = configparser.ConfigParser()
    config.read(config_path)

    expected_sections = ["nodes", "storage", "execution", "template"]
    for section in expected_sections:
        assert section in config, f"Section '{section}' should be present"

    assert "min_nodes" in config["nodes"]
    assert "filesystem_dir" in config["storage"]
    assert "job_manager" in config["execution"]
    assert "bash_template" in config["template"]


def test_load_config(tmp_path):
    utils = FileUtils()
    config_path = tmp_path / "test_config.ini"
    utils.generate_iops_config(config_path)

    config = utils.load_iops_config(config_path)

    assert config is not None
    assert hasattr(config, "nodes")
    assert hasattr(config, "storage")
    assert hasattr(config, "execution")
    assert hasattr(config, "template")


def test_load_file_not_found(tmp_path):
    utils = FileUtils()
    invalid_config_path = tmp_path / "missing.ini"

    with pytest.raises(FileNotFoundError):
        utils.load_iops_config(invalid_config_path)


def test_load_parse_error(tmp_path):
    utils = FileUtils()
    broken_config_path = tmp_path / "bad.ini"
    broken_config_path.write_text("[nodes]\nmin_nodes = 1\nmax_nodes = 2\n")  # Missing required sections

    with pytest.raises(configparser.Error):
        utils.load_iops_config(broken_config_path)
