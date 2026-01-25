"""
Integration tests for IOPS with SLURM executor using Docker Slurm environment.

These tests verify IOPS functionality when using the SLURM executor against
a real (containerized) Slurm cluster.

Requirements:
- Docker Slurm cluster running (slurmctld, c1, c2 containers)
- /tmp/iops_slurm_tests bind-mounted to the same path in containers

Run with:
    pytest tests/test_slurm_integration.py -v

Environment variables:
- IOPS_SKIP_SLURM_TESTS=1: Skip all Slurm integration tests
"""

import csv
import json
import os
import shutil
import subprocess
import uuid
import pytest
import yaml
import logging
from pathlib import Path

from iops.config.loader import load_generic_config
from iops.execution.runner import IOPSRunner
from iops.execution.executors import (
    BaseExecutor,
    SlurmExecutor,
    KickoffSingleAllocationExecutor,
)


# Suppress logging during tests
logging.getLogger("iops").setLevel(logging.WARNING)

# Shared path - same on host and in containers (bind mount)
SLURM_SHARED_PATH = Path("/tmp/iops_slurm_tests")


# ============================================================================ #
# Fixtures and Helpers
# ============================================================================ #


def is_slurm_available() -> bool:
    """Check if Docker Slurm cluster is available and running."""
    if os.environ.get("IOPS_SKIP_SLURM_TESTS") == "1":
        return False

    if not SLURM_SHARED_PATH.exists():
        return False

    try:
        # Check that slurmctld is running and has nodes
        result = subprocess.run(
            ["docker", "exec", "slurmctld", "sinfo", "--noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0 or "normal" not in result.stdout:
            return False

        # Verify the shared path is accessible from the container
        result = subprocess.run(
            ["docker", "exec", "slurmctld", "ls", str(SLURM_SHARED_PATH)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        return False


# Pytest marker for Slurm tests
slurm_available = pytest.mark.skipif(
    not is_slurm_available(),
    reason="Docker Slurm cluster not available. Start cluster or set IOPS_SKIP_SLURM_TESTS=1 to skip."
)


@pytest.fixture(scope="module")
def slurm_test_base():
    """Create a base test directory in the shared folder."""
    if not SLURM_SHARED_PATH.exists():
        pytest.skip(f"Shared folder not found: {SLURM_SHARED_PATH}")

    test_id = str(uuid.uuid4())[:8]
    base_dir = SLURM_SHARED_PATH / f"iops_tests_{test_id}"
    base_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(base_dir, 0o777)

    yield base_dir

    # Cleanup using docker exec to handle files created by Slurm jobs (may be owned by different user)
    subprocess.run(
        ["docker", "exec", "slurmctld", "rm", "-rf", str(base_dir)],
        capture_output=True,
    )
    # Also try local cleanup for any remaining files
    if base_dir.exists():
        shutil.rmtree(base_dir, ignore_errors=True)


@pytest.fixture
def slurm_workdir(slurm_test_base):
    """Create a unique workdir for each test."""
    test_id = str(uuid.uuid4())[:8]
    workdir = slurm_test_base / f"test_{test_id}"
    workdir.mkdir(parents=True, exist_ok=True)
    os.chmod(workdir, 0o777)
    yield workdir
    # Clean up using docker exec to handle files created by Slurm jobs
    subprocess.run(
        ["docker", "exec", "slurmctld", "rm", "-rf", str(workdir)],
        capture_output=True,
    )
    # Also try local cleanup for any remaining files
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)


class MockArgs:
    """Mock CLI args for IOPS runner."""
    def __init__(self, use_cache=False, dry_run=False):
        self.use_cache = use_cache
        self.dry_run = dry_run
        self.max_core_hours = None
        self.estimated_time = None
        self.log_level = "WARNING"


# ============================================================================ #
# IOPS Config and Executor Building Tests
# ============================================================================ #


@slurm_available
class TestIOPSConfigWithSlurm:
    """Tests for IOPS configuration loading with Slurm executor."""

    def test_slurm_executor_building(self, slurm_workdir):
        """Test that SlurmExecutor is correctly built from config."""
        config = {
            "benchmark": {
                "name": "Slurm Config Test",
                "workdir": str(slurm_workdir),
                "executor": "slurm",
                "repetitions": 1,
                "search_method": "exhaustive",
                "slurm_options": {
                    "poll_interval": 5,
                }
            },
            "vars": {
                "x": {"type": "int", "sweep": {"mode": "list", "values": [1]}},
            },
            "command": {"template": "echo {{ x }}"},
            "scripts": [{
                "name": "test",
                "script_template": "#!/bin/bash\necho {{ x }}",
            }],
            "output": {
                "sink": {"type": "csv", "path": "{{ workdir }}/results.csv"}
            }
        }

        config_file = slurm_workdir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        cfg = load_generic_config(config_file, logging.getLogger("test"))
        executor = BaseExecutor.build(cfg)

        assert isinstance(executor, SlurmExecutor)
        assert executor.poll_interval == 5

    def test_kickoff_allocation_executor_building(self, slurm_workdir):
        """Test that KickoffSingleAllocationExecutor is correctly built from config."""
        config = {
            "benchmark": {
                "name": "Single Alloc Config Test",
                "workdir": str(slurm_workdir),
                "executor": "slurm",
                "repetitions": 1,
                "search_method": "exhaustive",
                "slurm_options": {
                    "poll_interval": 3,
                    "allocation": {
                        "mode": "single",
                        "test_timeout": 300,
                        "allocation_script": """#SBATCH --nodes=2
#SBATCH --time=01:00:00
#SBATCH --partition=normal

module purge""",
                    }
                }
            },
            "vars": {
                "x": {"type": "int", "sweep": {"mode": "list", "values": [1]}},
            },
            "command": {"template": "echo {{ x }}"},
            "scripts": [{
                "name": "test",
                "script_template": "#!/bin/bash\necho {{ x }}",
            }],
            "output": {
                "sink": {"type": "csv", "path": "{{ workdir }}/results.csv"}
            }
        }

        config_file = slurm_workdir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        cfg = load_generic_config(config_file, logging.getLogger("test"))
        executor = BaseExecutor.build(cfg)

        assert isinstance(executor, KickoffSingleAllocationExecutor)
        assert "#SBATCH --nodes=2" in executor.allocation.allocation_script
        assert executor.poll_interval == 3

    def test_custom_slurm_commands_in_config(self, slurm_workdir):
        """Test that custom Slurm commands are correctly parsed from config."""
        config = {
            "benchmark": {
                "name": "Custom Commands Test",
                "workdir": str(slurm_workdir),
                "executor": "slurm",
                "repetitions": 1,
                "search_method": "exhaustive",
                "slurm_options": {
                    "commands": {
                        "status": "custom_squeue -j {job_id}",
                        "info": "custom_scontrol show job {job_id}",
                        "cancel": "custom_scancel {job_id}",
                    }
                }
            },
            "vars": {
                "x": {"type": "int", "sweep": {"mode": "list", "values": [1]}},
            },
            "command": {"template": "echo {{ x }}"},
            "scripts": [{
                "name": "test",
                "script_template": "#!/bin/bash\necho {{ x }}",
            }],
            "output": {
                "sink": {"type": "csv", "path": "{{ workdir }}/results.csv"}
            }
        }

        config_file = slurm_workdir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        cfg = load_generic_config(config_file, logging.getLogger("test"))
        executor = BaseExecutor.build(cfg)

        assert executor.cmd_submit == "custom_sbatch"
        assert "custom_squeue" in executor.cmd_status
        assert "custom_scontrol" in executor.cmd_info
        assert "custom_scancel" in executor.cmd_cancel


# ============================================================================ #
# End-to-End IOPS Runner Tests with Slurm
# ============================================================================ #


@slurm_available
class TestIOPSRunnerWithSlurm:
    """
    End-to-end tests that run the full IOPS workflow with real Slurm jobs.

    These tests verify that IOPS correctly:
    - Generates and submits Slurm scripts
    - Polls for job completion
    - Parses results from completed jobs
    - Handles job failures
    """

    def test_pertest_mode_basic(self, slurm_workdir):
        """Test basic IOPS run with per-test Slurm submissions."""
        config = {
            "benchmark": {
                "name": "Per-Test Basic",
                "workdir": str(slurm_workdir),
                "executor": "slurm",
                "repetitions": 1,
                "search_method": "exhaustive",
                "track_executions": True,
                "collect_system_info": False,
                "slurm_options": {
                    "poll_interval": 2,
                    "commands": {
                        "status": "docker exec slurmctld squeue -j {job_id} --noheader --format=%T",
                        "info": "docker exec slurmctld scontrol show job {job_id}",
                        "cancel": "docker exec slurmctld scancel {job_id}",
                    }
                }
            },
            "vars": {
                "value": {"type": "int", "sweep": {"mode": "list", "values": [10, 20]}},
            },
            "command": {"template": "echo 'value={{ value }}'"},
            "scripts": [{
                "name": "test_script",
                "script_template": """#!/bin/bash
#SBATCH --job-name=iops_{{ execution_id }}
#SBATCH --time=00:02:00
#SBATCH --nodes=1
#SBATCH --output={{ execution_dir }}/slurm.out

echo '{"result": {{ value }} }' > "{{ execution_dir }}/result.json"
""",
                "parser": {
                    "file": "{{ execution_dir }}/result.json",
                    "metrics": [{"name": "result", "type": "int"}],
                    "parser_script": """
import json
def parse(file_path):
    with open(file_path) as f:
        return json.load(f)
"""
                }
            }],
            "output": {
                "sink": {"type": "csv", "path": "{{ workdir }}/results.csv"}
            }
        }

        config_file = slurm_workdir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        cfg = load_generic_config(config_file, logging.getLogger("test"))
        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        # Verify results
        run_dirs = list(slurm_workdir.glob("run_*"))
        assert len(run_dirs) == 1

        results_file = run_dirs[0] / "results.csv"
        assert results_file.exists()

        with open(results_file) as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 2
        values = {int(row["vars.value"]): int(row["metrics.result"]) for row in rows}
        assert values[10] == 10
        assert values[20] == 20

    def test_pertest_with_repetitions(self, slurm_workdir):
        """Test per-test mode with multiple repetitions."""
        config = {
            "benchmark": {
                "name": "Per-Test Repetitions",
                "workdir": str(slurm_workdir),
                "executor": "slurm",
                "repetitions": 2,
                "search_method": "exhaustive",
                "track_executions": True,
                "collect_system_info": False,
                "slurm_options": {
                    "poll_interval": 2,
                    "commands": {
                        "status": "docker exec slurmctld squeue -j {job_id} --noheader --format=%T",
                        "info": "docker exec slurmctld scontrol show job {job_id}",
                        "cancel": "docker exec slurmctld scancel {job_id}",
                    }
                }
            },
            "vars": {
                "x": {"type": "int", "sweep": {"mode": "list", "values": [5]}},
            },
            "command": {"template": "echo {{ x }}"},
            "scripts": [{
                "name": "test",
                "script_template": """#!/bin/bash
#SBATCH --job-name=iops_{{ execution_id }}_r{{ repetition }}
#SBATCH --time=00:02:00
#SBATCH --nodes=1
#SBATCH --output={{ execution_dir }}/slurm.out

echo '{"value": {{ x }} }' > "{{ execution_dir }}/result.json"
""",
                "parser": {
                    "file": "{{ execution_dir }}/result.json",
                    "metrics": [{"name": "value", "type": "int"}],
                    "parser_script": """
import json
def parse(file_path):
    with open(file_path) as f:
        return json.load(f)
"""
                }
            }],
            "output": {
                "sink": {"type": "csv", "path": "{{ workdir }}/results.csv"}
            }
        }

        config_file = slurm_workdir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        cfg = load_generic_config(config_file, logging.getLogger("test"))
        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        # Should have 1 param * 2 reps = 2 results
        run_dirs = list(slurm_workdir.glob("run_*"))
        results_file = run_dirs[0] / "results.csv"

        with open(results_file) as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 2

    @pytest.mark.skip(reason="Requires SLURM compute nodes with srun support - Docker setup incomplete")
    def test_single_allocation_mode(self, slurm_workdir):
        """Test IOPS run with single-allocation mode."""
        config = {
            "benchmark": {
                "name": "Single Allocation",
                "workdir": str(slurm_workdir),
                "executor": "slurm",
                "repetitions": 1,
                "search_method": "exhaustive",
                "track_executions": True,
                "collect_system_info": False,
                "slurm_options": {
                    "poll_interval": 2,
                    "commands": {
                        "status": "docker exec slurmctld squeue -j {job_id} --noheader --format=%T",
                        "info": "docker exec slurmctld scontrol show job {job_id}",
                        "cancel": "docker exec slurmctld scancel {job_id}",
                        "srun": "docker exec slurmctld srun",
                    },
                    "allocation": {
                        "mode": "single",
                        "allocation_script": """#SBATCH --nodes=1
#SBATCH --time=00:10:00""",
                    }
                }
            },
            "vars": {
                "n": {"type": "int", "sweep": {"mode": "list", "values": [100, 200]}},
            },
            "command": {"template": "echo {{ n }}"},
            "scripts": [{
                "name": "test",
                "script_template": """#!/bin/bash
echo '{"value": {{ n }} }' > "{{ execution_dir }}/result.json"
""",
                "parser": {
                    "file": "{{ execution_dir }}/result.json",
                    "metrics": [{"name": "value", "type": "int"}],
                    "parser_script": """
import json
def parse(file_path):
    with open(file_path) as f:
        return json.load(f)
"""
                }
            }],
            "output": {
                "sink": {"type": "csv", "path": "{{ workdir }}/results.csv"}
            }
        }

        config_file = slurm_workdir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        cfg = load_generic_config(config_file, logging.getLogger("test"))
        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        # Verify results
        run_dirs = list(slurm_workdir.glob("run_*"))
        assert len(run_dirs) == 1

        results_file = run_dirs[0] / "results.csv"
        assert results_file.exists()

        with open(results_file) as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 2
        values = {int(row["vars.n"]): int(row["metrics.value"]) for row in rows}
        assert values[100] == 100
        assert values[200] == 200

    def test_failed_job_status_recorded(self, slurm_workdir):
        """Test that failed Slurm jobs are properly recorded with FAILED status."""
        config = {
            "benchmark": {
                "name": "Failed Job Test",
                "workdir": str(slurm_workdir),
                "executor": "slurm",
                "repetitions": 1,
                "search_method": "exhaustive",
                "track_executions": True,
                "collect_system_info": False,
                "slurm_options": {
                    "poll_interval": 2,
                    "commands": {
                        "status": "docker exec slurmctld squeue -j {job_id} --noheader --format=%T",
                        "info": "docker exec slurmctld scontrol show job {job_id}",
                        "cancel": "docker exec slurmctld scancel {job_id}",
                    }
                }
            },
            "vars": {
                "x": {"type": "int", "sweep": {"mode": "list", "values": [1]}},
            },
            "command": {"template": "exit 1"},
            "scripts": [{
                "name": "failing_script",
                "script_template": """#!/bin/bash
#SBATCH --job-name=iops_fail_{{ execution_id }}
#SBATCH --time=00:01:00
#SBATCH --nodes=1
#SBATCH --output={{ execution_dir }}/slurm.out

echo "About to fail"
exit 1
""",
                "parser": {
                    "file": "{{ execution_dir }}/result.json",
                    "metrics": [{"name": "value", "type": "int"}],
                    "parser_script": "def parse(f): return {'value': 0}"
                }
            }],
            "output": {
                "sink": {"type": "csv", "path": "{{ workdir }}/results.csv"}
            }
        }

        config_file = slurm_workdir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        cfg = load_generic_config(config_file, logging.getLogger("test"))
        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        # Check that status was recorded
        run_dirs = list(slurm_workdir.glob("run_*"))
        exec_dirs = list((run_dirs[0] / "runs").glob("exec_*"))
        assert len(exec_dirs) == 1

        # Check __iops_status.json shows FAILED
        status_file = exec_dirs[0] / "__iops_status.json"
        if status_file.exists():
            with open(status_file) as f:
                status = json.load(f)
            assert status["status"] == "FAILED"

    def test_caching_works_with_slurm(self, slurm_workdir):
        """Test that IOPS caching works correctly with Slurm executor."""
        config = {
            "benchmark": {
                "name": "Cache Test",
                "workdir": str(slurm_workdir),
                "executor": "slurm",
                "repetitions": 1,
                "search_method": "exhaustive",
                "track_executions": True,
                "collect_system_info": False,
                "slurm_options": {
                    "poll_interval": 2,
                    "commands": {
                        "status": "docker exec slurmctld squeue -j {job_id} --noheader --format=%T",
                        "info": "docker exec slurmctld scontrol show job {job_id}",
                        "cancel": "docker exec slurmctld scancel {job_id}",
                    }
                }
            },
            "vars": {
                "v": {"type": "int", "sweep": {"mode": "list", "values": [42]}},
            },
            "command": {"template": "echo {{ v }}"},
            "scripts": [{
                "name": "test",
                "script_template": """#!/bin/bash
#SBATCH --job-name=iops_cache_{{ execution_id }}
#SBATCH --time=00:02:00
#SBATCH --nodes=1
#SBATCH --output={{ execution_dir }}/slurm.out

echo '{"value": {{ v }} }' > "{{ execution_dir }}/result.json"
""",
                "parser": {
                    "file": "{{ execution_dir }}/result.json",
                    "metrics": [{"name": "value", "type": "int"}],
                    "parser_script": """
import json
def parse(file_path):
    with open(file_path) as f:
        return json.load(f)
"""
                }
            }],
            "output": {
                "sink": {"type": "csv", "path": "{{ workdir }}/results.csv"}
            }
        }

        config_file = slurm_workdir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        # First run
        cfg = load_generic_config(config_file, logging.getLogger("test"))
        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        # Count jobs submitted in first run
        run_dirs = list(slurm_workdir.glob("run_*"))
        first_run_results = run_dirs[0] / "results.csv"
        with open(first_run_results) as f:
            first_count = len(list(csv.DictReader(f)))
        assert first_count == 1

        # Second run with cache - should skip execution
        cfg2 = load_generic_config(config_file, logging.getLogger("test"))
        runner2 = IOPSRunner(cfg2, MockArgs(use_cache=True))
        runner2.run()

        # Should have 2 run directories now
        run_dirs = list(slurm_workdir.glob("run_*"))
        assert len(run_dirs) == 2
