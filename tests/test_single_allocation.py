"""Tests for single-allocation SLURM mode."""

import pytest
import yaml
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from iops.config.models import (
    ConfigValidationError,
    AllocationConfig,
    ExecutorOptionsConfig,
)
from iops.execution.executors import (
    BaseExecutor,
    SlurmExecutor,
    SingleAllocationSlurmExecutor,
    ALLOCATION_WRAPPER_FILENAME,
    ALLOCATION_STATUS_FILENAME,
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
    assert config.nodes is None
    assert config.ntasks_per_node is None
    assert config.time is None
    assert config.partition is None
    assert config.account is None
    assert config.extra_sbatch is None
    assert config.srun_options is None


def test_allocation_config_parsing(tmp_path, sample_config_dict):
    """Test that allocation config is properly parsed from YAML."""
    config_file = tmp_path / "alloc_config.yaml"

    # Add allocation config
    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["executor_options"] = {
        "allocation": {
            "mode": "single",
            "nodes": 8,
            "ntasks_per_node": 4,
            "time": "02:00:00",
            "partition": "batch",
            "account": "myaccount",
            "extra_sbatch": "#SBATCH --exclusive",
            "srun_options": "--nodes={{ nodes }}",
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    assert config.benchmark.executor_options is not None
    alloc = config.benchmark.executor_options.allocation
    assert alloc is not None
    assert alloc.mode == "single"
    assert alloc.nodes == 8
    assert alloc.ntasks_per_node == 4
    assert alloc.time == "02:00:00"
    assert alloc.partition == "batch"
    assert alloc.account == "myaccount"
    assert alloc.extra_sbatch == "#SBATCH --exclusive"
    assert alloc.srun_options == "--nodes={{ nodes }}"


def test_allocation_config_per_test_mode(tmp_path, sample_config_dict):
    """Test that per-test mode is the default."""
    config_file = tmp_path / "per_test_config.yaml"

    # Add allocation config with per-test mode
    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["executor_options"] = {
        "allocation": {
            "mode": "per-test"
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    alloc = config.benchmark.executor_options.allocation
    assert alloc.mode == "per-test"
    # nodes and time not required for per-test mode


# ============================================================================ #
# AllocationConfig Validation Tests
# ============================================================================ #


def test_allocation_invalid_mode(tmp_path, sample_config_dict):
    """Test that invalid allocation mode raises error."""
    config_file = tmp_path / "invalid_mode.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["executor_options"] = {
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
    sample_config_dict["benchmark"]["executor_options"] = {
        "allocation": {
            "mode": "single",
            "nodes": 4,
            "time": "01:00:00"
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(config_file)

    assert "slurm" in str(exc_info.value).lower()


def test_allocation_single_requires_nodes(tmp_path, sample_config_dict):
    """Test that single allocation mode requires nodes."""
    config_file = tmp_path / "no_nodes.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["executor_options"] = {
        "allocation": {
            "mode": "single",
            "time": "01:00:00"
            # nodes is missing
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(config_file)

    assert "nodes" in str(exc_info.value)


def test_allocation_single_requires_time(tmp_path, sample_config_dict):
    """Test that single allocation mode requires time."""
    config_file = tmp_path / "no_time.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["executor_options"] = {
        "allocation": {
            "mode": "single",
            "nodes": 4
            # time is missing
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(config_file)

    assert "time" in str(exc_info.value)


def test_allocation_time_format_validation(tmp_path, sample_config_dict):
    """Test that time format is validated."""
    config_file = tmp_path / "invalid_time.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["executor_options"] = {
        "allocation": {
            "mode": "single",
            "nodes": 4,
            "time": "invalid"
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(config_file)

    assert "time" in str(exc_info.value)
    assert "HH:MM:SS" in str(exc_info.value)


def test_allocation_time_format_hhmmss(tmp_path, sample_config_dict):
    """Test that HH:MM:SS time format is accepted."""
    config_file = tmp_path / "hhmmss.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["executor_options"] = {
        "allocation": {
            "mode": "single",
            "nodes": 4,
            "time": "02:30:00"
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    assert config.benchmark.executor_options.allocation.time == "02:30:00"


def test_allocation_time_format_dhhmmss(tmp_path, sample_config_dict):
    """Test that D-HH:MM:SS time format is accepted."""
    config_file = tmp_path / "dhhmmss.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["executor_options"] = {
        "allocation": {
            "mode": "single",
            "nodes": 4,
            "time": "1-12:00:00"
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    assert config.benchmark.executor_options.allocation.time == "1-12:00:00"


def test_allocation_invalid_srun_options_jinja(tmp_path, sample_config_dict):
    """Test that invalid Jinja2 in srun_options raises error."""
    config_file = tmp_path / "invalid_jinja.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["executor_options"] = {
        "allocation": {
            "mode": "single",
            "nodes": 4,
            "time": "01:00:00",
            "srun_options": "--nodes={{ nodes"  # unclosed
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(config_file)

    assert "srun_options" in str(exc_info.value)


# ============================================================================ #
# Executor Build Tests
# ============================================================================ #


def test_executor_build_returns_slurm_for_per_test():
    """Test that BaseExecutor.build returns SlurmExecutor for per-test mode."""
    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor = "slurm"
    config.benchmark.executor_options = ExecutorOptionsConfig(
        allocation=AllocationConfig(mode="per-test")
    )

    executor = BaseExecutor.build(config)
    assert isinstance(executor, SlurmExecutor)


def test_executor_build_returns_single_alloc_for_single_mode():
    """Test that BaseExecutor.build returns SingleAllocationSlurmExecutor for single mode."""
    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor = "slurm"
    config.benchmark.executor_options = ExecutorOptionsConfig(
        allocation=AllocationConfig(mode="single", nodes=4, time="01:00:00")
    )

    executor = BaseExecutor.build(config)
    assert isinstance(executor, SingleAllocationSlurmExecutor)


def test_executor_build_returns_slurm_without_allocation():
    """Test that BaseExecutor.build returns SlurmExecutor when no allocation config."""
    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor = "slurm"
    config.benchmark.executor_options = None

    executor = BaseExecutor.build(config)
    assert isinstance(executor, SlurmExecutor)


# ============================================================================ #
# SingleAllocationSlurmExecutor Tests
# ============================================================================ #


@pytest.fixture
def single_alloc_executor():
    """Create a SingleAllocationSlurmExecutor for testing."""
    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor = "slurm"
    config.benchmark.executor_options = ExecutorOptionsConfig(
        allocation=AllocationConfig(
            mode="single",
            nodes=4,
            ntasks_per_node=8,
            time="02:00:00",
            partition="batch",
            account="myaccount",
        )
    )
    config.benchmark.workdir = Path("/tmp/test_workdir")

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


def test_single_alloc_queue_test(single_alloc_executor, mock_test_instance):
    """Test queueing a test in single-allocation mode."""
    single_alloc_executor.queue_test(mock_test_instance)

    assert len(single_alloc_executor.pending_tests) == 1
    assert mock_test_instance in single_alloc_executor.pending_tests
    assert mock_test_instance.metadata["__executor_status"] == BaseExecutor.STATUS_PENDING


def test_single_alloc_submit_raises_not_implemented(single_alloc_executor, mock_test_instance):
    """Test that submit() raises NotImplementedError."""
    with pytest.raises(NotImplementedError):
        single_alloc_executor.submit(mock_test_instance)


def test_single_alloc_wait_and_collect_raises_not_implemented(single_alloc_executor, mock_test_instance):
    """Test that wait_and_collect() raises NotImplementedError."""
    with pytest.raises(NotImplementedError):
        single_alloc_executor.wait_and_collect(mock_test_instance)


def test_single_alloc_generate_wrapper_script(single_alloc_executor, mock_test_instance, tmp_path):
    """Test wrapper script generation."""
    # Update workdir to temp path
    single_alloc_executor.cfg.benchmark.workdir = tmp_path
    (tmp_path / "logs").mkdir()

    # Queue the test
    single_alloc_executor.queue_test(mock_test_instance)

    # Generate wrapper script
    wrapper = single_alloc_executor._generate_wrapper_script()

    # Check SBATCH directives
    assert "#!/bin/bash" in wrapper
    assert "#SBATCH --nodes=4" in wrapper
    assert "#SBATCH --ntasks-per-node=8" in wrapper
    assert "#SBATCH --time=02:00:00" in wrapper
    assert "#SBATCH --partition=batch" in wrapper
    assert "#SBATCH --account=myaccount" in wrapper
    assert "#SBATCH --job-name=iops_allocation" in wrapper

    # Check test execution
    assert "exec_0001_rep_001" in wrapper
    assert "EXIT_CODES" in wrapper
    assert str(mock_test_instance.script_file) in wrapper


def test_single_alloc_wrapper_with_srun_options(tmp_path):
    """Test wrapper script with srun_options template."""
    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor = "slurm"
    config.benchmark.executor_options = ExecutorOptionsConfig(
        allocation=AllocationConfig(
            mode="single",
            nodes=4,
            time="01:00:00",
            srun_options="--nodes={{ nodes }} --ntasks={{ ppn }}",
        )
    )
    config.benchmark.workdir = tmp_path
    (tmp_path / "logs").mkdir()

    executor = SingleAllocationSlurmExecutor(config)

    # Create test instance
    test = Mock(spec=ExecutionInstance)
    test.execution_id = 1
    test.repetition = 1
    test.execution_dir = tmp_path / "exec_001"
    test.execution_dir.mkdir()
    test.script_file = test.execution_dir / "run.sh"
    test.script_file.write_text("#!/bin/bash\necho test")
    test.metadata = {}
    test.vars = {"nodes": 2, "ppn": 8}

    executor.queue_test(test)
    wrapper = executor._generate_wrapper_script()

    # Check that srun options are rendered
    assert "srun --nodes=2 --ntasks=8" in wrapper


def test_single_alloc_wrapper_with_extra_sbatch(tmp_path):
    """Test wrapper script with extra_sbatch directives."""
    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor = "slurm"
    config.benchmark.executor_options = ExecutorOptionsConfig(
        allocation=AllocationConfig(
            mode="single",
            nodes=4,
            time="01:00:00",
            extra_sbatch="#SBATCH --exclusive\n#SBATCH --mem=0",
        )
    )
    config.benchmark.workdir = tmp_path
    (tmp_path / "logs").mkdir()

    executor = SingleAllocationSlurmExecutor(config)

    # Create minimal test
    test = Mock(spec=ExecutionInstance)
    test.execution_id = 1
    test.repetition = 1
    test.execution_dir = tmp_path / "exec_001"
    test.execution_dir.mkdir()
    test.script_file = test.execution_dir / "run.sh"
    test.metadata = {}
    test.vars = {}

    executor.queue_test(test)
    wrapper = executor._generate_wrapper_script()

    assert "#SBATCH --exclusive" in wrapper
    assert "#SBATCH --mem=0" in wrapper


def test_single_alloc_submit_allocation(single_alloc_executor, mock_test_instance, tmp_path):
    """Test allocation submission."""
    single_alloc_executor.cfg.benchmark.workdir = tmp_path
    (tmp_path / "logs").mkdir()

    single_alloc_executor.queue_test(mock_test_instance)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(
            returncode=0,
            stdout="Submitted batch job 12345",
            stderr=""
        )

        job_id = single_alloc_executor.submit_allocation()

        assert job_id == "12345"
        assert single_alloc_executor.allocation_job_id == "12345"
        assert mock_test_instance.metadata["__jobid"] == "12345"

        # Check wrapper script was written
        wrapper_path = tmp_path / ALLOCATION_WRAPPER_FILENAME
        assert wrapper_path.exists()


def test_single_alloc_submit_allocation_failure(single_alloc_executor, mock_test_instance, tmp_path):
    """Test allocation submission failure."""
    single_alloc_executor.cfg.benchmark.workdir = tmp_path
    (tmp_path / "logs").mkdir()

    single_alloc_executor.queue_test(mock_test_instance)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="sbatch: error: Invalid partition"
        )

        with pytest.raises(RuntimeError) as exc_info:
            single_alloc_executor.submit_allocation()

        assert "SLURM submission failed" in str(exc_info.value)
        assert mock_test_instance.metadata["__executor_status"] == BaseExecutor.STATUS_ERROR


def test_single_alloc_wait_for_allocation(single_alloc_executor):
    """Test waiting for allocation completion."""
    single_alloc_executor.allocation_job_id = "12345"
    single_alloc_executor.poll_interval = 0.01  # Fast polling for test

    # Create a test in pending_tests
    test = Mock()
    test.metadata = {}
    single_alloc_executor.pending_tests = [test]

    with patch.object(single_alloc_executor, "_squeue_state") as mock_squeue:
        # Simulate: PENDING -> RUNNING -> completed (None)
        mock_squeue.side_effect = ["PENDING", "RUNNING", None]

        single_alloc_executor.wait_for_allocation()

        assert mock_squeue.call_count == 3


def test_single_alloc_collect_results_success(single_alloc_executor, mock_test_instance, tmp_path):
    """Test collecting results from completed allocation."""
    single_alloc_executor.cfg.benchmark.workdir = tmp_path

    # Queue test
    single_alloc_executor.queue_test(mock_test_instance)

    # Write status file
    status_file = tmp_path / ALLOCATION_STATUS_FILENAME
    status_file.write_text('{"exec_0001_rep_001": 0}')

    # No parser for this test
    mock_test_instance.parser = None

    single_alloc_executor.collect_results()

    assert mock_test_instance.metadata["__executor_status"] == BaseExecutor.STATUS_SUCCEEDED
    assert mock_test_instance.metadata["__returncode"] == 0


def test_single_alloc_collect_results_failure(single_alloc_executor, mock_test_instance, tmp_path):
    """Test collecting results when test failed."""
    single_alloc_executor.cfg.benchmark.workdir = tmp_path

    # Queue test
    single_alloc_executor.queue_test(mock_test_instance)

    # Write status file with non-zero exit code
    status_file = tmp_path / ALLOCATION_STATUS_FILENAME
    status_file.write_text('{"exec_0001_rep_001": 1}')

    # No parser for this test
    mock_test_instance.parser = None

    single_alloc_executor.collect_results()

    assert mock_test_instance.metadata["__executor_status"] == BaseExecutor.STATUS_FAILED
    assert "code 1" in mock_test_instance.metadata["__error"]


def test_single_alloc_parse_jobid():
    """Test job ID parsing."""
    config = Mock()
    config.benchmark = Mock()
    config.benchmark.executor_options = ExecutorOptionsConfig(
        allocation=AllocationConfig(mode="single", nodes=1, time="00:10:00")
    )

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
    sample_config_dict["benchmark"]["executor_options"] = {
        "commands": {
            "submit": "sbatch",
            "status": "squeue -j {job_id} -h -o %T",
        },
        "poll_interval": 10,
        "allocation": {
            "mode": "single",
            "nodes": 16,
            "ntasks_per_node": 32,
            "time": "4:00:00",
            "partition": "compute",
            "account": "hpc_project",
            "extra_sbatch": "#SBATCH --exclusive\n#SBATCH --constraint=ib",
            "srun_options": "--nodes={{ nodes }} --ntasks={{ nodes * ppn }}",
        }
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    # Verify all settings
    eo = config.benchmark.executor_options
    assert eo.poll_interval == 10
    assert eo.commands["submit"] == "sbatch"

    alloc = eo.allocation
    assert alloc.mode == "single"
    assert alloc.nodes == 16
    assert alloc.ntasks_per_node == 32
    assert alloc.time == "4:00:00"
    assert alloc.partition == "compute"
    assert alloc.account == "hpc_project"
    assert "--exclusive" in alloc.extra_sbatch
    assert "{{ nodes * ppn }}" in alloc.srun_options
