"""Unit tests for IOPS reporting configuration models and parsing."""

import pytest
import yaml
from pathlib import Path
from typing import Dict, Any

from iops.config.models import (
    ReportingConfig,
    ReportThemeConfig,
    PlotConfig,
    MetricPlotsConfig,
    SectionConfig,
    BestResultsConfig,
    PlotDefaultsConfig,
    GenericBenchmarkConfig,
    ConfigValidationError,
)
from iops.config.loader import (
    _parse_reporting_config,
    load_report_config,
    load_generic_config,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def minimal_reporting_data() -> Dict[str, Any]:
    """Minimal reporting config with only required fields."""
    return {
        "enabled": True,
    }


@pytest.fixture
def full_reporting_data() -> Dict[str, Any]:
    """Complete reporting config with all fields specified."""
    return {
        "enabled": True,
        "output_dir": "/tmp/reports",
        "output_filename": "test_report.html",
        "theme": {
            "style": "plotly_dark",
            "colors": ["#FF0000", "#00FF00", "#0000FF"],
            "font_family": "Arial, sans-serif",
        },
        "sections": {
            "test_summary": True,
            "best_results": False,
            "variable_impact": True,
            "parallel_coordinates": False,
            "pareto_frontier": True,
            "bayesian_evolution": False,
            "custom_plots": True,
        },
        "best_results": {
            "top_n": 10,
            "show_command": False,
        },
        "plot_defaults": {
            "height": 600,
            "width": 800,
            "margin": {"l": 50, "r": 50, "t": 50, "b": 50},
        },
        "metrics": {
            "bandwidth": {
                "plots": [
                    {
                        "type": "line",
                        "x_var": "block_size",
                        "group_by": "nodes",
                        "title": "Bandwidth vs Block Size",
                        "xaxis_label": "Block Size (MB)",
                        "yaxis_label": "Bandwidth (MB/s)",
                        "height": 500,
                    },
                    {
                        "type": "bar",
                        "x_var": "nodes",
                        "show_error_bars": True,
                    },
                ]
            },
            "latency": {
                "plots": [
                    {
                        "type": "scatter",
                        "x_var": "block_size",
                        "y_var": "transfer_size",
                        "color_by": "latency",
                        "colorscale": "Plasma",
                    }
                ]
            },
        },
        "default_plots": [
            {
                "type": "heatmap",
                "x_var": "nodes",
                "y_var": "block_size",
                "z_metric": "bandwidth",
            }
        ],
    }


@pytest.fixture
def sample_benchmark_config_with_reporting(tmp_path) -> Dict[str, Any]:
    """Full benchmark config including reporting section."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    return {
        "benchmark": {
            "name": "Test Benchmark",
            "workdir": str(workdir),
            "executor": "local",
            "repetitions": 1,
        },
        "vars": {
            "nodes": {
                "type": "int",
                "sweep": {"mode": "list", "values": [1, 2]},
            }
        },
        "command": {
            "template": "echo test",
        },
        "scripts": [
            {
                "name": "test_script",
                "submit": "bash",
                "script_template": "#!/bin/bash\necho test",
                "parser": {
                    "file": "{{ execution_dir }}/output.txt",
                    "metrics": [{"name": "result", "type": "float"}],
                    "parser_script": "def parse(f):\n    return {'result': 1.0}"
                }
            }
        ],
        "output": {
            "sink": {
                "type": "csv",
                "path": "{{ workdir }}/results.csv",
            }
        },
        "reporting": {
            "enabled": True,
            "output_filename": "custom_report.html",
            "theme": {
                "style": "plotly_white",
            },
        },
    }


# ============================================================================
# Test Dataclass Instantiation
# ============================================================================

class TestDataclassDefaults:
    """Test default values for reporting configuration dataclasses."""

    def test_report_theme_config_defaults(self):
        """Test ReportThemeConfig with default values."""
        theme = ReportThemeConfig()

        assert theme.style == "plotly_white"
        assert theme.colors is None
        assert theme.font_family == "Segoe UI, Tahoma, Geneva, Verdana, sans-serif"

    def test_report_theme_config_custom(self):
        """Test ReportThemeConfig with custom values."""
        theme = ReportThemeConfig(
            style="plotly_dark",
            colors=["#FF0000", "#00FF00"],
            font_family="Arial",
        )

        assert theme.style == "plotly_dark"
        assert theme.colors == ["#FF0000", "#00FF00"]
        assert theme.font_family == "Arial"

    def test_plot_config_defaults(self):
        """Test PlotConfig with default values."""
        plot = PlotConfig(type="bar")

        assert plot.type == "bar"
        assert plot.x_var is None
        assert plot.y_var is None
        assert plot.z_metric is None
        assert plot.group_by is None
        assert plot.color_by is None
        assert plot.size_by is None
        assert plot.title is None
        assert plot.xaxis_label is None
        assert plot.yaxis_label is None
        assert plot.colorscale == "Viridis"
        assert plot.show_error_bars is True
        assert plot.show_outliers is True
        assert plot.height is None
        assert plot.width is None
        assert plot.per_variable is False
        assert plot.include_metric is True

    def test_plot_config_all_fields(self):
        """Test PlotConfig with all fields specified."""
        plot = PlotConfig(
            type="line",
            x_var="nodes",
            y_var="block_size",
            z_metric="bandwidth",
            group_by="ost_num",
            color_by="transfer_size",
            size_by="nodes",
            title="Custom Title",
            xaxis_label="X Label",
            yaxis_label="Y Label",
            colorscale="Plasma",
            show_error_bars=False,
            show_outliers=False,
            height=600,
            width=800,
            per_variable=True,
            include_metric=False,
        )

        assert plot.type == "line"
        assert plot.x_var == "nodes"
        assert plot.y_var == "block_size"
        assert plot.z_metric == "bandwidth"
        assert plot.group_by == "ost_num"
        assert plot.color_by == "transfer_size"
        assert plot.size_by == "nodes"
        assert plot.title == "Custom Title"
        assert plot.xaxis_label == "X Label"
        assert plot.yaxis_label == "Y Label"
        assert plot.colorscale == "Plasma"
        assert plot.show_error_bars is False
        assert plot.show_outliers is False
        assert plot.height == 600
        assert plot.width == 800
        assert plot.per_variable is True
        assert plot.include_metric is False

    def test_metric_plots_config_defaults(self):
        """Test MetricPlotsConfig with default values."""
        metric_plots = MetricPlotsConfig()

        assert metric_plots.plots == []

    def test_metric_plots_config_with_plots(self):
        """Test MetricPlotsConfig with multiple plots."""
        plots = [
            PlotConfig(type="bar", x_var="nodes"),
            PlotConfig(type="line", x_var="block_size"),
        ]
        metric_plots = MetricPlotsConfig(plots=plots)

        assert len(metric_plots.plots) == 2
        assert metric_plots.plots[0].type == "bar"
        assert metric_plots.plots[1].type == "line"

    def test_section_config_defaults(self):
        """Test SectionConfig with default values (all True)."""
        sections = SectionConfig()

        assert sections.test_summary is True
        assert sections.best_results is True
        assert sections.variable_impact is True
        assert sections.parallel_coordinates is True
        assert sections.pareto_frontier is True
        assert sections.bayesian_evolution is True
        assert sections.custom_plots is True

    def test_section_config_custom(self):
        """Test SectionConfig with custom values."""
        sections = SectionConfig(
            test_summary=False,
            best_results=True,
            variable_impact=False,
            parallel_coordinates=False,
            pareto_frontier=True,
            bayesian_evolution=False,
            custom_plots=True,
        )

        assert sections.test_summary is False
        assert sections.best_results is True
        assert sections.variable_impact is False

    def test_best_results_config_defaults(self):
        """Test BestResultsConfig with default values."""
        best = BestResultsConfig()

        assert best.top_n == 5
        assert best.show_command is True

    def test_best_results_config_custom(self):
        """Test BestResultsConfig with custom values."""
        best = BestResultsConfig(top_n=10, show_command=False)

        assert best.top_n == 10
        assert best.show_command is False

    def test_plot_defaults_config_defaults(self):
        """Test PlotDefaultsConfig with default values."""
        defaults = PlotDefaultsConfig()

        assert defaults.height == 500
        assert defaults.width is None
        assert defaults.margin is None

    def test_plot_defaults_config_custom(self):
        """Test PlotDefaultsConfig with custom values."""
        defaults = PlotDefaultsConfig(
            height=600,
            width=800,
            margin={"l": 50, "r": 50, "t": 50, "b": 50},
        )

        assert defaults.height == 600
        assert defaults.width == 800
        assert defaults.margin == {"l": 50, "r": 50, "t": 50, "b": 50}

    def test_reporting_config_defaults(self):
        """Test ReportingConfig with default values."""
        config = ReportingConfig()

        assert config.enabled is False
        assert config.output_dir is None
        assert config.output_filename == "analysis_report.html"
        assert isinstance(config.theme, ReportThemeConfig)
        assert isinstance(config.sections, SectionConfig)
        assert isinstance(config.best_results, BestResultsConfig)
        assert config.metrics == {}
        assert config.default_plots == []
        assert isinstance(config.plot_defaults, PlotDefaultsConfig)

    def test_reporting_config_custom(self):
        """Test ReportingConfig with custom values."""
        theme = ReportThemeConfig(style="plotly_dark")
        sections = SectionConfig(test_summary=False)
        best = BestResultsConfig(top_n=10)

        config = ReportingConfig(
            enabled=True,
            output_dir=Path("/tmp/reports"),
            output_filename="custom.html",
            theme=theme,
            sections=sections,
            best_results=best,
        )

        assert config.enabled is True
        assert config.output_dir == Path("/tmp/reports")
        assert config.output_filename == "custom.html"
        assert config.theme.style == "plotly_dark"
        assert config.sections.test_summary is False
        assert config.best_results.top_n == 10


# ============================================================================
# Test Configuration Parsing
# ============================================================================

class TestParseReportingConfig:
    """Test _parse_reporting_config function."""

    def test_parse_minimal_config(self, minimal_reporting_data):
        """Test parsing minimal configuration with defaults."""
        config = _parse_reporting_config(minimal_reporting_data)

        assert config.enabled is True
        assert config.output_filename == "analysis_report.html"
        assert config.output_dir is None

        # Check defaults
        assert config.theme.style == "plotly_white"
        assert config.sections.test_summary is True
        assert config.best_results.top_n == 5
        assert config.plot_defaults.height == 500
        assert config.metrics == {}
        assert config.default_plots == []

    def test_parse_full_config(self, full_reporting_data):
        """Test parsing complete configuration with all fields."""
        config = _parse_reporting_config(full_reporting_data)

        # Top-level fields
        assert config.enabled is True
        assert config.output_filename == "test_report.html"
        assert config.output_dir == Path("/tmp/reports")

        # Theme
        assert config.theme.style == "plotly_dark"
        assert config.theme.colors == ["#FF0000", "#00FF00", "#0000FF"]
        assert config.theme.font_family == "Arial, sans-serif"

        # Sections
        assert config.sections.test_summary is True
        assert config.sections.best_results is False
        assert config.sections.variable_impact is True
        assert config.sections.parallel_coordinates is False

        # Best results
        assert config.best_results.top_n == 10
        assert config.best_results.show_command is False

        # Plot defaults
        assert config.plot_defaults.height == 600
        assert config.plot_defaults.width == 800
        assert config.plot_defaults.margin == {"l": 50, "r": 50, "t": 50, "b": 50}

        # Metrics
        assert "bandwidth" in config.metrics
        assert len(config.metrics["bandwidth"].plots) == 2

        # First bandwidth plot
        plot1 = config.metrics["bandwidth"].plots[0]
        assert plot1.type == "line"
        assert plot1.x_var == "block_size"
        assert plot1.group_by == "nodes"
        assert plot1.title == "Bandwidth vs Block Size"
        assert plot1.xaxis_label == "Block Size (MB)"
        assert plot1.yaxis_label == "Bandwidth (MB/s)"
        assert plot1.height == 500

        # Second bandwidth plot
        plot2 = config.metrics["bandwidth"].plots[1]
        assert plot2.type == "bar"
        assert plot2.x_var == "nodes"
        assert plot2.show_error_bars is True

        # Latency metric
        assert "latency" in config.metrics
        latency_plot = config.metrics["latency"].plots[0]
        assert latency_plot.type == "scatter"
        assert latency_plot.x_var == "block_size"
        assert latency_plot.y_var == "transfer_size"
        assert latency_plot.color_by == "latency"
        assert latency_plot.colorscale == "Plasma"

        # Default plots
        assert len(config.default_plots) == 1
        default_plot = config.default_plots[0]
        assert default_plot.type == "heatmap"
        assert default_plot.x_var == "nodes"
        assert default_plot.y_var == "block_size"
        assert default_plot.z_metric == "bandwidth"

    def test_parse_with_null_theme(self):
        """Test parsing when theme is explicitly None."""
        data = {"enabled": True, "theme": None}
        config = _parse_reporting_config(data)

        # Should use default theme
        assert config.theme.style == "plotly_white"
        assert config.theme.colors is None

    def test_parse_with_null_sections(self):
        """Test parsing when sections is explicitly None."""
        data = {"enabled": True, "sections": None}
        config = _parse_reporting_config(data)

        # Should use default sections (all True)
        assert config.sections.test_summary is True
        assert config.sections.best_results is True

    def test_parse_with_partial_theme(self):
        """Test parsing theme with only some fields specified."""
        data = {
            "enabled": True,
            "theme": {
                "style": "plotly_dark",
                # colors and font_family not specified
            }
        }
        config = _parse_reporting_config(data)

        assert config.theme.style == "plotly_dark"
        assert config.theme.colors is None  # Default
        assert config.theme.font_family == "Segoe UI, Tahoma, Geneva, Verdana, sans-serif"  # Default

    def test_parse_with_partial_sections(self):
        """Test parsing sections with only some fields specified."""
        data = {
            "enabled": True,
            "sections": {
                "test_summary": False,
                "custom_plots": False,
                # Other fields not specified
            }
        }
        config = _parse_reporting_config(data)

        assert config.sections.test_summary is False
        assert config.sections.custom_plots is False
        assert config.sections.best_results is True  # Default
        assert config.sections.variable_impact is True  # Default

    def test_parse_metrics_with_no_plots(self):
        """Test parsing metric config with missing plots key."""
        data = {
            "enabled": True,
            "metrics": {
                "bandwidth": {},  # No 'plots' key
                "latency": None,  # Explicitly None
            }
        }
        config = _parse_reporting_config(data)

        # Both should be skipped/empty
        assert "bandwidth" not in config.metrics
        assert "latency" not in config.metrics

    def test_parse_plot_config_defaults(self):
        """Test that plot configs use correct defaults for optional fields."""
        data = {
            "enabled": True,
            "metrics": {
                "bandwidth": {
                    "plots": [
                        {
                            "type": "bar",
                            "x_var": "nodes",
                            # All other fields omitted
                        }
                    ]
                }
            }
        }
        config = _parse_reporting_config(data)

        plot = config.metrics["bandwidth"].plots[0]
        assert plot.type == "bar"
        assert plot.x_var == "nodes"
        assert plot.colorscale == "Viridis"  # Default
        assert plot.show_error_bars is True  # Default
        assert plot.show_outliers is True  # Default
        assert plot.per_variable is False  # Default
        assert plot.include_metric is True  # Default

    def test_parse_empty_metrics_dict(self):
        """Test parsing with empty metrics dictionary."""
        data = {"enabled": True, "metrics": {}}
        config = _parse_reporting_config(data)

        assert config.metrics == {}

    def test_parse_empty_default_plots(self):
        """Test parsing with empty default_plots list."""
        data = {"enabled": True, "default_plots": []}
        config = _parse_reporting_config(data)

        assert config.default_plots == []


# ============================================================================
# Test Standalone Report Config Loading
# ============================================================================

class TestLoadReportConfig:
    """Test load_report_config function."""

    def test_load_valid_report_config(self, tmp_path, full_reporting_data):
        """Test loading a valid standalone report configuration file."""
        config_file = tmp_path / "report_config.yaml"

        # Wrap in 'reporting' key as required
        yaml_data = {"reporting": full_reporting_data}

        with open(config_file, "w") as f:
            yaml.dump(yaml_data, f)

        config = load_report_config(config_file)

        assert config.enabled is True
        assert config.output_filename == "test_report.html"
        assert config.theme.style == "plotly_dark"
        assert len(config.metrics["bandwidth"].plots) == 2

    def test_load_minimal_report_config(self, tmp_path):
        """Test loading minimal report config with defaults."""
        config_file = tmp_path / "minimal_report.yaml"

        yaml_data = {
            "reporting": {
                "enabled": True,
            }
        }

        with open(config_file, "w") as f:
            yaml.dump(yaml_data, f)

        config = load_report_config(config_file)

        assert config.enabled is True
        assert config.output_filename == "analysis_report.html"
        assert config.theme.style == "plotly_white"

    def test_load_report_config_missing_reporting_section(self, tmp_path):
        """Test that missing 'reporting' section raises error."""
        config_file = tmp_path / "invalid.yaml"

        # No 'reporting' key
        yaml_data = {
            "enabled": True,
            "theme": {"style": "plotly_white"},
        }

        with open(config_file, "w") as f:
            yaml.dump(yaml_data, f)

        with pytest.raises(ConfigValidationError) as exc_info:
            load_report_config(config_file)

        assert "must have 'reporting' section" in str(exc_info.value)

    def test_load_report_config_nonexistent_file(self, tmp_path):
        """Test loading from non-existent file raises error."""
        config_file = tmp_path / "nonexistent.yaml"

        with pytest.raises(FileNotFoundError):
            load_report_config(config_file)


# ============================================================================
# Test Integration with GenericBenchmarkConfig
# ============================================================================

class TestReportingInGenericConfig:
    """Test reporting config integration with full benchmark config."""

    def test_load_benchmark_config_with_reporting(
        self, tmp_path, sample_benchmark_config_with_reporting
    ):
        """Test loading benchmark config that includes reporting section."""
        config_file = tmp_path / "benchmark_config.yaml"

        with open(config_file, "w") as f:
            yaml.dump(sample_benchmark_config_with_reporting, f)

        import logging
        logger = logging.getLogger("test")
        config = load_generic_config(config_file, logger)

        assert isinstance(config, GenericBenchmarkConfig)
        assert config.reporting is not None
        assert isinstance(config.reporting, ReportingConfig)
        assert config.reporting.enabled is True
        assert config.reporting.output_filename == "custom_report.html"
        assert config.reporting.theme.style == "plotly_white"

    def test_load_benchmark_config_without_reporting(self, tmp_path, sample_config_dict):
        """Test loading benchmark config without reporting section."""
        config_file = tmp_path / "benchmark_no_reporting.yaml"

        # sample_config_dict from conftest doesn't have reporting
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        import logging
        logger = logging.getLogger("test")
        config = load_generic_config(config_file, logger)

        assert isinstance(config, GenericBenchmarkConfig)
        assert config.reporting is None

    def test_benchmark_config_with_full_reporting(self, tmp_path, full_reporting_data):
        """Test benchmark config with comprehensive reporting configuration."""
        workdir = tmp_path / "workdir"
        workdir.mkdir()

        config_dict = {
            "benchmark": {
                "name": "Full Report Test",
                "workdir": str(workdir),
                "executor": "local",
                "repetitions": 1,
            },
            "vars": {
                "nodes": {
                    "type": "int",
                    "sweep": {"mode": "list", "values": [1, 2, 4]},
                }
            },
            "command": {
                "template": "echo test",
            },
            "scripts": [
                {
                    "name": "test_script",
                    "submit": "bash",
                    "script_template": "#!/bin/bash\necho test",
                    "parser": {
                        "file": "{{ execution_dir }}/output.txt",
                        "metrics": [{"name": "bandwidth", "type": "float"}],
                        "parser_script": "def parse(f):\n    return {'bandwidth': 1.0}"
                    }
                }
            ],
            "output": {
                "sink": {
                    "type": "csv",
                    "path": "{{ workdir }}/results.csv",
                }
            },
            "reporting": full_reporting_data,
        }

        config_file = tmp_path / "full_benchmark.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_dict, f)

        import logging
        logger = logging.getLogger("test")
        config = load_generic_config(config_file, logger)

        # Verify reporting config was parsed correctly
        assert config.reporting.enabled is True
        assert config.reporting.theme.style == "plotly_dark"
        assert len(config.reporting.theme.colors) == 3
        assert config.reporting.sections.best_results is False
        assert config.reporting.best_results.top_n == 10
        assert "bandwidth" in config.reporting.metrics
        assert "latency" in config.reporting.metrics
        assert len(config.reporting.default_plots) == 1


# ============================================================================
# Test Edge Cases
# ============================================================================

class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_parse_with_disabled_reporting(self):
        """Test parsing config with reporting disabled."""
        data = {
            "enabled": False,
            "metrics": {
                "bandwidth": {
                    "plots": [{"type": "bar", "x_var": "nodes"}]
                }
            }
        }
        config = _parse_reporting_config(data)

        assert config.enabled is False
        # Metrics should still be parsed even if disabled
        assert "bandwidth" in config.metrics

    def test_plot_types_are_literal(self):
        """Test that PlotConfig enforces literal plot types."""
        # This tests the type hint, which is validated by type checkers,
        # not at runtime. Here we just verify valid types work.
        valid_types = ["line", "bar", "scatter", "box", "violin", "heatmap", "surface_3d", "parallel_coordinates"]

        for plot_type in valid_types:
            plot = PlotConfig(type=plot_type)
            assert plot.type == plot_type

    def test_output_dir_path_expansion(self, tmp_path):
        """Test that output_dir is properly converted to Path."""
        data = {
            "enabled": True,
            "output_dir": str(tmp_path / "reports"),
        }
        config = _parse_reporting_config(data)

        assert isinstance(config.output_dir, Path)
        assert config.output_dir == tmp_path / "reports"

    def test_null_metrics_dict(self):
        """Test handling of None for metrics dict."""
        data = {
            "enabled": True,
            "metrics": None,
        }
        config = _parse_reporting_config(data)

        assert config.metrics == {}

    def test_null_default_plots(self):
        """Test handling of None for default_plots."""
        data = {
            "enabled": True,
            "default_plots": None,
        }
        config = _parse_reporting_config(data)

        assert config.default_plots == []

    def test_parse_complex_nested_structure(self):
        """Test parsing deeply nested configuration structure."""
        data = {
            "enabled": True,
            "theme": {
                "style": "plotly",
                "colors": ["#FF0000"],
                "font_family": "Courier",
            },
            "metrics": {
                "metric1": {
                    "plots": [
                        {
                            "type": "line",
                            "x_var": "var1",
                            "group_by": "var2",
                            "height": 400,
                        }
                    ]
                },
                "metric2": {
                    "plots": [
                        {
                            "type": "heatmap",
                            "x_var": "var1",
                            "y_var": "var2",
                            "colorscale": "Jet",
                        }
                    ]
                },
            },
            "default_plots": [
                {"type": "bar", "x_var": "var1"},
                {"type": "scatter", "x_var": "var1", "y_var": "var2"},
            ],
        }

        config = _parse_reporting_config(data)

        assert config.theme.style == "plotly"
        assert len(config.metrics) == 2
        assert len(config.default_plots) == 2
        assert config.metrics["metric1"].plots[0].group_by == "var2"
        assert config.metrics["metric2"].plots[0].colorscale == "Jet"
