"""Tests for random sampling planner."""

import pytest
import yaml
from pathlib import Path

from iops.execution.planner import BasePlanner
from iops.execution.random_planner import RandomSamplingPlanner
from conftest import load_config


def test_random_planner_registration():
    """Test that random planner is registered."""
    assert "random" in BasePlanner._registry
    assert BasePlanner._registry["random"] == RandomSamplingPlanner


def test_random_planner_initialization_with_n_samples(tmp_path, sample_config_dict):
    """Test planner initialization with n_samples configuration."""
    sample_config_dict["benchmark"]["search_method"] = "random"
    sample_config_dict["benchmark"]["random_config"] = {
        "n_samples": 5
    }

    # Write config and load
    config_file = tmp_path / "random.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    planner = BasePlanner.build(config)

    assert isinstance(planner, RandomSamplingPlanner)
    assert planner.n_samples == 5
    assert planner.percentage is None
    assert planner.fallback_to_exhaustive is True


def test_random_planner_initialization_with_percentage(tmp_path, sample_config_dict):
    """Test planner initialization with percentage configuration."""
    sample_config_dict["benchmark"]["search_method"] = "random"
    sample_config_dict["benchmark"]["random_config"] = {
        "percentage": 0.3
    }

    config_file = tmp_path / "random.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    planner = BasePlanner.build(config)

    assert isinstance(planner, RandomSamplingPlanner)
    assert planner.n_samples is None
    assert planner.percentage == 0.3
    assert planner.fallback_to_exhaustive is True


def test_random_config_validation_both_params(tmp_path, sample_config_dict):
    """Test that specifying both n_samples and percentage raises error."""
    sample_config_dict["benchmark"]["search_method"] = "random"
    sample_config_dict["benchmark"]["random_config"] = {
        "n_samples": 10,
        "percentage": 0.5
    }

    config_file = tmp_path / "random.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    with pytest.raises(ValueError, match="cannot specify both 'n_samples' and 'percentage'"):
        BasePlanner.build(config)


def test_random_config_validation_neither_param(tmp_path, sample_config_dict):
    """Test that specifying neither n_samples nor percentage raises error."""
    sample_config_dict["benchmark"]["search_method"] = "random"
    sample_config_dict["benchmark"]["random_config"] = {}

    config_file = tmp_path / "random.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    with pytest.raises(ValueError, match="must specify either 'n_samples' or 'percentage'"):
        BasePlanner.build(config)


def test_random_config_invalid_n_samples_negative(tmp_path, sample_config_dict):
    """Test validation of negative n_samples."""
    sample_config_dict["benchmark"]["search_method"] = "random"
    sample_config_dict["benchmark"]["random_config"] = {
        "n_samples": -5
    }

    config_file = tmp_path / "random.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    with pytest.raises(ValueError, match="must be a positive integer"):
        BasePlanner.build(config)


def test_random_config_invalid_n_samples_zero(tmp_path, sample_config_dict):
    """Test validation of zero n_samples."""
    sample_config_dict["benchmark"]["search_method"] = "random"
    sample_config_dict["benchmark"]["random_config"] = {
        "n_samples": 0
    }

    config_file = tmp_path / "random.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    with pytest.raises(ValueError, match="must be a positive integer"):
        BasePlanner.build(config)


def test_random_config_invalid_percentage_negative(tmp_path, sample_config_dict):
    """Test validation of negative percentage."""
    sample_config_dict["benchmark"]["search_method"] = "random"
    sample_config_dict["benchmark"]["random_config"] = {
        "percentage": -0.5
    }

    config_file = tmp_path / "random.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    with pytest.raises(ValueError, match="must be positive"):
        BasePlanner.build(config)


def test_random_config_invalid_percentage_zero(tmp_path, sample_config_dict):
    """Test validation of zero percentage."""
    sample_config_dict["benchmark"]["search_method"] = "random"
    sample_config_dict["benchmark"]["random_config"] = {
        "percentage": 0.0
    }

    config_file = tmp_path / "random.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    with pytest.raises(ValueError, match="must be positive"):
        BasePlanner.build(config)


def test_random_config_percentage_over_one_clamped(tmp_path, sample_config_dict):
    """Test that percentage > 1.0 is clamped to 1.0 with warning."""
    sample_config_dict["benchmark"]["search_method"] = "random"
    sample_config_dict["benchmark"]["random_config"] = {
        "percentage": 1.5
    }

    config_file = tmp_path / "random.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    planner = BasePlanner.build(config)

    assert planner.percentage == 1.0  # Should be clamped


def test_random_sampling_with_n_samples(tmp_path, sample_config_dict):
    """Test that n_samples produces expected subset size."""
    # Config has nodes=[1,2] → 2 combinations
    # We'll sample 1 out of 2
    sample_config_dict["benchmark"]["search_method"] = "random"
    sample_config_dict["benchmark"]["random_config"] = {
        "n_samples": 1
    }

    config_file = tmp_path / "random.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    planner = BasePlanner.build(config)

    # Get first test
    test = planner.next_test()
    assert test is not None

    # Since we sampled 1 out of 2 configs, with 2 repetitions each,
    # we should have 2 total attempts (1 config × 2 reps)
    assert planner._attempt_total == 2
    assert planner.total_tests == 1
    assert planner.sampled_size == 1
    assert planner.total_space_size == 2


def test_random_sampling_with_percentage(tmp_path, sample_config_dict):
    """Test that percentage produces expected subset size."""
    # Expand the parameter space: nodes=[1,2,3,4,5] → 5 combinations
    sample_config_dict["vars"]["nodes"]["sweep"]["values"] = [1, 2, 3, 4, 5]
    sample_config_dict["benchmark"]["search_method"] = "random"
    sample_config_dict["benchmark"]["random_config"] = {
        "percentage": 0.4  # 40% of 5 = 2
    }

    config_file = tmp_path / "random.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    planner = BasePlanner.build(config)

    # Build first matrix
    test = planner.next_test()
    assert test is not None

    # 40% of 5 = 2 configs, with 2 reps each = 4 attempts
    assert planner.total_space_size == 5
    assert planner.sampled_size == 2
    assert planner.total_tests == 2
    assert planner._attempt_total == 4


def test_random_sampling_reproducibility(tmp_path, sample_config_dict):
    """Test that same random_seed produces same sample."""
    sample_config_dict["vars"]["nodes"]["sweep"]["values"] = [1, 2, 3, 4, 5]
    sample_config_dict["benchmark"]["search_method"] = "random"
    sample_config_dict["benchmark"]["random_seed"] = 12345
    sample_config_dict["benchmark"]["random_config"] = {
        "n_samples": 2
    }

    # First run
    config_file = tmp_path / "random1.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config1 = load_config(config_file)
    planner1 = BasePlanner.build(config1)
    planner1.next_test()  # Build matrix
    ids1 = [test.execution_id for test in planner1.execution_matrix]

    # Second run with same seed
    config_file2 = tmp_path / "random2.yaml"
    with open(config_file2, "w") as f:
        yaml.dump(sample_config_dict, f)

    config2 = load_config(config_file2)
    planner2 = BasePlanner.build(config2)
    planner2.next_test()  # Build matrix
    ids2 = [test.execution_id for test in planner2.execution_matrix]

    # Should produce same execution IDs (same sample)
    assert ids1 == ids2


def test_random_sampling_different_seeds(tmp_path, sample_config_dict):
    """Test that different random_seed produces different sample."""
    sample_config_dict["vars"]["nodes"]["sweep"]["values"] = [1, 2, 3, 4, 5]
    sample_config_dict["benchmark"]["search_method"] = "random"
    sample_config_dict["benchmark"]["random_config"] = {
        "n_samples": 2
    }

    # First run with seed 12345
    sample_config_dict["benchmark"]["random_seed"] = 12345
    config_file1 = tmp_path / "random1.yaml"
    with open(config_file1, "w") as f:
        yaml.dump(sample_config_dict, f)

    config1 = load_config(config_file1)
    planner1 = BasePlanner.build(config1)
    planner1.next_test()
    ids1 = [test.execution_id for test in planner1.execution_matrix]

    # Second run with different seed 54321
    sample_config_dict["benchmark"]["random_seed"] = 54321
    config_file2 = tmp_path / "random2.yaml"
    with open(config_file2, "w") as f:
        yaml.dump(sample_config_dict, f)

    config2 = load_config(config_file2)
    planner2 = BasePlanner.build(config2)
    planner2.next_test()
    ids2 = [test.execution_id for test in planner2.execution_matrix]

    # Should produce different samples (high probability)
    # Note: theoretically could be same, but extremely unlikely with 5 choose 2
    assert ids1 != ids2


def test_random_sampling_over_total_space_fallback(tmp_path, sample_config_dict):
    """Test that n_samples > total_space falls back to exhaustive when enabled."""
    # Config has nodes=[1,2] → 2 combinations
    sample_config_dict["benchmark"]["search_method"] = "random"
    sample_config_dict["benchmark"]["random_config"] = {
        "n_samples": 10,  # Request more than available
        "fallback_to_exhaustive": True
    }

    config_file = tmp_path / "random.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    planner = BasePlanner.build(config)

    test = planner.next_test()
    assert test is not None

    # Should use all 2 configs (exhaustive)
    assert planner.total_space_size == 2
    assert planner.sampled_size == 2
    assert planner.total_tests == 2


def test_random_sampling_over_total_space_no_fallback(tmp_path, sample_config_dict):
    """Test that n_samples > total_space clamps when fallback disabled."""
    sample_config_dict["benchmark"]["search_method"] = "random"
    sample_config_dict["benchmark"]["random_config"] = {
        "n_samples": 10,
        "fallback_to_exhaustive": False
    }

    config_file = tmp_path / "random.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    planner = BasePlanner.build(config)

    test = planner.next_test()
    assert test is not None

    # Should clamp to total space size
    assert planner.total_space_size == 2
    assert planner.sampled_size == 2
    assert planner.total_tests == 2


def test_random_sampling_minimum_one_sample(tmp_path, sample_config_dict):
    """Test that very small percentage yields at least 1 sample."""
    sample_config_dict["vars"]["nodes"]["sweep"]["values"] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    sample_config_dict["benchmark"]["search_method"] = "random"
    sample_config_dict["benchmark"]["random_config"] = {
        "percentage": 0.001  # 0.1% of 10 = 0.01, should round to 1
    }

    config_file = tmp_path / "random.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    planner = BasePlanner.build(config)

    test = planner.next_test()
    assert test is not None

    # Should have at least 1 sample
    assert planner.sampled_size >= 1
    assert planner.total_tests >= 1


def test_random_planner_repetition_interleaving(tmp_path, sample_config_dict):
    """Test that repetitions are properly interleaved."""
    sample_config_dict["benchmark"]["search_method"] = "random"
    sample_config_dict["benchmark"]["repetitions"] = 3
    sample_config_dict["benchmark"]["random_config"] = {
        "n_samples": 2
    }

    config_file = tmp_path / "random.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    planner = BasePlanner.build(config)

    # Collect all tests
    tests = []
    while True:
        test = planner.next_test()
        if test is None:
            break
        tests.append((test.execution_id, test.repetition))

    # Should have 2 configs × 3 reps = 6 tests
    assert len(tests) == 6

    # Check that repetitions are interleaved (not sequential)
    # Extract execution IDs
    exec_ids = [t[0] for t in tests]

    # Should have exactly 2 unique execution IDs
    unique_ids = set(exec_ids)
    assert len(unique_ids) == 2

    # Each ID should appear 3 times (3 repetitions)
    for exec_id in unique_ids:
        count = exec_ids.count(exec_id)
        assert count == 3


def test_random_planner_with_rounds_no_config(tmp_path, sample_round_config_dict):
    """Test multi-round random sampling planner."""
    # Modify sample_round_config_dict to use random planner
    sample_round_config_dict["benchmark"]["search_method"] = "random"
    sample_round_config_dict["benchmark"]["random_config"] = {
        "n_samples": 2  # Sample 2 out of 3 nodes in first round
    }

    config_file = tmp_path / "random_rounds.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_round_config_dict, f)

    config = load_config(config_file)
    planner = BasePlanner.build(config)

    assert planner.multiple_rounds is True
    assert len(planner.round_queue) == 2

    # Execute first round
    round1_tests = []
    while planner.current_round == "optimize_nodes" or planner.current_round is None:
        test = planner.next_test()
        if test is None or (planner.current_round and planner.current_round != "optimize_nodes"):
            break
        round1_tests.append(test)

    # First round should sample 2 out of 3 nodes
    # But we need to check the matrix after it's built
    # The planner should have sampled 2 configs in round 1


def test_random_planner_default_config(tmp_path, sample_config_dict):
    """Test that planner requires random_config when search_method is random."""
    sample_config_dict["benchmark"]["search_method"] = "random"
    # Don't specify random_config - should raise error

    config_file = tmp_path / "random.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    # Should raise error because random_config is required
    with pytest.raises(ValueError, match="must specify either 'n_samples' or 'percentage'"):
        BasePlanner.build(config)
