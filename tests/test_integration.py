"""Integration tests for IOPS end-to-end workflows."""

import pytest
from pathlib import Path
import yaml
import csv

from conftest import load_config
from iops.execution.runner import IOPSRunner
from unittest.mock import Mock


@pytest.fixture
def simple_integration_config(tmp_path):
    """Create a simple end-to-end test configuration."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    # Create a simple script that outputs predictable results
    config = {
        "benchmark": {
            "name": "Integration Test",
            "workdir": str(workdir),
            "executor": "local",
            "repetitions": 2,
            "random_seed": 42,
        },
        "vars": {
            "size": {
                "type": "int",
                "sweep": {
                    "mode": "list",
                    "values": [10, 20],
                }
            }
        },
        "command": {
            "template": "echo 'size={{ size }}'",
            "metadata": {"operation": "test"}
        },
        "scripts": [
            {
                "name": "simple_test",
                "submit": "bash",
                "script_template": (
                    "#!/bin/bash\n"
                    "SIZE={{ size }}\n"
                    "RESULT=$((SIZE * 2))\n"
                    "echo \"result: $RESULT\" > {{ execution_dir }}/output.txt\n"
                ),
                "parser": {
                    "file": "{{ execution_dir }}/output.txt",
                    "metrics": [
                        {"name": "result", "type": "int"}
                    ],
                    "parser_script": (
                        "def parse(file_path):\n"
                        "    with open(file_path) as f:\n"
                        "        line = f.read().strip()\n"
                        "    value = int(line.split(':')[1].strip())\n"
                        "    return {'result': value}\n"
                    )
                }
            }
        ],
        "output": {
            "sink": {
                "type": "csv",
                "path": str(workdir / "results.csv"),
                "mode": "append"
            }
        }
    }

    config_file = tmp_path / "integration_config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config, f)

    return config_file


def test_end_to_end_execution(simple_integration_config):
    """Test complete end-to-end execution."""
    config = load_config(simple_integration_config)

    # Note: config.benchmark.workdir is modified by loader to point to run_XXX
    # The output file is in the parent directory (the original workdir)
    base_workdir = Path(config.benchmark.workdir).parent

    # Create mock args
    args = Mock()
    args.use_cache = False
    args.log_level = "INFO"
    args.max_core_hours = None

    runner = IOPSRunner(config, args)
    runner.run()

    # Check that output file was created (in the base workdir, not run_XXX)
    output_file = base_workdir / "results.csv"
    assert output_file.exists()

    # Read and verify results
    with open(output_file, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Should have 2 sizes * 2 repetitions = 4 rows
    assert len(rows) == 4

    # Verify metrics
    for row in rows:
        size = int(row["vars.size"])
        result = int(row["metrics.result"])
        assert result == size * 2  # Our script multiplies by 2


def test_integration_with_cache(simple_integration_config, tmp_path):
    """Test end-to-end execution with caching."""
    config = load_config(simple_integration_config)

    # Add cache database
    cache_db = tmp_path / "cache.db"
    config.benchmark.sqlite_db = cache_db

    # First run
    args = Mock()
    args.use_cache = False
    args.log_level = "INFO"
    args.max_core_hours = None

    runner1 = IOPSRunner(config, args)
    runner1.run()

    assert cache_db.exists()

    # Second run with cache
    args.use_cache = True
    runner2 = IOPSRunner(config, args)
    runner2.run()

    # Should have cache hits
    assert runner2.cache_hits > 0
    assert runner2.cache_hits + runner2.cache_misses == 4  # 2 tests * 2 reps


def test_integration_multi_round(tmp_path):
    """Test multi-round optimization workflow."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    config = {
        "benchmark": {
            "name": "Multi-Round Test",
            "workdir": str(workdir),
            "executor": "local",
            "repetitions": 1,
            "random_seed": 42,
        },
        "vars": {
            "nodes": {
                "type": "int",
                "sweep": {"mode": "list", "values": [1, 2]}
            },
            "ppn": {
                "type": "int",
                "sweep": {"mode": "list", "values": [2, 4]}
            }
        },
        "command": {
            "template": "echo 'nodes={{ nodes }} ppn={{ ppn }}'",
            "metadata": {"operation": "test"}
        },
        "rounds": [
            {
                "name": "optimize_nodes",
                "sweep_vars": ["nodes"],
                "fixed_overrides": {"ppn": 2},
                "search": {
                    "metric": "score",
                    "objective": "max"
                }
            },
            {
                "name": "optimize_ppn",
                "sweep_vars": ["ppn"],
                "search": {
                    "metric": "score",
                    "objective": "max"
                }
            }
        ],
        "scripts": [
            {
                "name": "test",
                "submit": "bash",
                "script_template": (
                    "#!/bin/bash\n"
                    "SCORE=$(({{ nodes }} * {{ ppn }}))\n"
                    "echo \"score: $SCORE\" > {{ execution_dir }}/output.txt\n"
                ),
                "parser": {
                    "file": "{{ execution_dir }}/output.txt",
                    "metrics": [{"name": "score", "type": "int"}],
                    "parser_script": (
                        "def parse(file_path):\n"
                        "    with open(file_path) as f:\n"
                        "        line = f.read().strip()\n"
                        "    return {'score': int(line.split(':')[1])}\n"
                    )
                }
            }
        ],
        "output": {
            "sink": {
                "type": "csv",
                "path": str(workdir / "results.csv"),
                "mode": "append"
            }
        }
    }

    config_file = tmp_path / "multi_round.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config, f)

    config = load_config(config_file)

    args = Mock()
    args.use_cache = False
    args.log_level = "INFO"
    args.max_core_hours = None

    runner = IOPSRunner(config, args)
    runner.run()

    # Check output
    output_file = workdir / "results.csv"
    assert output_file.exists()

    with open(output_file, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Round 1: 2 nodes (with ppn=2 fixed)
    # Round 2: 2 ppn (with best nodes from round 1)
    # Total: 2 + 2 = 4 tests
    assert len(rows) == 4


def test_integration_with_post_script(tmp_path):
    """Test integration with post-processing scripts."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    config = {
        "benchmark": {
            "name": "Post-Script Test",
            "workdir": str(workdir),
            "executor": "local",
            "repetitions": 1,
        },
        "vars": {
            "value": {
                "type": "int",
                "sweep": {"mode": "list", "values": [10, 20]}
            }
        },
        "command": {
            "template": "echo 'value={{ value }}'",
            "metadata": {"operation": "test"}
        },
        "scripts": [
            {
                "name": "with_post",
                "submit": "bash",
                "script_template": (
                    "#!/bin/bash\n"
                    "echo \"raw: {{ value }}\" > {{ execution_dir }}/raw.txt\n"
                ),
                "post": {
                    "script": (
                        "#!/bin/bash\n"
                        "VALUE=$(cat {{ execution_dir }}/raw.txt | cut -d' ' -f2)\n"
                        "DOUBLED=$((VALUE * 2))\n"
                        "echo \"result: $DOUBLED\" > {{ execution_dir }}/output.txt\n"
                    )
                },
                "parser": {
                    "file": "{{ execution_dir }}/output.txt",
                    "metrics": [{"name": "result", "type": "int"}],
                    "parser_script": (
                        "def parse(file_path):\n"
                        "    with open(file_path) as f:\n"
                        "        line = f.read().strip()\n"
                        "    return {'result': int(line.split(':')[1])}\n"
                    )
                }
            }
        ],
        "output": {
            "sink": {
                "type": "csv",
                "path": str(workdir / "results.csv"),
                "mode": "overwrite"
            }
        }
    }

    config_file = tmp_path / "post_script.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config, f)

    config = load_config(config_file)

    args = Mock()
    args.use_cache = False
    args.log_level = "INFO"
    args.max_core_hours = None

    runner = IOPSRunner(config, args)
    runner.run()

    # Verify post script ran and produced correct results
    output_file = workdir / "results.csv"
    with open(output_file, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    for row in rows:
        value = int(row["vars.value"])
        result = int(row["metrics.result"])
        assert result == value * 2  # Post script doubles the value
