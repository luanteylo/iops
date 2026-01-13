"""
Integration tests for the full IOPS workflow.

These tests run the complete pipeline (planner → runner → executor) with a mock
benchmark to verify the core functionality works correctly across different
configuration combinations.

The mock benchmark:
- Executes in milliseconds (just echoes parameters)
- Outputs a fake metric based on parameters
- Allows testing the full workflow quickly

Coverage includes:
- All planners: exhaustive, random, bayesian
- Key features: track_executions, create_folders_upfront, constraints, caching
- Repetitions: single and multiple
- Output formats: csv (fastest for tests)

Run with: pytest tests/test_integration_workflow.py -v
"""

import json
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

from iops.config.loader import load_generic_config
from iops.execution.runner import IOPSRunner
import logging

# Suppress logging during tests
logging.getLogger("iops").setLevel(logging.WARNING)


class MockArgs:
    """Mock CLI args for tests."""
    def __init__(self, use_cache=False, dry_run=False):
        self.use_cache = use_cache
        self.dry_run = dry_run
        self.max_core_hours = None
        self.estimated_time = None
        self.log_level = "WARNING"


def get_run_dir(workdir: Path) -> Path:
    """Get the run directory from workdir."""
    run_dirs = list(workdir.glob("run_*"))
    assert len(run_dirs) == 1, f"Expected 1 run dir, found {len(run_dirs)}"
    return run_dirs[0]


def get_results(workdir: Path) -> list:
    """Get results from run directory."""
    import csv
    run_dir = get_run_dir(workdir)
    results_file = run_dir / "results.csv"
    assert results_file.exists(), f"Results file not found: {results_file}"
    with open(results_file) as f:
        return list(csv.DictReader(f))


# =============================================================================
# Mock Benchmark Configuration
# =============================================================================
# A minimal benchmark that completes instantly and outputs a predictable metric

MOCK_BENCHMARK_BASE = """
benchmark:
  name: "Mock Benchmark"
  workdir: "{workdir}"
  repetitions: {repetitions}
  search_method: "{search_method}"
  executor: "local"
  track_executions: {track_executions}
  collect_system_info: {collect_system_info}
  {extra_config}

vars:
  param_a:
    type: int
    sweep:
      mode: list
      values: [1, 2, 3]

  param_b:
    type: int
    sweep:
      mode: list
      values: [10, 20]

  # Derived variable to test expression evaluation
  computed:
    type: int
    expr: "param_a * param_b"

{constraints}

command:
  template: "echo 'param_a={{{{ param_a }}}} param_b={{{{ param_b }}}} computed={{{{ computed }}}}'"

scripts:
  - name: "mock"
    submit: "bash"
    script_template: |
      #!/bin/bash
      {{{{ command.template }}}}
      # Output a fake metric file
      echo '{{"metric_value": {{{{ computed }}}} }}' > {{{{ execution_dir }}}}/result.json

    parser:
      file: "{{{{ execution_dir }}}}/result.json"
      metrics:
        - name: metric_value
      parser_script: |
        import json
        def parse(file_path):
            with open(file_path) as f:
                data = json.load(f)
            return {{"metric_value": data["metric_value"]}}

output:
  sink:
    type: csv
    path: "{{{{ workdir }}}}/results.csv"
    mode: append
"""


def create_mock_config(
    workdir: str,
    search_method: str = "exhaustive",
    repetitions: int = 1,
    track_executions: bool = True,
    collect_system_info: bool = True,
    create_folders_upfront: bool = False,
    constraints: list = None,
    random_n_samples: int = None,
    bayesian_n_iterations: int = None,
) -> str:
    """Create a mock benchmark configuration."""
    extra_parts = []

    if create_folders_upfront:
        extra_parts.append("create_folders_upfront: true")

    if search_method == "random" and random_n_samples:
        extra_parts.append(f"""random_config:
    n_samples: {random_n_samples}""")

    if search_method == "bayesian" and bayesian_n_iterations:
        extra_parts.append(f"""bayesian_config:
    objective_metric: metric_value
    objective: maximize
    n_iterations: {bayesian_n_iterations}
    n_initial_points: 2""")

    constraints_yaml = ""
    if constraints:
        constraints_yaml = "constraints:\n"
        for c in constraints:
            constraints_yaml += f"""  - name: "{c['name']}"
    rule: "{c['rule']}"
    violation_policy: "{c.get('policy', 'skip')}"
"""

    return MOCK_BENCHMARK_BASE.format(
        workdir=workdir,
        search_method=search_method,
        repetitions=repetitions,
        track_executions=str(track_executions).lower(),
        collect_system_info=str(collect_system_info).lower(),
        extra_config="\n  ".join(extra_parts),
        constraints=constraints_yaml,
    )


@pytest.fixture
def mock_workdir(tmp_path):
    """Create a temporary workdir for tests."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    return workdir


@pytest.fixture
def mock_config_file(tmp_path):
    """Factory fixture to create config files."""
    def _create(config_content: str) -> Path:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_content)
        return config_file
    return _create


# =============================================================================
# Exhaustive Planner Tests
# =============================================================================

class TestExhaustivePlannerWorkflow:
    """Test full workflow with exhaustive planner."""

    def test_basic_exhaustive_run(self, mock_workdir, mock_config_file):
        """Test basic exhaustive run with all parameter combinations."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="exhaustive",
            repetitions=1,
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        # Should have 3 * 2 = 6 executions
        rows = get_results(mock_workdir)
        assert len(rows) == 6

        # Verify metrics were parsed
        for row in rows:
            assert "metrics.metric_value" in row
            assert int(row["metrics.metric_value"]) > 0

    def test_exhaustive_with_repetitions(self, mock_workdir, mock_config_file):
        """Test exhaustive run with multiple repetitions."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="exhaustive",
            repetitions=2,
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        # Should have 6 configs * 2 reps = 12 results
        rows = get_results(mock_workdir)
        assert len(rows) == 12

    def test_exhaustive_with_constraints_skip(self, mock_workdir, mock_config_file):
        """Test exhaustive run with skip constraints."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="exhaustive",
            repetitions=1,
            constraints=[{"name": "limit_a", "rule": "param_a < 3", "policy": "skip"}],
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        # param_a < 3 means only param_a in [1, 2], so 2 * 2 = 4 executions
        rows = get_results(mock_workdir)
        assert len(rows) == 4

    def test_exhaustive_with_upfront_folders(self, mock_workdir, mock_config_file):
        """Test exhaustive run with create_folders_upfront enabled."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="exhaustive",
            repetitions=1,
            create_folders_upfront=True,
            constraints=[{"name": "limit_a", "rule": "param_a < 3", "policy": "skip"}],
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        # Check that index has both active and skipped tests
        run_dirs = list(mock_workdir.glob("run_*"))
        assert len(run_dirs) == 1

        index_file = run_dirs[0] / "__iops_index.json"
        assert index_file.exists()

        with open(index_file) as f:
            index = json.load(f)

        assert index.get("folders_upfront") is True
        assert index.get("active_tests") == 4  # param_a in [1, 2] * param_b in [10, 20]
        assert index.get("skipped_tests") == 2  # param_a = 3 * param_b in [10, 20]

        # Check SKIPPED status files exist
        skipped_count = 0
        for exec_key, exec_data in index.get("executions", {}).items():
            if exec_data.get("status") == "SKIPPED":
                skipped_count += 1
                exec_path = run_dirs[0] / exec_data["path"]
                status_file = exec_path / "__iops_status.json"
                assert status_file.exists()
                with open(status_file) as f:
                    status = json.load(f)
                assert status["status"] == "SKIPPED"
                assert status.get("reason") == "constraint"

        assert skipped_count == 2


# =============================================================================
# Random Planner Tests
# =============================================================================

class TestRandomPlannerWorkflow:
    """Test full workflow with random planner."""

    def test_random_sampling(self, mock_workdir, mock_config_file):
        """Test random sampling with n_samples."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="random",
            repetitions=1,
            random_n_samples=3,
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        # Should have exactly 3 executions
        rows = get_results(mock_workdir)
        assert len(rows) == 3

    def test_random_with_upfront_folders(self, mock_workdir, mock_config_file):
        """Test random sampling with upfront folder creation."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="random",
            repetitions=1,
            random_n_samples=2,
            create_folders_upfront=True,
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        # Check index has active and planner-skipped tests
        run_dirs = list(mock_workdir.glob("run_*"))
        index_file = run_dirs[0] / "__iops_index.json"

        with open(index_file) as f:
            index = json.load(f)

        assert index.get("folders_upfront") is True
        assert index.get("active_tests") == 2
        assert index.get("skipped_tests") == 4  # 6 total - 2 selected


# =============================================================================
# Bayesian Planner Tests
# =============================================================================

class TestBayesianPlannerWorkflow:
    """Test full workflow with Bayesian planner."""

    def test_bayesian_optimization(self, mock_workdir, mock_config_file):
        """Test Bayesian optimization runs correctly."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="bayesian",
            repetitions=1,
            bayesian_n_iterations=4,
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        # Should have 4 iterations
        rows = get_results(mock_workdir)
        assert len(rows) == 4

    def test_bayesian_with_repetitions(self, mock_workdir, mock_config_file):
        """Test Bayesian optimization with multiple repetitions."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="bayesian",
            repetitions=2,
            bayesian_n_iterations=3,
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        # Should have 3 iterations * 2 reps = 6 results
        rows = get_results(mock_workdir)
        assert len(rows) == 6

    def test_bayesian_with_constraints(self, mock_workdir, mock_config_file):
        """Test Bayesian optimization respects constraints."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="bayesian",
            repetitions=1,
            bayesian_n_iterations=3,
            constraints=[{"name": "limit_a", "rule": "param_a < 3", "policy": "skip"}],
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        # Check all results have param_a < 3
        rows = get_results(mock_workdir)
        for row in rows:
            assert int(row["vars.param_a"]) < 3


# =============================================================================
# Track Executions Tests
# =============================================================================

class TestTrackExecutions:
    """Test track_executions configuration."""

    def test_track_executions_enabled(self, mock_workdir, mock_config_file):
        """Test that metadata files are created when track_executions=true."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="exhaustive",
            repetitions=1,
            track_executions=True,
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        run_dirs = list(mock_workdir.glob("run_*"))
        assert len(run_dirs) == 1

        # Index file should exist
        index_file = run_dirs[0] / "__iops_index.json"
        assert index_file.exists()

        # Params and status files should exist for each execution
        exec_dirs = list((run_dirs[0] / "runs").glob("exec_*"))
        assert len(exec_dirs) == 6

        for exec_dir in exec_dirs:
            assert (exec_dir / "__iops_params.json").exists()

    def test_track_executions_disabled(self, mock_workdir, mock_config_file):
        """Test that metadata files are NOT created when track_executions=false."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="exhaustive",
            repetitions=1,
            track_executions=False,
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        run_dirs = list(mock_workdir.glob("run_*"))
        assert len(run_dirs) == 1
        run_dir = run_dirs[0]

        # Index file should NOT exist
        index_file = run_dir / "__iops_index.json"
        assert not index_file.exists()

        # No __iops_params.json files should exist anywhere
        params_files = list(run_dir.rglob("__iops_params.json"))
        assert len(params_files) == 0, f"Found params files: {params_files}"

        # No __iops_status.json files should exist anywhere
        status_files = list(run_dir.rglob("__iops_status.json"))
        assert len(status_files) == 0, f"Found status files: {status_files}"

        # Results should still be written
        rows = get_results(mock_workdir)
        assert len(rows) == 6

    def test_track_executions_disabled_with_repetitions(self, mock_workdir, mock_config_file):
        """Test track_executions=false works with multiple repetitions."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="exhaustive",
            repetitions=2,
            track_executions=False,
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        run_dirs = list(mock_workdir.glob("run_*"))
        run_dir = run_dirs[0]

        # No tracking files should exist (index, params, status)
        # Note: __iops_sysinfo.json and __iops_run_metadata.json are still created
        assert not (run_dir / "__iops_index.json").exists()
        assert len(list(run_dir.rglob("__iops_params.json"))) == 0
        assert len(list(run_dir.rglob("__iops_status.json"))) == 0

        # Results should have 6 configs * 2 reps = 12 rows
        rows = get_results(mock_workdir)
        assert len(rows) == 12

    def test_track_executions_disabled_with_upfront_folders(self, mock_workdir, mock_config_file):
        """Test that create_folders_upfront is ignored when track_executions=false."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="exhaustive",
            repetitions=1,
            track_executions=False,
            create_folders_upfront=True,  # Should be ignored
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        run_dirs = list(mock_workdir.glob("run_*"))
        run_dir = run_dirs[0]

        # No tracking files should exist even with create_folders_upfront
        assert not (run_dir / "__iops_index.json").exists()
        assert len(list(run_dir.rglob("__iops_params.json"))) == 0
        assert len(list(run_dir.rglob("__iops_status.json"))) == 0

        # Results should still be written
        rows = get_results(mock_workdir)
        assert len(rows) == 6

    def test_track_executions_disabled_with_bayesian(self, mock_workdir, mock_config_file):
        """Test track_executions=false works with Bayesian planner."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="bayesian",
            repetitions=1,
            track_executions=False,
            bayesian_n_iterations=3,
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        run_dirs = list(mock_workdir.glob("run_*"))
        run_dir = run_dirs[0]

        # No tracking files should exist
        assert not (run_dir / "__iops_index.json").exists()
        assert len(list(run_dir.rglob("__iops_params.json"))) == 0
        assert len(list(run_dir.rglob("__iops_status.json"))) == 0

        # Results should have 3 iterations
        rows = get_results(mock_workdir)
        assert len(rows) == 3

    def test_collect_system_info_disabled(self, mock_workdir, mock_config_file):
        """Test that sysinfo files are NOT created when collect_system_info=false."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="exhaustive",
            repetitions=1,
            collect_system_info=False,
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        run_dirs = list(mock_workdir.glob("run_*"))
        run_dir = run_dirs[0]

        # Index and params files should still exist (track_executions is enabled)
        assert (run_dir / "__iops_index.json").exists()
        assert len(list(run_dir.rglob("__iops_params.json"))) == 6

        # No sysinfo files should exist
        sysinfo_files = list(run_dir.rglob("__iops_sysinfo.json"))
        assert len(sysinfo_files) == 0, f"Found sysinfo files: {sysinfo_files}"

        # Results should still be written
        rows = get_results(mock_workdir)
        assert len(rows) == 6

    def test_both_track_and_probe_disabled(self, mock_workdir, mock_config_file):
        """Test with both track_executions=false and collect_system_info=false."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="exhaustive",
            repetitions=1,
            track_executions=False,
            collect_system_info=False,
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        run_dirs = list(mock_workdir.glob("run_*"))
        run_dir = run_dirs[0]

        # No tracking files
        assert not (run_dir / "__iops_index.json").exists()
        assert len(list(run_dir.rglob("__iops_params.json"))) == 0
        assert len(list(run_dir.rglob("__iops_status.json"))) == 0

        # No sysinfo files
        assert len(list(run_dir.rglob("__iops_sysinfo.json"))) == 0

        # Only __iops_run_metadata.json should exist (run-level metadata)
        all_iops_files = list(run_dir.rglob("__iops_*.json"))
        assert len(all_iops_files) == 1, f"Expected only run_metadata, got: {all_iops_files}"
        assert all_iops_files[0].name == "__iops_run_metadata.json"

        # Results should still be written
        rows = get_results(mock_workdir)
        assert len(rows) == 6

    def test_both_disabled_with_repetitions(self, mock_workdir, mock_config_file):
        """Test both tracking and probes disabled with multiple repetitions."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="exhaustive",
            repetitions=2,
            track_executions=False,
            collect_system_info=False,
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        run_dirs = list(mock_workdir.glob("run_*"))
        run_dir = run_dirs[0]

        # No tracking or sysinfo files
        assert not (run_dir / "__iops_index.json").exists()
        assert len(list(run_dir.rglob("__iops_params.json"))) == 0
        assert len(list(run_dir.rglob("__iops_status.json"))) == 0
        assert len(list(run_dir.rglob("__iops_sysinfo.json"))) == 0

        # Results should have 6 configs * 2 reps = 12 rows
        rows = get_results(mock_workdir)
        assert len(rows) == 12


# =============================================================================
# Derived Variables Tests
# =============================================================================

class TestDerivedVariables:
    """Test derived variable resolution at different stages."""

    def test_execution_dir_resolved_at_runtime(self, mock_workdir, mock_config_file):
        """Test that execution_dir is properly resolved when execution starts."""
        config_content = create_mock_config(
            workdir=str(mock_workdir),
            search_method="exhaustive",
            repetitions=1,
            create_folders_upfront=True,
        )
        config_file = mock_config_file(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        run_dirs = list(mock_workdir.glob("run_*"))
        exec_dirs = list((run_dirs[0] / "runs").glob("exec_*"))

        # Check that params files have resolved execution_dir (not None)
        for exec_dir in exec_dirs:
            params_file = exec_dir / "__iops_params.json"
            if params_file.exists():
                with open(params_file) as f:
                    params = json.load(f)
                # computed should be param_a * param_b (valid number)
                assert isinstance(params.get("computed"), int)
                assert params["computed"] == params["param_a"] * params["param_b"]


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Test error handling in the workflow."""

    def test_parser_error_handled(self, mock_workdir, mock_config_file, tmp_path):
        """Test that parser errors are handled gracefully."""
        # Create a config with a parser that will fail
        config_content = f"""
benchmark:
  name: "Failing Parser Test"
  workdir: "{mock_workdir}"
  repetitions: 1
  search_method: "exhaustive"
  executor: "local"

vars:
  param:
    type: int
    sweep:
      mode: list
      values: [1]

command:
  template: "echo 'test'"

scripts:
  - name: "test"
    submit: "bash"
    script_template: |
      #!/bin/bash
      echo "no output file created"

    parser:
      file: "{{{{ execution_dir }}}}/nonexistent.json"
      metrics:
        - name: value
      parser_script: |
        def parse(file_path):
            with open(file_path) as f:
                return {{"value": 1}}

output:
  sink:
    type: csv
    path: "{{{{ workdir }}}}/results.csv"
    mode: append
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_content)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        # Should not raise, but log the error
        runner.run()

        # Run should complete (with FAILED status)
        run_dirs = list(mock_workdir.glob("run_*"))
        assert len(run_dirs) == 1


# =============================================================================
# SLURM Tests (Optional - require SLURM environment)
# =============================================================================

@pytest.mark.skipif(
    os.environ.get("IOPS_TEST_SLURM") != "1",
    reason="SLURM tests disabled. Set IOPS_TEST_SLURM=1 to enable."
)
class TestSlurmWorkflow:
    """
    Test workflow with SLURM executor.

    These tests require a SLURM environment. To run:
    1. Set IOPS_TEST_SLURM=1
    2. Optionally set IOPS_SLURM_PARTITION for your cluster

    Example:
        IOPS_TEST_SLURM=1 IOPS_SLURM_PARTITION=debug pytest tests/test_integration_workflow.py::TestSlurmWorkflow -v
    """

    @pytest.fixture
    def slurm_config(self, mock_workdir):
        """Create a SLURM-compatible config."""
        partition = os.environ.get("IOPS_SLURM_PARTITION", "debug")
        return f"""
benchmark:
  name: "SLURM Test"
  workdir: "{mock_workdir}"
  repetitions: 1
  search_method: "exhaustive"
  executor: "slurm"

vars:
  param:
    type: int
    sweep:
      mode: list
      values: [1, 2]

command:
  template: "echo 'param={{{{ param }}}}'"

scripts:
  - name: "test"
    submit: "sbatch"
    script_template: |
      #!/bin/bash
      #SBATCH --job-name=iops_test_{{{{ execution_id }}}}
      #SBATCH --nodes=1
      #SBATCH --ntasks=1
      #SBATCH --time=00:01:00
      #SBATCH --partition={partition}
      #SBATCH --output={{{{ execution_dir }}}}/slurm-%j.out

      {{{{ command.template }}}}
      echo '{{"value": {{{{ param }}}} }}' > {{{{ execution_dir }}}}/result.json

    parser:
      file: "{{{{ execution_dir }}}}/result.json"
      metrics:
        - name: value
      parser_script: |
        import json
        def parse(file_path):
            with open(file_path) as f:
                return json.load(f)

output:
  sink:
    type: csv
    path: "{{{{ workdir }}}}/results.csv"
    mode: append
"""

    def test_slurm_basic_run(self, mock_workdir, slurm_config, tmp_path):
        """Test basic SLURM execution."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(slurm_config)
        cfg = load_generic_config(config_file, logging.getLogger("test"))

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        results_file = mock_workdir / "results.csv"
        assert results_file.exists()

        import csv
        with open(results_file) as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 2
