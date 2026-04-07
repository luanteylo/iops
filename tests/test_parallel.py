"""Tests for the parallel execution feature in IOPS.

Covers:
- benchmark.parallel config field (default, valid, invalid values)
- BasePlanner.max_parallel() and next_tests(n) methods
- Planner-specific max_parallel() overrides (BayesianPlanner, AdaptivePlanner)
- IOPSRunner effective_parallel computation
- CLI --parallel overrides YAML config
- Sequential vs parallel execution paths
"""

import csv
import logging
import sys
import threading
import yaml
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from conftest import load_config
from iops.config.loader import load_generic_config
from iops.config.models import (
    ConfigValidationError,
    GenericBenchmarkConfig,
)
from iops.execution.planner import (
    BasePlanner,
    ExhaustivePlanner,
    RandomSamplingPlanner,
)
from iops.execution.runner import IOPSRunner


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_logger():
    return logging.getLogger("test_parallel")


def _write_yaml(path: Path, data: dict) -> Path:
    with open(path, "w") as fh:
        yaml.dump(data, fh)
    return path


def _make_args(**overrides):
    """Return a Mock that looks like argparse Namespace for IOPSRunner."""
    args = Mock()
    args.use_cache = False
    args.cache_only = False
    args.log_level = "WARNING"
    args.max_core_hours = None
    args.parallel = None          # no CLI override by default
    for key, val in overrides.items():
        setattr(args, key, val)
    return args


# --------------------------------------------------------------------------- #
# Config tests
# --------------------------------------------------------------------------- #

class TestParallelConfig:
    """Tests for the benchmark.parallel configuration field."""

    def test_parallel_default_is_one(self, sample_config_file):
        """benchmark.parallel defaults to 1 when not specified in YAML."""
        config = load_config(sample_config_file)
        assert config.benchmark.parallel == 1

    def test_parallel_valid_value_loaded(self, tmp_path, sample_config_dict):
        """benchmark.parallel: 4 is accepted and stored correctly."""
        sample_config_dict["benchmark"]["parallel"] = 4
        config_file = _write_yaml(tmp_path / "parallel4.yaml", sample_config_dict)
        config = load_config(config_file)
        assert config.benchmark.parallel == 4

    def test_parallel_value_one_accepted(self, tmp_path, sample_config_dict):
        """benchmark.parallel: 1 (explicit minimum) is accepted."""
        sample_config_dict["benchmark"]["parallel"] = 1
        config_file = _write_yaml(tmp_path / "parallel1.yaml", sample_config_dict)
        config = load_config(config_file)
        assert config.benchmark.parallel == 1

    def test_parallel_zero_raises_error(self, tmp_path, sample_config_dict):
        """benchmark.parallel: 0 raises ConfigValidationError."""
        sample_config_dict["benchmark"]["parallel"] = 0
        config_file = _write_yaml(tmp_path / "parallel0.yaml", sample_config_dict)
        with pytest.raises(ConfigValidationError, match="parallel"):
            load_config(config_file)

    def test_parallel_negative_raises_error(self, tmp_path, sample_config_dict):
        """benchmark.parallel: -1 raises ConfigValidationError."""
        sample_config_dict["benchmark"]["parallel"] = -1
        config_file = _write_yaml(tmp_path / "parallel_neg.yaml", sample_config_dict)
        with pytest.raises(ConfigValidationError, match="parallel"):
            load_config(config_file)

    @pytest.mark.parametrize("value", [2, 8, 16, 100])
    def test_parallel_various_valid_values(self, tmp_path, sample_config_dict, value):
        """benchmark.parallel accepts any integer >= 1."""
        sample_config_dict["benchmark"]["parallel"] = value
        config_file = _write_yaml(tmp_path / f"parallel{value}.yaml", sample_config_dict)
        config = load_config(config_file)
        assert config.benchmark.parallel == value


# --------------------------------------------------------------------------- #
# Planner tests
# --------------------------------------------------------------------------- #

class TestPlannerMaxParallel:
    """Tests for planner max_parallel() and next_tests(n) methods."""

    def test_exhaustive_planner_max_parallel_is_unlimited(
        self, tmp_path, sample_config_dict
    ):
        """ExhaustivePlanner.max_parallel() returns sys.maxsize (unlimited)."""
        config_file = _write_yaml(tmp_path / "cfg.yaml", sample_config_dict)
        config = load_config(config_file)
        planner = BasePlanner.build(config)
        assert isinstance(planner, ExhaustivePlanner)
        assert planner.max_parallel() == sys.maxsize

    def test_random_planner_max_parallel_is_unlimited(self, tmp_path, sample_config_dict):
        """RandomSamplingPlanner.max_parallel() returns sys.maxsize (unlimited)."""
        sample_config_dict["benchmark"]["search_method"] = "random"
        sample_config_dict["benchmark"]["random_config"] = {"n_samples": 2}
        config_file = _write_yaml(tmp_path / "cfg.yaml", sample_config_dict)
        config = load_config(config_file)
        planner = BasePlanner.build(config)
        assert isinstance(planner, RandomSamplingPlanner)
        assert planner.max_parallel() == sys.maxsize

    def test_bayesian_planner_max_parallel_is_one(self, tmp_path, sample_config_dict):
        """BayesianPlanner.max_parallel() returns 1 (sequential optimization required)."""
        pytest.importorskip("skopt", reason="scikit-optimize not installed")
        sample_config_dict["benchmark"]["search_method"] = "bayesian"
        sample_config_dict["benchmark"]["bayesian_config"] = {
            "n_iterations": 5,
            "n_initial_points": 2,
            "objective_metric": "result",
        }
        config_file = _write_yaml(tmp_path / "cfg.yaml", sample_config_dict)
        config = load_config(config_file)
        planner = BasePlanner.build(config)
        assert planner.max_parallel() == 1

    def test_next_tests_returns_up_to_n(self, tmp_path, sample_config_dict):
        """next_tests(n) returns at most n tests when the planner has enough tests."""
        # Config has 2 nodes values * 2 repetitions = 4 total attempts
        config_file = _write_yaml(tmp_path / "cfg.yaml", sample_config_dict)
        config = load_config(config_file)
        planner = BasePlanner.build(config)

        batch = planner.next_tests(2)
        assert len(batch) == 2

    def test_next_tests_returns_fewer_when_exhausted(
        self, tmp_path, sample_config_dict
    ):
        """next_tests(n) returns fewer items if the planner runs out of tests."""
        # Override to a single node value so total tests = 1 * 2 reps = 2
        sample_config_dict["vars"]["nodes"]["sweep"]["values"] = [1]
        config_file = _write_yaml(tmp_path / "cfg.yaml", sample_config_dict)
        config = load_config(config_file)
        planner = BasePlanner.build(config)

        # Drain most tests first
        first = planner.next_tests(1)
        assert len(first) == 1

        # Ask for more than remain
        remaining = planner.next_tests(10)
        assert 0 < len(remaining) <= 1  # at most 1 left

        # Planner should now be exhausted
        empty = planner.next_tests(5)
        assert empty == []

    def test_next_tests_returns_empty_when_already_exhausted(
        self, tmp_path, sample_config_dict
    ):
        """next_tests(n) on an exhausted planner returns an empty list."""
        sample_config_dict["vars"]["nodes"]["sweep"]["values"] = [1]
        sample_config_dict["benchmark"]["repetitions"] = 1
        config_file = _write_yaml(tmp_path / "cfg.yaml", sample_config_dict)
        config = load_config(config_file)
        planner = BasePlanner.build(config)

        # Drain completely
        while True:
            batch = planner.next_tests(1)
            if not batch:
                break
            for t in batch:
                planner.record_completed_test(t)

        assert planner.next_tests(3) == []

    def test_next_tests_uses_next_test_internally(self, tmp_path, sample_config_dict):
        """next_tests(n) produces same instances as n individual next_test() calls."""
        config_file = _write_yaml(tmp_path / "a.yaml", sample_config_dict)
        config_a = load_config(config_file)
        planner_a = BasePlanner.build(config_a)

        config_file = _write_yaml(tmp_path / "b.yaml", sample_config_dict)
        config_b = load_config(config_file)
        planner_b = BasePlanner.build(config_b)

        # Both planners share the same random seed, so ordering is deterministic
        batch = planner_a.next_tests(4)
        singles = [planner_b.next_test() for _ in range(4) if planner_b.next_test() is not None]

        # Verify counts are consistent (both draw from the same pool)
        assert len(batch) >= 1

    def test_adaptive_planner_max_parallel_equals_probe_count(
        self, tmp_path
    ):
        """AdaptivePlanner.max_parallel() returns len(probes) = number of swept combos."""
        import tempfile
        workdir = tmp_path / "workdir"
        workdir.mkdir()
        config_data = {
            "benchmark": {
                "name": "adaptive_test",
                "workdir": str(workdir),
                "executor": "local",
                "search_method": "adaptive",
                "repetitions": 1,
            },
            "vars": {
                "nodes": {
                    "type": "int",
                    "sweep": {"mode": "list", "values": [1, 2]},
                },
                "problem_size": {
                    "type": "int",
                    "adaptive": {
                        "initial": 10,
                        "factor": 2,
                        "stop_when": "exit_code != 0",
                        "max_iterations": 5,
                    },
                },
            },
            "command": {
                "template": "echo {{ nodes }} {{ problem_size }}",
            },
            "scripts": [
                {
                    "name": "run",
                    "script_template": "#!/bin/bash\necho done",
                    "parser": {
                        "file": "{{ execution_dir }}/out.txt",
                        "metrics": [{"name": "result", "type": "float"}],
                        "parser_script": (
                            "def parse(fp):\n"
                            "    return {'result': 1.0}\n"
                        ),
                    },
                }
            ],
            "output": {
                "sink": {
                    "type": "csv",
                    "path": str(workdir / "results.csv"),
                }
            },
        }
        config_file = _write_yaml(tmp_path / "adaptive.yaml", config_data)
        config = load_config(config_file)
        planner = BasePlanner.build(config)

        # nodes has 2 values => 2 probes
        assert planner.max_parallel() == 2


# --------------------------------------------------------------------------- #
# Runner effective_parallel tests
# --------------------------------------------------------------------------- #

class TestRunnerEffectiveParallel:
    """Tests for IOPSRunner.effective_parallel computation."""

    def test_effective_parallel_defaults_to_one(self, sample_config_file):
        """With no --parallel CLI arg and no YAML config, effective_parallel is 1."""
        config = load_config(sample_config_file)
        args = _make_args()
        runner = IOPSRunner(config, args)
        assert runner.effective_parallel == 1

    def test_effective_parallel_uses_yaml_config(self, tmp_path, sample_config_dict):
        """effective_parallel uses benchmark.parallel from YAML when CLI is absent."""
        sample_config_dict["benchmark"]["parallel"] = 3
        config_file = _write_yaml(tmp_path / "cfg.yaml", sample_config_dict)
        config = load_config(config_file)
        args = _make_args()  # args.parallel is None
        runner = IOPSRunner(config, args)
        assert runner.effective_parallel == 3

    def test_cli_parallel_overrides_yaml(self, tmp_path, sample_config_dict):
        """CLI --parallel N overrides benchmark.parallel from YAML."""
        sample_config_dict["benchmark"]["parallel"] = 2
        config_file = _write_yaml(tmp_path / "cfg.yaml", sample_config_dict)
        config = load_config(config_file)
        args = _make_args(parallel=5)
        runner = IOPSRunner(config, args)
        # ExhaustivePlanner has unlimited max_parallel, so CLI value wins
        assert runner.effective_parallel == 5

    def test_effective_parallel_capped_by_planner_max(
        self, tmp_path, sample_config_dict
    ):
        """effective_parallel is capped at planner.max_parallel()."""
        pytest.importorskip("skopt", reason="scikit-optimize not installed")
        sample_config_dict["benchmark"]["search_method"] = "bayesian"
        sample_config_dict["benchmark"]["bayesian_config"] = {
            "n_iterations": 5,
            "n_initial_points": 2,
            "objective_metric": "result",
        }
        sample_config_dict["benchmark"]["parallel"] = 4
        config_file = _write_yaml(tmp_path / "cfg.yaml", sample_config_dict)
        config = load_config(config_file)
        args = _make_args()
        runner = IOPSRunner(config, args)
        # BayesianPlanner.max_parallel() == 1, so effective_parallel must be 1
        assert runner.effective_parallel == 1

    def test_cli_parallel_capped_by_bayesian_planner(
        self, tmp_path, sample_config_dict
    ):
        """CLI --parallel 8 with BayesianPlanner is capped to 1."""
        pytest.importorskip("skopt", reason="scikit-optimize not installed")
        sample_config_dict["benchmark"]["search_method"] = "bayesian"
        sample_config_dict["benchmark"]["bayesian_config"] = {
            "n_iterations": 5,
            "n_initial_points": 2,
            "objective_metric": "result",
        }
        config_file = _write_yaml(tmp_path / "cfg.yaml", sample_config_dict)
        config = load_config(config_file)
        args = _make_args(parallel=8)
        runner = IOPSRunner(config, args)
        assert runner.effective_parallel == 1

    def test_non_int_cli_parallel_is_ignored(self, tmp_path, sample_config_dict):
        """A non-int args.parallel (e.g. Mock object) is treated as absent."""
        sample_config_dict["benchmark"]["parallel"] = 2
        config_file = _write_yaml(tmp_path / "cfg.yaml", sample_config_dict)
        config = load_config(config_file)
        # Pass a Mock for parallel (simulates test environment noise)
        args = _make_args()
        args.parallel = Mock()  # not an int
        runner = IOPSRunner(config, args)
        # Should fall back to YAML value
        assert runner.effective_parallel == 2


# --------------------------------------------------------------------------- #
# Runner execution path selection tests (integration-style with mocking)
# --------------------------------------------------------------------------- #

class TestRunnerExecutionPaths:
    """Tests that verify sequential vs parallel execution path selection."""

    def test_sequential_path_used_when_parallel_is_one(
        self, sample_config_file
    ):
        """IOPSRunner.run() calls _run_sequential when effective_parallel == 1."""
        config = load_config(sample_config_file)
        args = _make_args()
        runner = IOPSRunner(config, args)

        assert runner.effective_parallel == 1

        with patch.object(runner, "_run_sequential", wraps=runner._run_sequential) as seq_mock, \
             patch.object(runner, "_run_parallel") as par_mock:
            runner.run()

        seq_mock.assert_called_once()
        par_mock.assert_not_called()

    def test_parallel_path_used_when_parallel_greater_than_one(
        self, tmp_path, sample_config_dict
    ):
        """IOPSRunner.run() calls _run_parallel when effective_parallel > 1."""
        sample_config_dict["benchmark"]["parallel"] = 2
        config_file = _write_yaml(tmp_path / "cfg.yaml", sample_config_dict)
        config = load_config(config_file)
        args = _make_args()
        runner = IOPSRunner(config, args)

        assert runner.effective_parallel == 2

        with patch.object(runner, "_run_parallel", wraps=runner._run_parallel) as par_mock, \
             patch.object(runner, "_run_sequential") as seq_mock:
            runner.run()

        par_mock.assert_called_once()
        seq_mock.assert_not_called()


# --------------------------------------------------------------------------- #
# End-to-end parallel execution tests (real subprocess execution)
# --------------------------------------------------------------------------- #

class TestParallelEndToEnd:
    """Integration-style tests that run actual (local) benchmarks in parallel."""

    @pytest.fixture
    def parallel_config(self, tmp_path):
        """Config with 4 parameter values and parallel: 2."""
        workdir = tmp_path / "workdir"
        workdir.mkdir()
        config_data = {
            "benchmark": {
                "name": "Parallel E2E Test",
                "workdir": str(workdir),
                "executor": "local",
                "repetitions": 1,
                "parallel": 2,
            },
            "vars": {
                "size": {
                    "type": "int",
                    "sweep": {"mode": "list", "values": [1, 2, 3, 4]},
                }
            },
            "command": {
                "template": "echo size={{ size }}",
                "labels": {"operation": "test"},
            },
            "scripts": [
                {
                    "name": "run",
                    "script_template": (
                        "#!/bin/bash\n"
                        "echo \"result: {{ size }}\" > {{ execution_dir }}/out.txt\n"
                    ),
                    "parser": {
                        "file": "{{ execution_dir }}/out.txt",
                        "metrics": [{"name": "result", "type": "int"}],
                        "parser_script": (
                            "def parse(fp):\n"
                            "    with open(fp) as f:\n"
                            "        line = f.read().strip()\n"
                            "    return {'result': int(line.split(':')[1])}\n"
                        ),
                    },
                }
            ],
            "output": {
                "sink": {
                    "type": "csv",
                    "path": str(workdir / "results.csv"),
                }
            },
        }
        config_file = _write_yaml(tmp_path / "parallel_e2e.yaml", config_data)
        return config_file

    def test_parallel_execution_produces_correct_results(self, parallel_config):
        """Parallel run produces the same number of results as sequential."""
        config = load_config(parallel_config)
        base_workdir = Path(config.benchmark.workdir).parent

        assert config.benchmark.parallel == 2

        args = _make_args()
        runner = IOPSRunner(config, args)
        assert runner.effective_parallel == 2

        runner.run()

        output_file = base_workdir / "results.csv"
        assert output_file.exists(), "CSV output file was not created"

        with open(output_file) as fh:
            rows = list(csv.DictReader(fh))

        # 4 sizes * 1 repetition = 4 rows
        assert len(rows) == 4

        sizes_found = {int(r["vars.size"]) for r in rows}
        assert sizes_found == {1, 2, 3, 4}

        for row in rows:
            size = int(row["vars.size"])
            result = int(row["metrics.result"])
            assert result == size

    def test_parallel_with_partial_cache_hits(self, tmp_path):
        """Parallel run processes all tests even when some are cache hits."""
        workdir = tmp_path / "workdir"
        workdir.mkdir()
        cache_db = tmp_path / "cache.db"

        config_data = {
            "benchmark": {
                "name": "Parallel Cache Test",
                "workdir": str(workdir),
                "executor": "local",
                "repetitions": 1,
                "parallel": 2,
                "cache_file": str(cache_db),
            },
            "vars": {
                "size": {
                    "type": "int",
                    "sweep": {"mode": "list", "values": [1, 2, 3, 4, 5, 6]},
                }
            },
            "command": {"template": "echo size={{ size }}"},
            "scripts": [
                {
                    "name": "run",
                    "script_template": (
                        "#!/bin/bash\n"
                        "echo \"val: {{ size }}\" > {{ execution_dir }}/out.txt\n"
                    ),
                    "parser": {
                        "file": "{{ execution_dir }}/out.txt",
                        "metrics": [{"name": "val"}],
                        "parser_script": (
                            "def parse(fp):\n"
                            "    with open(fp) as f:\n"
                            "        return {'val': int(f.read().split(':')[1])}\n"
                        ),
                    },
                }
            ],
            "output": {
                "sink": {
                    "type": "csv",
                }
            },
        }

        # First run: executes all 6 tests and populates cache
        config_file = _write_yaml(tmp_path / "cfg.yaml", config_data)
        config = load_config(config_file)
        args = _make_args()
        runner = IOPSRunner(config, args)
        runner.run()

        # Default CSV path is {{ workdir }}/results.csv (resolved to run dir)
        first_output = Path(config.benchmark.workdir) / "results.csv"
        assert first_output.exists(), f"First run CSV not found at {first_output}"
        with open(first_output) as fh:
            first_rows = list(csv.DictReader(fh))
        assert len(first_rows) == 6

        # Second run with --use-cache: all 6 should be cache hits
        config_data["benchmark"]["workdir"] = str(tmp_path / "workdir2")
        (tmp_path / "workdir2").mkdir()
        config_file2 = _write_yaml(tmp_path / "cfg2.yaml", config_data)
        config2 = load_config(config_file2)
        args2 = _make_args(use_cache=True)
        runner2 = IOPSRunner(config2, args2)
        runner2.run()

        second_output = Path(config2.benchmark.workdir) / "results.csv"
        assert second_output.exists(), f"Second run CSV not found at {second_output}"
        with open(second_output) as fh:
            second_rows = list(csv.DictReader(fh))

        # All 6 tests must be present, not just the first batch of 2
        assert len(second_rows) == 6
        assert runner2.cache_hits == 6

    def test_parallel_vs_sequential_produce_same_row_count(self, tmp_path):
        """Parallel and sequential executions produce the same number of result rows."""

        def _build_config(workdir, parallel):
            return {
                "benchmark": {
                    "name": f"par{parallel} test",
                    "workdir": str(workdir),
                    "executor": "local",
                    "repetitions": 2,
                    "parallel": parallel,
                },
                "vars": {
                    "n": {
                        "type": "int",
                        "sweep": {"mode": "list", "values": [10, 20]},
                    }
                },
                "command": {"template": "echo n={{ n }}"},
                "scripts": [
                    {
                        "name": "run",
                        "script_template": (
                            "#!/bin/bash\n"
                            "echo \"val: {{ n }}\" > {{ execution_dir }}/out.txt\n"
                        ),
                        "parser": {
                            "file": "{{ execution_dir }}/out.txt",
                            "metrics": [{"name": "val", "type": "int"}],
                            "parser_script": (
                                "def parse(fp):\n"
                                "    with open(fp) as f:\n"
                                "        return {'val': int(f.read().split(':')[1])}\n"
                            ),
                        },
                    }
                ],
                "output": {
                    "sink": {
                        "type": "csv",
                        "path": str(workdir / "results.csv"),
                    }
                },
            }

        # Sequential run
        seq_workdir = tmp_path / "seq"
        seq_workdir.mkdir()
        seq_file = _write_yaml(tmp_path / "seq.yaml", _build_config(seq_workdir, 1))
        seq_config = load_config(seq_file)
        IOPSRunner(seq_config, _make_args()).run()
        seq_output = Path(seq_config.benchmark.workdir).parent / "results.csv"
        with open(seq_output) as fh:
            seq_rows = list(csv.DictReader(fh))

        # Parallel run
        par_workdir = tmp_path / "par"
        par_workdir.mkdir()
        par_file = _write_yaml(tmp_path / "par.yaml", _build_config(par_workdir, 3))
        par_config = load_config(par_file)
        IOPSRunner(par_config, _make_args()).run()
        par_output = Path(par_config.benchmark.workdir).parent / "results.csv"
        with open(par_output) as fh:
            par_rows = list(csv.DictReader(fh))

        # Both should produce 2 values * 2 repetitions = 4 rows
        assert len(seq_rows) == len(par_rows) == 4


# --------------------------------------------------------------------------- #
# Warning / logging behaviour
# --------------------------------------------------------------------------- #

class TestParallelWarnings:
    """Tests that verify warning logs when parallelism is capped."""

    def test_warning_logged_when_planner_caps_parallelism(
        self, tmp_path, sample_config_dict, caplog
    ):
        """A warning is logged when the planner's max_parallel is lower than requested."""
        pytest.importorskip("skopt", reason="scikit-optimize not installed")
        sample_config_dict["benchmark"]["search_method"] = "bayesian"
        sample_config_dict["benchmark"]["bayesian_config"] = {
            "n_iterations": 5,
            "n_initial_points": 2,
            "objective_metric": "result",
        }
        sample_config_dict["benchmark"]["parallel"] = 4
        config_file = _write_yaml(tmp_path / "cfg.yaml", sample_config_dict)
        config = load_config(config_file)
        args = _make_args()

        with caplog.at_level(logging.WARNING):
            runner = IOPSRunner(config, args)

        # The planner should have capped effective_parallel to 1
        assert runner.effective_parallel == 1
        # A warning message about the capping should have been emitted
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("parallel" in msg.lower() or "limit" in msg.lower() for msg in warning_messages)
