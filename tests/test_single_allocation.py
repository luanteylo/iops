"""Tests for single-allocation SLURM mode and MPI configuration."""

import pytest
import yaml
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from iops.config.models import (
    ConfigValidationError,
    AllocationConfig,
    SlurmOptionsConfig,
    MPIConfig,
)
from iops.execution.executors import (
    BaseExecutor,
    SlurmExecutor,
    SingleAllocationSlurmExecutor,
)
from iops.execution.matrix import ExecutionInstance
from iops.execution.planner import BasePlanner, ExhaustivePlanner
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
    assert eo.commands["status"] == "squeue -j {job_id} -h -o %T"

    alloc = eo.allocation
    assert alloc.mode == "single"
    assert "#SBATCH --nodes=16" in alloc.allocation_script
    assert "#SBATCH --ntasks-per-node=32" in alloc.allocation_script
    assert "#SBATCH --time=4:00:00" in alloc.allocation_script
    assert "#SBATCH --partition=compute" in alloc.allocation_script
    assert "#SBATCH --account=hpc_project" in alloc.allocation_script
    assert "--exclusive" in alloc.allocation_script
    assert "--constraint=ib" in alloc.allocation_script


# ============================================================================ #
# MPIConfig Tests
# ============================================================================ #


def test_mpi_config_defaults():
    """Test MPIConfig default values."""
    config = MPIConfig(ppn="8")

    assert config.launcher == "mpirun"
    assert config.nodes == "all"
    assert config.ppn == "8"
    # pass_env defaults to empty; LD_LIBRARY_PATH and PATH are always added by the wrapper
    assert config.pass_env == []
    assert config.extra_options == []


def test_mpi_config_parsing(tmp_path, sample_config_dict):
    """Test that MPI config is properly parsed from YAML."""
    config_file = tmp_path / "mpi_config.yaml"

    # Add single-allocation mode (required for mpi config)
    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["slurm_options"] = {
        "allocation": {
            "mode": "single",
            "allocation_script": "#SBATCH --nodes=8\n#SBATCH --time=02:00:00",
        }
    }

    # Add mpi config to script
    sample_config_dict["scripts"][0]["mpi"] = {
        "nodes": "{{ nodes }}",
        "ppn": "{{ ppn }}",
        "pass_env": ["LD_LIBRARY_PATH", "PATH", "OMP_NUM_THREADS"],
        "extra_options": ["--mca btl tcp,self"],
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    script = config.scripts[0]
    assert script.mpi is not None
    assert script.mpi.launcher == "mpirun"
    assert script.mpi.nodes == "{{ nodes }}"
    assert script.mpi.ppn == "{{ ppn }}"
    assert "OMP_NUM_THREADS" in script.mpi.pass_env
    assert "--mca btl tcp,self" in script.mpi.extra_options


def test_mpi_config_with_srun_launcher(tmp_path, sample_config_dict):
    """Test MPI config with srun launcher."""
    config_file = tmp_path / "mpi_srun.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["slurm_options"] = {
        "allocation": {
            "mode": "single",
            "allocation_script": "#SBATCH --nodes=8\n#SBATCH --time=02:00:00",
        }
    }

    sample_config_dict["scripts"][0]["mpi"] = {
        "launcher": "srun",
        "nodes": "4",
        "ppn": "8",
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    script = config.scripts[0]
    assert script.mpi.launcher == "srun"
    assert script.mpi.nodes == "4"
    assert script.mpi.ppn == "8"


def test_mpi_config_requires_single_allocation(tmp_path, sample_config_dict):
    """Test that MPI config requires single-allocation mode."""
    config_file = tmp_path / "mpi_no_alloc.yaml"

    # No allocation config
    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["scripts"][0]["mpi"] = {
        "nodes": "{{ nodes }}",
        "ppn": "8",
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(config_file)

    assert "single" in str(exc_info.value).lower()
    assert "mpi" in str(exc_info.value).lower()


def test_mpi_config_requires_ppn(tmp_path, sample_config_dict):
    """Test that MPI config requires ppn."""
    config_file = tmp_path / "mpi_no_ppn.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["slurm_options"] = {
        "allocation": {
            "mode": "single",
            "allocation_script": "#SBATCH --nodes=8\n#SBATCH --time=02:00:00",
        }
    }

    # mpi config without ppn
    sample_config_dict["scripts"][0]["mpi"] = {
        "nodes": "{{ nodes }}",
        # ppn is missing
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(config_file)

    assert "ppn" in str(exc_info.value)


def test_mpi_config_invalid_launcher(tmp_path, sample_config_dict):
    """Test that invalid launcher raises error."""
    config_file = tmp_path / "mpi_bad_launcher.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["slurm_options"] = {
        "allocation": {
            "mode": "single",
            "allocation_script": "#SBATCH --nodes=8\n#SBATCH --time=02:00:00",
        }
    }

    sample_config_dict["scripts"][0]["mpi"] = {
        "launcher": "invalid",
        "ppn": "8",
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(config_file)

    assert "launcher" in str(exc_info.value)
    assert "mpirun" in str(exc_info.value) or "srun" in str(exc_info.value)


def test_mpi_config_invalid_nodes(tmp_path, sample_config_dict):
    """Test that invalid nodes value raises error."""
    config_file = tmp_path / "mpi_bad_nodes.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["slurm_options"] = {
        "allocation": {
            "mode": "single",
            "allocation_script": "#SBATCH --nodes=8\n#SBATCH --time=02:00:00",
        }
    }

    sample_config_dict["scripts"][0]["mpi"] = {
        "nodes": "invalid_string",  # Not a number, not "all", not a template
        "ppn": "8",
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(config_file)

    assert "nodes" in str(exc_info.value)


# ============================================================================ #
# MPI Script Wrapping Tests
# ============================================================================ #


@pytest.fixture
def mpi_planner(tmp_path, sample_config_dict):
    """Create a planner with MPI-enabled config for testing."""
    config_file = tmp_path / "mpi_test.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["slurm_options"] = {
        "allocation": {
            "mode": "single",
            "allocation_script": "#SBATCH --nodes=8\n#SBATCH --time=02:00:00",
        }
    }
    sample_config_dict["benchmark"]["collect_system_info"] = False
    sample_config_dict["benchmark"]["trace_resources"] = False

    sample_config_dict["scripts"][0]["mpi"] = {
        "nodes": "{{ nodes }}",
        "ppn": "{{ ppn }}",
        "pass_env": ["LD_LIBRARY_PATH", "PATH"],
    }

    sample_config_dict["scripts"][0]["script_template"] = """#!/bin/bash
module load openmpi
{{ command.template }}
"""

    # Add ppn variable
    sample_config_dict["vars"]["ppn"] = {
        "type": "int",
        "sweep": {"mode": "list", "values": [4, 8]},
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    return ExhaustivePlanner(config)


def test_mpi_wrapper_generates_nodeid_check(mpi_planner):
    """Test that MPI wrapper generates SLURM_NODEID check."""
    test = mpi_planner.next_test()

    # Read the generated script
    script_content = test.script_file.read_text()

    # Should have SLURM_NODEID check
    assert 'if [ "$SLURM_NODEID" = "0" ]' in script_content
    assert "fi" in script_content


def test_mpi_wrapper_generates_nodelist(mpi_planner):
    """Test that MPI wrapper generates nodelist construction."""
    test = mpi_planner.next_test()

    script_content = test.script_file.read_text()

    # Should have nodelist construction
    assert "__IOPS_NODELIST" in script_content
    assert "scontrol show hostnames" in script_content


def test_mpi_wrapper_generates_mpirun_command(mpi_planner):
    """Test that MPI wrapper generates mpirun command."""
    test = mpi_planner.next_test()

    script_content = test.script_file.read_text()

    # Should have mpirun with required flags
    assert "mpirun" in script_content
    assert "--host $__IOPS_NODELIST" in script_content
    assert "-np" in script_content
    assert "--mca plm rsh" in script_content
    assert "--oversubscribe" in script_content


def test_mpi_wrapper_passes_env_vars(mpi_planner):
    """Test that MPI wrapper passes environment variables."""
    test = mpi_planner.next_test()

    script_content = test.script_file.read_text()

    # Should pass environment variables
    assert '-x LD_LIBRARY_PATH="$LD_LIBRARY_PATH"' in script_content
    assert '-x PATH="$PATH"' in script_content


def test_mpi_wrapper_env_vars_additive(tmp_path, sample_config_dict):
    """Test that base env vars (LD_LIBRARY_PATH, PATH) are always passed even when user specifies only other vars."""
    config_file = tmp_path / "config.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["slurm_options"] = {
        "allocation": {
            "mode": "single",
            "allocation_script": "#SBATCH --nodes=8\n#SBATCH --time=02:00:00",
        }
    }
    sample_config_dict["benchmark"]["collect_system_info"] = False
    sample_config_dict["benchmark"]["trace_resources"] = False

    # User specifies ONLY LD_PRELOAD - base vars should still be passed
    sample_config_dict["scripts"][0]["mpi"] = {
        "ppn": "4",
        "pass_env": ["LD_PRELOAD"],
    }

    sample_config_dict["scripts"][0]["script_template"] = """#!/bin/bash
{{ command.template }}
"""

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    planner = ExhaustivePlanner(config)
    test = planner.next_test()

    script_content = test.script_file.read_text()

    # Base vars should ALWAYS be passed
    assert '-x LD_LIBRARY_PATH="$LD_LIBRARY_PATH"' in script_content
    assert '-x PATH="$PATH"' in script_content
    # User-specified var should also be passed
    assert '-x LD_PRELOAD="$LD_PRELOAD"' in script_content


def test_mpi_wrapper_preserves_setup_commands(mpi_planner):
    """Test that MPI wrapper preserves user setup commands."""
    test = mpi_planner.next_test()

    script_content = test.script_file.read_text()

    # Module load should be inside the if block
    assert "module load openmpi" in script_content
    # Should be within the if SLURM_NODEID block
    # The module load should come before the mpirun


def test_mpi_resolve_template_value():
    """Test that template values are resolved correctly."""
    planner = Mock(spec=BasePlanner)
    planner.logger = Mock()

    ctx = {"nodes": 4, "ppn": 8}

    # Test template resolution
    result = BasePlanner._resolve_mpi_value(planner, "{{ nodes }}", ctx)
    assert result == 4

    # Test literal number
    result = BasePlanner._resolve_mpi_value(planner, "2", ctx)
    assert result == 2

    # Test "all"
    result = BasePlanner._resolve_mpi_value(planner, "all", ctx)
    assert result is None


def test_mpi_generate_nodelist_command_with_nodes():
    """Test nodelist command generation with specific node count."""
    planner = Mock(spec=BasePlanner)

    cmd = BasePlanner._generate_nodelist_command(planner, nodes_value=4, ppn_value=8)

    assert "head -n 4" in cmd
    assert ":8" in cmd
    assert "scontrol show hostnames" in cmd


def test_mpi_generate_nodelist_command_all_nodes():
    """Test nodelist command generation for all nodes."""
    planner = Mock(spec=BasePlanner)

    cmd = BasePlanner._generate_nodelist_command(planner, nodes_value=None, ppn_value=8)

    # Should NOT have head -n
    assert "head -n" not in cmd
    assert ":8" in cmd
    assert "scontrol show hostnames" in cmd


def test_mpi_wrapper_with_srun_launcher(tmp_path, sample_config_dict):
    """Test MPI wrapper with srun launcher."""
    config_file = tmp_path / "mpi_srun_test.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["slurm_options"] = {
        "allocation": {
            "mode": "single",
            "allocation_script": "#SBATCH --nodes=8\n#SBATCH --time=02:00:00",
        }
    }
    sample_config_dict["benchmark"]["collect_system_info"] = False
    sample_config_dict["benchmark"]["trace_resources"] = False

    sample_config_dict["scripts"][0]["mpi"] = {
        "launcher": "srun",
        "nodes": "{{ nodes }}",
        "ppn": "{{ ppn }}",
    }

    sample_config_dict["scripts"][0]["script_template"] = """#!/bin/bash
module load openmpi
{{ command.template }}
"""

    sample_config_dict["vars"]["ppn"] = {
        "type": "int",
        "sweep": {"mode": "list", "values": [4, 8]},
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    planner = ExhaustivePlanner(config)
    test = planner.next_test()

    script_content = test.script_file.read_text()

    # Should have srun instead of mpirun
    assert "srun" in script_content
    assert "--ntasks-per-node=" in script_content
    assert "--overlap" in script_content
    # Should NOT have mpirun-specific flags
    assert "--mca plm rsh" not in script_content


def test_mpi_wrapper_with_extra_options(tmp_path, sample_config_dict):
    """Test MPI wrapper with extra options."""
    config_file = tmp_path / "mpi_extra_opts.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["slurm_options"] = {
        "allocation": {
            "mode": "single",
            "allocation_script": "#SBATCH --nodes=8\n#SBATCH --time=02:00:00",
        }
    }
    sample_config_dict["benchmark"]["collect_system_info"] = False
    sample_config_dict["benchmark"]["trace_resources"] = False

    sample_config_dict["scripts"][0]["mpi"] = {
        "nodes": "2",
        "ppn": "4",
        "extra_options": ["--mca btl tcp,self", "--mca mpi_show_mca_params all"],
    }

    sample_config_dict["scripts"][0]["script_template"] = """#!/bin/bash
{{ command.template }}
"""

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    planner = ExhaustivePlanner(config)
    test = planner.next_test()

    script_content = test.script_file.read_text()

    assert "--mca btl tcp,self" in script_content
    assert "--mca mpi_show_mca_params all" in script_content


def test_mpi_config_stored_in_execution_instance(tmp_path, sample_config_dict):
    """Test that MPI config is stored in ExecutionInstance."""
    config_file = tmp_path / "mpi_instance.yaml"

    sample_config_dict["benchmark"]["executor"] = "slurm"
    sample_config_dict["benchmark"]["slurm_options"] = {
        "allocation": {
            "mode": "single",
            "allocation_script": "#SBATCH --nodes=8\n#SBATCH --time=02:00:00",
        }
    }

    sample_config_dict["scripts"][0]["mpi"] = {
        "nodes": "{{ nodes }}",
        "ppn": "8",
    }

    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)

    from iops.execution.matrix import build_execution_matrix
    instances, _ = build_execution_matrix(config)

    assert len(instances) > 0
    instance = instances[0]
    assert instance.mpi_config is not None
    assert instance.mpi_config.ppn == "8"
    assert instance.mpi_config.nodes == "{{ nodes }}"
