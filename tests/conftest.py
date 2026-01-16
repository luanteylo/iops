"""Pytest fixtures for IOPS tests."""

import pytest
from pathlib import Path
import tempfile
import yaml
import logging


def load_config(config_path):
    """Helper to load config without logger dependency."""
    from iops.config.loader import load_generic_config
    logger = logging.getLogger("test")
    return load_generic_config(Path(config_path), logger)


@pytest.fixture
def tmp_workdir(tmp_path):
    """Create a temporary working directory."""
    workdir = tmp_path / "workdir"
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


@pytest.fixture
def sample_config_dict(tmp_workdir):
    """Create a sample configuration dictionary."""
    return {
        "benchmark": {
            "name": "Test Benchmark",
            "description": "A test benchmark",
            "workdir": str(tmp_workdir),
            "executor": "local",
            "repetitions": 2,
            "random_seed": 42,
        },
        "vars": {
            "nodes": {
                "type": "int",
                "sweep": {
                    "mode": "list",
                    "values": [1, 2],
                }
            },
            "ppn": {
                "type": "int",
                "expr": "4",
            },
            "total_procs": {
                "type": "int",
                "expr": "{{ nodes * ppn }}",
            }
        },
        "command": {
            "template": "echo 'nodes={{ nodes }} ppn={{ ppn }}'",
            "labels": {
                "operation": "test"
            }
        },
        "scripts": [
            {
                "name": "test_script",
                "script_template": "#!/bin/bash\necho 'nodes={{ nodes }} ppn={{ ppn }}'\necho 'result: 100' > {{ execution_dir }}/output.txt",
                "parser": {
                    "file": "{{ execution_dir }}/output.txt",
                    "metrics": [
                        {"name": "result", "type": "float"},
                    ],
                    "parser_script": "def parse(file_path):\n    with open(file_path) as f:\n        line = f.read().strip()\n    return {'result': float(line.split(':')[1])}"
                }
            }
        ],
        "output": {
            "sink": {
                "type": "csv",
                "path": "{{ workdir }}/results.csv",
                "mode": "append"
            }
        }
    }


@pytest.fixture
def sample_config_file(tmp_path, sample_config_dict):
    """Create a sample configuration YAML file."""
    config_file = tmp_path / "test_config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)
    return config_file


