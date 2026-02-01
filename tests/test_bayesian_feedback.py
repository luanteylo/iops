"""
Tests for Bayesian planner feedback alignment fix.

The fix ensures that when the optimizer suggests a configuration that gets mapped
to a different valid point (due to constraints or nearest-neighbor mapping), the
optimizer receives feedback about the actual configuration evaluated, not the
originally suggested one.
"""
import pytest
import yaml
import logging
from pathlib import Path


def load_config(config_path):
    """Helper to load config without logger dependency."""
    from iops.config.loader import load_generic_config
    logger = logging.getLogger("test")
    return load_generic_config(Path(config_path), logger)


@pytest.fixture
def bayesian_config_dict(tmp_path):
    """Create a sample Bayesian configuration dictionary."""
    workdir = tmp_path / "workdir"
    workdir.mkdir(parents=True, exist_ok=True)

    return {
        "benchmark": {
            "name": "Test Bayesian",
            "description": "Test Bayesian optimization feedback",
            "workdir": str(workdir),
            "executor": "local",
            "search_method": "bayesian",
            "repetitions": 1,
            "random_seed": 42,
            "bayesian_config": {
                "objective_metric": "metric",
                "objective": "maximize",
                "n_initial_points": 2,
                "n_iterations": 5,
            },
        },
        "vars": {
            "param1": {
                "type": "int",
                "sweep": {"mode": "list", "values": [1, 10, 100]},
            },
            "param2": {
                "type": "int",
                "sweep": {"mode": "list", "values": [1, 2, 3]},
            },
        },
        "command": {
            "template": "echo 'param1={{ param1 }} param2={{ param2 }}'",
        },
        "scripts": [
            {
                "name": "test_script",
                "script_template": "#!/bin/bash\necho 'metric: 100' > {{ execution_dir }}/output.txt",
                "parser": {
                    "file": "{{ execution_dir }}/output.txt",
                    "metrics": [{"name": "metric", "type": "float"}],
                    "parser_script": (
                        "def parse(file_path):\n"
                        "    with open(file_path) as f:\n"
                        "        line = f.read().strip()\n"
                        "    return {'metric': float(line.split(':')[1])}"
                    ),
                },
            }
        ],
        "output": {
            "sink": {
                "type": "csv",
                "path": "{{ workdir }}/results.csv",
            }
        },
    }


@pytest.fixture
def bayesian_config(tmp_path, bayesian_config_dict):
    """Create and load a Bayesian config."""
    config_file = tmp_path / "bayesian_config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(bayesian_config_dict, f)
    return load_config(config_file)


class TestSearchPointConversion:
    """Test conversion between search points and optimizer parameters."""

    def test_search_point_to_params_roundtrip(self, bayesian_config):
        """Test converting a search point back to optimizer indices and back."""
        pytest.importorskip("skopt")
        from iops.execution.planner import BayesianPlanner

        planner = BayesianPlanner(bayesian_config)

        # Get the valid search points from the planner
        valid_points = planner._valid_search_points

        # Test roundtrip for several valid points
        for search_point in valid_points[:5]:
            params = planner._search_point_to_params(search_point)
            roundtrip_point = planner._suggestion_to_search_point(params)
            assert roundtrip_point == search_point, (
                f"Roundtrip failed for {search_point}: got {roundtrip_point}"
            )


class TestFeedbackAlignment:
    """Test that optimizer receives correct feedback."""

    def test_current_params_uses_actual_indices(self, bayesian_config):
        """Test that current_params stores actual indices, not suggested."""
        pytest.importorskip("skopt")
        from iops.execution.planner import BayesianPlanner

        planner = BayesianPlanner(bayesian_config)

        # Get a test instance
        test = planner.next_test()
        assert test is not None

        # current_params should be the indices for the actual search point
        actual_search_point = planner._current_search_point
        expected_params = planner._search_point_to_params(actual_search_point)

        # Convert both to regular lists for comparison
        current = [int(p) for p in planner.current_params]
        expected = [int(p) for p in expected_params]

        assert current == expected, (
            f"current_params {current} should match actual point indices {expected}"
        )


class TestDuplicateAvoidance:
    """Test that duplicate configurations are avoided."""

    def test_visited_points_tracked(self, bayesian_config):
        """Test that visited search points are tracked."""
        pytest.importorskip("skopt")
        from iops.execution.planner import BayesianPlanner

        planner = BayesianPlanner(bayesian_config)

        # Initial state: no visited points
        assert len(planner._visited_search_points) == 0

        # Get first test
        test1 = planner.next_test()
        assert test1 is not None
        point1 = planner._current_search_point

        # Should have one visited point
        assert len(planner._visited_search_points) == 1
        assert point1 in planner._visited_search_points

    def test_unique_configs_explored(self, bayesian_config):
        """Test that the planner explores unique configurations."""
        pytest.importorskip("skopt")
        from iops.execution.planner import BayesianPlanner

        planner = BayesianPlanner(bayesian_config)

        explored = set()
        for _ in range(5):  # n_iterations=5
            test = planner.next_test()
            if test is None:
                break

            # Record the search point
            explored.add(planner._current_search_point)

            # Simulate completing the test
            test.metadata['metrics'] = {'metric': 100.0}
            planner.record_completed_test(test)

        # All explored points should be unique
        assert len(explored) == len(planner._visited_search_points), (
            "Each explored point should be unique"
        )


@pytest.fixture
def bayesian_exhaustive_config_dict(tmp_path):
    """Create a Bayesian configuration with exhaustive_vars."""
    workdir = tmp_path / "workdir"
    workdir.mkdir(parents=True, exist_ok=True)

    return {
        "benchmark": {
            "name": "Test Bayesian Exhaustive",
            "description": "Test Bayesian optimization with exhaustive_vars",
            "workdir": str(workdir),
            "executor": "local",
            "search_method": "bayesian",
            "repetitions": 2,  # 2 reps per config
            "random_seed": 42,
            "exhaustive_vars": ["exhaustive_param"],  # This var tested exhaustively
            "bayesian_config": {
                "objective_metric": "metric",
                "objective": "maximize",
                "n_initial_points": 1,
                "n_iterations": 2,  # Less than search space size (5) to avoid exhaustive fallback
            },
        },
        "vars": {
            "search_param": {
                "type": "int",
                "sweep": {"mode": "list", "values": [1, 2, 3, 4, 5]},  # Optimized by Bayesian (5 values)
            },
            "exhaustive_param": {
                "type": "int",
                "sweep": {"mode": "list", "values": [10, 20]},  # Tested exhaustively
            },
        },
        "command": {
            "template": "echo 'search={{ search_param }} exhaustive={{ exhaustive_param }}'",
        },
        "scripts": [
            {
                "name": "test_script",
                "script_template": "#!/bin/bash\necho 'metric: 100' > {{ execution_dir }}/output.txt",
                "parser": {
                    "file": "{{ execution_dir }}/output.txt",
                    "metrics": [{"name": "metric", "type": "float"}],
                    "parser_script": (
                        "def parse(file_path):\n"
                        "    with open(file_path) as f:\n"
                        "        line = f.read().strip()\n"
                        "    return {'metric': float(line.split(':')[1])}"
                    ),
                },
            }
        ],
        "output": {
            "sink": {
                "type": "csv",
                "path": "{{ workdir }}/results.csv",
            }
        },
    }


@pytest.fixture
def bayesian_exhaustive_config(tmp_path, bayesian_exhaustive_config_dict):
    """Create and load a Bayesian config with exhaustive_vars."""
    config_file = tmp_path / "bayesian_exhaustive_config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(bayesian_exhaustive_config_dict, f)
    return load_config(config_file)


class TestBayesianExhaustiveVars:
    """Test Bayesian optimization with exhaustive_vars."""

    def test_bayesian_search_space_excludes_exhaustive_vars(self, bayesian_exhaustive_config):
        """Test that exhaustive_vars are not included in the optimizer's search space."""
        pytest.importorskip("skopt")
        from iops.execution.planner import BayesianPlanner

        planner = BayesianPlanner(bayesian_exhaustive_config)

        # Check that exhaustive_param is NOT in var_names (optimizer dimensions)
        assert "exhaustive_param" not in planner.var_names, (
            "Exhaustive variables should not be in optimizer search space"
        )

        # Check that search_param IS in var_names
        assert "search_param" in planner.var_names, (
            "Search variables should be in optimizer search space"
        )

        # Check the search space has only 1 dimension (search_param)
        assert len(planner.search_space) == 1, (
            f"Expected 1 dimension in search space, got {len(planner.search_space)}"
        )

        # Check exhaustive_var_names is properly set
        assert "exhaustive_param" in planner.exhaustive_var_names, (
            "exhaustive_param should be in exhaustive_var_names"
        )

    def test_bayesian_all_exhaustive_instances_executed(self, bayesian_exhaustive_config):
        """Test that all exhaustive combinations are executed for each search point."""
        pytest.importorskip("skopt")
        from iops.execution.planner import BayesianPlanner

        planner = BayesianPlanner(bayesian_exhaustive_config)

        # Each search point should have 2 exhaustive instances (exhaustive_param=10, 20)
        for search_point, instances in planner._instance_lookup.items():
            assert len(instances) == 2, (
                f"Expected 2 exhaustive instances per search point, got {len(instances)}"
            )

        # Track all executed tests
        executed_configs = []
        tests_per_search_point = {}

        for i in range(100):  # Upper bound to prevent infinite loop
            test = planner.next_test()
            if test is None:
                break

            config = dict(test.base_vars)
            executed_configs.append(config)

            # Track by search point
            search_point = planner._current_search_point
            if search_point not in tests_per_search_point:
                tests_per_search_point[search_point] = []
            tests_per_search_point[search_point].append(config)

            # Simulate completing the test
            test.metadata['metrics'] = {'metric': 100.0}
            planner.record_completed_test(test)

        # Should have executed 3 iterations * 2 exhaustive * 2 reps = 12 tests
        # But each config/rep combo is returned once, so we track repetition via test.repetition
        # Actually let's just check we got tests from all exhaustive instances

        # For each search point visited, verify both exhaustive values were tested
        for search_point, configs in tests_per_search_point.items():
            exhaustive_values = set(c["exhaustive_param"] for c in configs)
            assert exhaustive_values == {10, 20}, (
                f"Expected exhaustive_param values {{10, 20}}, got {exhaustive_values} "
                f"for search_point {search_point}"
            )

    def test_bayesian_optimizer_receives_aggregated_feedback(self, bayesian_exhaustive_config):
        """Test that optimizer receives one aggregated feedback per search point."""
        pytest.importorskip("skopt")
        from iops.execution.planner import BayesianPlanner

        planner = BayesianPlanner(bayesian_exhaustive_config)

        # Track optimizer updates
        initial_observations = len(planner.y_observed)

        # Run through one complete iteration (all exhaustive instances and reps)
        iteration_count = 0
        while True:
            test = planner.next_test()
            if test is None:
                break

            # Check if we moved to a new iteration
            if planner.iteration > iteration_count:
                iteration_count = planner.iteration

            # Simulate different metrics for different exhaustive configs
            exhaustive_val = test.base_vars["exhaustive_param"]
            metric_value = 100.0 + exhaustive_val  # 110 or 120

            test.metadata['metrics'] = {'metric': metric_value}
            planner.record_completed_test(test)

            # Only run one full iteration for this test
            if iteration_count >= 1 and len(planner.y_observed) > initial_observations:
                break

        # After one complete iteration, optimizer should have received exactly 1 feedback
        assert len(planner.y_observed) == initial_observations + 1, (
            f"Expected 1 optimizer update after completing one search point, "
            f"got {len(planner.y_observed) - initial_observations}"
        )

    def test_bayesian_exhaustive_aggregation_uses_max(self, bayesian_exhaustive_config):
        """Test that aggregation across exhaustive instances uses max for maximization."""
        pytest.importorskip("skopt")
        from iops.execution.planner import BayesianPlanner

        planner = BayesianPlanner(bayesian_exhaustive_config)

        # Run through all tests for one iteration
        iteration = 0
        while True:
            test = planner.next_test()
            if test is None or planner.iteration > 1:
                break

            iteration = planner.iteration

            # Give different metrics to different exhaustive instances
            exhaustive_val = test.base_vars["exhaustive_param"]
            if exhaustive_val == 10:
                metric_value = 100.0
            else:  # 20
                metric_value = 200.0

            test.metadata['metrics'] = {'metric': metric_value}
            planner.record_completed_test(test)

        # Check that the aggregated value is the max (for maximization objective)
        # Each exhaustive instance has 2 reps, so:
        # - exhaustive_param=10: max of 2 reps = 100.0
        # - exhaustive_param=20: max of 2 reps = 200.0
        # - Overall max: max(100.0, 200.0) = 200.0
        # For maximization, y_observed stores -aggregated_value
        if len(planner.y_observed) > 0:
            # Since we're maximizing, y_value = -aggregated_value
            observed = -planner.y_observed[0]
            expected = 200.0  # max of 100 and 200
            assert abs(observed - expected) < 0.01, (
                f"Expected aggregated value ~{expected}, got {observed}"
            )
