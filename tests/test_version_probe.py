"""Unit tests for the software version capture probe (benchmark.probes.versions).

Covers:
1. Config parsing and validation of the probes.versions mapping
2. Version probe script generation (_build_version_probe_script) and JSON output
3. Script injection (_inject_iops_scripts writes and sources the probe)
4. Report rendering of the versions section, including cross-execution drift detection
"""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from iops.config.models import ProbesConfig, ReportingConfig, SectionConfig
from iops.config.loader import ConfigValidationError, _parse_version_probe
from iops.execution.planner import (
    ExhaustivePlanner,
    _build_version_probe_script,
    ATEXIT_VERSION_FILENAME,
    VERSIONS_FILENAME,
)
from iops.reporting.report_generator import ReportGenerator
from conftest import load_config


# ============================================================================ #
# Config parsing / validation
# ============================================================================ #

def test_probes_versions_defaults_to_none():
    assert ProbesConfig().versions is None


def test_parse_version_probe_valid_mapping():
    parsed = _parse_version_probe({"app": "app --version", "mpi": "mpirun --version"})
    assert parsed == {"app": "app --version", "mpi": "mpirun --version"}


def test_parse_version_probe_none_returns_none():
    assert _parse_version_probe(None) is None


def test_parse_version_probe_rejects_non_mapping():
    with pytest.raises(ConfigValidationError):
        _parse_version_probe(["app --version"])


def test_parse_version_probe_rejects_empty_command():
    with pytest.raises(ConfigValidationError):
        _parse_version_probe({"app": "   "})


def test_parse_version_probe_rejects_non_string_command():
    with pytest.raises(ConfigValidationError):
        _parse_version_probe({"app": 123})


def test_config_loads_versions_from_probes(sample_config_dict, tmp_path):
    sample_config_dict["benchmark"]["probes"] = {
        "system_snapshot": False,
        "versions": {"app": "echo 1.0", "python": "python3 --version"},
    }
    config_file = tmp_path / "cfg.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    config = load_config(config_file)
    assert config.benchmark.probes.versions == {
        "app": "echo 1.0",
        "python": "python3 --version",
    }


def test_config_rejects_invalid_versions_type(sample_config_dict, tmp_path):
    sample_config_dict["benchmark"]["probes"] = {"versions": ["not", "a", "map"]}
    config_file = tmp_path / "cfg.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config_dict, f)

    with pytest.raises(ConfigValidationError):
        load_config(config_file)


# ============================================================================ #
# Script generation
# ============================================================================ #

def test_build_version_probe_script_contains_components():
    script = _build_version_probe_script({"app": "echo hi", "mpi": "echo mpi"}, "/run/exec")
    assert "_iops_capture_versions" in script
    assert f"/run/exec/{VERSIONS_FILENAME}" in script
    assert "echo hi" in script
    assert "echo mpi" in script


def test_version_probe_script_produces_valid_json(tmp_path):
    versions = {
        "app": 'echo "MyApp 1.2.3"',
        "multi": 'printf "line1\nline2"',
        "missing": "this_command_does_not_exist_zzz --version",
    }
    script = _build_version_probe_script(versions, str(tmp_path))
    script_file = tmp_path / "probe.sh"
    script_file.write_text(script)

    subprocess.run(["bash", str(script_file)], check=True)

    data = json.loads((tmp_path / VERSIONS_FILENAME).read_text())
    assert data["app"] == "MyApp 1.2.3"
    assert data["multi"] == "line1\nline2"   # newline preserved and JSON-escaped
    assert data["missing"] == ""              # failing command yields empty string


# ============================================================================ #
# Script injection
# ============================================================================ #

def test_inject_versions_probe_creates_and_sources_file(sample_config_file, tmp_path):
    config = load_config(sample_config_file)
    config.benchmark.probes = ProbesConfig(
        system_snapshot=False, versions={"app": "echo 1.0"}
    )
    planner = ExhaustivePlanner(config)

    exec_dir = tmp_path / "exec"
    exec_dir.mkdir()
    result = planner._inject_iops_scripts("#!/bin/bash\necho run", exec_dir)

    probe_file = exec_dir / ATEXIT_VERSION_FILENAME
    assert probe_file.exists()
    assert "echo 1.0" in probe_file.read_text()
    assert f'source "{probe_file}"' in result


def test_no_version_probe_when_unset(sample_config_file, tmp_path):
    config = load_config(sample_config_file)
    config.benchmark.probes = ProbesConfig(system_snapshot=False, versions=None)
    planner = ExhaustivePlanner(config)

    exec_dir = tmp_path / "exec"
    exec_dir.mkdir()
    planner._inject_iops_scripts("#!/bin/bash\necho run", exec_dir)

    assert not (exec_dir / ATEXIT_VERSION_FILENAME).exists()


# ============================================================================ #
# Report rendering / drift detection
# ============================================================================ #

def _make_run_dir(tmp_path, versions_per_exec):
    """Build a minimal run directory with an index and per-execution version files."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    index = {"benchmark": "T", "executions": {}}
    for i, (params, versions) in enumerate(versions_per_exec, start=1):
        exec_key = f"exec_{i:04d}"
        rel = f"runs/{exec_key}"
        rep = run_dir / rel / "repetition_001"
        rep.mkdir(parents=True)
        (rep / VERSIONS_FILENAME).write_text(json.dumps(versions))
        index["executions"][exec_key] = {"path": rel, "params": params, "command": "x"}
    (run_dir / "__iops_index.json").write_text(json.dumps(index))
    return run_dir


def _report_stub(run_dir):
    gen = ReportGenerator.__new__(ReportGenerator)
    gen.workdir = run_dir
    gen.report_config = ReportingConfig(sections=SectionConfig())
    return gen


def test_versions_section_no_drift(tmp_path):
    run_dir = _make_run_dir(tmp_path, [
        ({"nodes": 1}, {"app": "1.0", "mpi": "4.1"}),
        ({"nodes": 2}, {"app": "1.0", "mpi": "4.1"}),
    ])
    html = _report_stub(run_dir)._generate_versions_section()
    assert "Software Versions" in html
    assert "version-drift" not in html       # identical versions -> no warning
    assert "1.0" in html and "4.1" in html


def test_versions_section_detects_drift(tmp_path):
    run_dir = _make_run_dir(tmp_path, [
        ({"nodes": 1}, {"app": "1.0"}),
        ({"nodes": 2}, {"app": "0.9-OLD"}),
    ])
    html = _report_stub(run_dir)._generate_versions_section()
    assert 'class="version-drift"' in html
    assert "drift detected" in html
    assert "version-mismatch" in html        # outlier cell highlighted
    assert "0.9-OLD" in html


def test_versions_section_empty_when_no_files(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "__iops_index.json").write_text(json.dumps({"executions": {}}))
    assert _report_stub(run_dir)._generate_versions_section() == ""


def test_versions_section_disabled_by_section_toggle(tmp_path):
    run_dir = _make_run_dir(tmp_path, [({"nodes": 1}, {"app": "1.0"})])
    gen = _report_stub(run_dir)
    gen.report_config.sections.versions = False
    assert gen._generate_versions_section() == ""


# ============================================================================ #
# Versions surfaced as version.* columns in the results sink
# ============================================================================ #

def _fake_test(execution_dir):
    """Minimal stand-in for an ExecutionInstance, enough for build_output_row."""
    return SimpleNamespace(
        benchmark_name="T",
        benchmark_description=None,
        execution_id=1,
        repetition=1,
        repetitions=1,
        workdir=execution_dir.parent,
        execution_dir=execution_dir,
        vars={"nodes": 1},
        metadata={"metrics": {"throughput": 5.0}},
    )


def test_build_output_row_includes_version_columns(tmp_path):
    from iops.results.writer import build_output_row

    exec_dir = tmp_path / "exec_0001" / "repetition_001"
    exec_dir.mkdir(parents=True)
    (exec_dir / VERSIONS_FILENAME).write_text(json.dumps({"app": "1.2.3", "mpi": "4.1"}))

    row = build_output_row(_fake_test(exec_dir))
    assert row["version.app"] == "1.2.3"
    assert row["version.mpi"] == "4.1"
    assert row["metrics.throughput"] == 5.0   # existing columns still present


def test_build_output_row_no_version_columns_when_absent(tmp_path):
    from iops.results.writer import build_output_row

    exec_dir = tmp_path / "exec_0001" / "repetition_001"
    exec_dir.mkdir(parents=True)

    row = build_output_row(_fake_test(exec_dir))
    assert not any(k.startswith("version.") for k in row)
