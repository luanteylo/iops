"""Tests for execution matrix generation."""

import pytest
from pathlib import Path

from conftest import load_config
from iops.execution.matrix import build_execution_matrix, ExecutionInstance


def test_build_basic_matrix(sample_config_file):
    """Test building a basic execution matrix."""
    config = load_config(sample_config_file)
    matrix, skipped = build_execution_matrix(config)

    # Should have 2 tests (nodes=[1,2])
    assert len(matrix) == 2
    assert len(skipped) == 0  # No constraints, so no skipped
    assert all(isinstance(test, ExecutionInstance) for test in matrix)


def test_matrix_variable_expansion(sample_config_file):
    """Test that variables are properly expanded in matrix."""
    config = load_config(sample_config_file)
    matrix, _ = build_execution_matrix(config)

    # Check first test
    test1 = matrix[0]
    assert "nodes" in test1.vars
    assert "ppn" in test1.vars
    assert test1.vars["nodes"] in [1, 2]
    assert test1.vars["ppn"] == 4


def test_matrix_derived_variables(sample_config_file):
    """Test that derived variables are computed correctly."""
    config = load_config(sample_config_file)
    matrix, _ = build_execution_matrix(config)

    for test in matrix:
        # total_procs should equal nodes * ppn
        expected = test.vars["nodes"] * test.vars["ppn"]
        assert test.vars["total_procs"] == expected


def test_matrix_execution_ids(sample_config_file):
    """Test that execution IDs are sequential."""
    config = load_config(sample_config_file)
    matrix, _ = build_execution_matrix(config)

    execution_ids = [test.execution_id for test in matrix]
    assert execution_ids == list(range(1, len(matrix) + 1))


def test_matrix_repetitions(sample_config_file):
    """Test that repetitions are set correctly."""
    config = load_config(sample_config_file)
    matrix, _ = build_execution_matrix(config)

    for test in matrix:
        assert test.repetitions == 2


def test_matrix_lazy_rendering(sample_config_file):
    """Test that templates are rendered lazily."""
    config = load_config(sample_config_file)
    matrix, _ = build_execution_matrix(config)

    test = matrix[0]

    # Command should render with actual variable values
    command = test.command
    assert str(test.vars["nodes"]) in command
    assert str(test.vars["ppn"]) in command


def test_matrix_script_text_rendering(sample_config_file):
    """Test that script text is rendered correctly."""
    config = load_config(sample_config_file)
    matrix, _ = build_execution_matrix(config)

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
    matrix, _ = build_execution_matrix(config)

    # Should have 2 nodes * 2 threads = 4 tests
    assert len(matrix) == 4

    # Check all combinations exist
    combinations = {(t.vars["nodes"], t.vars["threads"]) for t in matrix}
    expected = {(1, 1), (1, 2), (2, 1), (2, 2)}
    assert combinations == expected


def test_matrix_exhaustive_vars(tmp_path, sample_config_dict):
    """Test exhaustive_vars feature for full expansion."""
    # Add exhaustive_vars to benchmark config
    sample_config_dict["benchmark"]["exhaustive_vars"] = ["ppn"]

    # Add another variable to sweep
    sample_config_dict["vars"]["block_size"] = {
        "type": "int",
        "sweep": {
            "mode": "list",
            "values": [4, 16]
        }
    }

    # ppn becomes exhaustive (will be fully expanded for each search point)
    # Remove expr first (can't have both sweep and expr)
    sample_config_dict["vars"]["ppn"] = {
        "type": "int",
        "sweep": {
            "mode": "list",
            "values": [1, 2, 4]
        }
    }

    config_file = tmp_path / "exhaustive.yaml"
    import yaml
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    matrix, _ = build_execution_matrix(config)

    # Should have (2 nodes * 2 block_size) * 3 ppn = 12 tests
    # Search space: nodes × block_size = 4 points
    # Exhaustive space: ppn = 3 values
    # Total: 4 * 3 = 12
    assert len(matrix) == 12

    # Check that for each (nodes, block_size) combination, all ppn values exist
    search_points = {(t.vars["nodes"], t.vars["block_size"]) for t in matrix}
    assert len(search_points) == 4  # 2 nodes * 2 block_size

    for search_point in search_points:
        nodes, block_size = search_point
        # Filter tests for this search point
        tests_at_point = [t for t in matrix
                         if t.vars["nodes"] == nodes and t.vars["block_size"] == block_size]

        # Should have all 3 ppn values
        ppn_values = {t.vars["ppn"] for t in tests_at_point}
        assert ppn_values == {1, 2, 4}, f"Missing ppn values for {search_point}"


def test_matrix_exhaustive_vars_validation(tmp_path, sample_config_dict):
    """Test that exhaustive_vars validation catches errors."""
    from iops.config.models import ConfigValidationError

    # Add a non-existent variable to exhaustive_vars
    sample_config_dict["benchmark"]["exhaustive_vars"] = ["nonexistent_var"]

    config_file = tmp_path / "invalid.yaml"
    import yaml
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    # Should raise validation error during config loading (undefined variable)
    with pytest.raises(ConfigValidationError) as excinfo:
        load_config(config_file)

    assert "nonexistent_var" in str(excinfo.value)
    assert "exhaustive_vars" in str(excinfo.value)


def test_matrix_exhaustive_vars_not_swept_validation(tmp_path, sample_config_dict):
    """Test that exhaustive_vars validation catches non-swept variables."""
    from iops.config.models import ConfigValidationError

    # Add a derived (not swept) variable to exhaustive_vars
    sample_config_dict["benchmark"]["exhaustive_vars"] = ["total_procs"]

    config_file = tmp_path / "invalid.yaml"
    import yaml
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    # Should raise validation error when building matrix (variable exists but is not swept)
    with pytest.raises(ConfigValidationError) as excinfo:
        build_execution_matrix(config)

    assert "total_procs" in str(excinfo.value) and "not swept" in str(excinfo.value)


# ----------------- Conditional Variable Tests ----------------- #


def test_conditional_var_basic(tmp_path, sample_config_dict):
    """Test basic conditional variable: has_flag controls flag_value sweep."""
    import yaml

    # Add conditional variables
    sample_config_dict["vars"]["has_flag"] = {
        "type": "bool",
        "sweep": {
            "mode": "list",
            "values": [True, False]
        }
    }
    sample_config_dict["vars"]["flag_value"] = {
        "type": "int",
        "sweep": {
            "mode": "list",
            "values": [1, 2, 4]
        },
        "when": "has_flag",
        "default": 0
    }

    config_file = tmp_path / "conditional.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    matrix, _ = build_execution_matrix(config)

    # Without conditional: 2 nodes * 2 has_flag * 3 flag_value = 12
    # With conditional: 2 nodes * (3 when True + 1 when False) = 2 * 4 = 8
    assert len(matrix) == 8

    # Check that flag_value=0 when has_flag=False
    for test in matrix:
        if not test.vars["has_flag"]:
            assert test.vars["flag_value"] == 0, "flag_value should be 0 when has_flag is False"

    # Check that flag_value varies when has_flag=True
    true_flag_values = {t.vars["flag_value"] for t in matrix if t.vars["has_flag"]}
    assert true_flag_values == {1, 2, 4}, "All flag_value sweep values should be present when has_flag is True"


def test_conditional_var_deduplication(tmp_path, sample_config_dict):
    """Test that conditional variables properly deduplicate redundant combinations."""
    import yaml

    # Remove nodes sweep (just one value)
    sample_config_dict["vars"]["nodes"] = {
        "type": "int",
        "sweep": {"mode": "list", "values": [1]}
    }

    # Simple conditional
    sample_config_dict["vars"]["has_flag"] = {
        "type": "bool",
        "sweep": {"mode": "list", "values": [True, False]}
    }
    sample_config_dict["vars"]["flag_value"] = {
        "type": "int",
        "sweep": {"mode": "list", "values": [1, 2, 4]},
        "when": "has_flag",
        "default": 0
    }

    config_file = tmp_path / "dedup.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    matrix, _ = build_execution_matrix(config)

    # Should be: 1 node * (3 when True + 1 when False) = 4
    # NOT: 1 node * 2 has_flag * 3 flag_value = 6
    assert len(matrix) == 4


def test_conditional_var_dependency_chain(tmp_path, sample_config_dict):
    """Test dependency chain: level3 depends on level2 depends on level1."""
    import yaml

    # Remove existing vars except nodes
    sample_config_dict["vars"] = {
        "nodes": {"type": "int", "sweep": {"mode": "list", "values": [1]}},
        "level1": {
            "type": "bool",
            "sweep": {"mode": "list", "values": [True, False]}
        },
        "level2": {
            "type": "bool",
            "sweep": {"mode": "list", "values": [True, False]},
            "when": "level1",
            "default": False
        },
        "level3": {
            "type": "int",
            "sweep": {"mode": "list", "values": [1, 2]},
            "when": "level2",
            "default": 0
        },
    }

    config_file = tmp_path / "chain.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    matrix, _ = build_execution_matrix(config)

    # Expected combinations:
    # level1=True, level2=True, level3=1: 1
    # level1=True, level2=True, level3=2: 1
    # level1=True, level2=False, level3=0: 1
    # level1=False, level2=False, level3=0: 1
    # Total: 4
    assert len(matrix) == 4

    # Verify the specific combinations
    combos = [(t.vars["level1"], t.vars["level2"], t.vars["level3"]) for t in matrix]
    expected = {
        (True, True, 1),
        (True, True, 2),
        (True, False, 0),
        (False, False, 0),
    }
    assert set(combos) == expected


def test_conditional_var_circular_dependency(tmp_path, sample_config_dict):
    """Test that circular dependencies are detected and rejected."""
    import yaml
    from iops.config.models import ConfigValidationError

    sample_config_dict["vars"] = {
        "nodes": {"type": "int", "sweep": {"mode": "list", "values": [1]}},
        "a": {
            "type": "bool",
            "sweep": {"mode": "list", "values": [True, False]},
            "when": "b",
            "default": False
        },
        "b": {
            "type": "bool",
            "sweep": {"mode": "list", "values": [True, False]},
            "when": "a",
            "default": False
        },
    }

    config_file = tmp_path / "circular.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    with pytest.raises(ConfigValidationError) as excinfo:
        build_execution_matrix(config)

    assert "Circular dependency" in str(excinfo.value)


def test_when_without_default_error(tmp_path, sample_config_dict):
    """Test that when without default raises validation error."""
    import yaml
    from iops.config.models import ConfigValidationError

    sample_config_dict["vars"]["conditional_var"] = {
        "type": "int",
        "sweep": {"mode": "list", "values": [1, 2]},
        "when": "nodes > 1"
        # Missing: default
    }

    config_file = tmp_path / "no_default.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError) as excinfo:
        load_config(config_file)

    assert "default" in str(excinfo.value)


def test_when_on_derived_error(tmp_path, sample_config_dict):
    """Test that when on derived variable raises validation error."""
    import yaml
    from iops.config.models import ConfigValidationError

    sample_config_dict["vars"]["bad_var"] = {
        "type": "int",
        "expr": "nodes * 2",
        "when": "nodes > 1",
        "default": 0
    }

    config_file = tmp_path / "when_on_derived.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError) as excinfo:
        load_config(config_file)

    assert "when" in str(excinfo.value) and "sweep" in str(excinfo.value)


def test_default_without_when_error(tmp_path, sample_config_dict):
    """Test that default without when raises validation error."""
    import yaml
    from iops.config.models import ConfigValidationError

    sample_config_dict["vars"]["bad_var"] = {
        "type": "int",
        "sweep": {"mode": "list", "values": [1, 2]},
        "default": 0  # Has default but no when
    }

    config_file = tmp_path / "default_no_when.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError) as excinfo:
        load_config(config_file)

    assert "default" in str(excinfo.value) and "when" in str(excinfo.value)


def test_complex_when_expression(tmp_path, sample_config_dict):
    """Test complex when expressions with operators."""
    import yaml

    sample_config_dict["vars"]["threads"] = {
        "type": "int",
        "sweep": {"mode": "list", "values": [1, 2, 4]},
        "when": "nodes > 1",
        "default": 1
    }

    config_file = tmp_path / "complex_when.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    matrix, _ = build_execution_matrix(config)

    # Check threads value based on nodes
    for test in matrix:
        if test.vars["nodes"] > 1:
            assert test.vars["threads"] in [1, 2, 4], "threads should be swept when nodes > 1"
        else:
            assert test.vars["threads"] == 1, "threads should be default (1) when nodes <= 1"


def test_conditional_backward_compatibility(tmp_path, sample_config_dict):
    """Test that configs without conditional vars work as before."""
    import yaml

    # Standard config without when/default
    sample_config_dict["vars"]["extra"] = {
        "type": "int",
        "sweep": {"mode": "list", "values": [10, 20]}
    }

    config_file = tmp_path / "no_conditional.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    matrix, _ = build_execution_matrix(config)

    # Should have 2 nodes * 2 extra = 4 tests
    assert len(matrix) == 4

    # Verify all combinations
    combos = {(t.vars["nodes"], t.vars["extra"]) for t in matrix}
    expected = {(1, 10), (1, 20), (2, 10), (2, 20)}
    assert combos == expected
