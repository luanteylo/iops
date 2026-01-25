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


# ============== Unknown Key Validation Tests ==============


def test_unknown_top_level_key(tmp_path, sample_config_dict):
    """Unknown top-level keys should raise validation error."""
    sample_config_dict["executor_options"] = {"submit": "sbatch"}  # Wrong key
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError, match="Unknown key 'executor_options'"):
        load_config(config_file)


def test_unknown_benchmark_key_with_suggestion(tmp_path, sample_config_dict):
    """Typos in benchmark keys should suggest correct key."""
    sample_config_dict["benchmark"]["slurm_optionz"] = {}  # Typo
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError, match="did you mean 'slurm_options'"):
        load_config(config_file)


def test_unknown_benchmark_key_no_suggestion(tmp_path, sample_config_dict):
    """Completely unknown keys should list allowed keys."""
    sample_config_dict["benchmark"]["foobar_xyz"] = "test"  # No close match
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError, match="Allowed keys:"):
        load_config(config_file)


def test_unknown_slurm_options_key(tmp_path, sample_config_dict):
    """Unknown keys in slurm_options should be rejected."""
    sample_config_dict["benchmark"]["slurm_options"] = {
        "submit_command": "sbatch"  # Wrong key (should be under commands)
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError, match="Unknown key 'benchmark.slurm_options.submit_command'"):
        load_config(config_file)


def test_unknown_slurm_commands_key(tmp_path, sample_config_dict):
    """Unknown keys in slurm_options.commands should be rejected."""
    sample_config_dict["benchmark"]["slurm_options"] = {
        "commands": {"submit_cmd": "sbatch"}  # Wrong key (should be 'submit')
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError, match="did you mean 'submit'"):
        load_config(config_file)


def test_unknown_var_key(tmp_path, sample_config_dict):
    """Unknown keys in variable definitions should be rejected."""
    sample_config_dict["vars"]["nodes"]["value"] = [1, 2]  # Wrong key (should be in sweep)
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError, match="Unknown key 'vars.nodes.value'"):
        load_config(config_file)


def test_unknown_sweep_key(tmp_path, sample_config_dict):
    """Unknown keys in sweep config should be rejected."""
    sample_config_dict["vars"]["nodes"]["sweep"]["vals"] = [1, 2]  # Typo (should be 'values')
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError, match="did you mean 'values'"):
        load_config(config_file)


def test_unknown_command_key(tmp_path, sample_config_dict):
    """Unknown keys in command section should be rejected."""
    sample_config_dict["command"]["templates"] = "echo test"  # Typo
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError, match="did you mean 'template'"):
        load_config(config_file)


def test_unknown_script_key(tmp_path, sample_config_dict):
    """Unknown keys in script definitions should be rejected."""
    sample_config_dict["scripts"][0]["script_templates"] = "echo test"  # Typo
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError, match="did you mean 'script_template'"):
        load_config(config_file)


def test_unknown_parser_key(tmp_path, sample_config_dict):
    """Unknown keys in parser config should be rejected."""
    sample_config_dict["scripts"][0]["parser"]["parser_scripts"] = "def parse(f): pass"  # Typo
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError, match="did you mean 'parser_script'"):
        load_config(config_file)


def test_unknown_output_sink_key(tmp_path, sample_config_dict):
    """Unknown keys in output.sink should be rejected."""
    sample_config_dict["output"]["sink"]["file_type"] = "csv"  # Wrong key
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError, match="Unknown key 'output.sink.file_type'"):
        load_config(config_file)


def test_unknown_output_key(tmp_path, sample_config_dict):
    """Unknown keys in output section should be rejected."""
    sample_config_dict["output"]["sinks"] = {}  # Typo
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError, match="did you mean 'sink'"):
        load_config(config_file)


def test_unknown_constraint_key(tmp_path, sample_config_dict):
    """Unknown keys in constraint definitions should be rejected."""
    sample_config_dict["constraints"] = [
        {"name": "test", "rule": "nodes > 0", "violation_polcy": "skip"}  # Typo
    ]
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError, match="did you mean 'violation_policy'"):
        load_config(config_file)


def test_valid_config_passes_key_validation(sample_config_file):
    """Ensure valid configs still load successfully after adding key validation."""
    config = load_config(sample_config_file)
    assert config is not None
    assert config.benchmark.name == "Test Benchmark"


def test_deprecated_executor_options_backwards_compat(tmp_path, sample_config_dict):
    """Using deprecated executor_options should work but emit warning."""
    sample_config_dict["benchmark"]["executor_options"] = {
        "poll_interval": 60
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        config = load_config(config_file)

        # Should have emitted a deprecation warning
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "executor_options" in str(w[0].message)
        assert "slurm_options" in str(w[0].message)

    # Config should still load correctly with the value
    assert config.benchmark.slurm_options is not None
    assert config.benchmark.slurm_options.poll_interval == 60


# ============================================================================
# Script file path validation tests
# ============================================================================

def test_script_template_file_not_found(tmp_path, sample_config_dict):
    """Test that missing script_template file raises error."""
    sample_config_dict["scripts"][0]["script_template"] = "./missing_script.sh"
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError, match="file was not found"):
        load_config(config_file)


def test_post_script_file_not_found(tmp_path, sample_config_dict):
    """Test that missing post.script file raises error."""
    sample_config_dict["scripts"][0]["post"] = {"script": "./missing_post.sh"}
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError, match="file was not found"):
        load_config(config_file)


def test_parser_script_file_not_found(tmp_path, sample_config_dict):
    """Test that missing parser_script file raises error."""
    sample_config_dict["scripts"][0]["parser"]["parser_script"] = "./missing_parser.py"
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError, match="file was not found"):
        load_config(config_file)


def test_script_template_file_loads_successfully(tmp_path, sample_config_dict):
    """Test that existing script_template file loads correctly."""
    script_file = tmp_path / "my_script.sh"
    script_file.write_text("#!/bin/bash\necho 'Hello from file'\n")

    sample_config_dict["scripts"][0]["script_template"] = str(script_file)
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    assert "Hello from file" in config.scripts[0].script_template


def test_post_script_file_loads_successfully(tmp_path, sample_config_dict):
    """Test that existing post.script file loads correctly."""
    post_file = tmp_path / "cleanup.sh"
    post_file.write_text("#!/bin/bash\nrm -rf /tmp/test\n")

    sample_config_dict["scripts"][0]["post"] = {"script": str(post_file)}
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    assert "rm -rf /tmp/test" in config.scripts[0].post.script


def test_parser_script_file_loads_successfully(tmp_path, sample_config_dict):
    """Test that existing parser_script file loads correctly."""
    parser_file = tmp_path / "parser.py"
    parser_file.write_text("def parse(file_path):\n    return {'metric': 42.0}\n")

    sample_config_dict["scripts"][0]["parser"]["parser_script"] = str(parser_file)
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    assert "return {'metric': 42.0}" in config.scripts[0].parser.parser_script


def test_inline_script_not_mistaken_for_file(tmp_path, sample_config_dict):
    """Test that inline scripts with multiple lines are not treated as file paths."""
    # Multi-line inline script should work even if first line looks like a path
    sample_config_dict["scripts"][0]["script_template"] = "#!/bin/bash\necho 'inline script'"
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    assert "inline script" in config.scripts[0].script_template


def test_script_with_jinja_not_mistaken_for_file(tmp_path, sample_config_dict):
    """Test that scripts with Jinja2 templates are not treated as file paths."""
    # Single line with many braces should be treated as inline content
    sample_config_dict["scripts"][0]["script_template"] = "echo {{ var1 }} {{ var2 }} {{ var3 }}"
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    assert "{{ var1 }}" in config.scripts[0].script_template
