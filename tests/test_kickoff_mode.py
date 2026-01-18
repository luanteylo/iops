"""
Tests for single-allocation mode.

Single-allocation mode pre-generates an execution script containing ALL tests.
This eliminates per-test overhead (srun startup, SSH agent issues) by running
tests sequentially within the allocation.
"""

import json
import logging
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from iops.config.models import (
    GenericBenchmarkConfig,
    BenchmarkConfig,
    VarConfig,
    SweepConfig,
    CommandConfig,
    ScriptConfig,
    OutputSinkConfig,
    SlurmOptionsConfig,
    AllocationConfig,
)
from iops.config.loader import load_generic_config, ConfigValidationError
from iops.execution.executors import (
    BaseExecutor,
    KickoffSingleAllocationExecutor,
    KICKOFF_SCRIPT_FILENAME,
    KICKOFF_STATUS_FILENAME,
)
from iops.execution.planner import BasePlanner


def _get_logger():
    """Get a logger for config loading."""
    logger = logging.getLogger("test_kickoff_mode")
    logger.setLevel(logging.DEBUG)
    return logger


# ============================================================================ #
# Fixtures
# ============================================================================ #

@pytest.fixture
def sample_kickoff_config_dict():
    """Return a minimal YAML config dict for single-allocation mode testing."""
    return {
        "benchmark": {
            "name": "single_alloc_test",
            "workdir": "./workdir",
            "executor": "slurm",
            "search_method": "exhaustive",
            "repetitions": 1,
            "slurm_options": {
                "allocation": {
                    "mode": "single",
                    "test_timeout": 300,
                    "allocation_script": """
#SBATCH --nodes=4
#SBATCH --time=01:00:00
#SBATCH --partition=compute
"""
                }
            }
        },
        "vars": {
            "param_a": {
                "type": "int",
                "sweep": {
                    "mode": "list",
                    "values": [1, 2]
                }
            }
        },
        "command": {
            "template": "echo {{ param_a }}"
        },
        "scripts": [
            {
                "name": "main",
                "submit": "bash",
                "script_template": "#!/bin/bash\n{{ command.template }}\n"
            }
        ],
        "output": {
            "sink": {
                "type": "csv",
                "path": "{{ workdir }}/results.csv"
            }
        }
    }


@pytest.fixture
def sample_kickoff_config(sample_kickoff_config_dict, tmp_path):
    """Create a single-allocation config from dict and temp directory."""
    # Update workdir to temp path
    sample_kickoff_config_dict["benchmark"]["workdir"] = str(tmp_path / "workdir")
    return sample_kickoff_config_dict


# ============================================================================ #
# AllocationConfig Tests
# ============================================================================ #

class TestAllocationConfigKickoff:
    """Tests for single-allocation mode in AllocationConfig."""

    def test_allocation_config_kickoff_mode_default_timeout(self):
        """Test that single-allocation mode has default test_timeout of 3600."""
        cfg = AllocationConfig(
            mode="single",
            allocation_script="#SBATCH --nodes=4"
        )
        assert cfg.mode == "single"
        assert cfg.test_timeout == 3600

    def test_allocation_config_kickoff_mode_custom_timeout(self):
        """Test that single-allocation mode can set custom test_timeout."""
        cfg = AllocationConfig(
            mode="single",
            allocation_script="#SBATCH --nodes=4",
            test_timeout=300
        )
        assert cfg.mode == "single"
        assert cfg.test_timeout == 300


# ============================================================================ #
# Loader Validation Tests
# ============================================================================ #

class TestKickoffModeValidation:
    """Tests for single-allocation mode validation in loader."""

    def test_kickoff_mode_is_valid(self, sample_kickoff_config, tmp_path):
        """Test that single-allocation mode is accepted by the loader."""
        import yaml
        # Create workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())
        assert cfg.benchmark.slurm_options.allocation.mode == "single"

    def test_kickoff_mode_requires_slurm_executor(self, sample_kickoff_config, tmp_path):
        """Test that single-allocation mode requires executor='slurm'."""
        import yaml
        # Create workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        sample_kickoff_config["benchmark"]["executor"] = "local"
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        with pytest.raises(ConfigValidationError, match="requires executor='slurm'"):
            load_generic_config(Path(config_file), _get_logger())

    def test_kickoff_mode_requires_allocation_script(self, sample_kickoff_config, tmp_path):
        """Test that single-allocation mode requires allocation_script."""
        import yaml
        # Create workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        sample_kickoff_config["benchmark"]["slurm_options"]["allocation"]["allocation_script"] = None
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        with pytest.raises(ConfigValidationError, match="allocation_script is required"):
            load_generic_config(Path(config_file), _get_logger())

    def test_kickoff_mode_requires_sbatch_directive(self, sample_kickoff_config, tmp_path):
        """Test that single-allocation mode allocation_script must have #SBATCH."""
        import yaml
        # Create workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        sample_kickoff_config["benchmark"]["slurm_options"]["allocation"]["allocation_script"] = "#!/bin/bash\necho hello"
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        with pytest.raises(ConfigValidationError, match="must contain at least one #SBATCH"):
            load_generic_config(Path(config_file), _get_logger())

    def test_kickoff_mode_invalid_test_timeout(self, sample_kickoff_config, tmp_path):
        """Test that single-allocation mode rejects non-positive test_timeout."""
        import yaml
        # Create workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        sample_kickoff_config["benchmark"]["slurm_options"]["allocation"]["test_timeout"] = 0
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        with pytest.raises(ConfigValidationError, match="test_timeout must be a positive integer"):
            load_generic_config(Path(config_file), _get_logger())

    def test_kickoff_mode_incompatible_with_bayesian(self, sample_kickoff_config, tmp_path):
        """Test that single-allocation mode is incompatible with Bayesian search."""
        import yaml
        # Create workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        sample_kickoff_config["benchmark"]["search_method"] = "bayesian"
        sample_kickoff_config["benchmark"]["bayesian_config"] = {
            "objective_metric": "throughput",
            "objective": "maximize",
            "n_iterations": 10
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        with pytest.raises(ConfigValidationError, match="incompatible with search_method='bayesian'"):
            load_generic_config(Path(config_file), _get_logger())

    def test_kickoff_mode_rejects_mpi_config(self, sample_kickoff_config, tmp_path):
        """Test that MPI config is no longer supported (raises error)."""
        import yaml
        # Create workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        sample_kickoff_config["scripts"][0]["mpi"] = {
            "nodes": "{{ param_a }}",
            "ppn": "8",
            "launcher": "mpirun"
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        with pytest.raises(ConfigValidationError, match="'mpi' config which is no longer supported"):
            load_generic_config(Path(config_file), _get_logger())


# ============================================================================ #
# Executor Build Tests
# ============================================================================ #

class TestKickoffExecutorBuild:
    """Tests for executor build with single-allocation mode."""

    def test_executor_build_requires_kickoff_path_for_kickoff_mode(self, sample_kickoff_config, tmp_path):
        """Test that building single-allocation executor without path raises error."""
        import yaml
        # Create workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())

        with pytest.raises(ValueError, match="requires kickoff_path"):
            BaseExecutor.build(cfg)

    def test_executor_build_returns_kickoff_executor_with_path(self, sample_kickoff_config, tmp_path):
        """Test that building with kickoff_path returns KickoffSingleAllocationExecutor."""
        import yaml
        # Create workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())
        kickoff_path = tmp_path / "__iops_kickoff.sh"
        kickoff_path.write_text("#!/bin/bash\necho test")

        executor = BaseExecutor.build(cfg, kickoff_path=kickoff_path)
        assert isinstance(executor, KickoffSingleAllocationExecutor)


# ============================================================================ #
# Kickoff Script Generation Tests
# ============================================================================ #

class TestKickoffScriptGeneration:
    """Tests for single-allocation script generation in planner."""

    def test_prepare_kickoff_mode_generates_script(self, sample_kickoff_config, tmp_path):
        """Test that prepare_kickoff_mode creates the execution script."""
        import yaml

        # Create workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())
        planner = BasePlanner.build(cfg)

        kickoff_path = planner.prepare_kickoff_mode()

        assert kickoff_path.exists()
        assert kickoff_path.name == "__iops_kickoff.sh"

    def test_kickoff_script_contains_sbatch_directives(self, sample_kickoff_config, tmp_path):
        """Test that execution script includes user's SBATCH directives."""
        import yaml

        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())
        planner = BasePlanner.build(cfg)

        kickoff_path = planner.prepare_kickoff_mode()
        content = kickoff_path.read_text()

        assert "#SBATCH --nodes=4" in content
        assert "#SBATCH --time=01:00:00" in content
        assert "#SBATCH --partition=compute" in content
        assert "#SBATCH --job-name=iops_single_alloc" in content

    def test_kickoff_script_contains_run_test_function(self, sample_kickoff_config, tmp_path):
        """Test that execution script defines run_test function."""
        import yaml

        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())
        planner = BasePlanner.build(cfg)

        kickoff_path = planner.prepare_kickoff_mode()
        content = kickoff_path.read_text()

        assert "run_test()" in content
        assert "timeout" in content
        assert "__iops_status.json" in content

    def test_kickoff_script_contains_test_calls(self, sample_kickoff_config, tmp_path):
        """Test that execution script includes calls for each test."""
        import yaml

        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())
        planner = BasePlanner.build(cfg)

        kickoff_path = planner.prepare_kickoff_mode()
        content = kickoff_path.read_text()

        # With 2 param_a values and 1 repetition, should have 2 tests
        assert "Test 1/2" in content
        assert "Test 2/2" in content
        assert "run_test" in content

    def test_kickoff_script_with_timeout_setting(self, sample_kickoff_config, tmp_path):
        """Test that execution script uses configured test_timeout."""
        import yaml

        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)
        sample_kickoff_config["benchmark"]["slurm_options"]["allocation"]["test_timeout"] = 600

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())
        planner = BasePlanner.build(cfg)

        kickoff_path = planner.prepare_kickoff_mode()
        content = kickoff_path.read_text()

        assert "_IOPS_TEST_TIMEOUT=600" in content

    def test_kickoff_creates_test_folders(self, sample_kickoff_config, tmp_path):
        """Test that prepare_kickoff_mode creates all test folders."""
        import yaml

        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())
        planner = BasePlanner.build(cfg)

        planner.prepare_kickoff_mode()

        # Check that execution folders were created
        # Note: cfg.benchmark.workdir is the rendered workdir (e.g., workdir/run_001)
        actual_workdir = Path(cfg.benchmark.workdir)
        runs_dir = actual_workdir / "runs"
        assert runs_dir.exists()

        # Should have 2 exec folders
        exec_folders = list(runs_dir.glob("exec_*"))
        assert len(exec_folders) == 2

    def test_kickoff_creates_test_scripts(self, sample_kickoff_config, tmp_path):
        """Test that prepare_kickoff_mode creates per-test scripts."""
        import yaml

        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())
        planner = BasePlanner.build(cfg)

        planner.prepare_kickoff_mode()

        # Check that script files were created
        actual_workdir = Path(cfg.benchmark.workdir)
        runs_dir = actual_workdir / "runs"
        script_files = list(runs_dir.glob("exec_*/repetition_*/run_*.sh"))
        assert len(script_files) == 2


# ============================================================================ #
# Kickoff Executor Tests
# ============================================================================ #

class TestKickoffSingleAllocationExecutor:
    """Tests for KickoffSingleAllocationExecutor."""

    def test_executor_stores_kickoff_path(self, sample_kickoff_config, tmp_path):
        """Test that executor stores the kickoff path."""
        import yaml
        # Create workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())
        kickoff_path = tmp_path / "__iops_kickoff.sh"
        kickoff_path.write_text("#!/bin/bash\necho test")

        executor = KickoffSingleAllocationExecutor(cfg, kickoff_path)
        assert executor.kickoff_path == kickoff_path

    def test_executor_stores_test_timeout(self, sample_kickoff_config, tmp_path):
        """Test that executor stores test_timeout from config."""
        import yaml
        # Create workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())
        kickoff_path = tmp_path / "__iops_kickoff.sh"
        kickoff_path.write_text("#!/bin/bash\necho test")

        executor = KickoffSingleAllocationExecutor(cfg, kickoff_path)
        assert executor.test_timeout == 300

    def test_executor_initial_state(self, sample_kickoff_config, tmp_path):
        """Test executor initial state flags."""
        import yaml
        # Create workdir
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())
        kickoff_path = tmp_path / "__iops_kickoff.sh"
        kickoff_path.write_text("#!/bin/bash\necho test")

        executor = KickoffSingleAllocationExecutor(cfg, kickoff_path)

        assert executor.allocation_job_id is None
        assert executor.kickoff_submitted is False
        assert executor.kickoff_failed is False

    @patch('subprocess.run')
    def test_submit_submits_kickoff_on_first_call(self, mock_run, sample_kickoff_config, tmp_path):
        """Test that first submit() submits the kickoff script."""
        import yaml
        from iops.execution.matrix import ExecutionInstance

        # Create workdir and kickoff script
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())

        # Use the rendered workdir (e.g., workdir/run_001)
        actual_workdir = Path(cfg.benchmark.workdir)

        kickoff_path = actual_workdir / "__iops_kickoff.sh"
        kickoff_path.write_text("#!/bin/bash\necho test")

        # Create test execution dir and script
        exec_dir = actual_workdir / "runs" / "exec_0001" / "repetition_001"
        exec_dir.mkdir(parents=True)
        script_file = exec_dir / "run_main.sh"
        script_file.write_text("#!/bin/bash\necho hello")

        executor = KickoffSingleAllocationExecutor(cfg, kickoff_path)

        # Mock sbatch to return job ID
        mock_run.return_value = Mock(
            returncode=0,
            stdout="Submitted batch job 12345\n",
            stderr=""
        )

        # Create test instance
        test = ExecutionInstance(
            execution_id=1,
            base_vars={"param_a": 1},
            command_template="echo 1",
            script_template="#!/bin/bash\necho 1",
            script_name="main"
        )
        test.execution_dir = exec_dir
        test.script_file = script_file

        executor.submit(test)

        assert executor.kickoff_submitted is True
        assert executor.allocation_job_id == "12345"
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_submit_reuses_allocation_on_subsequent_calls(self, mock_run, sample_kickoff_config, tmp_path):
        """Test that subsequent submit() calls don't re-submit the kickoff."""
        import yaml
        from iops.execution.matrix import ExecutionInstance

        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())

        # Use the rendered workdir (e.g., workdir/run_001)
        actual_workdir = Path(cfg.benchmark.workdir)

        kickoff_path = actual_workdir / "__iops_kickoff.sh"
        kickoff_path.write_text("#!/bin/bash\necho test")

        executor = KickoffSingleAllocationExecutor(cfg, kickoff_path)

        # Mock sbatch
        mock_run.return_value = Mock(
            returncode=0,
            stdout="Submitted batch job 12345\n",
            stderr=""
        )

        # Create two test instances
        for i in [1, 2]:
            exec_dir = actual_workdir / "runs" / f"exec_{i:04d}" / "repetition_001"
            exec_dir.mkdir(parents=True)
            script_file = exec_dir / "run_main.sh"
            script_file.write_text("#!/bin/bash\necho hello")

            test = ExecutionInstance(
                execution_id=i,
                base_vars={"param_a": i},
                command_template=f"echo {i}",
                script_template=f"#!/bin/bash\necho {i}",
                script_name="main"
            )
            test.execution_dir = exec_dir
            test.script_file = script_file

            executor.submit(test)

        # sbatch should only be called once
        assert mock_run.call_count == 1
        assert executor.allocation_job_id == "12345"


# ============================================================================ #
# Runner Integration Tests
# ============================================================================ #

class TestRunnerKickoffMode:
    """Tests for runner kickoff mode detection and initialization."""

    def test_runner_detects_kickoff_mode(self, sample_kickoff_config, tmp_path):
        """Test that runner detects kickoff mode from config."""
        import yaml
        from iops.execution.runner import IOPSRunner

        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())

        # Create minimal args mock
        args = Mock()
        args.use_cache = False

        runner = IOPSRunner(cfg, args)

        assert runner.kickoff_mode is True
        assert isinstance(runner.executor, KickoffSingleAllocationExecutor)

    def test_runner_creates_kickoff_script(self, sample_kickoff_config, tmp_path):
        """Test that runner creates kickoff script during init."""
        import yaml
        from iops.execution.runner import IOPSRunner

        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())

        args = Mock()
        args.use_cache = False

        runner = IOPSRunner(cfg, args)

        # Kickoff script is created in the rendered workdir (e.g., workdir/run_001)
        actual_workdir = Path(cfg.benchmark.workdir)
        kickoff_script = actual_workdir / "__iops_kickoff.sh"
        assert kickoff_script.exists()

    def test_runner_not_kickoff_mode_for_per_test(self, sample_kickoff_config, tmp_path):
        """Test that runner is not in kickoff mode for per-test mode."""
        import yaml
        from iops.execution.runner import IOPSRunner

        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True)
        sample_kickoff_config["benchmark"]["workdir"] = str(workdir)
        sample_kickoff_config["benchmark"]["slurm_options"]["allocation"]["mode"] = "per-test"

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(sample_kickoff_config))

        cfg = load_generic_config(Path(config_file), _get_logger())

        args = Mock()
        args.use_cache = False

        runner = IOPSRunner(cfg, args)

        assert runner.kickoff_mode is False
        assert not isinstance(runner.executor, KickoffSingleAllocationExecutor)
