"""Tests for parser script context injection.

Tests that parser scripts have access to execution context variables:
- vars: Dict of all execution variables
- env: Dict of rendered command.env variables
- execution_id: The execution ID
- execution_dir: The execution directory path
- workdir: The root working directory path
- repetition: The current repetition number
- repetitions: Total number of repetitions
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock

from iops.execution.parser import (
    _build_parse_fn,
    parse_metrics_from_execution,
    ParserScriptError,
    ParserContractError,
)
from iops.config.models import ParserConfig, MetricConfig


class TestBuildParseFnWithContext:
    """Tests for _build_parse_fn with context injection."""

    def test_vars_accessible_in_parser(self):
        """Parser script can access vars global."""
        script = """
def parse(file_path):
    return {"result": vars["nodes"] * 10}
"""
        context = {"vars": {"nodes": 4, "ppn": 8}}
        fn = _build_parse_fn(script, context)
        result = fn("/tmp/test.txt")
        assert result == {"result": 40}

    def test_env_accessible_in_parser(self):
        """Parser script can access env global."""
        script = """
def parse(file_path):
    return {"result": int(env["MY_VALUE"])}
"""
        context = {"vars": {}, "env": {"MY_VALUE": "123", "OTHER": "abc"}}
        fn = _build_parse_fn(script, context)
        result = fn("/tmp/test.txt")
        assert result == {"result": 123}

    def test_execution_id_accessible_in_parser(self):
        """Parser script can access execution_id global."""
        script = """
def parse(file_path):
    return {"exec_id": execution_id}
"""
        context = {"vars": {}, "env": {}, "execution_id": "exec_0042"}
        fn = _build_parse_fn(script, context)
        result = fn("/tmp/test.txt")
        assert result == {"exec_id": "exec_0042"}

    def test_repetition_accessible_in_parser(self):
        """Parser script can access repetition global."""
        script = """
def parse(file_path):
    return {"rep": repetition}
"""
        context = {"vars": {}, "env": {}, "repetition": 3}
        fn = _build_parse_fn(script, context)
        result = fn("/tmp/test.txt")
        assert result == {"rep": 3}

    def test_execution_dir_accessible_in_parser(self):
        """Parser script can access execution_dir global."""
        script = """
def parse(file_path):
    return {"exec_dir": execution_dir}
"""
        context = {"vars": {}, "env": {}, "execution_dir": "/path/to/exec_0001"}
        fn = _build_parse_fn(script, context)
        result = fn("/tmp/test.txt")
        assert result == {"exec_dir": "/path/to/exec_0001"}

    def test_workdir_accessible_in_parser(self):
        """Parser script can access workdir global."""
        script = """
def parse(file_path):
    return {"work_dir": workdir}
"""
        context = {"vars": {}, "env": {}, "workdir": "/path/to/workdir"}
        fn = _build_parse_fn(script, context)
        result = fn("/tmp/test.txt")
        assert result == {"work_dir": "/path/to/workdir"}

    def test_repetitions_accessible_in_parser(self):
        """Parser script can access repetitions global."""
        script = """
def parse(file_path):
    return {"total_reps": repetitions}
"""
        context = {"vars": {}, "env": {}, "repetitions": 5}
        fn = _build_parse_fn(script, context)
        result = fn("/tmp/test.txt")
        assert result == {"total_reps": 5}

    def test_all_context_variables_accessible(self):
        """Parser script can access all context variables together."""
        script = """
def parse(file_path):
    return {
        "nodes": vars["nodes"],
        "env_val": env["TEST"],
        "exec": execution_id,
        "exec_dir": execution_dir,
        "work_dir": workdir,
        "rep": repetition,
        "total_reps": repetitions,
    }
"""
        context = {
            "vars": {"nodes": 8, "ppn": 4},
            "env": {"TEST": "hello"},
            "execution_id": "exec_0001",
            "execution_dir": "/workdir/runs/exec_0001",
            "workdir": "/workdir",
            "repetition": 2,
            "repetitions": 5,
        }
        fn = _build_parse_fn(script, context)
        result = fn("/tmp/test.txt")
        assert result == {
            "nodes": 8,
            "env_val": "hello",
            "exec": "exec_0001",
            "exec_dir": "/workdir/runs/exec_0001",
            "work_dir": "/workdir",
            "rep": 2,
            "total_reps": 5,
        }

    def test_backwards_compatibility_without_context(self):
        """Parser script works without context (backwards compatibility)."""
        script = """
def parse(file_path):
    return {"result": 42}
"""
        fn = _build_parse_fn(script)  # No context
        result = fn("/tmp/test.txt")
        assert result == {"result": 42}

    def test_empty_context(self):
        """Parser script works with empty context dict."""
        script = """
def parse(file_path):
    return {"result": 99}
"""
        fn = _build_parse_fn(script, {})
        result = fn("/tmp/test.txt")
        assert result == {"result": 99}

    def test_vars_used_for_computation(self):
        """Parser can use vars for derived metric computation."""
        script = """
def parse(file_path):
    total_bw = 1000  # simulated parsed value
    # Compute per-node throughput
    per_node = total_bw / vars["nodes"]
    return {"throughput_per_node": per_node}
"""
        context = {"vars": {"nodes": 4}}
        fn = _build_parse_fn(script, context)
        result = fn("/tmp/test.txt")
        assert result == {"throughput_per_node": 250.0}

    def test_conditional_logic_based_on_vars(self):
        """Parser can use conditional logic based on vars."""
        script = """
def parse(file_path):
    if vars["operation"] == "write":
        return {"metric": 100}
    else:
        return {"metric": 200}
"""
        # Test write operation
        context = {"vars": {"operation": "write"}}
        fn = _build_parse_fn(script, context)
        assert fn("/tmp/test.txt") == {"metric": 100}

        # Test read operation
        context = {"vars": {"operation": "read"}}
        fn = _build_parse_fn(script, context)
        assert fn("/tmp/test.txt") == {"metric": 200}

    def test_env_with_default_value(self):
        """Parser can use env.get() for optional env vars."""
        script = """
def parse(file_path):
    val = env.get("OPTIONAL_VAR", "default_value")
    return {"result": val}
"""
        # Without the optional var
        context = {"env": {}}
        fn = _build_parse_fn(script, context)
        assert fn("/tmp/test.txt") == {"result": "default_value"}

        # With the optional var
        context = {"env": {"OPTIONAL_VAR": "custom_value"}}
        fn = _build_parse_fn(script, context)
        assert fn("/tmp/test.txt") == {"result": "custom_value"}

    def test_accessing_undefined_var_raises_error(self):
        """Accessing undefined var key raises KeyError."""
        script = """
def parse(file_path):
    return {"result": vars["nonexistent"]}
"""
        context = {"vars": {"nodes": 4}}
        fn = _build_parse_fn(script, context)
        # Direct call raises KeyError; ParserScriptError wrapping happens in parse_metrics_from_execution
        with pytest.raises(KeyError) as exc_info:
            fn("/tmp/test.txt")
        assert "nonexistent" in str(exc_info.value)

    def test_complex_computation_with_multiple_vars(self):
        """Parser can perform complex computations with multiple vars."""
        script = """
def parse(file_path):
    # Simulate: efficiency = bandwidth / (nodes * ppn * block_size)
    bandwidth = 8000  # simulated parsed value
    total_cores = vars["nodes"] * vars["ppn"]
    efficiency = bandwidth / (total_cores * vars["block_size_mb"])
    return {
        "bandwidth": bandwidth,
        "efficiency": round(efficiency, 2),
        "total_cores": total_cores,
    }
"""
        context = {"vars": {"nodes": 2, "ppn": 4, "block_size_mb": 100}}
        fn = _build_parse_fn(script, context)
        result = fn("/tmp/test.txt")
        assert result == {
            "bandwidth": 8000,
            "efficiency": 10.0,  # 8000 / (8 * 100)
            "total_cores": 8,
        }


class TestParseMetricsFromExecution:
    """Tests for parse_metrics_from_execution with full ExecutionInstance."""

    def _create_mock_execution(
        self,
        vars_dict: dict,
        env_dict: dict,
        execution_id: str,
        repetition: int,
        parser_file: str,
        parser_script: str,
        metrics: list[str],
        execution_dir: str = "/workdir/runs/exec_0001",
        workdir: str = "/workdir",
        repetitions: int = 3,
    ):
        """Create a mock ExecutionInstance with the given attributes."""
        mock = MagicMock()
        mock.vars = vars_dict
        mock.env = env_dict
        mock.execution_id = execution_id
        mock.execution_dir = execution_dir
        mock.workdir = workdir
        mock.repetition = repetition
        mock.repetitions = repetitions

        # Create parser config
        metric_configs = [MetricConfig(name=name) for name in metrics]
        parser_config = ParserConfig(
            file=parser_file,
            metrics=metric_configs,
            parser_script=parser_script,
        )
        mock.parser = parser_config

        return mock

    def test_vars_passed_to_parser(self, tmp_path):
        """Vars from ExecutionInstance are passed to parser script."""
        # Create a test output file
        output_file = tmp_path / "output.txt"
        output_file.write_text("bandwidth: 1000\n")

        parser_script = """
def parse(file_path):
    with open(file_path) as f:
        line = f.read()
    bw = float(line.split(':')[1])
    # Use vars to compute per-node metric
    return {"throughput_per_node": bw / vars["nodes"]}
"""
        mock_exec = self._create_mock_execution(
            vars_dict={"nodes": 4, "ppn": 8},
            env_dict={},
            execution_id="exec_0001",
            repetition=1,
            parser_file=str(output_file),
            parser_script=parser_script,
            metrics=["throughput_per_node"],
        )

        result = parse_metrics_from_execution(mock_exec)
        assert result["metrics"]["throughput_per_node"] == 250.0

    def test_env_passed_to_parser(self, tmp_path):
        """Env from ExecutionInstance are passed to parser script."""
        output_file = tmp_path / "output.txt"
        output_file.write_text("value: 42\n")

        parser_script = """
def parse(file_path):
    # Use env variable in computation
    multiplier = int(env.get("MULTIPLIER", "1"))
    return {"result": 42 * multiplier}
"""
        mock_exec = self._create_mock_execution(
            vars_dict={},
            env_dict={"MULTIPLIER": "10"},
            execution_id="exec_0001",
            repetition=1,
            parser_file=str(output_file),
            parser_script=parser_script,
            metrics=["result"],
        )

        result = parse_metrics_from_execution(mock_exec)
        assert result["metrics"]["result"] == 420

    def test_execution_id_passed_to_parser(self, tmp_path):
        """Execution ID from ExecutionInstance is passed to parser script."""
        output_file = tmp_path / "output.txt"
        output_file.write_text("data\n")

        parser_script = """
def parse(file_path):
    # Return execution_id as part of result
    return {"exec_id_suffix": int(execution_id.split("_")[1])}
"""
        mock_exec = self._create_mock_execution(
            vars_dict={},
            env_dict={},
            execution_id="exec_0042",
            repetition=1,
            parser_file=str(output_file),
            parser_script=parser_script,
            metrics=["exec_id_suffix"],
        )

        result = parse_metrics_from_execution(mock_exec)
        assert result["metrics"]["exec_id_suffix"] == 42

    def test_repetition_passed_to_parser(self, tmp_path):
        """Repetition from ExecutionInstance is passed to parser script."""
        output_file = tmp_path / "output.txt"
        output_file.write_text("data\n")

        parser_script = """
def parse(file_path):
    return {"rep_number": repetition}
"""
        mock_exec = self._create_mock_execution(
            vars_dict={},
            env_dict={},
            execution_id="exec_0001",
            repetition=5,
            parser_file=str(output_file),
            parser_script=parser_script,
            metrics=["rep_number"],
        )

        result = parse_metrics_from_execution(mock_exec)
        assert result["metrics"]["rep_number"] == 5

    def test_execution_dir_passed_to_parser(self, tmp_path):
        """Execution dir from ExecutionInstance is passed to parser script."""
        output_file = tmp_path / "output.txt"
        output_file.write_text("data\n")

        parser_script = """
def parse(file_path):
    return {"exec_dir": execution_dir}
"""
        mock_exec = self._create_mock_execution(
            vars_dict={},
            env_dict={},
            execution_id="exec_0001",
            repetition=1,
            parser_file=str(output_file),
            parser_script=parser_script,
            metrics=["exec_dir"],
            execution_dir="/workdir/runs/exec_0042",
        )

        result = parse_metrics_from_execution(mock_exec)
        assert result["metrics"]["exec_dir"] == "/workdir/runs/exec_0042"

    def test_workdir_passed_to_parser(self, tmp_path):
        """Workdir from ExecutionInstance is passed to parser script."""
        output_file = tmp_path / "output.txt"
        output_file.write_text("data\n")

        parser_script = """
def parse(file_path):
    return {"work_dir": workdir}
"""
        mock_exec = self._create_mock_execution(
            vars_dict={},
            env_dict={},
            execution_id="exec_0001",
            repetition=1,
            parser_file=str(output_file),
            parser_script=parser_script,
            metrics=["work_dir"],
            workdir="/my/workdir/path",
        )

        result = parse_metrics_from_execution(mock_exec)
        assert result["metrics"]["work_dir"] == "/my/workdir/path"

    def test_repetitions_passed_to_parser(self, tmp_path):
        """Repetitions from ExecutionInstance is passed to parser script."""
        output_file = tmp_path / "output.txt"
        output_file.write_text("data\n")

        parser_script = """
def parse(file_path):
    return {"total_reps": repetitions}
"""
        mock_exec = self._create_mock_execution(
            vars_dict={},
            env_dict={},
            execution_id="exec_0001",
            repetition=1,
            parser_file=str(output_file),
            parser_script=parser_script,
            metrics=["total_reps"],
            repetitions=10,
        )

        result = parse_metrics_from_execution(mock_exec)
        assert result["metrics"]["total_reps"] == 10

    def test_full_context_integration(self, tmp_path):
        """Full integration test with all context variables."""
        output_file = tmp_path / "output.json"
        output_file.write_text('{"raw_bw": 2000, "latency": 5.5}')

        parser_script = """
import json

def parse(file_path):
    with open(file_path) as f:
        data = json.load(f)

    raw_bw = data["raw_bw"]
    latency = data["latency"]

    # Use vars for normalization
    nodes = vars["nodes"]
    ppn = vars["ppn"]
    total_procs = nodes * ppn

    # Use env for scaling factor
    scale = float(env.get("SCALE_FACTOR", "1.0"))

    return {
        "bandwidth_per_node": raw_bw / nodes * scale,
        "bandwidth_per_proc": raw_bw / total_procs * scale,
        "latency": latency,
        "repetition_id": f"{execution_id}_r{repetition}",
    }
"""
        mock_exec = self._create_mock_execution(
            vars_dict={"nodes": 4, "ppn": 8},
            env_dict={"SCALE_FACTOR": "1.5"},
            execution_id="exec_0010",
            repetition=3,
            parser_file=str(output_file),
            parser_script=parser_script,
            metrics=["bandwidth_per_node", "bandwidth_per_proc", "latency", "repetition_id"],
        )

        result = parse_metrics_from_execution(mock_exec)
        metrics = result["metrics"]

        assert metrics["bandwidth_per_node"] == 750.0  # 2000/4 * 1.5
        assert metrics["bandwidth_per_proc"] == 93.75  # 2000/32 * 1.5
        assert metrics["latency"] == 5.5
        assert metrics["repetition_id"] == "exec_0010_r3"

    def test_parser_without_using_context(self, tmp_path):
        """Parser that doesn't use context still works (backwards compatible)."""
        output_file = tmp_path / "output.txt"
        output_file.write_text("result: 123\n")

        parser_script = """
def parse(file_path):
    with open(file_path) as f:
        line = f.read()
    val = float(line.split(':')[1])
    return {"result": val}
"""
        mock_exec = self._create_mock_execution(
            vars_dict={"nodes": 4},
            env_dict={"TEST": "value"},
            execution_id="exec_0001",
            repetition=1,
            parser_file=str(output_file),
            parser_script=parser_script,
            metrics=["result"],
        )

        result = parse_metrics_from_execution(mock_exec)
        assert result["metrics"]["result"] == 123.0
