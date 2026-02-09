# tests/test_parser_directory_bug.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from iops.execution.executors import SlurmExecutor
from iops.execution.matrix import ExecutionInstance


def test_slurm_parser_accepts_directory_with_parser_script(tmp_path):
    """Fix: When parser_script is defined, directories should be accepted."""
    
    # Create a directory with a result file
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "result.json").write_text('{"value": 42}')
    
    # Mock config
    cfg = MagicMock()
    cfg.benchmark.slurm_options = None
    cfg.benchmark.executor = "slurm"
    
    executor = SlurmExecutor(cfg)
    
    # Create mock test with parser.file pointing to a DIRECTORY
    test = MagicMock(spec=ExecutionInstance)
    test.parser = MagicMock()
    test.parser.file = str(output_dir)  # Directory, not file
    test.parser.parser_script = "def parse(p): return {'value': 42}"
    test.parser.metrics = [MagicMock(name="value")]
    test.metadata = {}
    test.execution_dir = tmp_path
    
    metrics = {"value": None}
    
    # Mock parse_metrics_from_execution to return expected result
    with patch('iops.execution.executors.parse_metrics_from_execution') as mock_parse:
        mock_parse.return_value = {"metrics": {"value": 42}}
        result = executor._try_parse_metrics(test, metrics)
    
    # Fix: should succeed because parser_script is defined
    assert result is True
    assert metrics["value"] == 42
    assert "__error" not in test.metadata or test.metadata.get("__error") is None


def test_slurm_parser_rejects_missing_path_with_parser_script(tmp_path):
    """Even with parser_script, non-existent paths should be rejected."""
    
    # Mock config
    cfg = MagicMock()
    cfg.benchmark.slurm_options = None
    cfg.benchmark.executor = "slurm"
    
    executor = SlurmExecutor(cfg)
    
    # Create mock test with parser.file pointing to NON-EXISTENT path
    test = MagicMock(spec=ExecutionInstance)
    test.parser = MagicMock()
    test.parser.file = str(tmp_path / "does_not_exist")
    test.parser.parser_script = "def parse(p): return {}"
    test.metadata = {}
    
    metrics = {"value": None}
    
    result = executor._try_parse_metrics(test, metrics)
    
    # Should fail because path doesn't exist at all
    assert result is False
    assert "does not exist" in test.metadata.get("__error", "")


def test_slurm_parser_rejects_directory_without_parser_script(tmp_path):
    """Without parser_script, directories should still be rejected (original behavior)."""
    
    # Create a directory
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    
    # Mock config
    cfg = MagicMock()
    cfg.benchmark.slurm_options = None
    cfg.benchmark.executor = "slurm"
    
    executor = SlurmExecutor(cfg)
    
    # Create mock test with parser.file pointing to a DIRECTORY but NO parser_script
    test = MagicMock(spec=ExecutionInstance)
    test.parser = MagicMock()
    test.parser.file = str(output_dir)
    test.parser.parser_script = None  # No parser_script
    test.metadata = {}
    
    metrics = {"value": None}
    
    result = executor._try_parse_metrics(test, metrics)
    
    # Should fail because no parser_script and path is a directory
    assert result is False
    assert "does not exist" in test.metadata.get("__error", "")