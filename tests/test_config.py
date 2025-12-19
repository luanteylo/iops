"""Tests for configuration loading and validation."""

import pytest
import yaml
from pathlib import Path

from conftest import load_config
from iops.config.models import GenericBenchmarkConfig


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
    with pytest.raises(FileNotFoundError):
        load_config(Path("nonexistent.yaml"))


def test_config_invalid_yaml(tmp_path):
    """Test loading invalid YAML."""
    invalid_file = tmp_path / "invalid.yaml"
    invalid_file.write_text("{ invalid yaml content [")

    with pytest.raises(yaml.YAMLError):
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


def test_config_with_rounds(tmp_path, sample_round_config_dict):
    """Test loading config with multiple rounds."""
    config_file = tmp_path / "rounds_config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_round_config_dict, f)

    config = load_config(config_file)

    assert config.rounds is not None
    assert len(config.rounds) == 2
    assert config.rounds[0].name == "optimize_nodes"
    assert config.rounds[0].sweep_vars == ["nodes"]
    assert config.rounds[0].fixed_overrides == {"ppn": 2}
    assert config.rounds[0].search.metric == "bandwidth"
    assert config.rounds[0].search.objective == "max"


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
