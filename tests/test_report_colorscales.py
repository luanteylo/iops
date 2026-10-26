"""Tests for report colorscale configuration.

Covers:
- reporting.theme.colorscale as the default for every colorbar.
- reporting.theme.section_colorscales overriding single built-in sections.
- Per-plot colorscale winning over the theme.
- Validation of colorscale values against Plotly.
- Round trip through run metadata and report_config.yaml.
"""

import pandas as pd
import plotly.graph_objects as go
import pytest
import yaml

from iops.config.loader import ConfigValidationError, _parse_reporting_config
from iops.config.models import (
    MetricPlotsConfig,
    PlotConfig,
    ReportingConfig,
    ReportThemeConfig,
)
from iops.reporting.config_template import (
    _create_clean_report_config,
    serialize_reporting_config,
)
from iops.reporting.plots import HeatmapPlot
from iops.reporting.report_generator import ReportGenerator


def _expanded(colorscale):
    """Plotly expands a colorscale name into its color stops on assignment."""
    return go.Heatmap(colorscale=colorscale).colorscale


# ============================================================================
# Parsing and validation
# ============================================================================

class TestParseColorscales:
    def test_theme_defaults(self):
        cfg = _parse_reporting_config({"enabled": True})

        assert cfg.theme.colorscale == "Viridis"
        assert cfg.theme.section_colorscales == {}

    def test_theme_colorscale_and_section_overrides(self):
        cfg = _parse_reporting_config({
            "theme": {
                "colorscale": "Cividis",
                "section_colorscales": {
                    "variable_impact": "Plasma",
                    "parallel_coordinates": "Turbo",
                    "bayesian_parameter_evolution": "Blues",
                },
            },
        })

        assert cfg.theme.colorscale == "Cividis"
        assert cfg.theme.colorscale_for("variable_impact") == "Plasma"
        assert cfg.theme.colorscale_for("parallel_coordinates") == "Turbo"
        assert cfg.theme.colorscale_for("bayesian_parameter_evolution") == "Blues"

    def test_section_without_override_uses_theme_colorscale(self):
        cfg = _parse_reporting_config({
            "theme": {
                "colorscale": "Cividis",
                "section_colorscales": {"variable_impact": "Plasma"},
            },
        })

        assert cfg.theme.colorscale_for("parallel_coordinates") == "Cividis"

    @pytest.mark.parametrize("value", ["viridis", "RdBu_r", ["#000000", "#ffffff"],
                                       [[0, "red"], [1, "blue"]]])
    def test_accepts_what_plotly_accepts(self, value):
        cfg = _parse_reporting_config({"theme": {"colorscale": value}})

        assert cfg.theme.colorscale == value

    def test_invalid_theme_colorscale(self):
        with pytest.raises(ConfigValidationError, match="reporting.theme.colorscale"):
            _parse_reporting_config({"theme": {"colorscale": "Virdis"}})

    def test_unknown_section_suggests_close_match(self):
        with pytest.raises(ConfigValidationError, match="variable_impact"):
            _parse_reporting_config({
                "theme": {"section_colorscales": {"variable_impcat": "Plasma"}},
            })

    def test_section_without_colorbar_is_rejected(self):
        with pytest.raises(ConfigValidationError, match="best_results"):
            _parse_reporting_config({
                "theme": {"section_colorscales": {"best_results": "Plasma"}},
            })

    def test_invalid_section_colorscale(self):
        with pytest.raises(ConfigValidationError,
                           match="section_colorscales.variable_impact"):
            _parse_reporting_config({
                "theme": {"section_colorscales": {"variable_impact": "nope"}},
            })

    def test_section_colorscales_must_be_mapping(self):
        with pytest.raises(ConfigValidationError, match="must be a mapping"):
            _parse_reporting_config({
                "theme": {"section_colorscales": ["Plasma"]},
            })

    def test_plot_colorscale_unset_is_none(self):
        cfg = _parse_reporting_config({
            "default_plots": [{"type": "heatmap", "x_var": "a", "y_var": "b"}],
        })

        assert cfg.default_plots[0].colorscale is None

    def test_invalid_plot_colorscale(self):
        with pytest.raises(ConfigValidationError,
                           match=r"reporting.metrics.bw.plots\[0\].colorscale"):
            _parse_reporting_config({
                "metrics": {"bw": {"plots": [
                    {"type": "heatmap", "x_var": "a", "y_var": "b", "colorscale": "Jett"},
                ]}},
            })


# ============================================================================
# Custom plots
# ============================================================================

class TestCustomPlotColorscale:
    @pytest.fixture
    def df(self):
        return pd.DataFrame({
            "vars.nodes": [1, 1, 2, 2],
            "vars.ppn": [4, 8, 4, 8],
            "metrics.bw": [10.0, 20.0, 30.0, 40.0],
        })

    def _heatmap(self, df, plot_colorscale, theme):
        plot = HeatmapPlot(
            df=df,
            metric="bw",
            plot_config=PlotConfig(type="heatmap", x_var="nodes", y_var="ppn",
                                   colorscale=plot_colorscale),
            theme=theme,
            var_column_fn=lambda v: f"vars.{v}",
            metric_column_fn=lambda m: f"metrics.{m}",
        )
        return plot.generate().data[0].colorscale

    def test_plot_without_colorscale_uses_theme(self, df):
        colorscale = self._heatmap(df, None, ReportThemeConfig(colorscale="Cividis"))

        assert colorscale == _expanded("Cividis")

    def test_plot_colorscale_wins_over_theme(self, df):
        colorscale = self._heatmap(df, "Hot", ReportThemeConfig(colorscale="Cividis"))

        assert colorscale == _expanded("Hot")

    def test_section_override_does_not_reach_custom_plots(self, df):
        theme = ReportThemeConfig(colorscale="Cividis",
                                  section_colorscales={"variable_impact": "Plasma"})

        assert self._heatmap(df, None, theme) == _expanded("Cividis")


# ============================================================================
# Built-in sections
# ============================================================================

class TestBuiltinSectionColorscale:
    @pytest.fixture
    def gen(self, tmp_path):
        gen = ReportGenerator(workdir=tmp_path)
        gen.metadata = {"variables": {"nodes": {"type": "int"}, "ppn": {"type": "int"}}}
        gen.df = pd.DataFrame({
            "execution.execution_id": [1, 2, 3, 4],
            "vars.nodes": [1, 1, 2, 2],
            "vars.ppn": [4, 8, 4, 8],
            "metrics.bw": [10.0, 20.0, 30.0, 45.0],
        })
        return gen

    def _set_theme(self, gen, **theme):
        gen.report_config = ReportingConfig(theme=ReportThemeConfig(**theme))

    def test_variable_impact_defaults_to_viridis(self, gen):
        self._set_theme(gen)

        fig = gen._create_variable_impact_plot("bw", ["nodes", "ppn"])

        assert fig.data[0].marker.colorscale == _expanded("Viridis")

    def test_variable_impact_uses_theme_colorscale(self, gen):
        self._set_theme(gen, colorscale="Cividis")

        fig = gen._create_variable_impact_plot("bw", ["nodes", "ppn"])

        assert fig.data[0].marker.colorscale == _expanded("Cividis")

    def test_variable_impact_section_override(self, gen):
        self._set_theme(gen, colorscale="Cividis",
                        section_colorscales={"variable_impact": "Plasma"})

        fig = gen._create_variable_impact_plot("bw", ["nodes", "ppn"])

        assert fig.data[0].marker.colorscale == _expanded("Plasma")

    def test_parallel_coordinates_section_override(self, gen):
        self._set_theme(gen, colorscale="Cividis",
                        section_colorscales={"parallel_coordinates": "Turbo"})

        fig = gen._create_parallel_coordinates("bw", ["nodes", "ppn"])

        assert fig.data[0].line.colorscale == _expanded("Turbo")

    def test_bayesian_parameter_evolution_uses_theme_colorscale(self, gen):
        self._set_theme(gen, colorscale="Cividis")

        fig = gen._create_bayesian_parameter_evolution_plot(
            ["nodes", "ppn"], "bw", "maximize", n_initial_points=2
        )

        markers = [trace.marker.colorscale for trace in fig.data
                   if trace.marker is not None and trace.marker.colorscale is not None]
        assert markers
        assert all(colorscale == _expanded("Cividis") for colorscale in markers)


# ============================================================================
# Serialization
# ============================================================================

class TestColorscaleRoundTrip:
    @pytest.fixture
    def reporting(self):
        return ReportingConfig(
            enabled=True,
            theme=ReportThemeConfig(
                colorscale="Cividis",
                section_colorscales={"variable_impact": "Plasma"},
            ),
            metrics={"bw": MetricPlotsConfig(plots=[
                PlotConfig(type="heatmap", x_var="nodes", y_var="ppn"),
                PlotConfig(type="heatmap", x_var="nodes", y_var="ppn", colorscale="Hot"),
            ])},
        )

    def test_run_metadata_round_trip(self, reporting, tmp_path):
        data = serialize_reporting_config(reporting)
        restored = ReportGenerator(workdir=tmp_path)._deserialize_reporting_config(data)

        assert restored.theme.colorscale == "Cividis"
        assert restored.theme.section_colorscales == {"variable_impact": "Plasma"}
        plots = restored.metrics["bw"].plots
        assert plots[0].colorscale is None
        assert plots[1].colorscale == "Hot"

    def test_report_config_yaml_round_trip(self, reporting):
        clean = _create_clean_report_config(reporting, scripts=[])
        restored = _parse_reporting_config(yaml.safe_load(yaml.safe_dump(clean)))

        assert clean["theme"]["colorscale"] == "Cividis"
        assert "colorscale" not in clean["metrics"]["bw"]["plots"][0]
        assert restored.theme.colorscale == "Cividis"
        assert restored.theme.section_colorscales == {"variable_impact": "Plasma"}
        assert restored.metrics["bw"].plots[0].colorscale is None
        assert restored.metrics["bw"].plots[1].colorscale == "Hot"

    def test_default_colorscales_are_not_written(self):
        clean = _create_clean_report_config(ReportingConfig(enabled=True), scripts=[])
        theme = clean.get("theme", {})

        assert "colorscale" not in theme
        assert "section_colorscales" not in theme
