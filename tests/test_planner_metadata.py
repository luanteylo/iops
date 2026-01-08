"""Unit tests for planner metadata file generation (_write_params_file, _update_index_file)."""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from iops.execution.planner import (
    BasePlanner,
    ExhaustivePlanner,
    PARAMS_FILENAME,
    INDEX_FILENAME,
)
from iops.execution.matrix import ExecutionInstance
from iops.config.models import GenericBenchmarkConfig


class TestWriteParamsFile:
    """Test _write_params_file method that creates __iops_params.json."""

    def test_write_params_basic(self, sample_config_file):
        """Test basic params file creation with simple variables."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        # Create test execution instance with base_vars
        test = ExecutionInstance(
            execution_id=1,
            base_vars={"nodes": 4, "ppn": 8, "total_procs": 32},
            repetitions=1,
        )

        exec_dir = workdir / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)

        # Call the method
        planner._write_params_file(test, exec_dir)

        # Verify params file was created
        params_file = exec_dir / PARAMS_FILENAME
        assert params_file.exists()

        # Verify content
        with open(params_file, 'r') as f:
            params = json.load(f)

        assert params == {"nodes": 4, "ppn": 8, "total_procs": 32}

    def test_write_params_filters_internal_vars(self, sample_config_file):
        """Test that variables starting with __ are filtered out."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        # Create test with internal variables
        test = ExecutionInstance(
            execution_id=1,
            base_vars={
                "nodes": 4,
                "ppn": 8,
                "__internal_cache_key": "abc123",
                "__iops_version": "3.0.0",
                "user_var": "value"
            },
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )

        exec_dir = workdir / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)

        planner._write_params_file(test, exec_dir)

        # Verify internal vars are excluded
        params_file = exec_dir / PARAMS_FILENAME
        with open(params_file, 'r') as f:
            params = json.load(f)

        assert "nodes" in params
        assert "ppn" in params
        assert "user_var" in params
        assert "__internal_cache_key" not in params
        assert "__iops_version" not in params

    def test_write_params_with_different_types(self, sample_config_file):
        """Test params file with various data types."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        test = ExecutionInstance(
            execution_id=1,
            base_vars={
                "int_var": 42,
                "float_var": 3.14,
                "str_var": "test_string",
                "bool_var": True,
                "list_var": [1, 2, 3],  # Should be serialized correctly
            },
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )

        exec_dir = workdir / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)

        planner._write_params_file(test, exec_dir)

        params_file = exec_dir / PARAMS_FILENAME
        with open(params_file, 'r') as f:
            params = json.load(f)

        assert params["int_var"] == 42
        assert params["float_var"] == 3.14
        assert params["str_var"] == "test_string"
        assert params["bool_var"] is True
        assert params["list_var"] == [1, 2, 3]

    def test_write_params_empty_vars(self, sample_config_file):
        """Test params file creation with no variables."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        test = ExecutionInstance(
            execution_id=1,
            base_vars={},
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )

        exec_dir = workdir / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)

        planner._write_params_file(test, exec_dir)

        params_file = exec_dir / PARAMS_FILENAME
        assert params_file.exists()

        with open(params_file, 'r') as f:
            params = json.load(f)

        assert params == {}

    def test_write_params_only_internal_vars(self, sample_config_file):
        """Test params file when all variables are internal (should create empty params)."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        test = ExecutionInstance(
            execution_id=1,
            base_vars={
                "__internal1": "value1",
                "__internal2": "value2",
            },
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )

        exec_dir = workdir / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)

        planner._write_params_file(test, exec_dir)

        params_file = exec_dir / PARAMS_FILENAME
        with open(params_file, 'r') as f:
            params = json.load(f)

        assert params == {}

    def test_write_params_json_formatting(self, sample_config_file):
        """Test that JSON is formatted with indentation for readability."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        test = ExecutionInstance(
            execution_id=1,
            base_vars={"nodes": 4, "ppn": 8},
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )

        exec_dir = workdir / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)

        planner._write_params_file(test, exec_dir)

        params_file = exec_dir / PARAMS_FILENAME
        content = params_file.read_text()

        # Should have indentation (pretty-printed JSON)
        assert '  "nodes"' in content or '  "ppn"' in content
        # Should have newlines (not single line)
        assert content.count('\n') > 1


class TestUpdateIndexFile:
    """Test _update_index_file method that creates/updates __iops_index.json."""

    def test_update_index_creates_new_file(self, sample_config_file):
        """Test that index file is created if it doesn't exist."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        test = ExecutionInstance(
            execution_id=1,
            base_vars={"nodes": 4, "ppn": 8},
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )

        exec_dir = workdir / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)

        params = {"nodes": 4, "ppn": 8}
        planner._update_index_file(test, params, exec_dir)

        # Verify index file was created in run root (workdir)
        index_file = workdir / INDEX_FILENAME
        assert index_file.exists()

        with open(index_file, 'r') as f:
            index = json.load(f)

        assert "benchmark" in index
        assert "executions" in index
        assert index["benchmark"] == "Test Benchmark"
        assert "exec_0001" in index["executions"]

    def test_update_index_relative_path(self, sample_config_file):
        """Test that execution paths are stored as relative paths."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        test = ExecutionInstance(
            execution_id=1,
            base_vars={"nodes": 4, "ppn": 8},
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )

        exec_dir = workdir / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)

        params = {"nodes": 4, "ppn": 8}
        planner._update_index_file(test, params, exec_dir)

        index_file = workdir / INDEX_FILENAME
        with open(index_file, 'r') as f:
            index = json.load(f)

        # Path should be relative to workdir
        exec_entry = index["executions"]["exec_0001"]
        assert exec_entry["path"] == "runs/exec_0001"
        # Should not contain absolute path
        assert str(workdir) not in exec_entry["path"]

    def test_update_index_multiple_executions(self, sample_config_file):
        """Test that index is updated with multiple executions."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        # Add first execution
        test1 = ExecutionInstance(
            execution_id=1,
            base_vars={"nodes": 1, "ppn": 4},
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )
        exec_dir1 = workdir / "runs" / "exec_0001"
        exec_dir1.mkdir(parents=True)
        planner._update_index_file(test1, {"nodes": 1, "ppn": 4}, exec_dir1)

        # Add second execution
        test2 = ExecutionInstance(
            execution_id=2,
            base_vars={"nodes": 2, "ppn": 8},
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )
        exec_dir2 = workdir / "runs" / "exec_0002"
        exec_dir2.mkdir(parents=True)
        planner._update_index_file(test2, {"nodes": 2, "ppn": 8}, exec_dir2)

        # Verify both executions in index
        index_file = workdir / INDEX_FILENAME
        with open(index_file, 'r') as f:
            index = json.load(f)

        assert len(index["executions"]) == 2
        assert "exec_0001" in index["executions"]
        assert "exec_0002" in index["executions"]

        # Verify parameters
        assert index["executions"]["exec_0001"]["params"] == {"nodes": 1, "ppn": 4}
        assert index["executions"]["exec_0002"]["params"] == {"nodes": 2, "ppn": 8}

        # Verify paths
        assert index["executions"]["exec_0001"]["path"] == "runs/exec_0001"
        assert index["executions"]["exec_0002"]["path"] == "runs/exec_0002"

    def test_update_index_preserves_existing_entries(self, sample_config_file):
        """Test that updating index preserves existing executions."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        # Create initial index manually
        index_file = workdir / INDEX_FILENAME
        initial_index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1}},
                "exec_0002": {"path": "runs/exec_0002", "params": {"nodes": 2}},
            }
        }
        with open(index_file, 'w') as f:
            json.dump(initial_index, f)

        # Add new execution
        test3 = ExecutionInstance(
            execution_id=3,
            base_vars={"nodes": 4, "ppn": 16},
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )
        exec_dir3 = workdir / "runs" / "exec_0003"
        exec_dir3.mkdir(parents=True)
        planner._update_index_file(test3, {"nodes": 4, "ppn": 16}, exec_dir3)

        # Verify all executions are preserved
        with open(index_file, 'r') as f:
            index = json.load(f)

        assert len(index["executions"]) == 3
        assert "exec_0001" in index["executions"]
        assert "exec_0002" in index["executions"]
        assert "exec_0003" in index["executions"]

    def test_update_index_execution_structure(self, sample_config_file):
        """Test that execution entries have correct structure."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        test = ExecutionInstance(
            execution_id=5,
            base_vars={"nodes": 8, "ppn": 16, "block_size": "1M"},
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )

        exec_dir = workdir / "runs" / "exec_0005"
        exec_dir.mkdir(parents=True)

        params = {"nodes": 8, "ppn": 16, "block_size": "1M"}
        planner._update_index_file(test, params, exec_dir)

        index_file = workdir / INDEX_FILENAME
        with open(index_file, 'r') as f:
            index = json.load(f)

        exec_entry = index["executions"]["exec_0005"]

        # Should have both path and params
        assert "path" in exec_entry
        assert "params" in exec_entry
        assert isinstance(exec_entry["path"], str)
        assert isinstance(exec_entry["params"], dict)

        # Params should match input
        assert exec_entry["params"] == params

    def test_update_index_benchmark_name(self, sample_config_file):
        """Test that benchmark name is stored in index."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        test = ExecutionInstance(
            execution_id=1,
            base_vars={"nodes": 4},
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )

        exec_dir = workdir / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)

        planner._update_index_file(test, {"nodes": 4}, exec_dir)

        index_file = workdir / INDEX_FILENAME
        with open(index_file, 'r') as f:
            index = json.load(f)

        assert index["benchmark"] == "Test Benchmark"

    def test_update_index_json_formatting(self, sample_config_file):
        """Test that index JSON is formatted with indentation."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        test = ExecutionInstance(
            execution_id=1,
            base_vars={"nodes": 4, "ppn": 8},
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )

        exec_dir = workdir / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)

        planner._update_index_file(test, {"nodes": 4, "ppn": 8}, exec_dir)

        index_file = workdir / INDEX_FILENAME
        content = index_file.read_text()

        # Should have indentation
        assert '  "benchmark"' in content or '  "executions"' in content
        # Should be multi-line
        assert content.count('\n') > 3


class TestPrepareExecutionArtifactsIntegration:
    """Test that _prepare_execution_artifacts calls metadata file methods correctly."""

    def test_prepare_creates_params_file_first_repetition(self, sample_config_file):
        """Test that _prepare_execution_artifacts creates params file on first repetition."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        test = ExecutionInstance(
            execution_id=1,
            base_vars={"nodes": 4, "ppn": 8},
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=3,
        )

        # Call with first repetition
        planner._prepare_execution_artifacts(test, repetition=1)

        # Verify params file was created
        params_file = workdir / "runs" / "exec_0001" / PARAMS_FILENAME
        assert params_file.exists()

        # Verify index file was created
        index_file = workdir / INDEX_FILENAME
        assert index_file.exists()

    def test_prepare_skips_params_file_subsequent_repetitions(self, sample_config_file):
        """Test that params file is only written once (first repetition)."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        test = ExecutionInstance(
            execution_id=1,
            base_vars={"nodes": 4, "ppn": 8},
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=3,
        )

        # First repetition
        planner._prepare_execution_artifacts(test, repetition=1)
        params_file = workdir / "runs" / "exec_0001" / PARAMS_FILENAME
        first_mtime = params_file.stat().st_mtime

        # Second repetition
        import time
        time.sleep(0.01)  # Small delay to ensure different mtime if file was rewritten
        planner._prepare_execution_artifacts(test, repetition=2)

        # Verify params file wasn't modified
        assert params_file.stat().st_mtime == first_mtime

    def test_prepare_creates_index_for_multiple_tests(self, sample_config_file):
        """Test that index accumulates entries from multiple test preparations."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        # Prepare first test
        test1 = ExecutionInstance(
            execution_id=1,
            base_vars={"nodes": 1, "ppn": 4},
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )
        planner._prepare_execution_artifacts(test1, repetition=1)

        # Prepare second test
        test2 = ExecutionInstance(
            execution_id=2,
            base_vars={"nodes": 2, "ppn": 8},
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )
        planner._prepare_execution_artifacts(test2, repetition=1)

        # Verify index has both entries
        index_file = workdir / INDEX_FILENAME
        with open(index_file, 'r') as f:
            index = json.load(f)

        assert len(index["executions"]) == 2
        assert "exec_0001" in index["executions"]
        assert "exec_0002" in index["executions"]


class TestMetadataFileEdgeCases:
    """Test edge cases and error conditions for metadata file generation."""

    def test_params_file_with_special_characters(self, sample_config_file):
        """Test params file handles special characters in values."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        test = ExecutionInstance(
            execution_id=1,
            base_vars={
                "path": "/path/with spaces/and-dashes",
                "pattern": "*.txt",
                "message": "Test with \"quotes\" and 'apostrophes'",
            },
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )

        exec_dir = workdir / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)

        planner._write_params_file(test, exec_dir)

        params_file = exec_dir / PARAMS_FILENAME
        with open(params_file, 'r') as f:
            params = json.load(f)

        # Verify special characters are preserved
        assert params["path"] == "/path/with spaces/and-dashes"
        assert params["pattern"] == "*.txt"
        assert params["message"] == "Test with \"quotes\" and 'apostrophes'"

    def test_index_with_zero_padded_execution_ids(self, sample_config_file):
        """Test that execution IDs are properly zero-padded in index keys."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        # Test various execution IDs
        for exec_id in [1, 10, 100, 999]:
            test = ExecutionInstance(
                execution_id=exec_id,
                base_vars={"test_id": exec_id},
                script_name="test_script",
                script_template="#!/bin/bash\necho test",
                repetitions=1,
            )

            exec_dir = workdir / "runs" / f"exec_{exec_id:04d}"
            exec_dir.mkdir(parents=True, exist_ok=True)

            planner._update_index_file(test, {"test_id": exec_id}, exec_dir)

        index_file = workdir / INDEX_FILENAME
        with open(index_file, 'r') as f:
            index = json.load(f)

        # Verify all keys are properly formatted
        assert "exec_0001" in index["executions"]
        assert "exec_0010" in index["executions"]
        assert "exec_0100" in index["executions"]
        assert "exec_0999" in index["executions"]

    def test_params_file_with_none_values(self, sample_config_file):
        """Test params file handles None values correctly."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        test = ExecutionInstance(
            execution_id=1,
            base_vars={
                "nodes": 4,
                "optional_param": None,
            },
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )

        exec_dir = workdir / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)

        planner._write_params_file(test, exec_dir)

        params_file = exec_dir / PARAMS_FILENAME
        with open(params_file, 'r') as f:
            params = json.load(f)

        assert params["nodes"] == 4
        assert params["optional_param"] is None

    def test_index_file_location(self, sample_config_file):
        """Test that index file is created in correct location (workdir root)."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        test = ExecutionInstance(
            execution_id=1,
            base_vars={"nodes": 4},
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )

        exec_dir = workdir / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)

        planner._update_index_file(test, {"nodes": 4}, exec_dir)

        # Index should be in workdir root, not in runs/ or exec_0001/
        index_in_workdir = workdir / INDEX_FILENAME
        index_in_runs = workdir / "runs" / INDEX_FILENAME
        index_in_exec = exec_dir / INDEX_FILENAME

        assert index_in_workdir.exists()
        assert not index_in_runs.exists()
        assert not index_in_exec.exists()

    def test_params_file_location(self, sample_config_file):
        """Test that params file is created in exec_XXXX folder, not repetition folder."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        test = ExecutionInstance(
            execution_id=1,
            base_vars={"nodes": 4},
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=3,
        )

        planner._prepare_execution_artifacts(test, repetition=1)

        # Params should be in exec_0001/, not in repetition_001/
        params_in_exec = workdir / "runs" / "exec_0001" / PARAMS_FILENAME
        params_in_rep = workdir / "runs" / "exec_0001" / "repetition_001" / PARAMS_FILENAME

        assert params_in_exec.exists()
        assert not params_in_rep.exists()

    def test_index_handles_non_serializable_values(self, sample_config_file):
        """Test that index file handles non-JSON-serializable values gracefully."""
        from conftest import load_config
        from datetime import datetime
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        # Path objects should be converted to strings by json.dump's default=str
        test = ExecutionInstance(
            execution_id=1,
            base_vars={
                "nodes": 4,
                "timestamp": datetime.now(),  # Not JSON serializable by default
            },
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )

        exec_dir = workdir / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)

        params = {"nodes": 4, "timestamp": datetime.now()}

        # Should not raise - json.dump uses default=str
        planner._update_index_file(test, params, exec_dir)

        index_file = workdir / INDEX_FILENAME
        assert index_file.exists()

        # Verify it's valid JSON
        with open(index_file, 'r') as f:
            index = json.load(f)

        assert "exec_0001" in index["executions"]
        # Timestamp should be converted to string
        assert isinstance(index["executions"]["exec_0001"]["params"]["timestamp"], str)

    def test_update_index_stores_command(self, sample_config_file):
        """Test that rendered command is stored in index file."""
        from conftest import load_config
        cfg = load_config(sample_config_file)
        planner = ExhaustivePlanner(cfg)
        workdir = Path(cfg.benchmark.workdir)

        test = ExecutionInstance(
            execution_id=1,
            base_vars={"nodes": 4, "ppn": 8},
            command_template="mpirun -np {{ nodes * ppn }} ./benchmark",
            script_name="test_script",
            script_template="#!/bin/bash\necho test",
            repetitions=1,
        )

        exec_dir = workdir / "runs" / "exec_0001"
        exec_dir.mkdir(parents=True)

        params = {"nodes": 4, "ppn": 8}
        planner._update_index_file(test, params, exec_dir)

        index_file = workdir / INDEX_FILENAME
        with open(index_file, 'r') as f:
            index = json.load(f)

        # Command should be stored and rendered
        exec_entry = index["executions"]["exec_0001"]
        assert "command" in exec_entry
        assert exec_entry["command"] == "mpirun -np 32 ./benchmark"
