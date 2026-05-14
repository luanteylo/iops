"""Tests for declarative script input files (scripts[].inputs)."""

import copy
import logging
from pathlib import Path

import pytest
import yaml

from conftest import load_config
from iops.config.models import ConfigValidationError
from iops.execution.matrix import build_execution_matrix
from iops.execution.planner import BasePlanner


def _write_config(tmp_path, config_dict, name="config.yaml"):
    cfg_path = tmp_path / name
    with open(cfg_path, "w") as f:
        yaml.dump(config_dict, f)
    return cfg_path


def _add_inputs(config_dict, inputs):
    config_dict = copy.deepcopy(config_dict)
    config_dict["scripts"][0]["inputs"] = inputs
    return config_dict


# ----------------- Parsing & validation ----------------- #


def test_inputs_optional_when_omitted(sample_config_file):
    """Configs without 'inputs' continue to parse with no inputs attached."""
    config = load_config(sample_config_file)
    assert config.scripts[0].inputs == []


def test_inputs_inline_template_parsed(tmp_path, sample_config_dict):
    cfg = _add_inputs(sample_config_dict, [
        {"name": "ior_config", "template": "blockSize = {{ nodes }}m\n"}
    ])
    config_file = _write_config(tmp_path, cfg)
    config = load_config(config_file)

    inputs = config.scripts[0].inputs
    assert len(inputs) == 1
    assert inputs[0].name == "ior_config"
    assert "{{ nodes }}" in inputs[0].template
    assert inputs[0].path is None  # default path applied at render time


def test_inputs_external_file_loaded(tmp_path, sample_config_dict):
    template_file = tmp_path / "ior.tpl"
    template_file.write_text("blockSize = {{ nodes }}m\n")

    cfg = _add_inputs(sample_config_dict, [
        {"name": "ior_config", "file": "ior.tpl"}
    ])
    config_file = _write_config(tmp_path, cfg)
    config = load_config(config_file)

    inputs = config.scripts[0].inputs
    assert len(inputs) == 1
    # `file` is materialized into `template` at load time
    assert inputs[0].template.strip() == "blockSize = {{ nodes }}m"
    assert inputs[0].file is None


def test_inputs_reject_both_template_and_file(tmp_path, sample_config_dict):
    cfg = _add_inputs(sample_config_dict, [
        {"name": "a", "template": "x", "file": "./missing.tpl"}
    ])
    config_file = _write_config(tmp_path, cfg)

    with pytest.raises(ConfigValidationError, match="exactly one of 'template' or 'file'"):
        load_config(config_file)


def test_inputs_reject_neither_template_nor_file(tmp_path, sample_config_dict):
    cfg = _add_inputs(sample_config_dict, [
        {"name": "a", "path": "{{ execution_dir }}/a.conf"}
    ])
    config_file = _write_config(tmp_path, cfg)

    with pytest.raises(ConfigValidationError, match="must specify either 'template'"):
        load_config(config_file)


def test_inputs_reject_duplicate_name(tmp_path, sample_config_dict):
    cfg = _add_inputs(sample_config_dict, [
        {"name": "shared", "template": "a"},
        {"name": "shared", "template": "b"},
    ])
    config_file = _write_config(tmp_path, cfg)

    with pytest.raises(ConfigValidationError, match="duplicate input name 'shared'"):
        load_config(config_file)


def test_inputs_reject_unknown_key(tmp_path, sample_config_dict):
    cfg = _add_inputs(sample_config_dict, [
        {"name": "a", "template": "x", "bogus": "no"}
    ])
    config_file = _write_config(tmp_path, cfg)

    with pytest.raises(ConfigValidationError, match="bogus"):
        load_config(config_file)


def test_inputs_reject_non_identifier_name(tmp_path, sample_config_dict):
    cfg = _add_inputs(sample_config_dict, [
        {"name": "1bad-name", "template": "x"}
    ])
    config_file = _write_config(tmp_path, cfg)

    with pytest.raises(ConfigValidationError, match="not a valid identifier"):
        load_config(config_file)


def test_inputs_reject_bad_jinja_in_template(tmp_path, sample_config_dict):
    cfg = _add_inputs(sample_config_dict, [
        {"name": "broken", "template": "{% if no_endif %}"}
    ])
    config_file = _write_config(tmp_path, cfg)

    with pytest.raises(ConfigValidationError):
        load_config(config_file)


def test_inputs_reject_bad_mode(tmp_path, sample_config_dict):
    cfg = _add_inputs(sample_config_dict, [
        {"name": "a", "template": "x", "mode": "not-octal"}
    ])
    config_file = _write_config(tmp_path, cfg)

    with pytest.raises(ConfigValidationError, match="invalid mode"):
        load_config(config_file)


# ----------------- Rendering ----------------- #


def test_input_files_rendered_with_vars(tmp_path, sample_config_dict):
    cfg = _add_inputs(sample_config_dict, [
        {"name": "ior_config",
         "template": "nodes = {{ nodes }}\nppn = {{ ppn }}\n"}
    ])
    config_file = _write_config(tmp_path, cfg)
    config = load_config(config_file)

    kept, _ = build_execution_matrix(config)
    assert kept, "matrix should produce at least one instance"

    instance = kept[0]
    instance.execution_dir = tmp_path / "execdir"  # path-only render uses this
    files = instance.input_files

    assert len(files) == 1
    entry = files[0]
    assert entry["name"] == "ior_config"
    assert entry["path"].endswith("/ior_config")  # default path
    assert "nodes = " in entry["content"]
    assert "ppn = " in entry["content"]


def test_input_path_template_rendered(tmp_path, sample_config_dict):
    cfg = _add_inputs(sample_config_dict, [
        {"name": "ior_config",
         "path": "{{ execution_dir }}/run_{{ nodes }}.conf",
         "template": "x = {{ nodes }}\n"}
    ])
    config_file = _write_config(tmp_path, cfg)
    config = load_config(config_file)

    kept, _ = build_execution_matrix(config)
    instance = kept[0]
    instance.execution_dir = tmp_path / "execdir"

    files = instance.input_files
    nodes_val = instance.vars["nodes"]
    assert files[0]["path"] == f"{instance.execution_dir}/run_{nodes_val}.conf"


def test_inputs_path_available_in_script(tmp_path, sample_config_dict):
    """{{ inputs.<name>.path }} must resolve when rendering script_template."""
    cfg = copy.deepcopy(sample_config_dict)
    cfg["scripts"][0]["inputs"] = [
        {"name": "ior_config", "template": "x={{ nodes }}\n"}
    ]
    cfg["scripts"][0]["script_template"] = (
        "#!/bin/bash\nior -f {{ inputs.ior_config.path }}\n"
        "echo 'result: 100' > {{ execution_dir }}/output.txt\n"
    )
    config_file = _write_config(tmp_path, cfg)
    config = load_config(config_file)

    kept, _ = build_execution_matrix(config)
    instance = kept[0]
    instance.execution_dir = tmp_path / "execdir"
    script = instance.script_text

    expected_path = f"{instance.execution_dir}/ior_config"
    assert f"ior -f {expected_path}" in script


# ----------------- Disk write ----------------- #


def _make_runner(config):
    """Build a planner; logger is a property on HasLogger so no setup needed."""
    return BasePlanner.build(config)


def test_input_files_written_to_disk(tmp_path, sample_config_dict):
    cfg = _add_inputs(sample_config_dict, [
        {"name": "ior_config",
         "template": "nodes = {{ nodes }}\n",
         "mode": "0644"},
    ])
    config_file = _write_config(tmp_path, cfg)
    config = load_config(config_file)

    kept, _ = build_execution_matrix(config)
    instance = kept[0]
    instance.execution_dir = tmp_path / "exec_0001" / "repetition_001"
    instance.execution_dir.mkdir(parents=True)

    planner = _make_runner(config)
    planner._write_input_files(instance)

    written = instance.execution_dir / "ior_config"
    assert written.is_file()
    content = written.read_text()
    assert content.startswith(f"nodes = {instance.vars['nodes']}")


def test_input_files_skipped_when_none(tmp_path, sample_config_dict):
    """Config without inputs leaves nothing to write; method is a no-op."""
    config_file = _write_config(tmp_path, sample_config_dict)
    config = load_config(config_file)

    kept, _ = build_execution_matrix(config)
    instance = kept[0]
    instance.execution_dir = tmp_path / "exec_0001"
    instance.execution_dir.mkdir(parents=True)

    planner = _make_runner(config)
    planner._write_input_files(instance)  # should not raise

    # Only files the planner might create are not inputs
    assert list(instance.execution_dir.iterdir()) == []
