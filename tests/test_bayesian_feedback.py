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
                "mode": "append",
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
