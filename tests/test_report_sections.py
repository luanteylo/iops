"""Every toggle in reporting.sections must change the generated report.

test_summary, best_results, bayesian_evolution, and custom_plots were accepted by
the loader and written to report_config.yaml, but the generator never read them,
so turning one off (from Studio's report editor, for instance) regenerated an
identical report.
"""

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from iops.config.loader import load_report_config
from iops.reporting.report_generator import generate_report_from_workdir

CUSTOM_TITLE = "Throughput by node count"


def _make_run(tmp_path: Path, search_method: str = "exhaustive") -> Path:
    workdir = tmp_path / "run_001"
    workdir.mkdir()
    df = pd.DataFrame({
        "benchmark.name": ["b"] * 6,
        "execution.execution_id": [1, 2, 3, 4, 5, 6],
        "execution.repetition": [1] * 6,
        "vars.nodes": [1, 2, 4, 1, 2, 4],
        "vars.mode": ["a", "a", "a", "b", "b", "b"],
        "metrics.tput": [10.0, 20.0, 40.0, 12.0, 22.0, 41.0],
        "metadata.__executor_status": ["SUCCEEDED"] * 6,
    })
    results = workdir / "results.csv"
    df.to_csv(results, index=False)
    metadata = {
        "benchmark": {
            "name": "Sections", "workdir": str(workdir), "executor": "local",
            "repetitions": 1, "report_vars": ["nodes", "mode"],
            "search_method": search_method, "timestamp": "2026-06-05T00:00:00",
        },
        "variables": {
            "nodes": {"type": "int", "swept": True,
                      "sweep": {"mode": "list", "values": [1, 2, 4]}},
            "mode": {"type": "str", "swept": True,
                     "sweep": {"mode": "list", "values": ["a", "b"]}},
        },
        "metrics": [{"name": "tput", "script": "s"}],
        "output": {"type": "csv", "path": str(results)},
        "command": {"template": "run --nodes {{ nodes }}", "labels": {}},
    }
    (workdir / "__iops_run_metadata.json").write_text(json.dumps(metadata))
    return workdir


def _report(workdir: Path, tmp_path: Path, sections: dict) -> str:
    cfg_path = tmp_path / "report_config.yaml"
    cfg_path.write_text(yaml.dump({"reporting": {
        "enabled": True,
        "sections": sections,
        "metrics": {"tput": {"plots": [
            {"type": "scatter", "x_var": "nodes", "title": CUSTOM_TITLE},
        ]}},
    }}))
    out = tmp_path / f"report_{len(list(tmp_path.glob('report_*.html')))}.html"
    path = generate_report_from_workdir(workdir, output_path=out,
                                        report_config=load_report_config(cfg_path))
    return Path(path).read_text()


@pytest.mark.parametrize("toggle, marker", [
    ("test_summary", "<h2>Summary Statistics</h2>"),
    ("best_results", "<h2>Best Configurations</h2>"),
    ("custom_plots", CUSTOM_TITLE),
])
def test_turning_a_section_off_removes_it(tmp_path, toggle, marker):
    workdir = _make_run(tmp_path)
    assert marker in _report(workdir, tmp_path, {toggle: True})
    assert marker not in _report(workdir, tmp_path, {toggle: False})


def test_sections_default_to_on_when_not_configured(tmp_path):
    workdir = _make_run(tmp_path)
    html = _report(workdir, tmp_path, {})
    assert "<h2>Summary Statistics</h2>" in html
    assert "<h2>Best Configurations</h2>" in html
    assert CUSTOM_TITLE in html


def test_other_sections_survive_when_one_is_off(tmp_path):
    workdir = _make_run(tmp_path)
    html = _report(workdir, tmp_path, {"best_results": False})
    assert "<h2>Summary Statistics</h2>" in html
    assert CUSTOM_TITLE in html


def test_bayesian_evolution_toggle_gates_the_optimization_section(tmp_path, monkeypatch):
    from iops.reporting import report_generator as rg

    monkeypatch.setattr(rg.ReportGenerator, "_generate_bayesian_optimization_section",
                        lambda self, metrics, report_vars: "<h2>BAYES_MARKER</h2>")
    workdir = _make_run(tmp_path, search_method="bayesian")
    assert "BAYES_MARKER" in _report(workdir, tmp_path, {"bayesian_evolution": True})
    assert "BAYES_MARKER" not in _report(workdir, tmp_path, {"bayesian_evolution": False})
