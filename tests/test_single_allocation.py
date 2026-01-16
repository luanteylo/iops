"""Tests for single-allocation SLURM mode."""

import pytest
import yaml
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from iops.config.models import (
    ConfigValidationError,
    AllocationConfig,
    SlurmOptionsConfig,
)
from iops.execution.executors import (
    BaseExecutor,
    SlurmExecutor,
    SingleAllocationSlurmExecutor,
)
from iops.execution.matrix import ExecutionInstance
from conftest import load_config


# ============================================================================ #
# AllocationConfig Parsing Tests
# ============================================================================ #


def test_allocation_config_defaults():
    """Test AllocationConfig default values."""
    config = AllocationConfig()

    assert config.mode == "per-test"
    assert config.allocation_script is None


def test_allocation_config_parsing(tmp_path, sample_config_dict):
    """Test that allocation config is properly parsed from YAML."""
    config_file = tmp_path / "alloc_config.yaml"

    # Add allocation config
    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["slurm_options"] = {
        "allocation": {
            "mode": "single",
            "allocation_script": """#SBATCH --nodes=8
#SBATCH --ntasks-per-node=4
#SBATCH --time=02:00:00
#SBATCH --partition=batch
#SBATCH --account=myaccount
#SBATCH --exclusive""",
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    assert config.benchmark.slurm_options is not None
    alloc = config.benchmark.slurm_options.allocation
    assert alloc is not None
    assert alloc.mode == "single"
    assert "#SBATCH --nodes=8" in alloc.allocation_script
    assert "#SBATCH --ntasks-per-node=4" in alloc.allocation_script
    assert "#SBATCH --time=02:00:00" in alloc.allocation_script
    assert "#SBATCH --partition=batch" in alloc.allocation_script
    assert "#SBATCH --account=myaccount" in alloc.allocation_script
    assert "#SBATCH --exclusive" in alloc.allocation_script


def test_allocation_config_per_test_mode(tmp_path, sample_config_dict):
    """Test that per-test mode is the default."""
    config_file = tmp_path / "per_test_config.yaml"

    # Add allocation config with per-test mode
    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["slurm_options"] = {
        "allocation": {
            "mode": "per-test"
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    alloc = config.benchmark.slurm_options.allocation
    assert alloc.mode == "per-test"
    # allocation_script not required for per-test mode


# ============================================================================ #
# AllocationConfig Validation Tests
# ============================================================================ #


def test_allocation_invalid_mode(tmp_path, sample_config_dict):
    """Test that invalid allocation mode raises error."""
    config_file = tmp_path / "invalid_mode.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["slurm_options"] = {
        "allocation": {
            "mode": "invalid"
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(config_file)

    assert "mode" in str(exc_info.value)
    assert "single" in str(exc_info.value) or "per-test" in str(exc_info.value)


def test_allocation_single_requires_slurm(tmp_path, sample_config_dict):
    """Test that single allocation mode requires slurm executor."""
    config_file = tmp_path / "local_single.yaml"

    # Local executor with single allocation mode
    sample_config_dict["benchmark"]["executor"] = "local"
    sample_config_dict["benchmark"]["slurm_options"] = {
        "allocation": {
            "mode": "single",
            "allocation_script": "#SBATCH --nodes=4\n#SBATCH --time=01:00:00"
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(config_file)

    assert "slurm" in str(exc_info.value).lower()


def test_allocation_single_requires_allocation_script(tmp_path, sample_config_dict):
    """Test that single allocation mode requires allocation_script."""
    config_file = tmp_path / "no_script.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["slurm_options"] = {
        "allocation": {
            "mode": "single",
            # allocation_script is missing
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(config_file)

    assert "allocation_script" in str(exc_info.value)


def test_allocation_script_requires_sbatch(tmp_path, sample_config_dict):
    """Test that allocation_script must contain #SBATCH directives."""
    config_file = tmp_path / "no_sbatch.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["slurm_options"] = {
        "allocation": {
            "mode": "single",
            "allocation_script": "echo 'no sbatch here'"  # No #SBATCH
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(config_file)

    assert "#SBATCH" in str(exc_info.value)


# ============================================================================ #
# Executor Build Tests
# ============================================================================ #


def test_executor_build_returns_slurm_for_per_test():
    """Test that BaseExecutor.build returns SlurmExecutor for per-test mode."""
    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor = "slurm"
    config.benchmark.slurm_options = SlurmOptionsConfig(
        allocation=AllocationConfig(mode="per-test")
    )

    executor = BaseExecutor.build(config)
    assert isinstance(executor, SlurmExecutor)


def test_executor_build_returns_single_alloc_for_single_mode():
    """Test that BaseExecutor.build returns SingleAllocationSlurmExecutor for single mode."""
    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor = "slurm"
    config.benchmark.slurm_options = SlurmOptionsConfig(
        allocation=AllocationConfig(
            mode="single",
            allocation_script="#SBATCH --nodes=4\n#SBATCH --time=01:00:00"
        )
    )

    executor = BaseExecutor.build(config)
    assert isinstance(executor, SingleAllocationSlurmExecutor)


def test_executor_build_returns_slurm_without_allocation():
    """Test that BaseExecutor.build returns SlurmExecutor when no allocation config."""
    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor = "slurm"
    config.benchmark.slurm_options = None

    executor = BaseExecutor.build(config)
    assert isinstance(executor, SlurmExecutor)


# ============================================================================ #
# SingleAllocationSlurmExecutor Tests
# ============================================================================ #


@pytest.fixture
def single_alloc_executor(tmp_path):
    """Create a SingleAllocationSlurmExecutor for testing."""
    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor = "slurm"
    config.benchmark.slurm_options = SlurmOptionsConfig(
        allocation=AllocationConfig(
            mode="single",
            allocation_script="""#SBATCH --nodes=4
#SBATCH --ntasks-per-node=8
#SBATCH --time=02:00:00
#SBATCH --partition=batch
#SBATCH --account=myaccount""",
        )
    )
    config.benchmark.workdir = tmp_path
    (tmp_path / "logs").mkdir()

    return SingleAllocationSlurmExecutor(config)


@pytest.fixture
def mock_test_instance(tmp_path):
    """Create a mock ExecutionInstance for testing."""
    test = Mock(spec=ExecutionInstance)
    test.execution_id = 1
    test.repetition = 1
    test.repetitions = 1
    test.execution_dir = tmp_path / "exec_001" / "repetition_001"
    test.execution_dir.mkdir(parents=True, exist_ok=True)
    test.script_file = test.execution_dir / "run_script.sh"
    test.script_file.write_text("#!/bin/bash\necho 'test'")
    test.post_script_file = None
    test.metadata = {}
    test.parser = Mock()
    test.parser.metrics = []
    test.vars = {"nodes": 2, "ppn": 4}
    return test


def test_single_alloc_generates_allocation_script(single_alloc_executor):
    """Test allocation script generation."""
    script = single_alloc_executor._generate_allocation_script()

    # Check shebang is added
    assert script.startswith("#!/bin/bash")

    # Check user directives are present
    assert "#SBATCH --nodes=4" in script
    assert "#SBATCH --ntasks-per-node=8" in script
    assert "#SBATCH --time=02:00:00" in script
    assert "#SBATCH --partition=batch" in script
    assert "#SBATCH --account=myaccount" in script

    # Check IOPS-generated directives
    assert "#SBATCH --job-name=iops_allocation" in script
    assert "#SBATCH --output=" in script
    assert "#SBATCH --error=" in script

    # Check sleep command is added
    assert "sleep" in script


def test_single_alloc_shebang_not_duplicated(tmp_path):
    """Test that shebang is not duplicated if user provides one."""
    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor = "slurm"
    config.benchmark.slurm_options = SlurmOptionsConfig(
        allocation=AllocationConfig(
            mode="single",
            allocation_script="""#!/bin/bash
#SBATCH --nodes=4
#SBATCH --time=01:00:00""",
        )
    )
    config.benchmark.workdir = tmp_path
    (tmp_path / "logs").mkdir()

    executor = SingleAllocationSlurmExecutor(config)
    script = executor._generate_allocation_script()

    # Should only have one shebang
    assert script.count("#!/bin/bash") == 1
    assert script.startswith("#!/bin/bash")


def test_single_alloc_first_submit_creates_allocation(single_alloc_executor, mock_test_instance):
    """Test that first submit() creates the allocation."""
    single_alloc_executor.poll_interval = 0.01  # Fast polling for test

    with patch("subprocess.run") as mock_run:
        # Mock sbatch submission
        mock_run.return_value = Mock(
            returncode=0,
            stdout="Submitted batch job 12345",
            stderr=""
        )

        with patch.object(single_alloc_executor, "_wait_for_allocation_running"):
            with patch.object(single_alloc_executor, "_run_test_in_allocation"):
                single_alloc_executor.submit(mock_test_instance)

        assert single_alloc_executor.allocation_submitted is True
        assert single_alloc_executor.allocation_job_id == "12345"


def test_single_alloc_subsequent_submits_reuse_allocation(single_alloc_executor, mock_test_instance):
    """Test that subsequent submit() calls reuse the existing allocation."""
    single_alloc_executor.allocation_submitted = True
    single_alloc_executor.allocation_job_id = "12345"

    with patch.object(single_alloc_executor, "_run_test_in_allocation") as mock_run:
        with patch.object(single_alloc_executor, "_squeue_state", return_value="RUNNING"):
            single_alloc_executor.submit(mock_test_instance)

        mock_run.assert_called_once_with(mock_test_instance)


def test_single_alloc_submit_failure(single_alloc_executor, mock_test_instance):
    """Test allocation submission failure."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="sbatch: error: Invalid partition"
        )

        # submit() catches the exception and sets error metadata
        single_alloc_executor.submit(mock_test_instance)

        assert mock_test_instance.metadata["__executor_status"] == BaseExecutor.STATUS_ERROR
        assert "Failed to create allocation" in mock_test_instance.metadata["__error"]


def test_single_alloc_check_allocation_alive(single_alloc_executor, mock_test_instance):
    """Test that submit() checks if allocation is still alive."""
    single_alloc_executor.allocation_submitted = True
    single_alloc_executor.allocation_job_id = "12345"

    # Test: allocation is dead (None state)
    with patch.object(single_alloc_executor, "_squeue_state", return_value=None):
        single_alloc_executor.submit(mock_test_instance)

        assert mock_test_instance.metadata["__executor_status"] == BaseExecutor.STATUS_FAILED
        assert "no longer available" in mock_test_instance.metadata["__error"]


def test_single_alloc_run_test_srun_command(single_alloc_executor, mock_test_instance):
    """Test that tests are run via srun with correct options."""
    single_alloc_executor.allocation_job_id = "12345"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        single_alloc_executor._run_test_in_allocation(mock_test_instance)

        # Verify srun command
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert "srun" in cmd
        assert "--jobid=12345" in cmd
        assert "--overlap" in cmd
        assert "bash" in cmd
        assert str(mock_test_instance.script_file) in cmd


def test_single_alloc_run_test_failure(single_alloc_executor, mock_test_instance):
    """Test handling test execution failure."""
    single_alloc_executor.allocation_job_id = "12345"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="error")

        single_alloc_executor._run_test_in_allocation(mock_test_instance)

        assert mock_test_instance.metadata["__executor_status"] == BaseExecutor.STATUS_FAILED
        assert mock_test_instance.metadata["__returncode"] == 1


def test_single_alloc_wait_and_collect_with_parser(single_alloc_executor, mock_test_instance, tmp_path):
    """Test wait_and_collect parses metrics."""
    # Set up parser
    mock_test_instance.parser = Mock()
    mock_test_instance.parser.file = str(tmp_path / "result.json")
    mock_test_instance.parser.parser_script = "def parse(f): return {'value': 42}"
    mock_test_instance.parser.metrics = [Mock(name="value")]

    # Write result file
    result_file = tmp_path / "result.json"
    result_file.write_text('{"value": 42}')

    # Mark as succeeded
    mock_test_instance.metadata["__executor_status"] = BaseExecutor.STATUS_SUCCEEDED

    with patch("iops.execution.executors.parse_metrics_from_execution") as mock_parse:
        mock_parse.return_value = {"metrics": {"value": 42}}
        single_alloc_executor.wait_and_collect(mock_test_instance)

        mock_parse.assert_called_once()


def test_single_alloc_parse_jobid():
    """Test job ID parsing."""
    config = Mock()
    config.benchmark = Mock()
    config.benchmark.slurm_options = SlurmOptionsConfig(
        allocation=AllocationConfig(
            mode="single",
            allocation_script="#SBATCH --nodes=1\n#SBATCH --time=00:10:00"
        )
    )
    config.benchmark.workdir = Path("/tmp")

    executor = SingleAllocationSlurmExecutor(config)

    # Standard format
    assert executor._parse_jobid("Submitted batch job 12345") == "12345"

    # Parsable format
    assert executor._parse_jobid("12345;cluster") == "12345"

    # Empty
    assert executor._parse_jobid("") is None


# ============================================================================ #
# Integration Tests
# ============================================================================ #


def test_full_single_allocation_config(tmp_path, sample_config_dict):
    """Test loading and validating a complete single-allocation config."""
    config_file = tmp_path / "full_single.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["slurm_options"] = {
        "commands": {
            "submit": "sbatch",
            "status": "squeue -j {job_id} -h -o %T",
        },
        "poll_interval": 10,
        "allocation": {
            "mode": "single",
            "allocation_script": """#SBATCH --nodes=16
#SBATCH --ntasks-per-node=32
#SBATCH --time=4:00:00
#SBATCH --partition=compute
#SBATCH --account=hpc_project
#SBATCH --exclusive
#SBATCH --constraint=ib""",
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    # Verify all settings
    eo = config.benchmark.slurm_options
    assert eo.poll_interval == 10
    assert eo.commands["submit"] == "sbatch"

    alloc = eo.allocation
    assert alloc.mode == "single"
    assert "#SBATCH --nodes=16" in alloc.allocation_script
    assert "#SBATCH --ntasks-per-node=32" in alloc.allocation_script
    assert "#SBATCH --time=4:00:00" in alloc.allocation_script
    assert "#SBATCH --partition=compute" in alloc.allocation_script
    assert "#SBATCH --account=hpc_project" in alloc.allocation_script
    assert "--exclusive" in alloc.allocation_script
    assert "--constraint=ib" in alloc.allocation_script
