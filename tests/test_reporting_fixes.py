"""Regression tests for reporting fixes.

Covers:
- Core-hours calculation pairing each row with its own duration when the
  results DataFrame has a gappy index (filtered to SUCCEEDED rows).
- HTML escaping of user and probe derived strings in report sections.
- Variable impact plot rendering when all impact scores are zero.
- Report config serializer/deserializer round trip (coverage_heatmap fields,
  sections, best_results.min_samples).
- report_config.yaml round trip keeping every PlotConfig field (log_y was lost).
- Bar value labels readable for small metric values.
- Scatter plot with a string-typed color_by variable.
"""

import json
from dataclasses import fields

import pandas as pd
import pytest

from iops.config.models import (
    BestResultsConfig,
    MetricPlotsConfig,
    PlotConfig,
    ReportingConfig,
    ReportThemeConfig,
    SectionConfig,
)
from iops.config.loader import load_report_config
from iops.reporting.config_template import (
    _create_clean_report_config,
    _literal_block_dumper,
    serialize_reporting_config,
)
from iops.reporting.plots import BarPlot, ScatterPlot
from iops.reporting.report_generator import ReportGenerator


# ============================================================================
# Core-hours: row/duration pairing with a gappy index
# ============================================================================

class TestCoreHoursGappyIndex:
    def _make_generator(self, tmp_path):
        gen = ReportGenerator(workdir=tmp_path)
        gen.metadata = {
            'benchmark': {'cores_expr': '{{ cores }}'},
            'variables': {'cores': {'type': 'int'}},
        }
        df = pd.DataFrame({
            'vars.cores': [1, 10, 100],
            'metadata.__job_start': ['2026-01-01T00:00:00'] * 3,
            'metadata.__end': [
                '2026-01-01T01:00:00',  # 1 hour
                '2026-01-01T02:00:00',  # 2 hours
                '2026-01-01T04:00:00',  # 4 hours
            ],
        })
        # Simulate SUCCEEDED-only filtering: index labels have gaps.
        df.index = [0, 2, 5]
        gen.df = df
        return gen

    def test_total_core_hours_pairs_each_row_with_its_own_duration(self, tmp_path):
        gen = self._make_generator(tmp_path)
        total = gen._calculate_total_core_hours()
        # 1 core * 1h + 10 cores * 2h + 100 cores * 4h = 421 core-hours.
        # The old positional/label mixup yielded 41 (mismatched durations and
        # a silently swallowed IndexError on the last row).
        assert total == pytest.approx(421.0)

    def test_total_core_hours_with_default_range_index(self, tmp_path):
        gen = self._make_generator(tmp_path)
        gen.df = gen.df.reset_index(drop=True)
        total = gen._calculate_total_core_hours()
        assert total == pytest.approx(421.0)


# ============================================================================
# HTML escaping of user and probe derived strings
# ============================================================================

@pytest.fixture
def workdir_with_hostile_strings(tmp_path):
    """Workdir whose metadata contains HTML/JS payloads in string fields."""
    workdir = tmp_path / "run_001"
    workdir.mkdir()

    results = pd.DataFrame({
        "benchmark.name": ["evil"] * 4,
        "execution.execution_id": [1, 2, 3, 4],
        "execution.repetition": [1, 1, 1, 1],
        "vars.nodes": [1, 2, 1, 2],
        "vars.evil_str": ['<script>alert(3)</script>'] * 4,
        "metrics.bandwidth": [100.0, 200.0, 110.0, 210.0],
    })
    results_path = workdir / "results.csv"
    results.to_csv(results_path, index=False)

    metadata = {
        "benchmark": {
            "name": 'Bench <script>alert(1)</script>',
            "description": 'Desc <img src=x onerror=alert(2)>',
            "hostname": '<b>evil-host</b><script>alert(4)</script>',
            "workdir": str(workdir),
            "executor": "local",
            "repetitions": 1,
            "report_vars": ["nodes"],
            "timestamp": "2026-01-01T00:00:00",
        },
        "variables": {
            "nodes": {
                "type": "int",
                "swept": True,
                "sweep": {"mode": "list", "values": [1, 2]},
            },
            "evil_str": {
                "type": "str",
                "swept": True,
                "sweep": {"mode": "list", "values": ['<script>alert(3)</script>']},
            },
        },
        "metrics": [{"name": "bandwidth", "script": "bench"}],
        "system_environment": {
            "node_count": 2,
            "nodes": ['node<script>alert(5)</script>', "node2"],
            "cpu_model": 'CPU <script>alert(6)</script>',
            "os": 'OS <script>alert(7)</script>',
            "kernel": "5.15.0",
            "filesystems": ['lustre<script>alert(8)</script>:/mnt/<script>alert(9)</script>'],
            "interconnect": ['mlx5_0<script>alert(10)</script>'],
        },
        "output": {"type": "csv", "path": str(results_path)},
        "command": {
            "template": "bench --nodes {{ nodes }}",
            "labels": {},
        },
        "reporting": {
            "enabled": True,
            "output_filename": "report.html",
            "metrics": {
                "bandwidth": {
                    "plots": [{"type": "line", "x_var": "nodes"}]
                }
            },
            "default_plots": [],
        },
    }

    with open(workdir / "__iops_run_metadata.json", "w") as f:
        json.dump(metadata, f)

    return workdir


class TestHtmlEscaping:
    def test_hostile_strings_are_escaped_in_report(self, workdir_with_hostile_strings):
        gen = ReportGenerator(workdir=workdir_with_hostile_strings)
        gen.load_metadata()
        gen.load_results()
        output = gen.generate_report()

        html = output.read_text()

        # None of the injected payloads may appear unescaped.
        for i in range(1, 11):
            assert f'<script>alert({i})</script>' not in html, (
                f"payload alert({i}) was not escaped"
            )
        assert '<img src=x onerror=' not in html
        assert '<b>evil-host</b>' not in html

        # Escaped versions are present (benchmark name appears in the header).
        assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html

    def test_variable_impact_plot_handles_all_zero_impacts(self, tmp_path):
        gen = ReportGenerator(workdir=tmp_path)
        gen.metadata = {'variables': {'nodes': {'type': 'int'}}}
        # Constant metric: between-group and total variance are both zero,
        # so every impact score is zero.
        gen.df = pd.DataFrame({
            'vars.nodes': [1, 2, 1, 2],
            'metrics.bandwidth': [5.0, 5.0, 5.0, 5.0],
        })

        fig = gen._create_variable_impact_plot('bandwidth', ['nodes'])

        assert fig is not None
        # Degenerate [0, 0] range would hide the plot; expect a default range.
        assert tuple(fig.layout.yaxis.range) == (0, 1)


# ============================================================================
# Report config serialization round trip
# ============================================================================

class TestConfigTemplateRoundTrip:
    def test_coverage_heatmap_fields_survive_round_trip(self, tmp_path):
        original = ReportingConfig(
            enabled=True,
            metrics={
                "bandwidth": MetricPlotsConfig(plots=[
                    PlotConfig(
                        type="coverage_heatmap",
                        row_vars=["nodes", "ppn"],
                        col_var="block_size",
                        aggregation="median",
                        show_missing=False,
                        sort_rows_by="values",
                        sort_cols_by="values",
                        sort_ascending=True,
                    )
                ])
            },
            sections=SectionConfig(
                bayesian_parameter_evolution=True,
                resource_sampling=False,
            ),
            best_results=BestResultsConfig(top_n=7, show_command=False, min_samples=3),
        )

        serialized = serialize_reporting_config(original)
        # Must survive a JSON round trip (this is how it is stored in metadata).
        serialized = json.loads(json.dumps(serialized))

        gen = ReportGenerator(workdir=tmp_path)
        restored = gen._deserialize_reporting_config(serialized)

        plot = restored.metrics["bandwidth"].plots[0]
        assert plot.type == "coverage_heatmap"
        assert plot.row_vars == ["nodes", "ppn"]
        assert plot.col_var == "block_size"
        assert plot.aggregation == "median"
        assert plot.show_missing is False
        assert plot.sort_rows_by == "values"
        assert plot.sort_cols_by == "values"
        assert plot.sort_ascending is True

        assert restored.sections.bayesian_parameter_evolution is True
        assert restored.sections.resource_sampling is False

        assert restored.best_results.top_n == 7
        assert restored.best_results.show_command is False
        assert restored.best_results.min_samples == 3


def _plot_config_with_every_field_changed() -> PlotConfig:
    """A PlotConfig where every field differs from its default."""
    return PlotConfig(
        type="scatter",
        x_var="nodes",
        y_var="ppn",
        z_metric="latency",
        group_by="mode",
        color_by="mode",
        size_by="ppn",
        title="Custom title",
        xaxis_label="Nodes",
        yaxis_label="Bandwidth",
        log_x=True,
        log_y=True,
        colorscale="Plasma",
        show_error_bars=False,
        show_outliers=False,
        height=700,
        width=900,
        per_variable=True,
        include_metric=False,
        row_vars=["nodes", "ppn"],
        col_var="mode",
        aggregation="median",
        show_missing=False,
        sort_rows_by="values",
        sort_cols_by="values",
        sort_ascending=True,
    )


class TestReportConfigYamlRoundTrip:
    """report_config.yaml is auto-loaded by `iops report`, so it must not drop plot options."""

    def _round_trip(self, reporting, tmp_path):
        import yaml

        path = tmp_path / "report_config.yaml"
        clean = _create_clean_report_config(reporting, scripts=[])
        with open(path, "w") as f:
            yaml.dump({"reporting": clean}, f, Dumper=_literal_block_dumper(), sort_keys=False)
        return load_report_config(path)

    def test_fixture_changes_every_plot_field(self):
        changed = _plot_config_with_every_field_changed()
        default = PlotConfig(type=changed.type)
        unchanged = [
            f.name for f in fields(PlotConfig)
            if f.name != "type" and getattr(changed, f.name) == getattr(default, f.name)
        ]
        assert unchanged == [], "update the fixture for new PlotConfig fields"

    def test_metric_plot_fields_survive(self, tmp_path):
        original = _plot_config_with_every_field_changed()
        reporting = ReportingConfig(
            enabled=True,
            metrics={"bandwidth": MetricPlotsConfig(plots=[original])},
        )

        restored = self._round_trip(reporting, tmp_path)

        assert restored.metrics["bandwidth"].plots[0] == original

    def test_default_plot_fields_survive(self, tmp_path):
        original = _plot_config_with_every_field_changed()
        reporting = ReportingConfig(enabled=True, default_plots=[original])

        restored = self._round_trip(reporting, tmp_path)

        assert restored.default_plots[0] == original

    def test_log_y_bar_plot_survives(self, tmp_path):
        original = PlotConfig(type="bar", x_var="levelmin", log_y=True)
        reporting = ReportingConfig(
            enabled=True,
            metrics={"l1_norm": MetricPlotsConfig(plots=[original])},
        )

        restored = self._round_trip(reporting, tmp_path)

        assert restored.metrics["l1_norm"].plots[0].log_y is True

    def test_default_values_are_omitted(self):
        reporting = ReportingConfig(
            enabled=True,
            metrics={"bandwidth": MetricPlotsConfig(plots=[PlotConfig(type="bar", x_var="nodes")])},
        )

        clean = _create_clean_report_config(reporting, scripts=[])

        assert clean["metrics"]["bandwidth"]["plots"] == [{"type": "bar", "x_var": "nodes"}]


# ============================================================================
# Bar plot value labels
# ============================================================================

class TestBarPlotLabels:
    def test_small_values_are_not_rounded_to_zero(self):
        df = pd.DataFrame({
            "vars.levelmin": [4, 5, 7],
            "metrics.l1_norm": [9.56e-4, 9.57e-4, 9.10e-4],
        })
        plot = BarPlot(
            df=df,
            metric="l1_norm",
            plot_config=PlotConfig(type="bar", x_var="levelmin"),
            theme=ReportThemeConfig(),
            var_column_fn=lambda v: f"vars.{v}",
            metric_column_fn=lambda m: f"metrics.{m}",
        )

        labels = list(plot.generate().data[0].text)

        assert labels == ["0.000956", "0.000957", "0.00091"]


# ============================================================================
# Scatter plot with string-typed columns
# ============================================================================

class TestScatterStringValues:
    def _make_plot(self, df, config):
        return ScatterPlot(
            df=df,
            metric="bandwidth",
            plot_config=config,
            theme=ReportThemeConfig(),
            var_column_fn=lambda v: f"vars.{v}",
            metric_column_fn=lambda m: f"metrics.{m}",
        )

    def test_string_color_by_does_not_raise(self):
        df = pd.DataFrame({
            "vars.nodes": [1, 2, 1, 2],
            "vars.mode": ["read", "write", "read", "write"],
            "metrics.bandwidth": [100.0, 200.0, 110.0, 210.0],
        })
        config = PlotConfig(type="scatter", x_var="nodes", color_by="mode")

        fig = self._make_plot(df, config).generate()

        assert fig is not None
        trace = fig.data[0]
        # Category names must still be visible in the hover text.
        assert any("mode: read" in t for t in trace.text)
        assert any("mode: write" in t for t in trace.text)

    def test_string_y_var_does_not_raise(self):
        df = pd.DataFrame({
            "vars.nodes": [1, 2, 1, 2],
            "vars.mode": ["read", "write", "read", "write"],
            "metrics.bandwidth": [100.0, 200.0, 110.0, 210.0],
        })
        config = PlotConfig(type="scatter", x_var="nodes", y_var="mode")

        fig = self._make_plot(df, config).generate()

        assert fig is not None
        assert any("mode: read" in t for t in fig.data[0].text)

    def test_numeric_color_by_still_formats_numbers(self):
        df = pd.DataFrame({
            "vars.nodes": [1, 2],
            "metrics.bandwidth": [100.0, 200.0],
        })
        config = PlotConfig(type="scatter", x_var="nodes")

        fig = self._make_plot(df, config).generate()

        assert any("bandwidth: 100.0000" in t for t in fig.data[0].text)
