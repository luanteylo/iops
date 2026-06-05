"""Tests for the execution status breakdown in HTML reports.

The results DataFrame is filtered to SUCCEEDED rows at load time, so the report
sources status counts from the run index and per-execution status files instead.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from iops.reporting.report_generator import ReportGenerator


def _write_status(exec_dir: Path, status: str):
    """Write a repetition-level status file under an execution folder."""
    rep_dir = exec_dir / "repetition_1"
    rep_dir.mkdir(parents=True, exist_ok=True)
    if status != "PENDING":  # PENDING is represented by the absence of a status file
        (rep_dir / "__iops_status.json").write_text(json.dumps({"status": status}))


def _write_skipped(exec_dir: Path, reason: str = "constraint"):
    """Write a test-level skipped marker."""
    exec_dir.mkdir(parents=True, exist_ok=True)
    (exec_dir / "__iops_skipped").write_text(json.dumps({"reason": reason}))


@pytest.fixture
def workdir_with_statuses(tmp_path):
    """Create a run workdir with a mix of execution statuses.

    Layout: 3 SUCCEEDED, 1 FAILED, 1 SKIPPED, 1 PENDING (6 total).
    """
    workdir = tmp_path / "run_001"
    workdir.mkdir()

    # Results CSV only needs SUCCEEDED rows (matches what the report consumes).
    df = pd.DataFrame({
        "benchmark.name": ["b"] * 3,
        "execution.execution_id": [1, 2, 3],
        "execution.repetition": [1, 1, 1],
        "vars.nodes": [1, 2, 4],
        "metrics.tput": [10.0, 20.0, 40.0],
        "metadata.__executor_status": ["SUCCEEDED"] * 3,
    })
    results_path = workdir / "results.csv"
    df.to_csv(results_path, index=False)

    metadata = {
        "benchmark": {
            "name": "StatusDemo", "workdir": str(workdir), "executor": "local",
            "repetitions": 1, "report_vars": ["nodes"],
            "timestamp": "2026-06-05T00:00:00",
        },
        "variables": {
            "nodes": {"type": "int", "swept": True,
                      "sweep": {"mode": "list", "values": [1, 2, 4]}},
        },
        "metrics": [{"name": "tput", "script": "s"}],
        "output": {"type": "csv", "path": str(results_path)},
        "command": {"template": "run --nodes {{ nodes }}", "labels": {}},
    }
    (workdir / "__iops_run_metadata.json").write_text(json.dumps(metadata))

    index = {
        "benchmark": "StatusDemo",
        "executions": {
            f"exec_{i:04d}": {"path": f"runs/exec_{i:04d}", "params": {"nodes": i}}
            for i in range(1, 7)
        },
    }
    (workdir / "__iops_index.json").write_text(json.dumps(index))

    runs = workdir / "runs"
    _write_status(runs / "exec_0001", "SUCCEEDED")
    _write_status(runs / "exec_0002", "SUCCEEDED")
    _write_status(runs / "exec_0003", "SUCCEEDED")
    _write_status(runs / "exec_0004", "FAILED")
    _write_skipped(runs / "exec_0005")
    _write_status(runs / "exec_0006", "PENDING")

    return workdir


def test_gather_execution_status_counts(workdir_with_statuses):
    """Status counts are aggregated from the index and per-execution status files."""
    generator = ReportGenerator(workdir=workdir_with_statuses)
    counts = generator._gather_execution_status_counts()

    assert dict(counts) == {
        "SUCCEEDED": 3,
        "FAILED": 1,
        "SKIPPED": 1,
        "PENDING": 1,
    }


def test_gather_execution_status_counts_no_index(tmp_path):
    """Returns an empty Counter when no index is present."""
    generator = ReportGenerator(workdir=tmp_path)
    assert generator._gather_execution_status_counts() == {}


def test_report_includes_execution_status_section(workdir_with_statuses):
    """The generated report shows the Execution Status table and a success rate."""
    generator = ReportGenerator(workdir=workdir_with_statuses)
    generator.load_metadata()
    generator.load_results()
    report_path = generator.generate_report()

    html = Path(report_path).read_text()

    assert "<h3>Execution Status</h3>" in html
    # Each status with its count appears in the table.
    assert "SUCCEEDED" in html and "FAILED" in html
    assert "SKIPPED" in html and "PENDING" in html
    # Total across all statuses and the success rate (3 of 6).
    assert "<strong>6</strong>" in html
    assert "3/6 (50.0%)" in html


def test_report_no_success_rate_when_all_succeeded(tmp_path):
    """Success Rate row is omitted when every execution succeeded."""
    workdir = tmp_path / "run_all_ok"
    workdir.mkdir()

    df = pd.DataFrame({
        "benchmark.name": ["b"] * 2,
        "execution.execution_id": [1, 2],
        "execution.repetition": [1, 1],
        "vars.nodes": [1, 2],
        "metrics.tput": [10.0, 20.0],
        "metadata.__executor_status": ["SUCCEEDED"] * 2,
    })
    results_path = workdir / "results.csv"
    df.to_csv(results_path, index=False)

    metadata = {
        "benchmark": {"name": "AllOK", "workdir": str(workdir), "executor": "local",
                      "repetitions": 1, "report_vars": ["nodes"],
                      "timestamp": "2026-06-05T00:00:00"},
        "variables": {"nodes": {"type": "int", "swept": True,
                                "sweep": {"mode": "list", "values": [1, 2]}}},
        "metrics": [{"name": "tput", "script": "s"}],
        "output": {"type": "csv", "path": str(results_path)},
        "command": {"template": "run", "labels": {}},
    }
    (workdir / "__iops_run_metadata.json").write_text(json.dumps(metadata))

    index = {"benchmark": "AllOK", "executions": {
        f"exec_{i:04d}": {"path": f"runs/exec_{i:04d}", "params": {"nodes": i}}
        for i in range(1, 3)
    }}
    (workdir / "__iops_index.json").write_text(json.dumps(index))
    _write_status(workdir / "runs" / "exec_0001", "SUCCEEDED")
    _write_status(workdir / "runs" / "exec_0002", "SUCCEEDED")

    generator = ReportGenerator(workdir=workdir)
    generator.load_metadata()
    generator.load_results()
    html = Path(generator.generate_report()).read_text()

    assert "Success Rate" not in html
    # The status table still appears, showing all succeeded.
    assert "<h3>Execution Status</h3>" in html
    assert "<strong>2</strong>" in html
