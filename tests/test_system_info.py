"""Comprehensive unit tests for system information collection feature.

This module tests the automatic collection of system information from compute nodes
during benchmark execution. The feature involves:
1. Config option: collect_system_info (default True)
2. System probe injection in generated scripts
3. System info reading by executors
4. Aggregation by runner for reports
"""

import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from iops.config.models import GenericBenchmarkConfig, BenchmarkConfig
from iops.execution.planner import BasePlanner, ExhaustivePlanner, SYSTEM_PROBE_TEMPLATE, PROBE_FILENAME
from iops.execution.executors import BaseExecutor, SYSINFO_FILENAME
from iops.execution.matrix import ExecutionInstance
from iops.execution.runner import IOPSRunner
from conftest import load_config


# ============================================================================ #
# Config Tests - collect_system_info field
# ============================================================================ #

def test_config_collect_system_info_default_true(sample_config_dict, tmp_path):
    """Test that collect_system_info defaults to True."""
    config_file = tmp_path / "test_config.yaml"
    import yaml
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    # Default should be True
    assert config.benchmark.collect_system_info is True


def test_config_collect_system_info_can_be_disabled(sample_config_dict, tmp_path):
    """Test that collect_system_info can be set to False."""
    config_file = tmp_path / "test_config.yaml"
    import yaml

    # Explicitly set to False
    sample_config_dict["benchmark"]["collect_system_info"] = False

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    assert config.benchmark.collect_system_info is False


def test_config_collect_system_info_can_be_enabled(sample_config_dict, tmp_path):
    """Test that collect_system_info can be explicitly set to True."""
    config_file = tmp_path / "test_config.yaml"
    import yaml

    # Explicitly set to True
    sample_config_dict["benchmark"]["collect_system_info"] = True

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    assert config.benchmark.collect_system_info is True


# ============================================================================ #
# Probe Injection Tests - _inject_system_probe and _prepare_execution_artifacts
# ============================================================================ #

def test_system_probe_template_structure():
    """Test that SYSTEM_PROBE_TEMPLATE contains expected content."""
    # Verify key components of the probe
    assert "_iops_collect_sysinfo" in SYSTEM_PROBE_TEMPLATE
    assert "trap '_iops_collect_sysinfo' EXIT" in SYSTEM_PROBE_TEMPLATE
    assert "__iops_sysinfo.json" in SYSTEM_PROBE_TEMPLATE
    assert "hostname" in SYSTEM_PROBE_TEMPLATE
    assert "cpu_model" in SYSTEM_PROBE_TEMPLATE
    assert "cpu_cores" in SYSTEM_PROBE_TEMPLATE
    assert "memory_kb" in SYSTEM_PROBE_TEMPLATE
    assert "kernel" in SYSTEM_PROBE_TEMPLATE
    assert "os" in SYSTEM_PROBE_TEMPLATE
    assert "ib_devices" in SYSTEM_PROBE_TEMPLATE
    assert "filesystems" in SYSTEM_PROBE_TEMPLATE
    assert "duration_seconds" in SYSTEM_PROBE_TEMPLATE
    # Verify duration_seconds uses $SECONDS (bash built-in)
    # Note: Template uses ${{SECONDS}} to escape Python string formatting
    assert "${{SECONDS}}" in SYSTEM_PROBE_TEMPLATE
    # Verify it uses EXIT trap
    assert "EXIT" in SYSTEM_PROBE_TEMPLATE
    # Verify error handling (never fail)
    assert "2>/dev/null" in SYSTEM_PROBE_TEMPLATE
    assert "|| true" in SYSTEM_PROBE_TEMPLATE


def test_inject_system_probe_creates_separate_file(sample_config_file, tmp_path):
    """Test that system probe is written to a separate file."""
    config = load_config(sample_config_file)
    planner = ExhaustivePlanner(config)

    script_text = "#!/bin/bash\necho 'test'\necho 'more content'"
    exec_dir = tmp_path / "test_exec"
    exec_dir.mkdir(parents=True, exist_ok=True)

    result = planner._inject_system_probe(script_text, exec_dir)

    # Probe file should be created
    probe_file = exec_dir / PROBE_FILENAME
    assert probe_file.exists(), "Probe file should be created"

    # Probe file should contain the probe content
    probe_content = probe_file.read_text()
    assert "_iops_collect_sysinfo" in probe_content
    assert "trap '_iops_collect_sysinfo' EXIT" in probe_content
    assert str(exec_dir) in probe_content

    # User script should NOT contain probe functions (only source line)
    assert "_iops_collect_sysinfo" not in result
    assert "trap '_iops_collect_sysinfo' EXIT" not in result

    # User script should contain source line
    assert f'source "{probe_file}"' in result

    # Original content should be preserved
    assert "#!/bin/bash\n" in result
    assert "echo 'test'" in result
    assert "echo 'more content'" in result


def test_inject_system_probe_preserves_slurm_directives(sample_config_file, tmp_path):
    """Test that system probe doesn't interfere with SLURM #SBATCH directives."""
    config = load_config(sample_config_file)
    planner = ExhaustivePlanner(config)

    script_text = """#!/bin/bash
#SBATCH --job-name=test
#SBATCH --nodes=2
#SBATCH --constraint=bora

module load mpi
mpirun ./my_app"""
    exec_dir = tmp_path / "test_exec"
    exec_dir.mkdir(parents=True, exist_ok=True)

    result = planner._inject_system_probe(script_text, exec_dir)

    # Source line should be at the end
    source_pos = result.find("source")
    for directive in ["#SBATCH --job-name", "#SBATCH --nodes", "#SBATCH --constraint"]:
        directive_pos = result.find(directive)
        assert directive_pos < source_pos, f"{directive} should be before source line"

    # Original user commands should also be before source line
    assert result.find("module load mpi") < source_pos
    assert result.find("mpirun ./my_app") < source_pos


def test_inject_system_probe_empty_script(sample_config_file, tmp_path):
    """Test probe injection with empty script."""
    config = load_config(sample_config_file)
    planner = ExhaustivePlanner(config)

    script_text = ""
    exec_dir = tmp_path / "test_exec"
    exec_dir.mkdir(parents=True, exist_ok=True)

    result = planner._inject_system_probe(script_text, exec_dir)

    # Probe file should be created even with empty script
    probe_file = exec_dir / PROBE_FILENAME
    assert probe_file.exists()
    probe_content = probe_file.read_text()
    assert "_iops_collect_sysinfo" in probe_content
    assert "trap '_iops_collect_sysinfo' EXIT" in probe_content

    # User script should have source line
    assert "source" in result


def test_prepare_execution_artifacts_injects_probe_when_enabled(sample_config_file, tmp_path):
    """Test that _prepare_execution_artifacts creates probe file when collect_system_info=True."""
    config = load_config(sample_config_file)
    config.benchmark.collect_system_info = True  # Ensure enabled

    planner = ExhaustivePlanner(config)
    planner._build_execution_matrix()

    test = planner.execution_matrix[0]

    # Prepare artifacts
    planner._prepare_execution_artifacts(test, repetition=1)

    # Probe file should be created
    probe_file = test.execution_dir / PROBE_FILENAME
    assert probe_file.exists(), "Probe file should be created"

    # Probe file should contain probe content
    probe_content = probe_file.read_text()
    assert "_iops_collect_sysinfo" in probe_content
    assert "trap '_iops_collect_sysinfo' EXIT" in probe_content
    assert "__iops_sysinfo.json" in probe_content

    # User script should have source line (not inline probe)
    script_content = test.script_file.read_text()
    assert "source" in script_content
    assert PROBE_FILENAME in script_content


def test_prepare_execution_artifacts_skips_probe_when_disabled(sample_config_file, tmp_path):
    """Test that _prepare_execution_artifacts skips probe when collect_system_info=False."""
    config = load_config(sample_config_file)
    config.benchmark.collect_system_info = False  # Explicitly disable

    planner = ExhaustivePlanner(config)
    planner._build_execution_matrix()

    test = planner.execution_matrix[0]

    # Prepare artifacts
    planner._prepare_execution_artifacts(test, repetition=1)

    # Probe file should NOT be created
    probe_file = test.execution_dir / PROBE_FILENAME
    assert not probe_file.exists(), "Probe file should not be created when disabled"

    # User script should NOT have source line for probe
    script_content = test.script_file.read_text()
    assert PROBE_FILENAME not in script_content


def test_prepare_execution_artifacts_probe_default_behavior(sample_config_file, tmp_path):
    """Test that probe is created by default (when collect_system_info not specified)."""
    config = load_config(sample_config_file)
    # Don't set collect_system_info - should default to True

    planner = ExhaustivePlanner(config)
    planner._build_execution_matrix()

    test = planner.execution_matrix[0]

    # Prepare artifacts
    planner._prepare_execution_artifacts(test, repetition=1)

    # Probe file should be created (default behavior)
    probe_file = test.execution_dir / PROBE_FILENAME
    assert probe_file.exists(), "Probe file should be created by default"

    probe_content = probe_file.read_text()
    assert "_iops_collect_sysinfo" in probe_content
    assert "trap '_iops_collect_sysinfo' EXIT" in probe_content


# ============================================================================ #
# Bash Compatibility Tests
# ============================================================================ #

from iops.config.loader import _is_bash_compatible


def test_is_bash_compatible_with_bash_submit():
    """Test that bash submit command is always compatible."""
    # bash submit should always be compatible, regardless of shebang
    assert _is_bash_compatible("#!/bin/sh\necho hello", "bash") is True
    assert _is_bash_compatible("#!/bin/bash\necho hello", "bash") is True
    assert _is_bash_compatible("echo hello", "bash") is True
    assert _is_bash_compatible("#!/bin/sh\necho hello", "BASH") is True
    assert _is_bash_compatible("#!/bin/sh\necho hello", "/usr/bin/bash") is True


def test_is_bash_compatible_with_sh_submit():
    """Test that sh submit command is never compatible."""
    # sh submit should never be compatible
    assert _is_bash_compatible("#!/bin/bash\necho hello", "sh") is False
    assert _is_bash_compatible("#!/bin/sh\necho hello", "sh") is False
    assert _is_bash_compatible("echo hello", "sh") is False


def test_is_bash_compatible_with_sbatch_and_bash_shebang():
    """Test sbatch with bash shebang is compatible."""
    # sbatch respects shebang - bash shebang is OK
    assert _is_bash_compatible("#!/bin/bash\necho hello", "sbatch") is True
    assert _is_bash_compatible("#!/usr/bin/env bash\necho hello", "sbatch") is True


def test_is_bash_compatible_with_sbatch_and_sh_shebang():
    """Test sbatch with sh shebang is not compatible."""
    # sbatch respects shebang - sh shebang is NOT OK
    assert _is_bash_compatible("#!/bin/sh\necho hello", "sbatch") is False
    assert _is_bash_compatible("#!/usr/bin/env sh\necho hello", "sbatch") is False


def test_is_bash_compatible_with_unknown_command_and_no_shebang():
    """Test unknown command with no shebang assumes compatible."""
    # Unknown command + no shebang → assume OK (most systems default to bash)
    assert _is_bash_compatible("echo hello", "my_wrapper") is True
    assert _is_bash_compatible("", "custom_submit") is True


def test_is_bash_compatible_with_unknown_command_and_sh_shebang():
    """Test unknown command with sh shebang is not compatible."""
    # Unknown command + sh shebang → NOT compatible
    assert _is_bash_compatible("#!/bin/sh\necho hello", "my_wrapper") is False


def test_check_system_probe_compatibility_disables_for_sh_script(sample_config_dict, tmp_path):
    """Test that check_system_probe_compatibility disables collect_system_info for sh scripts."""
    import yaml
    from iops.config.loader import check_system_probe_compatibility

    # Set script to use #!/bin/sh shebang with sbatch
    sample_config_dict["scripts"][0]["script_template"] = "#!/bin/sh\necho hello\n"
    sample_config_dict["scripts"][0]["submit"] = "sbatch"

    config_file = tmp_path / "test_config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    # Load config
    config = load_config(config_file)

    # Initially enabled (default)
    assert config.benchmark.collect_system_info is True

    # Check compatibility - should disable and warn
    check_system_probe_compatibility(config, logger=None)

    # collect_system_info should be automatically disabled
    assert config.benchmark.collect_system_info is False


def test_check_system_probe_compatibility_keeps_for_bash_script(sample_config_dict, tmp_path):
    """Test that check_system_probe_compatibility keeps collect_system_info for bash scripts."""
    import yaml
    from iops.config.loader import check_system_probe_compatibility

    # Set script to use #!/bin/bash shebang with sbatch
    sample_config_dict["scripts"][0]["script_template"] = "#!/bin/bash\necho hello\n"
    sample_config_dict["scripts"][0]["submit"] = "sbatch"

    config_file = tmp_path / "test_config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    # Load config
    config = load_config(config_file)

    # Check compatibility - should keep enabled
    check_system_probe_compatibility(config, logger=None)

    # collect_system_info should remain enabled
    assert config.benchmark.collect_system_info is True


def test_prepare_execution_artifacts_injects_probe_for_bash_script(sample_config_file, tmp_path):
    """Test that probe is injected when script uses #!/bin/bash shebang."""
    config = load_config(sample_config_file)
    config.benchmark.collect_system_info = True

    planner = ExhaustivePlanner(config)
    planner._build_execution_matrix()

    test = planner.execution_matrix[0]
    # Modify script template to use #!/bin/bash (script_text/submit_cmd are properties)
    test.script_template = "#!/bin/bash\necho hello\n"
    test.submit_cmd_template = "sbatch"

    # Prepare artifacts
    planner._prepare_execution_artifacts(test, repetition=1)

    # Probe file SHOULD be created
    probe_file = test.execution_dir / PROBE_FILENAME
    assert probe_file.exists(), "Probe file should be created for bash scripts"


# ============================================================================ #
# System Info Collection Tests - BaseExecutor methods
# ============================================================================ #

@pytest.fixture
def mock_executor():
    """Create a mock executor for testing."""
    # Create a concrete implementation of BaseExecutor for testing
    class TestExecutor(BaseExecutor):
        def submit(self, test):
            pass

        def wait_and_collect(self, test):
            pass

    config = Mock()
    executor = TestExecutor(config)
    return executor


@pytest.fixture
def sample_sysinfo_data():
    """Sample system info data matching probe output format."""
    return {
        "hostname": "compute-node-01",
        "cpu_model": "Intel(R) Xeon(R) CPU E5-2680 v4 @ 2.40GHz",
        "cpu_cores": 56,
        "memory_kb": 131072000,
        "kernel": "5.4.0-42-generic",
        "os": "Ubuntu 20.04.1 LTS",
        "ib_devices": "mlx5_0,mlx5_1",
        "filesystems": "lustre:/scratch,gpfs:/projects",
        "duration_seconds": 120
    }


def test_collect_system_info_reads_valid_json(mock_executor, tmp_path, sample_sysinfo_data):
    """Test that _collect_system_info reads and parses valid JSON."""
    # Create test instance with execution_dir
    test = Mock(spec=ExecutionInstance)
    test.execution_dir = tmp_path / "exec_001"
    test.execution_dir.mkdir(parents=True, exist_ok=True)

    # Write sysinfo JSON
    sysinfo_path = test.execution_dir / SYSINFO_FILENAME
    with open(sysinfo_path, 'w') as f:
        json.dump(sample_sysinfo_data, f)

    # Collect system info
    result = mock_executor._collect_system_info(test)

    assert result is not None
    assert result["hostname"] == "compute-node-01"
    assert result["cpu_model"] == "Intel(R) Xeon(R) CPU E5-2680 v4 @ 2.40GHz"
    assert result["cpu_cores"] == 56
    assert result["memory_kb"] == 131072000
    assert result["kernel"] == "5.4.0-42-generic"
    assert result["os"] == "Ubuntu 20.04.1 LTS"


def test_collect_system_info_returns_none_when_file_missing(mock_executor, tmp_path):
    """Test that _collect_system_info returns None when file doesn't exist."""
    test = Mock(spec=ExecutionInstance)
    test.execution_dir = tmp_path / "exec_001"
    test.execution_dir.mkdir(parents=True, exist_ok=True)
    # Don't create sysinfo file

    result = mock_executor._collect_system_info(test)

    assert result is None


def test_collect_system_info_returns_none_when_execution_dir_none(mock_executor):
    """Test that _collect_system_info returns None when execution_dir is None."""
    test = Mock(spec=ExecutionInstance)
    test.execution_dir = None

    result = mock_executor._collect_system_info(test)

    assert result is None


def test_collect_system_info_handles_malformed_json(mock_executor, tmp_path):
    """Test that _collect_system_info handles malformed JSON gracefully."""
    test = Mock(spec=ExecutionInstance)
    test.execution_dir = tmp_path / "exec_001"
    test.execution_dir.mkdir(parents=True, exist_ok=True)

    # Write malformed JSON
    sysinfo_path = test.execution_dir / SYSINFO_FILENAME
    with open(sysinfo_path, 'w') as f:
        f.write("{ invalid json content [")

    result = mock_executor._collect_system_info(test)

    # Should return None, not raise exception
    assert result is None


def test_collect_system_info_handles_empty_file(mock_executor, tmp_path):
    """Test that _collect_system_info handles empty file gracefully."""
    test = Mock(spec=ExecutionInstance)
    test.execution_dir = tmp_path / "exec_001"
    test.execution_dir.mkdir(parents=True, exist_ok=True)

    # Write empty file
    sysinfo_path = test.execution_dir / SYSINFO_FILENAME
    sysinfo_path.touch()

    result = mock_executor._collect_system_info(test)

    assert result is None


def test_collect_system_info_handles_missing_fields(mock_executor, tmp_path):
    """Test that _collect_system_info validates expected fields."""
    test = Mock(spec=ExecutionInstance)
    test.execution_dir = tmp_path / "exec_001"
    test.execution_dir.mkdir(parents=True, exist_ok=True)

    # Write JSON with missing required fields
    sysinfo_path = test.execution_dir / SYSINFO_FILENAME
    with open(sysinfo_path, 'w') as f:
        json.dump({"some_field": "value"}, f)  # Missing hostname, cpu_model, etc.

    result = mock_executor._collect_system_info(test)

    # Should return None for incomplete data
    assert result is None


def test_collect_system_info_handles_trailing_period(mock_executor, tmp_path, sample_sysinfo_data):
    """Test that _collect_system_info handles trailing period from shell escaping."""
    test = Mock(spec=ExecutionInstance)
    test.execution_dir = tmp_path / "exec_001"
    test.execution_dir.mkdir(parents=True, exist_ok=True)

    # Write JSON with trailing period (from shell script workaround)
    sysinfo_path = test.execution_dir / SYSINFO_FILENAME
    with open(sysinfo_path, 'w') as f:
        json.dump(sample_sysinfo_data, f)

    # Add trailing period to simulate shell output
    content = sysinfo_path.read_text()
    sysinfo_path.write_text(content + ".")

    result = mock_executor._collect_system_info(test)

    # Should still parse correctly
    assert result is not None
    assert result["hostname"] == "compute-node-01"


def test_store_system_info_stores_in_metadata(mock_executor, tmp_path, sample_sysinfo_data):
    """Test that _store_system_info stores sysinfo in test metadata."""
    test = Mock(spec=ExecutionInstance)
    test.execution_dir = tmp_path / "exec_001"
    test.execution_dir.mkdir(parents=True, exist_ok=True)
    test.metadata = {}

    # Write sysinfo JSON
    sysinfo_path = test.execution_dir / SYSINFO_FILENAME
    with open(sysinfo_path, 'w') as f:
        json.dump(sample_sysinfo_data, f)

    # Store system info
    mock_executor._store_system_info(test)

    # Should be stored in metadata
    assert "__sysinfo" in test.metadata
    assert test.metadata["__sysinfo"]["hostname"] == "compute-node-01"
    assert test.metadata["__sysinfo"]["cpu_cores"] == 56


def test_store_system_info_does_nothing_when_no_file(mock_executor, tmp_path):
    """Test that _store_system_info does nothing when sysinfo file missing."""
    test = Mock(spec=ExecutionInstance)
    test.execution_dir = tmp_path / "exec_001"
    test.execution_dir.mkdir(parents=True, exist_ok=True)
    test.metadata = {}

    # No sysinfo file exists

    mock_executor._store_system_info(test)

    # Metadata should not have __sysinfo
    assert "__sysinfo" not in test.metadata


# ============================================================================ #
# Runner Aggregation Tests - _track_system_info and _aggregate_system_info
# ============================================================================ #

@pytest.fixture
def mock_runner(sample_config_file):
    """Create a mock runner for testing."""
    config = load_config(sample_config_file)
    args = Mock()
    args.use_cache = False
    args.max_core_hours = None
    args.time_estimate = None
    args.log_level = "INFO"

    runner = IOPSRunner(config, args)
    return runner


def test_track_system_info_collects_new_hostname(mock_runner, sample_sysinfo_data):
    """Test that _track_system_info tracks system info from new hostname."""
    test = Mock(spec=ExecutionInstance)
    test.metadata = {"__sysinfo": sample_sysinfo_data}

    mock_runner._track_system_info(test)

    # Should be added to collected_system_info
    assert "compute-node-01" in mock_runner.collected_system_info
    assert mock_runner.collected_system_info["compute-node-01"]["cpu_cores"] == 56


def test_track_system_info_deduplicates_by_hostname(mock_runner, sample_sysinfo_data):
    """Test that _track_system_info deduplicates by hostname."""
    test1 = Mock(spec=ExecutionInstance)
    test1.metadata = {"__sysinfo": sample_sysinfo_data.copy()}

    test2 = Mock(spec=ExecutionInstance)
    # Same hostname, different data (simulating multiple tests on same node)
    test2_sysinfo = sample_sysinfo_data.copy()
    test2_sysinfo["cpu_cores"] = 999  # Modified data
    test2.metadata = {"__sysinfo": test2_sysinfo}

    # Track both tests
    mock_runner._track_system_info(test1)
    mock_runner._track_system_info(test2)

    # Should only have one entry for the hostname (first one wins)
    assert len(mock_runner.collected_system_info) == 1
    assert mock_runner.collected_system_info["compute-node-01"]["cpu_cores"] == 56  # Original


def test_track_system_info_handles_multiple_nodes(mock_runner, sample_sysinfo_data):
    """Test that _track_system_info tracks multiple different nodes."""
    test1 = Mock(spec=ExecutionInstance)
    test1.metadata = {"__sysinfo": sample_sysinfo_data.copy()}

    test2 = Mock(spec=ExecutionInstance)
    test2_sysinfo = sample_sysinfo_data.copy()
    test2_sysinfo["hostname"] = "compute-node-02"
    test2.metadata = {"__sysinfo": test2_sysinfo}

    test3 = Mock(spec=ExecutionInstance)
    test3_sysinfo = sample_sysinfo_data.copy()
    test3_sysinfo["hostname"] = "compute-node-03"
    test3.metadata = {"__sysinfo": test3_sysinfo}

    # Track all tests
    mock_runner._track_system_info(test1)
    mock_runner._track_system_info(test2)
    mock_runner._track_system_info(test3)

    # Should have three entries
    assert len(mock_runner.collected_system_info) == 3
    assert "compute-node-01" in mock_runner.collected_system_info
    assert "compute-node-02" in mock_runner.collected_system_info
    assert "compute-node-03" in mock_runner.collected_system_info


def test_track_system_info_handles_missing_sysinfo(mock_runner):
    """Test that _track_system_info handles tests without sysinfo gracefully."""
    test = Mock(spec=ExecutionInstance)
    test.metadata = {}  # No __sysinfo

    mock_runner._track_system_info(test)

    # Should not add anything
    assert len(mock_runner.collected_system_info) == 0


def test_track_system_info_handles_missing_hostname(mock_runner):
    """Test that _track_system_info handles sysinfo without hostname."""
    test = Mock(spec=ExecutionInstance)
    test.metadata = {"__sysinfo": {"cpu_cores": 56}}  # No hostname field

    mock_runner._track_system_info(test)

    # Should track with "unknown" hostname
    assert "unknown" in mock_runner.collected_system_info


def test_aggregate_system_info_empty_collection(mock_runner):
    """Test that _aggregate_system_info returns empty dict when no info collected."""
    result = mock_runner._aggregate_system_info()

    assert result == {}


def test_aggregate_system_info_single_node(mock_runner, sample_sysinfo_data):
    """Test aggregation with single node."""
    mock_runner.collected_system_info["compute-node-01"] = sample_sysinfo_data

    result = mock_runner._aggregate_system_info()

    assert result["nodes"] == ["compute-node-01"]
    assert result["node_count"] == 1
    assert result["cpu_model"] == "Intel(R) Xeon(R) CPU E5-2680 v4 @ 2.40GHz"
    assert result["cpu_cores_per_node"] == 56
    assert result["kernel"] == "5.4.0-42-generic"
    assert result["os"] == "Ubuntu 20.04.1 LTS"


def test_aggregate_system_info_multiple_identical_nodes(mock_runner, sample_sysinfo_data):
    """Test aggregation with multiple nodes having identical hardware."""
    mock_runner.collected_system_info["node-01"] = sample_sysinfo_data.copy()
    mock_runner.collected_system_info["node-02"] = sample_sysinfo_data.copy()
    mock_runner.collected_system_info["node-03"] = sample_sysinfo_data.copy()

    result = mock_runner._aggregate_system_info()

    assert result["node_count"] == 3
    assert len(result["nodes"]) == 3
    # Should show single value for identical hardware
    assert result["cpu_cores_per_node"] == 56  # Not a range
    assert result["memory_gb_per_node"] == pytest.approx(125.0, abs=1.0)


def test_aggregate_system_info_heterogeneous_nodes(mock_runner, sample_sysinfo_data):
    """Test aggregation with nodes having different hardware."""
    node1_info = sample_sysinfo_data.copy()
    node1_info["hostname"] = "node-01"
    node1_info["cpu_cores"] = 32
    node1_info["memory_kb"] = 65536000

    node2_info = sample_sysinfo_data.copy()
    node2_info["hostname"] = "node-02"
    node2_info["cpu_cores"] = 64
    node2_info["memory_kb"] = 131072000

    mock_runner.collected_system_info["node-01"] = node1_info
    mock_runner.collected_system_info["node-02"] = node2_info

    result = mock_runner._aggregate_system_info()

    assert result["node_count"] == 2
    # Should show range for different values
    assert result["cpu_cores_per_node"] == "32-64"
    assert "memory_gb_per_node" in result
    # Memory should be a range string
    assert "-" in str(result["memory_gb_per_node"])


def test_aggregate_system_info_filesystems_parsing(mock_runner, sample_sysinfo_data):
    """Test that filesystems are properly parsed and aggregated."""
    mock_runner.collected_system_info["node-01"] = sample_sysinfo_data

    result = mock_runner._aggregate_system_info()

    assert "filesystems" in result
    assert "lustre:/scratch" in result["filesystems"]
    assert "gpfs:/projects" in result["filesystems"]


def test_aggregate_system_info_ib_devices_parsing(mock_runner, sample_sysinfo_data):
    """Test that InfiniBand devices are properly parsed."""
    mock_runner.collected_system_info["node-01"] = sample_sysinfo_data

    result = mock_runner._aggregate_system_info()

    assert "interconnect" in result
    assert "mlx5_0" in result["interconnect"]
    assert "mlx5_1" in result["interconnect"]


def test_aggregate_system_info_includes_detailed_info(mock_runner, sample_sysinfo_data):
    """Test that aggregated result includes detailed per-node info."""
    mock_runner.collected_system_info["node-01"] = sample_sysinfo_data

    result = mock_runner._aggregate_system_info()

    assert "nodes_detail" in result
    assert "node-01" in result["nodes_detail"]
    assert result["nodes_detail"]["node-01"]["cpu_cores"] == 56


def test_aggregate_system_info_handles_missing_optional_fields(mock_runner):
    """Test aggregation with minimal sysinfo (only required fields)."""
    minimal_info = {
        "hostname": "node-01",
        "cpu_model": "Intel Xeon",
        "cpu_cores": 32,
        "memory_kb": 65536000,
        "kernel": "5.4.0"
    }
    mock_runner.collected_system_info["node-01"] = minimal_info

    result = mock_runner._aggregate_system_info()

    # Should not crash, should have basic fields
    assert result["nodes"] == ["node-01"]
    assert result["node_count"] == 1
    assert result["cpu_cores_per_node"] == 32
    # Optional fields should be absent (not raise KeyError)
    assert "filesystems" not in result or not result["filesystems"]
    assert "interconnect" not in result or not result["interconnect"]


def test_aggregate_system_info_memory_conversion_to_gb(mock_runner, sample_sysinfo_data):
    """Test that memory is properly converted from KB to GB."""
    mock_runner.collected_system_info["node-01"] = sample_sysinfo_data

    result = mock_runner._aggregate_system_info()

    # 131072000 KB should be ~125 GB
    assert "memory_gb_per_node" in result
    memory_gb = result["memory_gb_per_node"]
    assert isinstance(memory_gb, float)
    assert 120 < memory_gb < 130  # Approximate check


# ============================================================================ #
# Integration Tests - End-to-End System Info Flow
# ============================================================================ #

def test_system_info_end_to_end_enabled(sample_config_file, tmp_path):
    """Test complete system info flow when enabled."""
    config = load_config(sample_config_file)
    config.benchmark.collect_system_info = True

    # 1. Planner generates script with probe
    planner = ExhaustivePlanner(config)
    planner._build_execution_matrix()
    test = planner.execution_matrix[0]
    planner._prepare_execution_artifacts(test, repetition=1)

    # Verify probe file is created and script sources it
    probe_file = test.execution_dir / PROBE_FILENAME
    assert probe_file.exists()
    probe_content = probe_file.read_text()
    assert "_iops_collect_sysinfo" in probe_content

    script_content = test.script_file.read_text()
    assert "source" in script_content
    assert PROBE_FILENAME in script_content

    # 2. Simulate executor collecting sysinfo
    sysinfo_data = {
        "hostname": "test-node",
        "cpu_model": "Test CPU",
        "cpu_cores": 16,
        "memory_kb": 32768000,
        "kernel": "5.4.0"
    }
    sysinfo_path = test.execution_dir / SYSINFO_FILENAME
    with open(sysinfo_path, 'w') as f:
        json.dump(sysinfo_data, f)

    # 3. Executor stores in metadata
    # Create a concrete executor implementation for testing
    class TestExecutor(BaseExecutor):
        def submit(self, test):
            pass
        def wait_and_collect(self, test):
            pass

    executor = TestExecutor(config)
    executor._store_system_info(test)

    assert "__sysinfo" in test.metadata
    assert test.metadata["__sysinfo"]["hostname"] == "test-node"

    # 4. Runner tracks and aggregates
    args = Mock()
    args.use_cache = False
    args.max_core_hours = None
    args.time_estimate = None
    args.log_level = "INFO"
    runner = IOPSRunner(config, args)
    runner._track_system_info(test)

    result = runner._aggregate_system_info()
    assert result["nodes"] == ["test-node"]
    assert result["node_count"] == 1


def test_system_info_end_to_end_disabled(sample_config_file, tmp_path):
    """Test complete system info flow when disabled."""
    config = load_config(sample_config_file)
    config.benchmark.collect_system_info = False

    # 1. Planner generates script WITHOUT probe
    planner = ExhaustivePlanner(config)
    planner._build_execution_matrix()
    test = planner.execution_matrix[0]
    planner._prepare_execution_artifacts(test, repetition=1)

    # Verify probe file is NOT created
    probe_file = test.execution_dir / PROBE_FILENAME
    assert not probe_file.exists()

    # Verify script has NO source line for probe
    script_content = test.script_file.read_text()
    assert PROBE_FILENAME not in script_content

    # 2. Runner should not have any system info
    args = Mock()
    args.use_cache = False
    args.max_core_hours = None
    args.time_estimate = None
    args.log_level = "INFO"
    runner = IOPSRunner(config, args)

    result = runner._aggregate_system_info()
    assert result == {}


def test_system_info_with_multiple_repetitions(sample_config_file, tmp_path, sample_sysinfo_data):
    """Test that system info is collected once per node despite multiple repetitions."""
    config = load_config(sample_config_file)
    config.benchmark.repetitions = 3

    planner = ExhaustivePlanner(config)

    args = Mock()
    args.use_cache = False
    args.max_core_hours = None
    args.time_estimate = None
    args.log_level = "INFO"
    runner = IOPSRunner(config, args)

    # Simulate multiple tests on same node
    for rep in range(3):
        test = Mock(spec=ExecutionInstance)
        test.metadata = {"__sysinfo": sample_sysinfo_data.copy()}
        runner._track_system_info(test)

    # Should only have one entry despite 3 repetitions
    assert len(runner.collected_system_info) == 1
    assert "compute-node-01" in runner.collected_system_info


# ============================================================================ #
# Edge Case Tests
# ============================================================================ #

def test_collect_system_info_with_special_characters(mock_executor, tmp_path):
    """Test system info with special characters in values."""
    test = Mock(spec=ExecutionInstance)
    test.execution_dir = tmp_path / "exec_001"
    test.execution_dir.mkdir(parents=True, exist_ok=True)

    sysinfo_data = {
        "hostname": "node-with-dashes-123",
        "cpu_model": "Intel(R) Xeon(R) CPU @ 2.40GHz \"Skylake\"",
        "cpu_cores": 32,
        "memory_kb": 65536000,
        "kernel": "5.4.0-42-generic"
    }

    sysinfo_path = test.execution_dir / SYSINFO_FILENAME
    with open(sysinfo_path, 'w') as f:
        json.dump(sysinfo_data, f)

    result = mock_executor._collect_system_info(test)

    assert result is not None
    assert result["hostname"] == "node-with-dashes-123"
    # Quotes should be preserved in JSON
    assert '"Skylake"' in result["cpu_model"]


def test_aggregate_system_info_with_empty_strings(mock_runner):
    """Test aggregation with empty string values."""
    sysinfo_data = {
        "hostname": "node-01",
        "cpu_model": "Intel Xeon",
        "cpu_cores": 32,
        "memory_kb": 65536000,
        "kernel": "5.4.0",
        "ib_devices": "",  # Empty
        "filesystems": ""  # Empty
    }
    mock_runner.collected_system_info["node-01"] = sysinfo_data

    result = mock_runner._aggregate_system_info()

    # Should not include empty fields in result
    assert "interconnect" not in result or not result["interconnect"]
    assert "filesystems" not in result or not result["filesystems"]


def test_probe_template_is_safe_bash(sample_config_file, tmp_path):
    """Test that probe template generates valid, safe bash."""
    config = load_config(sample_config_file)
    planner = ExhaustivePlanner(config)

    script_text = "#!/bin/bash\necho 'test'"
    exec_dir = tmp_path / "test"
    exec_dir.mkdir(parents=True, exist_ok=True)

    planner._inject_system_probe(script_text, exec_dir)

    # Read the probe file content
    probe_file = exec_dir / PROBE_FILENAME
    probe_content = probe_file.read_text()

    # Verify bash safety features
    assert "2>/dev/null" in probe_content  # Error suppression
    assert "|| true" in probe_content  # Never fail
    assert "|| echo" in probe_content  # Fallback values

    # Verify it won't break scripts
    assert "set -e" not in probe_content  # Doesn't set strict mode
    # Verify EXIT trap is used (not explicit exit commands in the probe itself)
    assert "trap '_iops_collect_sysinfo' EXIT" in probe_content
    # The word "exit" in "EXIT" (trap) is okay, but no standalone "exit" commands
    assert "\nexit " not in probe_content and "\nexit\n" not in probe_content


def test_system_probe_with_path_containing_spaces(sample_config_file, tmp_path):
    """Test probe injection with execution_dir containing spaces."""
    config = load_config(sample_config_file)
    planner = ExhaustivePlanner(config)

    script_text = "#!/bin/bash\necho 'test'"
    exec_dir = tmp_path / "test dir with spaces" / "exec_001"
    exec_dir.mkdir(parents=True, exist_ok=True)

    result = planner._inject_system_probe(script_text, exec_dir)

    # Probe file should be created
    probe_file = exec_dir / PROBE_FILENAME
    assert probe_file.exists()

    # Probe file should contain the path with spaces
    probe_content = probe_file.read_text()
    assert "test dir with spaces" in probe_content

    # User script source line should have quoted path
    assert f'source "{probe_file}"' in result


# ============================================================================ #
# Core-Hours Calculation Tests - _compute_core_hours with duration_seconds
# ============================================================================ #

def test_compute_core_hours_uses_sysinfo_duration(mock_runner, sample_sysinfo_data):
    """Test that _compute_core_hours prefers duration_seconds from sysinfo."""
    test = Mock(spec=ExecutionInstance)
    test.execution_id = 1
    test.vars = {"nodes": 1, "ppn": 4}  # For cores calculation (will use default 1)
    test.metadata = {
        "__sysinfo": sample_sysinfo_data,  # duration_seconds = 120
        "__start": "2024-01-01T00:00:00",
        "__end": "2024-01-01T00:10:00",  # 10 minutes = 600 seconds
    }

    # With default cores_expr = "1", 120 seconds = 120/3600 hours = 0.0333... core-hours
    result = mock_runner._compute_core_hours(test)

    # Should use sysinfo duration (120s), not timestamps (600s)
    expected = 1 * (120 / 3600.0)  # cores * hours
    assert result == pytest.approx(expected, abs=0.001)


def test_compute_core_hours_falls_back_to_timestamps(mock_runner):
    """Test that _compute_core_hours falls back to timestamps when sysinfo unavailable."""
    test = Mock(spec=ExecutionInstance)
    test.execution_id = 1
    test.vars = {"nodes": 1}
    test.metadata = {
        "__start": "2024-01-01T00:00:00",
        "__end": "2024-01-01T00:10:00",  # 10 minutes = 600 seconds
        # No __sysinfo
    }

    result = mock_runner._compute_core_hours(test)

    # Should use timestamps (600 seconds)
    expected = 1 * (600 / 3600.0)  # cores * hours
    assert result == pytest.approx(expected, abs=0.001)


def test_compute_core_hours_falls_back_when_sysinfo_missing_duration(mock_runner):
    """Test fallback when sysinfo exists but lacks duration_seconds."""
    test = Mock(spec=ExecutionInstance)
    test.execution_id = 1
    test.vars = {"nodes": 1}
    test.metadata = {
        "__sysinfo": {
            "hostname": "test-node",
            "cpu_cores": 32,
            # No duration_seconds field
        },
        "__start": "2024-01-01T00:00:00",
        "__end": "2024-01-01T00:05:00",  # 5 minutes = 300 seconds
    }

    result = mock_runner._compute_core_hours(test)

    # Should use timestamps (300 seconds)
    expected = 1 * (300 / 3600.0)  # cores * hours
    assert result == pytest.approx(expected, abs=0.001)


def test_compute_core_hours_returns_zero_when_no_timing_info(mock_runner):
    """Test that _compute_core_hours returns 0 when no timing info available."""
    test = Mock(spec=ExecutionInstance)
    test.execution_id = 1
    test.vars = {"nodes": 1}
    test.metadata = {}  # No sysinfo, no timestamps

    result = mock_runner._compute_core_hours(test)

    assert result == 0.0


def test_compute_core_hours_handles_invalid_sysinfo_duration(mock_runner):
    """Test fallback when sysinfo has invalid duration_seconds value."""
    test = Mock(spec=ExecutionInstance)
    test.execution_id = 1
    test.vars = {"nodes": 1}
    test.metadata = {
        "__sysinfo": {
            "hostname": "test-node",
            "duration_seconds": "invalid",  # Not a number
        },
        "__start": "2024-01-01T00:00:00",
        "__end": "2024-01-01T00:02:00",  # 2 minutes = 120 seconds
    }

    result = mock_runner._compute_core_hours(test)

    # Should fall back to timestamps (120 seconds)
    expected = 1 * (120 / 3600.0)
    assert result == pytest.approx(expected, abs=0.001)


def test_compute_core_hours_accurate_for_slurm_jobs(mock_runner, sample_sysinfo_data):
    """Test that core-hours are accurate for SLURM jobs (using actual execution time).

    This test demonstrates the fix for the queue wait time issue. Previously,
    _compute_core_hours used __start (job submission) to __end (job completion),
    which included queue wait time. Now it uses duration_seconds from sysinfo
    which captures only the actual script execution time.
    """
    test = Mock(spec=ExecutionInstance)
    test.execution_id = 1
    test.vars = {"nodes": 1}

    # Simulate a job that was queued for 10 minutes, then ran for 2 minutes
    # __start is when we submitted, __end is when we detected completion
    test.metadata = {
        "__sysinfo": {
            "hostname": "compute-node",
            "duration_seconds": 120,  # Actual execution: 2 minutes
        },
        "__start": "2024-01-01T00:00:00",  # Submitted at 00:00
        "__end": "2024-01-01T00:12:00",    # Completed at 00:12 (10min queue + 2min run)
    }

    result = mock_runner._compute_core_hours(test)

    # Should use 120 seconds (actual execution), NOT 720 seconds (total including queue)
    expected = 1 * (120 / 3600.0)  # 0.0333... core-hours
    wrong_value = 1 * (720 / 3600.0)  # 0.2 core-hours (what it would be with queue time)

    assert result == pytest.approx(expected, abs=0.001)
    assert result != pytest.approx(wrong_value, abs=0.001)
