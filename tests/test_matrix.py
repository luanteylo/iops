"""Tests for execution matrix generation."""

import pytest
from pathlib import Path

from conftest import load_config
from iops.execution.matrix import build_execution_matrix, ExecutionInstance


def test_build_basic_matrix(sample_config_file):
    """Test building a basic execution matrix."""
    config = load_config(sample_config_file)
    matrix = build_execution_matrix(config)

    # Should have 2 tests (nodes=[1,2])
    assert len(matrix) == 2
    assert all(isinstance(test, ExecutionInstance) for test in matrix)


def test_matrix_variable_expansion(sample_config_file):
    """Test that variables are properly expanded in matrix."""
    config = load_config(sample_config_file)
    matrix = build_execution_matrix(config)

    # Check first test
    test1 = matrix[0]
    assert "nodes" in test1.vars
    assert "ppn" in test1.vars
    assert test1.vars["nodes"] in [1, 2]
    assert test1.vars["ppn"] == 4


def test_matrix_derived_variables(sample_config_file):
    """Test that derived variables are computed correctly."""
    config = load_config(sample_config_file)
    matrix = build_execution_matrix(config)

    for test in matrix:
        # total_procs should equal nodes * ppn
        expected = test.vars["nodes"] * test.vars["ppn"]
        assert test.vars["total_procs"] == expected


def test_matrix_execution_ids(sample_config_file):
    """Test that execution IDs are sequential."""
    config = load_config(sample_config_file)
    matrix = build_execution_matrix(config)

    execution_ids = [test.execution_id for test in matrix]
    assert execution_ids == list(range(1, len(matrix) + 1))


def test_matrix_repetitions(sample_config_file):
    """Test that repetitions are set correctly."""
    config = load_config(sample_config_file)
    matrix = build_execution_matrix(config)

    for test in matrix:
        assert test.repetitions == 2


def test_matrix_with_rounds(tmp_path, sample_round_config_dict):
    """Test matrix generation for specific rounds."""
    import yaml
    config_file = tmp_path / "rounds.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_round_config_dict, f)

    config = load_config(config_file)

    # Build matrix for first round (sweep only nodes)
    matrix_round1 = build_execution_matrix(config, round_name="optimize_nodes")

    # Should have 3 tests (nodes=[1,2,4])
    assert len(matrix_round1) == 3

    # All should have ppn=2 (fixed override)
    for test in matrix_round1:
        assert test.vars["ppn"] == 2
        assert test.vars["nodes"] in [1, 2, 4]


def test_matrix_lazy_rendering(sample_config_file):
    """Test that templates are rendered lazily."""
    config = load_config(sample_config_file)
    matrix = build_execution_matrix(config)

    test = matrix[0]

    # Command should render with actual variable values
    command = test.command
    assert str(test.vars["nodes"]) in command
    assert str(test.vars["ppn"]) in command


def test_matrix_script_text_rendering(sample_config_file):
    """Test that script text is rendered correctly."""
    config = load_config(sample_config_file)
    matrix = build_execution_matrix(config)

    test = matrix[0]
    script_text = test.script_text

    # Should contain rendered variable values
    assert f"nodes={test.vars['nodes']}" in script_text
    assert f"ppn={test.vars['ppn']}" in script_text


def test_matrix_cartesian_product(tmp_path, sample_config_dict):
    """Test Cartesian product of multiple sweep variables."""
    # Add another sweep variable
    sample_config_dict["vars"]["threads"] = {
        "type": "int",
        "sweep": {
            "mode": "list",
            "values": [1, 2]
        }
    }

    config_file = tmp_path / "multi_sweep.yaml"
    import yaml
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    matrix = build_execution_matrix(config)

    # Should have 2 nodes * 2 threads = 4 tests
    assert len(matrix) == 4

    # Check all combinations exist
    combinations = {(t.vars["nodes"], t.vars["threads"]) for t in matrix}
    expected = {(1, 1), (1, 2), (2, 1), (2, 2)}
    assert combinations == expected
