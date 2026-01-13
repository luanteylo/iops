"""Tests for configuration loading and validation."""

import pytest
import yaml
from pathlib import Path

from conftest import load_config
from iops.config.models import GenericBenchmarkConfig, ConfigValidationError


def test_load_valid_config(sample_config_file):
    """Test loading a valid configuration file."""
    config = load_config(sample_config_file)

    assert isinstance(config, GenericBenchmarkConfig)
    assert config.benchmark.name == "Test Benchmark"
    assert config.benchmark.repetitions == 2
    assert len(config.vars) == 3
    assert "nodes" in config.vars
    assert "ppn" in config.vars
    assert "total_procs" in config.vars


def test_config_missing_file():
    """Test loading non-existent config file."""
    with pytest.raises(ConfigValidationError, match="not found"):
        load_config(Path("nonexistent.yaml"))


def test_config_invalid_yaml(tmp_path):
    """Test loading invalid YAML."""
    invalid_file = tmp_path / "invalid.yaml"
    invalid_file.write_text("{ invalid yaml content [")

    with pytest.raises(ConfigValidationError, match="YAML syntax error"):
        load_config(invalid_file)


def test_config_missing_benchmark_section(tmp_path):
    """Test config without benchmark section."""
    config_file = tmp_path / "no_benchmark.yaml"
    with open(config_file, "w") as f:
        yaml.dump({"vars": {}, "scripts": [], "output": {}}, f)

    with pytest.raises((Exception, KeyError)):
        load_config(config_file)


def test_config_missing_required_fields(tmp_path, sample_config_dict):
    """Test config with missing required fields."""
    config_file = tmp_path / "incomplete.yaml"

    # Remove required field
    del sample_config_dict["benchmark"]["name"]

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises((Exception, KeyError, TypeError)):
        load_config(config_file)


def test_config_derived_variables(sample_config_file):
    """Test that derived variables are properly configured."""
    config = load_config(sample_config_file)

    # Check that total_procs is a derived variable
    total_procs = config.vars["total_procs"]
    assert total_procs.expr is not None
    assert "nodes" in total_procs.expr
    assert "ppn" in total_procs.expr


def test_config_sweep_variables(sample_config_file):
    """Test that sweep variables are properly configured."""
    config = load_config(sample_config_file)

    nodes_var = config.vars["nodes"]
    assert nodes_var.sweep is not None
    assert nodes_var.sweep.mode == "list"
    assert nodes_var.sweep.values == [1, 2]


def test_config_parser_validation(sample_config_file):
    """Test that parser script is validated."""
    config = load_config(sample_config_file)

    script = config.scripts[0]
    assert script.parser is not None
    assert "parse" in script.parser.parser_script
    assert len(script.parser.metrics) == 1
    assert script.parser.metrics[0].name == "result"


def test_config_output_settings(sample_config_file):
    """Test output configuration."""
    config = load_config(sample_config_file)

    assert config.output.sink.type == "csv"
    assert config.output.sink.mode == "append"
    assert "workdir" in config.output.sink.path


def test_config_report_vars_valid(tmp_path, sample_config_dict):
    """Test that valid report_vars is accepted."""
    from iops.config.models import ConfigValidationError

    config_file = tmp_path / "valid_report_vars.yaml"

    # Add valid report_vars (using existing variables)
    sample_config_dict["benchmark"]["report_vars"] = ["nodes", "ppn"]

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    assert config.benchmark.report_vars == ["nodes", "ppn"]


def test_config_report_vars_invalid(tmp_path, sample_config_dict):
    """Test that invalid report_vars raises an error."""
    from iops.config.models import ConfigValidationError

    config_file = tmp_path / "invalid_report_vars.yaml"

    # Add invalid report_vars (non-existent variable)
    sample_config_dict["benchmark"]["report_vars"] = ["nodes", "nonexistent_var"]

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(config_file)

    assert "report_vars" in str(exc_info.value)
    assert "nonexistent_var" in str(exc_info.value)


def test_config_create_folders_upfront_default(sample_config_file):
    """Test that create_folders_upfront defaults to False."""
    config = load_config(sample_config_file)
    assert config.benchmark.create_folders_upfront is False


def test_config_create_folders_upfront_enabled(tmp_path, sample_config_dict):
    """Test that create_folders_upfront can be enabled via YAML."""
    config_file = tmp_path / "upfront.yaml"

    # Enable create_folders_upfront
    sample_config_dict["benchmark"]["create_folders_upfront"] = True

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    assert config.benchmark.create_folders_upfront is True


def test_config_track_executions_default(sample_config_file):
    """Test that track_executions defaults to True."""
    config = load_config(sample_config_file)
    assert config.benchmark.track_executions is True


def test_config_track_executions_disabled(tmp_path, sample_config_dict):
    """Test that track_executions can be disabled via YAML."""
    config_file = tmp_path / "no_track.yaml"

    # Disable track_executions
    sample_config_dict["benchmark"]["track_executions"] = False

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    assert config.benchmark.track_executions is False
