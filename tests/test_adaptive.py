"""Tests for the adaptive variable feature.

Covers config parsing, validation, planner behavior (all step modes,
directions, repetitions), and an end-to-end integration test with
LocalExecutor.
"""

import csv
import json
import logging
from pathlib import Path

import pytest
import yaml

from iops.config.loader import load_generic_config
from iops.config.models import ConfigValidationError
from iops.execution.planner import AdaptivePlanner
from iops.execution.runner import IOPSRunner


# ------------------------------------------------------------------ #
# Shared helpers
# ------------------------------------------------------------------ #


def _get_logger():
    return logging.getLogger("test_adaptive")


def _build_config(tmp_path, config_dict):
    """Write a config dict to YAML, load it, and return the parsed config."""
    workdir = tmp_path / "workdir"
    workdir.mkdir(parents=True, exist_ok=True)
    config_dict["benchmark"]["workdir"] = str(workdir)

    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(config_dict))
    return load_generic_config(Path(config_file), _get_logger())


def _run_planner_pass(cfg, simulate_metadata_fn):
    """
    Drive a full AdaptivePlanner cycle and return (probe_results, recorded_tests).

    simulate_metadata_fn(test) -> dict: populates test.metadata with simulated
    execution results. Must set at least __returncode, __executor_status, and
    optionally metrics.
    """
    planner = AdaptivePlanner(cfg)
    recorded_tests = []

    while True:
        test = planner.next_test()
        if test is None:
            if all(p.finished for p in planner._probes):
                break
            break

        metadata = simulate_metadata_fn(test)
        test.metadata.update(metadata)
        planner.record_completed_test(test)

        recorded_tests.append({
            "base_vars": dict(test.base_vars),
            "metadata": dict(test.metadata),
        })

    return planner.get_probe_results(), recorded_tests


def _make_base_config(workdir, **overrides):
    """Return a minimal config dict with an adaptive var placeholder.

    Caller should set vars.x.adaptive (or equivalent) before loading.
    """
    cfg = {
        "benchmark": {
            "name": "Adaptive Test",
            "workdir": str(workdir),
            "executor": "local",
            "search_method": "adaptive",
            "repetitions": 1,
        },
        "vars": {},
        "command": {
            "template": "echo 'x={{ x }}'",
        },
        "scripts": [
            {
                "name": "bench",
                "script_template": "#!/bin/bash\necho test",
                "parser": {
                    "file": "{{ execution_dir }}/output.txt",
                    "metrics": [{"name": "throughput", "type": "float"}],
                    "parser_script": (
                        "def parse(file_path):\n"
                        "    return {'throughput': 100.0}"
                    ),
                },
            }
        ],
        "output": {
            "sink": {
                "type": "csv",
                "path": "{{ workdir }}/results.csv",
            }
        },
    }
    for k, v in overrides.items():
        if k in cfg:
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def _succeed_metadata(metrics=None):
    return {
        "__returncode": 0,
        "__executor_status": "SUCCEEDED",
        "metrics": metrics or {},
    }


def _fail_metadata():
    return {
        "__returncode": 1,
        "__executor_status": "FAILED",
        "metrics": {},
    }


# ------------------------------------------------------------------ #
# Class 1: Config parsing
# ------------------------------------------------------------------ #


class TestAdaptiveConfigParsing:
    """Tests that valid adaptive configs parse correctly into AdaptiveConfig."""

    def test_valid_adaptive_config_with_factor(self, tmp_path):
        cfg_dict = _make_base_config(tmp_path)
        cfg_dict["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "factor": 2,
                "stop_when": "exit_code != 0",
            },
        }
        cfg = _build_config(tmp_path, cfg_dict)

        assert cfg.vars["x"].adaptive is not None
        assert cfg.vars["x"].adaptive.factor == 2
        assert cfg.vars["x"].adaptive.initial == 100
        assert cfg.vars["x"].adaptive.stop_when == "exit_code != 0"
        assert cfg.vars["x"].adaptive.direction == "ascending"

    def test_valid_adaptive_config_with_increment(self, tmp_path):
        cfg_dict = _make_base_config(tmp_path)
        cfg_dict["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "increment": 50,
                "stop_when": "exit_code != 0",
            },
        }
        cfg = _build_config(tmp_path, cfg_dict)

        assert cfg.vars["x"].adaptive.increment == 50
        assert cfg.vars["x"].adaptive.factor is None
        assert cfg.vars["x"].adaptive.step_expr is None

    def test_valid_adaptive_config_with_step_expr(self, tmp_path):
        cfg_dict = _make_base_config(tmp_path)
        cfg_dict["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "step_expr": "{{ previous * 3 }}",
                "stop_when": "exit_code != 0",
            },
        }
        cfg = _build_config(tmp_path, cfg_dict)

        assert cfg.vars["x"].adaptive.step_expr == "{{ previous * 3 }}"
        assert cfg.vars["x"].adaptive.factor is None
        assert cfg.vars["x"].adaptive.increment is None

    def test_adaptive_config_optional_fields_defaults(self, tmp_path):
        cfg_dict = _make_base_config(tmp_path)
        cfg_dict["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 10,
                "factor": 2,
                "stop_when": "exit_code != 0",
            },
        }
        cfg = _build_config(tmp_path, cfg_dict)

        assert cfg.vars["x"].adaptive.max_iterations is None
        assert cfg.vars["x"].adaptive.direction == "ascending"


# ------------------------------------------------------------------ #
# Class 2: Config validation
# ------------------------------------------------------------------ #


class TestAdaptiveConfigValidation:
    """Tests that invalid configs raise ConfigValidationError."""

    def _load_invalid(self, tmp_path, config_dict, match):
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True, exist_ok=True)
        config_dict["benchmark"]["workdir"] = str(workdir)
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_dict))
        with pytest.raises(ConfigValidationError, match=match):
            load_generic_config(Path(config_file), _get_logger())

    def test_sweep_and_adaptive_mutual_exclusivity(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "int",
            "sweep": {"mode": "list", "values": [1, 2]},
            "adaptive": {
                "initial": 100,
                "factor": 2,
                "stop_when": "exit_code != 0",
            },
        }
        self._load_invalid(tmp_path, cfg, "only one of")

    def test_expr_and_adaptive_mutual_exclusivity(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "int",
            "expr": "42",
            "adaptive": {
                "initial": 100,
                "factor": 2,
                "stop_when": "exit_code != 0",
            },
        }
        self._load_invalid(tmp_path, cfg, "only one of")

    def test_missing_initial_raises_error(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "factor": 2,
                "stop_when": "exit_code != 0",
            },
        }
        self._load_invalid(tmp_path, cfg, "'initial' is required")

    def test_missing_stop_when_raises_error(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "factor": 2,
            },
        }
        self._load_invalid(tmp_path, cfg, "'stop_when' is required")

    def test_factor_and_increment_together_raises_error(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "factor": 2,
                "increment": 50,
                "stop_when": "exit_code != 0",
            },
        }
        self._load_invalid(tmp_path, cfg, "exactly one of")

    def test_no_step_method_raises_error(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "stop_when": "exit_code != 0",
            },
        }
        self._load_invalid(tmp_path, cfg, "exactly one of")

    def test_factor_zero_raises_error(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "factor": 0,
                "stop_when": "exit_code != 0",
            },
        }
        self._load_invalid(tmp_path, cfg, "must not be 0")

    def test_ascending_factor_must_be_greater_than_one(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "float",
            "adaptive": {
                "initial": 100,
                "factor": 0.5,
                "stop_when": "exit_code != 0",
                "direction": "ascending",
            },
        }
        self._load_invalid(tmp_path, cfg, r"'factor' must be > 1 for ascending")

    def test_descending_factor_must_be_less_than_one(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "float",
            "adaptive": {
                "initial": 1000,
                "factor": 2,
                "stop_when": "exit_code != 0",
                "direction": "descending",
            },
        }
        self._load_invalid(tmp_path, cfg, r"'factor' must be < 1 for descending")

    def test_ascending_increment_must_be_positive(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "increment": -10,
                "stop_when": "exit_code != 0",
                "direction": "ascending",
            },
        }
        self._load_invalid(tmp_path, cfg, r"'increment' must be > 0 for ascending")

    def test_descending_increment_must_be_negative(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 1000,
                "increment": 10,
                "stop_when": "exit_code != 0",
                "direction": "descending",
            },
        }
        self._load_invalid(tmp_path, cfg, r"'increment' must be < 0 for descending")

    def test_invalid_direction_raises_error(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "factor": 2,
                "stop_when": "exit_code != 0",
                "direction": "sideways",
            },
        }
        self._load_invalid(tmp_path, cfg, "'direction' must be 'ascending' or 'descending'")

    def test_max_iterations_must_be_positive(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "factor": 2,
                "stop_when": "exit_code != 0",
                "max_iterations": 0,
            },
        }
        self._load_invalid(tmp_path, cfg, "'max_iterations' must be a positive integer")

    def test_non_numeric_type_with_factor_raises_error(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "str",
            "adaptive": {
                "initial": "abc",
                "factor": 2,
                "stop_when": "exit_code != 0",
            },
        }
        self._load_invalid(tmp_path, cfg, "must be 'int' or 'float'")

    def test_adaptive_in_exhaustive_vars_raises_error(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "factor": 2,
                "stop_when": "exit_code != 0",
            },
        }
        cfg["benchmark"]["exhaustive_vars"] = ["x"]
        self._load_invalid(tmp_path, cfg, "cannot be listed in 'exhaustive_vars'")

    def test_adaptive_in_cache_exclude_vars_raises_error(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "factor": 2,
                "stop_when": "exit_code != 0",
            },
        }
        cfg["benchmark"]["cache_exclude_vars"] = ["x"]
        self._load_invalid(tmp_path, cfg, "cannot be listed in 'cache_exclude_vars'")

    def test_conditional_when_references_adaptive_var_raises_error(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "factor": 2,
                "stop_when": "exit_code != 0",
            },
        }
        cfg["vars"]["compression_level"] = {
            "type": "int",
            "sweep": {"mode": "list", "values": [1, 5, 9]},
            "when": "x > 200",
            "default": 0,
        }
        self._load_invalid(tmp_path, cfg, "references adaptive variable")

    def test_multiple_adaptive_vars_raises_error(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "factor": 2,
                "stop_when": "exit_code != 0",
            },
        }
        cfg["vars"]["y"] = {
            "type": "int",
            "adaptive": {
                "initial": 200,
                "factor": 3,
                "stop_when": "exit_code != 0",
            },
        }
        self._load_invalid(tmp_path, cfg, "Only one adaptive")

    def test_search_method_mismatch_raises_error(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["benchmark"]["search_method"] = "exhaustive"
        cfg["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "factor": 2,
                "stop_when": "exit_code != 0",
            },
        }
        self._load_invalid(tmp_path, cfg, "search_method to 'adaptive'")

    def test_adaptive_search_method_without_adaptive_var_raises_error(self, tmp_path):
        cfg = _make_base_config(tmp_path)
        cfg["benchmark"]["search_method"] = "adaptive"
        cfg["vars"]["x"] = {
            "type": "int",
            "sweep": {"mode": "list", "values": [1, 2]},
        }
        self._load_invalid(tmp_path, cfg, "no variable has an 'adaptive' configuration")


# ------------------------------------------------------------------ #
# Class 3: Planner basics
# ------------------------------------------------------------------ #


class TestAdaptivePlannerBasic:
    """Tests the planner probe sequence for different step modes."""

    def test_factor_mode_probe_sequence(self, tmp_path):
        """factor=2 produces sequence 1000, 2000, 4000; stop at 4000."""
        cfg_dict = _make_base_config(tmp_path)
        cfg_dict["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 1000,
                "factor": 2,
                "stop_when": "exit_code != 0",
            },
        }
        cfg = _build_config(tmp_path, cfg_dict)

        probed_values = []

        def metadata_fn(test):
            val = test.base_vars["x"]
            probed_values.append(val)
            if val >= 4000:
                return _fail_metadata()
            return _succeed_metadata()

        results, _ = _run_planner_pass(cfg, metadata_fn)

        assert probed_values == [1000, 2000, 4000]

        label = "(no swept vars)"
        assert results[label].found_value == 2000
        assert results[label].failed_value == 4000
        assert results[label].stop_reason == "condition_met"

    def test_increment_mode_probe_sequence(self, tmp_path):
        """increment=50 produces sequence 100, 150, 200, 250; stop at 250."""
        cfg_dict = _make_base_config(tmp_path)
        cfg_dict["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "increment": 50,
                "stop_when": "exit_code != 0",
            },
        }
        cfg = _build_config(tmp_path, cfg_dict)

        probed_values = []

        def metadata_fn(test):
            val = test.base_vars["x"]
            probed_values.append(val)
            if val >= 250:
                return _fail_metadata()
            return _succeed_metadata()

        results, _ = _run_planner_pass(cfg, metadata_fn)

        assert probed_values == [100, 150, 200, 250]

        label = "(no swept vars)"
        assert results[label].found_value == 200
        assert results[label].failed_value == 250

    def test_step_expr_mode_probe_sequence(self, tmp_path):
        """step_expr '{{ previous * 2 + 100 }}' from 100 produces 100, 300, 700."""
        cfg_dict = _make_base_config(tmp_path)
        cfg_dict["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "step_expr": "{{ previous * 2 + 100 }}",
                "stop_when": "exit_code != 0",
            },
        }
        cfg = _build_config(tmp_path, cfg_dict)

        probed_values = []

        def metadata_fn(test):
            val = test.base_vars["x"]
            probed_values.append(val)
            if val >= 700:
                return _fail_metadata()
            return _succeed_metadata()

        results, _ = _run_planner_pass(cfg, metadata_fn)

        assert probed_values == [100, 300, 700]

        label = "(no swept vars)"
        assert results[label].found_value == 300
        assert results[label].failed_value == 700

    def test_max_iterations_stops_probe(self, tmp_path):
        """All succeed, max_iterations=3 stops after 3 values."""
        cfg_dict = _make_base_config(tmp_path)
        cfg_dict["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 10,
                "factor": 2,
                "stop_when": "exit_code != 0",
                "max_iterations": 3,
            },
        }
        cfg = _build_config(tmp_path, cfg_dict)

        probed_values = []

        def metadata_fn(test):
            probed_values.append(test.base_vars["x"])
            return _succeed_metadata()

        results, _ = _run_planner_pass(cfg, metadata_fn)

        # 3 iterations: 10, 20, 40
        assert probed_values == [10, 20, 40]

        label = "(no swept vars)"
        assert results[label].stop_reason == "max_iterations"
        assert results[label].failed_value is None
        assert results[label].found_value == 40

    def test_metric_based_stop(self, tmp_path):
        """stop_when: 'metrics.get(\"throughput\", 0) < 100', throughput degrades."""
        cfg_dict = _make_base_config(tmp_path)
        cfg_dict["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "factor": 2,
                "stop_when": "metrics.get('throughput', 0) < 100",
            },
        }
        cfg = _build_config(tmp_path, cfg_dict)

        # throughput: 100->500, 200->250, 400->80 (triggers)
        def metadata_fn(test):
            size = test.base_vars["x"]
            throughput = 50000.0 / size
            return _succeed_metadata(metrics={"throughput": throughput})

        results, _ = _run_planner_pass(cfg, metadata_fn)

        label = "(no swept vars)"
        # 100 (500, ok), 200 (250, ok), 400 (125, ok), 800 (62.5, stop)
        assert results[label].found_value == 400
        assert results[label].failed_value == 800
        assert results[label].stop_reason == "condition_met"


# ------------------------------------------------------------------ #
# Class 4: Planner advanced
# ------------------------------------------------------------------ #


class TestAdaptivePlannerAdvanced:
    """Advanced planner tests covering direction, swept vars, and repetitions."""

    def test_descending_direction(self, tmp_path):
        """Descending: initial=1000, factor=0.5 produces 1000, 500, 250."""
        cfg_dict = _make_base_config(tmp_path)
        cfg_dict["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 1000,
                "factor": 0.5,
                "stop_when": "exit_code != 0",
                "direction": "descending",
            },
        }
        cfg = _build_config(tmp_path, cfg_dict)

        probed_values = []

        def metadata_fn(test):
            val = test.base_vars["x"]
            probed_values.append(val)
            # Fail when value drops below 300
            if val < 300:
                return _fail_metadata()
            return _succeed_metadata()

        results, _ = _run_planner_pass(cfg, metadata_fn)

        assert probed_values == [1000, 500, 250]

        label = "(no swept vars)"
        assert results[label].found_value == 500
        assert results[label].failed_value == 250
        assert results[label].stop_reason == "condition_met"

    def test_with_swept_vars_independent_probes(self, tmp_path):
        """Adaptive + swept var (nodes=[1,2,4]) creates 3 independent probes."""
        cfg_dict = _make_base_config(tmp_path)
        cfg_dict["vars"]["nodes"] = {
            "type": "int",
            "sweep": {"mode": "list", "values": [1, 2, 4]},
        }
        cfg_dict["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "factor": 2,
                "stop_when": "exit_code != 0",
                "max_iterations": 2,
            },
        }
        cfg_dict["command"]["template"] = "echo 'nodes={{ nodes }} x={{ x }}'"
        cfg = _build_config(tmp_path, cfg_dict)

        def metadata_fn(test):
            return _succeed_metadata()

        results, _ = _run_planner_pass(cfg, metadata_fn)

        # 3 independent probes, one per nodes value
        assert len(results) == 3
        # Each probe runs max_iterations=2 values (100, 200) and stops
        for label, result in results.items():
            assert result.stop_reason == "max_iterations"
            assert result.found_value == 200

    def test_multiple_repetitions(self, tmp_path):
        """repetitions=3, stop triggers when any rep has exit_code != 0."""
        cfg_dict = _make_base_config(tmp_path)
        cfg_dict["benchmark"]["repetitions"] = 3
        cfg_dict["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "factor": 2,
                "stop_when": "exit_code != 0",
            },
        }
        cfg = _build_config(tmp_path, cfg_dict)

        probed = []

        def metadata_fn(test):
            val = test.base_vars["x"]
            probed.append(val)
            # At x=200: 2 of 3 reps fail (enough to trigger stop)
            if val >= 200:
                return _fail_metadata()
            return _succeed_metadata()

        results, _ = _run_planner_pass(cfg, metadata_fn)

        # x=100: 3 reps (all succeed), x=200: 3 reps (all fail, stop triggers)
        assert probed.count(100) == 3
        assert probed.count(200) == 3

        label = "(no swept vars)"
        assert results[label].found_value == 100
        assert results[label].failed_value == 200

    def test_first_value_triggers_stop(self, tmp_path):
        """Stop triggers on the very first adaptive value."""
        cfg_dict = _make_base_config(tmp_path)
        cfg_dict["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "factor": 2,
                "stop_when": "exit_code != 0",
            },
        }
        cfg = _build_config(tmp_path, cfg_dict)

        def metadata_fn(test):
            return _fail_metadata()

        results, _ = _run_planner_pass(cfg, metadata_fn)

        label = "(no swept vars)"
        assert results[label].found_value is None
        assert results[label].failed_value == 100

    def test_probe_results_structure(self, tmp_path):
        """Verify get_probe_results() returns correct ProbeResult fields."""
        cfg_dict = _make_base_config(tmp_path)
        cfg_dict["vars"]["nodes"] = {
            "type": "int",
            "sweep": {"mode": "list", "values": [1, 2]},
        }
        cfg_dict["vars"]["x"] = {
            "type": "int",
            "adaptive": {
                "initial": 100,
                "factor": 2,
                "stop_when": "exit_code != 0",
                "max_iterations": 2,
            },
        }
        cfg_dict["command"]["template"] = "echo '{{ nodes }} {{ x }}'"
        cfg = _build_config(tmp_path, cfg_dict)

        def metadata_fn(test):
            return _succeed_metadata()

        results, _ = _run_planner_pass(cfg, metadata_fn)

        # Two probes keyed by combo label
        assert len(results) == 2
        for label, result in results.items():
            assert hasattr(result, "found_value")
            assert hasattr(result, "failed_value")
            assert hasattr(result, "iterations")
            assert hasattr(result, "stop_reason")
            assert result.stop_reason == "max_iterations"
            assert result.iterations == 3  # iteration counter + 1 for finished


# ------------------------------------------------------------------ #
# Class 5: Integration
# ------------------------------------------------------------------ #


class MockArgs:
    """Mock CLI args for tests."""
    def __init__(self, use_cache=False, dry_run=False):
        self.use_cache = use_cache
        self.dry_run = dry_run
        self.max_core_hours = None
        self.estimated_time = None
        self.log_level = "WARNING"


class TestAdaptiveIntegration:
    """End-to-end integration test with LocalExecutor."""

    def test_end_to_end_with_local_executor(self, tmp_path):
        """Full integration: bash script returns exit 1 when x >= 400."""
        workdir = tmp_path / "workdir"
        workdir.mkdir(parents=True, exist_ok=True)

        config_dict = {
            "benchmark": {
                "name": "Adaptive Integration",
                "workdir": str(workdir),
                "executor": "local",
                "search_method": "adaptive",
                "repetitions": 1,
                "collect_system_info": False,
            },
            "vars": {
                "x": {
                    "type": "int",
                    "adaptive": {
                        "initial": 100,
                        "factor": 2,
                        "stop_when": "exit_code != 0",
                        "max_iterations": 10,
                    },
                },
            },
            "command": {
                "template": "echo 'x={{ x }}'",
            },
            "scripts": [
                {
                    "name": "bench",
                    "submit": "bash",
                    "script_template": (
                        "#!/bin/bash\n"
                        "echo '{\"throughput\": {{ x }} }' > {{ execution_dir }}/result.json\n"
                        "if [ {{ x }} -ge 400 ]; then exit 1; fi\n"
                        "exit 0\n"
                    ),
                    "parser": {
                        "file": "{{ execution_dir }}/result.json",
                        "metrics": [{"name": "throughput", "type": "float"}],
                        "parser_script": (
                            "import json\n"
                            "def parse(file_path):\n"
                            "    with open(file_path) as f:\n"
                            "        return json.load(f)\n"
                        ),
                    },
                }
            ],
            "output": {
                "sink": {
                    "type": "csv",
                    "path": "{{ workdir }}/results.csv",
                }
            },
        }

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_dict))
        cfg = load_generic_config(Path(config_file), _get_logger())

        runner = IOPSRunner(cfg, MockArgs())
        runner.run()

        # Find the run directory
        run_dirs = list(workdir.glob("run_*"))
        assert len(run_dirs) == 1
        run_dir = run_dirs[0]

        # Verify CSV output exists with rows for executed tests
        results_file = run_dir / "results.csv"
        assert results_file.exists()
        with open(results_file) as f:
            rows = list(csv.DictReader(f))
        # Sequence: x=100 (ok), 200 (ok), 400 (fail) => 3 rows
        assert len(rows) == 3

        # Verify run metadata file exists with adaptive_results key
        metadata_file = run_dir / "__iops_run_metadata.json"
        assert metadata_file.exists()
        with open(metadata_file) as f:
            run_meta = json.load(f)

        assert "adaptive_results" in run_meta
        adaptive = run_meta["adaptive_results"]
        assert "x" in adaptive

        # Check found/failed values
        probe_key = list(adaptive["x"].keys())[0]
        probe_data = adaptive["x"][probe_key]
        assert probe_data["found_value"] == 200
        assert probe_data["failed_value"] == 400
        assert probe_data["stop_reason"] == "condition_met"
