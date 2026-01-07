"""Tests for JSON serialization helpers used in metadata and results storage."""

import json
import pytest
import numpy as np
from pathlib import Path

from iops.config.models import (
    BayesianConfig,
    RandomSamplingConfig,
    ExecutorOptionsConfig,
)
from iops.execution.runner import IOPSRunner


class TestJsonSerializeHelper:
    """Tests for IOPSRunner._json_serialize_helper."""

    def test_serialize_bayesian_config(self):
        """Test that BayesianConfig dataclass is properly serialized."""
        config = BayesianConfig(
            n_initial_points=10,
            n_iterations=50,
            acquisition_func="EI",
            base_estimator="RF",
            xi=0.01,
            kappa=1.96,
            objective="maximize",
            objective_metric="throughput",
        )

        result = IOPSRunner._json_serialize_helper(config)

        assert isinstance(result, dict)
        assert result["n_initial_points"] == 10
        assert result["n_iterations"] == 50
        assert result["acquisition_func"] == "EI"
        assert result["base_estimator"] == "RF"
        assert result["xi"] == 0.01
        assert result["kappa"] == 1.96
        assert result["objective"] == "maximize"
        assert result["objective_metric"] == "throughput"

    def test_serialize_bayesian_config_defaults(self):
        """Test BayesianConfig with default values serializes correctly."""
        config = BayesianConfig()

        result = IOPSRunner._json_serialize_helper(config)

        assert isinstance(result, dict)
        assert result["n_initial_points"] == 5
        assert result["n_iterations"] == 20
        assert result["acquisition_func"] == "EI"
        assert result["base_estimator"] == "RF"
        assert result["objective"] == "minimize"
        assert result["objective_metric"] is None

    def test_serialize_random_sampling_config(self):
        """Test that RandomSamplingConfig dataclass is properly serialized."""
        config = RandomSamplingConfig(
            n_samples=100,
            percentage=None,
            fallback_to_exhaustive=False,
        )

        result = IOPSRunner._json_serialize_helper(config)

        assert isinstance(result, dict)
        assert result["n_samples"] == 100
        assert result["percentage"] is None
        assert result["fallback_to_exhaustive"] is False

    def test_serialize_executor_options_config(self):
        """Test that ExecutorOptionsConfig dataclass is properly serialized."""
        config = ExecutorOptionsConfig(
            commands={"submit": "sbatch", "status": "squeue -j {job_id}"},
            poll_interval=30,
        )

        result = IOPSRunner._json_serialize_helper(config)

        assert isinstance(result, dict)
        assert result["commands"]["submit"] == "sbatch"
        assert result["poll_interval"] == 30

    def test_serialize_numpy_int64(self):
        """Test numpy int64 serialization."""
        value = np.int64(42)
        result = IOPSRunner._json_serialize_helper(value)
        assert result == 42
        assert isinstance(result, int)

    def test_serialize_numpy_int32(self):
        """Test numpy int32 serialization."""
        value = np.int32(42)
        result = IOPSRunner._json_serialize_helper(value)
        assert result == 42
        assert isinstance(result, int)

    def test_serialize_numpy_float64(self):
        """Test numpy float64 serialization."""
        value = np.float64(3.14159)
        result = IOPSRunner._json_serialize_helper(value)
        assert abs(result - 3.14159) < 1e-5
        assert isinstance(result, float)

    def test_serialize_numpy_float32(self):
        """Test numpy float32 serialization."""
        value = np.float32(3.14)
        result = IOPSRunner._json_serialize_helper(value)
        assert abs(result - 3.14) < 1e-2
        assert isinstance(result, float)

    def test_serialize_numpy_array(self):
        """Test numpy array serialization."""
        value = np.array([1, 2, 3, 4, 5])
        result = IOPSRunner._json_serialize_helper(value)
        assert result == [1, 2, 3, 4, 5]
        assert isinstance(result, list)

    def test_serialize_numpy_2d_array(self):
        """Test 2D numpy array serialization."""
        value = np.array([[1, 2], [3, 4]])
        result = IOPSRunner._json_serialize_helper(value)
        assert result == [[1, 2], [3, 4]]
        assert isinstance(result, list)

    def test_serialize_unsupported_type_raises(self):
        """Test that unsupported types raise TypeError."""
        class CustomClass:
            pass

        with pytest.raises(TypeError) as exc_info:
            IOPSRunner._json_serialize_helper(CustomClass())

        assert "CustomClass" in str(exc_info.value)
        assert "not JSON serializable" in str(exc_info.value)


class TestJsonDumpWithHelper:
    """Integration tests for json.dump with the serialize helper."""

    def test_dump_dict_with_bayesian_config(self):
        """Test json.dump works with dict containing BayesianConfig."""
        metadata = {
            "name": "test",
            "bayesian_config": BayesianConfig(
                objective_metric="bwMiB",
                objective="maximize",
                n_iterations=30,
            ),
        }

        result = json.dumps(metadata, default=IOPSRunner._json_serialize_helper)
        parsed = json.loads(result)

        assert parsed["name"] == "test"
        assert parsed["bayesian_config"]["objective_metric"] == "bwMiB"
        assert parsed["bayesian_config"]["objective"] == "maximize"
        assert parsed["bayesian_config"]["n_iterations"] == 30

    def test_dump_dict_with_numpy_values(self):
        """Test json.dump works with dict containing numpy values."""
        metadata = {
            "count": np.int64(100),
            "mean": np.float64(42.5),
            "values": np.array([1, 2, 3]),
        }

        result = json.dumps(metadata, default=IOPSRunner._json_serialize_helper)
        parsed = json.loads(result)

        assert parsed["count"] == 100
        assert abs(parsed["mean"] - 42.5) < 1e-5
        assert parsed["values"] == [1, 2, 3]

    def test_dump_nested_dataclass(self):
        """Test json.dump works with nested structures containing dataclasses."""
        metadata = {
            "benchmark": {
                "name": "test",
                "config": {
                    "bayesian": BayesianConfig(objective_metric="latency"),
                    "random": RandomSamplingConfig(n_samples=50),
                }
            }
        }

        result = json.dumps(metadata, default=IOPSRunner._json_serialize_helper)
        parsed = json.loads(result)

        assert parsed["benchmark"]["config"]["bayesian"]["objective_metric"] == "latency"
        assert parsed["benchmark"]["config"]["random"]["n_samples"] == 50

    def test_dump_mixed_types(self):
        """Test json.dump with mixed standard and special types."""
        metadata = {
            "string": "hello",
            "integer": 42,
            "float": 3.14,
            "list": [1, 2, 3],
            "numpy_int": np.int64(100),
            "numpy_array": np.array([4, 5, 6]),
            "dataclass": BayesianConfig(),
        }

        result = json.dumps(metadata, default=IOPSRunner._json_serialize_helper)
        parsed = json.loads(result)

        assert parsed["string"] == "hello"
        assert parsed["integer"] == 42
        assert parsed["float"] == 3.14
        assert parsed["list"] == [1, 2, 3]
        assert parsed["numpy_int"] == 100
        assert parsed["numpy_array"] == [4, 5, 6]
        assert isinstance(parsed["dataclass"], dict)
