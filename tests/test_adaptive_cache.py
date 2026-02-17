"""Tests verifying adaptive planner produces identical results from cached metadata.

When caching is enabled, the runner restores metadata from the cache into
test.metadata before calling planner.record_completed_test(). These tests
prove that the AdaptivePlanner produces identical probe results regardless
of whether metadata comes from a live execution or from a cache replay.
"""

import logging
from pathlib import Path

import pytest
import yaml

from iops.config.loader import load_generic_config
from iops.execution.planner import AdaptivePlanner


def _get_logger():
    return logging.getLogger("test_adaptive_cache")


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
    (or cached) execution results. Must set at least __returncode,
    __executor_status, and optionally metrics.
    """
    planner = AdaptivePlanner(cfg)
    recorded_tests = []

    while True:
        test = planner.next_test()
        if test is None:
            # Check if all probes are finished
            all_done = all(p.finished for p in planner._probes)
            if all_done:
                break
            # Some probes still waiting (shouldn't happen with 1 rep), bail
            break

        # Populate metadata as the runner/cache would
        metadata = simulate_metadata_fn(test)
        test.metadata.update(metadata)
        planner.record_completed_test(test)

        # Save a snapshot of the test for later cache replay
        recorded_tests.append({
            "base_vars": dict(test.base_vars),
            "metadata": dict(test.metadata),
        })

    return planner.get_probe_results(), recorded_tests


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #


@pytest.fixture
def exit_code_config_dict():
    """Config with adaptive var using exit_code-based stop_when."""
    return {
        "benchmark": {
            "name": "Adaptive Cache Test",
            "workdir": "./workdir",
            "executor": "local",
            "search_method": "adaptive",
            "repetitions": 1,
        },
        "vars": {
            "nodes": {
                "type": "int",
                "sweep": {
                    "mode": "list",
                    "values": [1, 2],
                },
            },
            "problem_size": {
                "type": "int",
                "adaptive": {
                    "initial": 100,
                    "factor": 2,
                    "stop_when": "exit_code != 0",
                    "max_iterations": 5,
                },
            },
        },
        "command": {
            "template": "echo 'nodes={{ nodes }} size={{ problem_size }}'",
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


@pytest.fixture
def metric_config_dict():
    """Config with adaptive var using metric-based stop_when."""
    return {
        "benchmark": {
            "name": "Adaptive Metric Cache Test",
            "workdir": "./workdir",
            "executor": "local",
            "search_method": "adaptive",
            "repetitions": 1,
        },
        "vars": {
            "problem_size": {
                "type": "int",
                "adaptive": {
                    "initial": 100,
                    "factor": 2,
                    "stop_when": "metrics.get('throughput', 0) < 50",
                    "max_iterations": 5,
                },
            },
        },
        "command": {
            "template": "echo 'size={{ problem_size }}'",
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


# ------------------------------------------------------------------ #
# Tests
# ------------------------------------------------------------------ #


class TestAdaptiveCacheExitCode:
    """Verify cache replay produces identical results for exit_code-based stop."""

    def test_cache_produces_same_probe_results(self, exit_code_config_dict, tmp_path):
        """
        Simulate two passes through the planner with exit_code-based stopping.

        Pass 1 (fresh): metadata comes from simulated execution.
        Pass 2 (cached): metadata is replayed from pass 1 snapshots.

        Both passes must produce identical probe results.
        """
        cfg = _build_config(tmp_path, exit_code_config_dict)

        # Simulate: problem_size 100 and 200 succeed, 400 fails
        def fresh_metadata(test):
            size = test.base_vars["problem_size"]
            if size >= 400:
                return {
                    "__returncode": 1,
                    "__executor_status": "FAILED",
                    "metrics": {},
                }
            return {
                "__returncode": 0,
                "__executor_status": "SUCCEEDED",
                "metrics": {"throughput": 1000.0 / size},
            }

        # Pass 1: fresh run
        results_fresh, cache_entries = _run_planner_pass(cfg, fresh_metadata)

        # Build a lookup from (sorted base_vars tuple) -> metadata
        cache_lookup = {}
        for entry in cache_entries:
            key = tuple(sorted(entry["base_vars"].items()))
            cache_lookup[key] = entry["metadata"]

        # Pass 2: replay from "cache"
        def cached_metadata(test):
            key = tuple(sorted(test.base_vars.items()))
            assert key in cache_lookup, (
                f"Cache miss for {dict(key)}, available: {list(cache_lookup.keys())}"
            )
            return dict(cache_lookup[key])

        results_cached, _ = _run_planner_pass(cfg, cached_metadata)

        # Verify identical probe results
        assert set(results_fresh.keys()) == set(results_cached.keys())

        for label in results_fresh:
            fresh = results_fresh[label]
            cached = results_cached[label]
            assert fresh.found_value == cached.found_value, (
                f"Probe '{label}': found_value mismatch "
                f"(fresh={fresh.found_value}, cached={cached.found_value})"
            )
            assert fresh.failed_value == cached.failed_value, (
                f"Probe '{label}': failed_value mismatch "
                f"(fresh={fresh.failed_value}, cached={cached.failed_value})"
            )
            assert fresh.iterations == cached.iterations, (
                f"Probe '{label}': iterations mismatch "
                f"(fresh={fresh.iterations}, cached={cached.iterations})"
            )
            assert fresh.stop_reason == cached.stop_reason, (
                f"Probe '{label}': stop_reason mismatch "
                f"(fresh={fresh.stop_reason}, cached={cached.stop_reason})"
            )

    def test_probe_results_are_correct(self, exit_code_config_dict, tmp_path):
        """Verify the actual probe result values are what we expect."""
        cfg = _build_config(tmp_path, exit_code_config_dict)

        def fresh_metadata(test):
            size = test.base_vars["problem_size"]
            if size >= 400:
                return {
                    "__returncode": 1,
                    "__executor_status": "FAILED",
                    "metrics": {},
                }
            return {
                "__returncode": 0,
                "__executor_status": "SUCCEEDED",
                "metrics": {"throughput": 1000.0 / size},
            }

        results, _ = _run_planner_pass(cfg, fresh_metadata)

        # Two probes: nodes=1 and nodes=2
        assert len(results) == 2

        for label, probe_result in results.items():
            # 100 succeeds (found), 200 succeeds (found), 400 fails (failed)
            assert probe_result.found_value == 200
            assert probe_result.failed_value == 400
            assert probe_result.stop_reason == "condition_met"
            # iterations = 3 (values 100, 200, 400 were tested)
            assert probe_result.iterations == 3


class TestAdaptiveCacheMetricBased:
    """Verify cache replay produces identical results for metric-based stop."""

    def test_metric_based_cache_replay(self, metric_config_dict, tmp_path):
        """
        Metric-based stopping: all tests SUCCEED (exit_code=0) but
        stop_when triggers when throughput drops below threshold.

        Since all tests succeed, they would all be cached. The cache replay
        must produce the same results.
        """
        cfg = _build_config(tmp_path, metric_config_dict)

        # Throughput degrades as problem_size grows:
        # 100 -> throughput 200, 200 -> 100, 400 -> 30 (triggers stop)
        def fresh_metadata(test):
            size = test.base_vars["problem_size"]
            throughput = 20000.0 / size
            return {
                "__returncode": 0,
                "__executor_status": "SUCCEEDED",
                "metrics": {"throughput": throughput},
            }

        # Pass 1
        results_fresh, cache_entries = _run_planner_pass(cfg, fresh_metadata)

        # Build cache lookup
        cache_lookup = {}
        for entry in cache_entries:
            key = tuple(sorted(entry["base_vars"].items()))
            cache_lookup[key] = entry["metadata"]

        # Pass 2: all from cache (all were SUCCEEDED)
        def cached_metadata(test):
            key = tuple(sorted(test.base_vars.items()))
            assert key in cache_lookup
            return dict(cache_lookup[key])

        results_cached, _ = _run_planner_pass(cfg, cached_metadata)

        # Verify identical
        assert set(results_fresh.keys()) == set(results_cached.keys())
        for label in results_fresh:
            fresh = results_fresh[label]
            cached = results_cached[label]
            assert fresh.found_value == cached.found_value
            assert fresh.failed_value == cached.failed_value
            assert fresh.iterations == cached.iterations
            assert fresh.stop_reason == cached.stop_reason

    def test_metric_probe_results_correct(self, metric_config_dict, tmp_path):
        """Verify metric-based probe results have expected values."""
        cfg = _build_config(tmp_path, metric_config_dict)

        # 100 -> 200 throughput, 200 -> 100, 400 -> 50, 800 -> 25 (triggers)
        def fresh_metadata(test):
            size = test.base_vars["problem_size"]
            throughput = 20000.0 / size
            return {
                "__returncode": 0,
                "__executor_status": "SUCCEEDED",
                "metrics": {"throughput": throughput},
            }

        results, _ = _run_planner_pass(cfg, fresh_metadata)

        # Single probe (no swept vars -> "(no swept vars)" label)
        assert len(results) == 1
        label = "(no swept vars)"
        assert label in results

        probe = results[label]
        # 100 (200 tput, ok), 200 (100 tput, ok), 400 (50 tput, ok), 800 (25 tput, stop)
        assert probe.found_value == 400
        assert probe.failed_value == 800
        assert probe.stop_reason == "condition_met"
        assert probe.iterations == 4


class TestAdaptiveCacheMaxIterations:
    """Verify cache replay when max_iterations is reached (no stop triggered)."""

    def test_max_iterations_cache_replay(self, tmp_path):
        """All probes succeed, max_iterations cuts off the search."""
        config_dict = {
            "benchmark": {
                "name": "Max Iter Cache Test",
                "workdir": "./workdir",
                "executor": "local",
                "search_method": "adaptive",
                "repetitions": 1,
            },
            "vars": {
                "problem_size": {
                    "type": "int",
                    "adaptive": {
                        "initial": 10,
                        "factor": 2,
                        "stop_when": "exit_code != 0",
                        "max_iterations": 3,
                    },
                },
            },
            "command": {
                "template": "echo '{{ problem_size }}'",
            },
            "scripts": [
                {
                    "name": "bench",
                    "script_template": "#!/bin/bash\necho test",
                    "parser": {
                        "file": "{{ execution_dir }}/output.txt",
                        "metrics": [{"name": "result", "type": "float"}],
                        "parser_script": (
                            "def parse(file_path):\n"
                            "    return {'result': 1.0}"
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

        cfg = _build_config(tmp_path, config_dict)

        # All succeed (never trigger stop_when)
        def fresh_metadata(test):
            return {
                "__returncode": 0,
                "__executor_status": "SUCCEEDED",
                "metrics": {"result": 1.0},
            }

        results_fresh, cache_entries = _run_planner_pass(cfg, fresh_metadata)

        # Build cache
        cache_lookup = {}
        for entry in cache_entries:
            key = tuple(sorted(entry["base_vars"].items()))
            cache_lookup[key] = entry["metadata"]

        def cached_metadata(test):
            key = tuple(sorted(test.base_vars.items()))
            assert key in cache_lookup
            return dict(cache_lookup[key])

        results_cached, _ = _run_planner_pass(cfg, cached_metadata)

        # Verify identical
        label = "(no swept vars)"
        fresh = results_fresh[label]
        cached = results_cached[label]
        assert fresh.found_value == cached.found_value
        assert fresh.failed_value == cached.failed_value
        assert fresh.iterations == cached.iterations
        assert fresh.stop_reason == cached.stop_reason

        # Verify actual values: 3 values probed (10, 20, 40), all succeed
        # probe.iteration ends at 3, get_probe_results adds +1 for finished
        assert fresh.found_value == 40
        assert fresh.failed_value is None
        assert fresh.stop_reason == "max_iterations"
        assert fresh.iterations == 4
