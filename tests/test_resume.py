"""Tests for `iops run --resume`: reusing an existing run_NNN folder."""

import json
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from iops.config.loader import (
    ConfigValidationError,
    _resolve_resume_target,
    load_generic_config,
)
from iops.execution.runner import IOPSRunner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _base_config(workdir: Path, values):
    return {
        "benchmark": {
            "name": "Resume Test",
            "workdir": str(workdir),
            "executor": "local",
            "repetitions": 1,
        },
        "vars": {
            "size": {
                "type": "int",
                "sweep": {"mode": "list", "values": list(values)},
            }
        },
        "command": {
            "template": "echo 'size={{ size }}'",
            "labels": {"op": "test"},
        },
        "scripts": [
            {
                "name": "simple",
                "script_template": (
                    "#!/bin/bash\n"
                    "SIZE={{ size }}\n"
                    "echo \"result: $((SIZE * 2))\" > {{ execution_dir }}/output.txt\n"
                ),
                "parser": {
                    "file": "{{ execution_dir }}/output.txt",
                    "metrics": [{"name": "result", "type": "int"}],
                    "parser_script": (
                        "def parse(file_path):\n"
                        "    with open(file_path) as f:\n"
                        "        line = f.read().strip()\n"
                        "    return {'result': int(line.split(':')[1].strip())}\n"
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


def _write_config(tmp_path: Path, values) -> Path:
    workdir = tmp_path / "workdir"
    workdir.mkdir(exist_ok=True)
    cfg = _base_config(workdir, values)
    config_file = tmp_path / "resume_config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(cfg, f)
    return config_file


def _make_args(**overrides):
    args = Mock()
    args.use_cache = False
    args.cache_only = False
    args.log_level = "INFO"
    args.max_core_hours = None
    args.config_file = overrides.pop("config_file", None)
    args.dry_run = False
    args.resume = None
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


def _run_once(config_file: Path, resume: str = None):
    logger = logging.getLogger("test_resume")
    cfg = load_generic_config(config_file, logger=logger, resume=resume)
    args = _make_args(config_file=config_file)
    runner = IOPSRunner(cfg, args)
    runner.run()
    return cfg, runner


# ---------------------------------------------------------------------------
# _resolve_resume_target unit tests
# ---------------------------------------------------------------------------


def test_resolve_latest_picks_highest_numbered(tmp_path):
    base = tmp_path / "wd"
    base.mkdir()
    for n in ("run_001", "run_003", "run_002"):
        d = base / n
        d.mkdir()
        (d / "__iops_index.json").write_text("{}")
    target = _resolve_resume_target(base, "__latest__")
    assert target.name == "run_003"


def test_resolve_by_explicit_name(tmp_path):
    base = tmp_path / "wd"
    base.mkdir()
    (base / "run_002").mkdir()
    (base / "run_002" / "__iops_config.yaml").write_text("")
    target = _resolve_resume_target(base, "run_002")
    assert target.name == "run_002"


def test_resolve_by_bare_number(tmp_path):
    base = tmp_path / "wd"
    base.mkdir()
    (base / "run_007").mkdir()
    (base / "run_007" / "__iops_index.json").write_text("{}")
    target = _resolve_resume_target(base, "7")
    assert target.name == "run_007"


def test_resolve_missing_folder_errors(tmp_path):
    base = tmp_path / "wd"
    base.mkdir()
    with pytest.raises(ConfigValidationError, match="not found"):
        _resolve_resume_target(base, "run_999")


def test_resolve_non_iops_folder_errors(tmp_path):
    base = tmp_path / "wd"
    base.mkdir()
    (base / "run_001").mkdir()  # no IOPS metadata files
    with pytest.raises(ConfigValidationError, match="does not look like an IOPS run folder"):
        _resolve_resume_target(base, "__latest__")


def test_resolve_empty_base_errors(tmp_path):
    base = tmp_path / "wd"
    base.mkdir()
    with pytest.raises(ConfigValidationError, match="no run_NNN folders found"):
        _resolve_resume_target(base, "__latest__")


# ---------------------------------------------------------------------------
# End-to-end: run, resume with extended sweep
# ---------------------------------------------------------------------------


def test_resume_appends_new_executions_and_preserves_old(tmp_path):
    # 1. Initial run with 2 sweep values -> exec_0001, exec_0002
    config_file = _write_config(tmp_path, [10, 20])
    cfg1, _ = _run_once(config_file)
    run_root = Path(cfg1.benchmark.workdir)
    assert run_root.name == "run_001"

    exec_dirs_after_first = sorted(
        d.name for d in (run_root / "runs").iterdir() if d.is_dir() and d.name.startswith("exec_")
    )
    assert exec_dirs_after_first == ["exec_0001", "exec_0002"]

    # Read original metadata for comparison
    meta_path = run_root / "__iops_run_metadata.json"
    with open(meta_path) as f:
        meta_before = json.load(f)
    original_start = meta_before["benchmark"]["benchmark_start_time"]

    # Snapshot original exec folder mtimes to confirm they're untouched
    exec_0001 = run_root / "runs" / "exec_0001"
    original_mtime = exec_0001.stat().st_mtime

    # Capture original row count
    results_csv = run_root / "results.csv"
    assert results_csv.exists()
    original_row_count = sum(1 for _ in open(results_csv)) - 1  # minus header
    assert original_row_count == 2

    # 2. Edit config: extend sweep to [10, 20, 30]
    with open(config_file) as f:
        cfg_data = yaml.safe_load(f)
    cfg_data["vars"]["size"]["sweep"]["values"] = [10, 20, 30]
    with open(config_file, "w") as f:
        yaml.dump(cfg_data, f)

    # 3. Resume into the same run folder
    cfg2, runner2 = _run_once(config_file, resume="__latest__")
    assert Path(cfg2.benchmark.workdir) == run_root  # same folder

    # 4. Assert: only exec_0003 was added; original folders untouched
    exec_dirs_after_resume = sorted(
        d.name for d in (run_root / "runs").iterdir() if d.is_dir() and d.name.startswith("exec_")
    )
    assert exec_dirs_after_resume == ["exec_0001", "exec_0002", "exec_0003"]
    assert exec_0001.stat().st_mtime == original_mtime  # untouched

    # 5. Results csv has 3 rows now
    new_row_count = sum(1 for _ in open(results_csv)) - 1
    assert new_row_count == 3

    # 6. Original benchmark_start_time is preserved
    with open(meta_path) as f:
        meta_after = json.load(f)
    assert meta_after["benchmark"]["benchmark_start_time"] == original_start
    # End time was updated
    assert meta_after["benchmark"]["benchmark_end_time"] != meta_before["benchmark"].get("benchmark_end_time")

    # 7. Index has 3 entries
    with open(run_root / "__iops_index.json") as f:
        index = json.load(f)
    assert set(index["executions"].keys()) == {"exec_0001", "exec_0002", "exec_0003"}

    # 8. Lockfile is gone
    assert not (run_root / "__iops_resume.lock").exists()

    # 9. Resumed config audit copy exists
    resumed_copies = list(run_root.glob("__iops_config_resume_*.yaml"))
    assert len(resumed_copies) == 1
    # Original config copy still present and unchanged
    assert (run_root / "__iops_config.yaml").exists()
