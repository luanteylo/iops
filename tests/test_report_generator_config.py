"""Unit tests for ReportGenerator reporting configuration handling."""

import pytest
import json
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
)
from iops.reporting.report_generator import ReportGenerator


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_workdir(tmp_path):
    """Create temporary workdir structure."""
    workdir = tmp_path / "run_001"
    workdir.mkdir(parents=True)
    return workdir


@pytest.fixture
def sample_metadata() -> Dict[str, Any]:
    """Create sample run metadata without reporting config (legacy)."""
    return {
        "benchmark": {
            "name": "Test Benchmark",
            "executor": "local",
            "repetitions": 2,
            "cores_expr": None,
        },
        "variables": {
            "nodes": {
                "type": "int",
                "swept": True,
            },
            "block_size": {
                "type": "int",
                "swept": True,
            },
        },
        "output": {
            "type": "csv",
            "path": "/tmp/results.csv",
            "table": None,
        },
        "metrics": ["bandwidth", "latency"],
    }


@pytest.fixture
def metadata_with_reporting() -> Dict[str, Any]:
    """Create sample run metadata with reporting config."""
    base = {
        "benchmark": {
            "name": "Test Benchmark",
            "executor": "local",
            "repetitions": 2,
            "cores_expr": None,
        },
        "variables": {
            "nodes": {
                "type": "int",
                "swept": True,
            },
            "block_size": {
                "type": "int",
                "swept": True,
            },
        },
        "output": {
            "type": "csv",
            "path": "/tmp/results.csv",
            "table": None,
        },
        "metrics": ["bandwidth", "latency"],
    }

    # Add reporting config
    base["reporting"] = {
        "enabled": True,
        "output_dir": None,
        "output_filename": "custom_report.html",
        "theme": {
            "style": "plotly_dark",
            "colors": ["#FF0000", "#00FF00"],
            "font_family": "Arial",
        },
        "sections": {
            "test_summary": True,
            "best_results": False,
            "variable_impact": True,
            "parallel_coordinates": True,
            "pareto_frontier": False,
            "bayesian_evolution": True,
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
                        "title": "Bandwidth Plot",
                        "xaxis_label": "Block Size",
                        "yaxis_label": "Bandwidth",
                        "colorscale": "Viridis",
                        "show_error_bars": True,
                        "show_outliers": True,
                        "height": 500,
                        "width": None,
                        "per_variable": False,
                        "include_metric": True,
                    }
                ]
            }
        },
        "default_plots": [
            {
                "type": "bar",
                "x_var": "nodes",
                "y_var": None,
                "z_metric": None,
                "group_by": None,
                "color_by": None,
                "size_by": None,
                "title": None,
                "xaxis_label": None,
                "yaxis_label": None,
                "colorscale": "Viridis",
                "show_error_bars": True,
                "show_outliers": True,
                "height": None,
                "width": None,
                "per_variable": False,
                "include_metric": True,
            }
        ],
    }

    return base


@pytest.fixture
def override_reporting_config() -> ReportingConfig:
    """Create a reporting config to use as override."""
    return ReportingConfig(
        enabled=True,
        output_filename="override_report.html",
        theme=ReportThemeConfig(style="plotly_white", colors=["#0000FF"]),
        sections=SectionConfig(test_summary=False, best_results=True),
        best_results=BestResultsConfig(top_n=3),
    )


# ============================================================================
# Test ReportGenerator Initialization
# ============================================================================

class TestReportGeneratorInit:
    """Test ReportGenerator initialization."""

    def test_init_without_config(self, temp_workdir):
        """Test initialization without report config (will load from metadata)."""
        generator = ReportGenerator(workdir=temp_workdir)

        assert generator.workdir == temp_workdir
        assert generator.metadata_path == temp_workdir / "run_metadata.json"
        assert generator.metadata is None
        assert generator.df is None
        assert generator.report_config is None

    def test_init_with_config_override(self, temp_workdir, override_reporting_config):
        """Test initialization with config override."""
        generator = ReportGenerator(
            workdir=temp_workdir,
            report_config=override_reporting_config,
        )

        assert generator.workdir == temp_workdir
        assert generator.report_config == override_reporting_config
        assert generator.report_config.output_filename == "override_report.html"


# ============================================================================
# Test Metadata Loading
# ============================================================================

class TestLoadMetadata:
    """Test load_metadata method."""

    def test_load_metadata_missing_file(self, temp_workdir):
        """Test loading metadata when file doesn't exist."""
        generator = ReportGenerator(workdir=temp_workdir)

        with pytest.raises(FileNotFoundError) as exc_info:
            generator.load_metadata()

        assert "Metadata file not found" in str(exc_info.value)

    def test_load_metadata_legacy_without_reporting(self, temp_workdir, sample_metadata):
        """Test loading legacy metadata without reporting config."""
        metadata_file = temp_workdir / "run_metadata.json"
        with open(metadata_file, "w") as f:
            json.dump(sample_metadata, f)

        generator = ReportGenerator(workdir=temp_workdir)
        generator.load_metadata()

        assert generator.metadata == sample_metadata
        assert generator.report_config is not None
        # Should create legacy defaults
        assert isinstance(generator.report_config, ReportingConfig)
        assert generator.report_config.enabled is False
        assert generator.report_config.metrics == {}
        assert generator.report_config.default_plots == []

    def test_load_metadata_with_reporting(self, temp_workdir, metadata_with_reporting):
        """Test loading metadata with reporting config."""
        metadata_file = temp_workdir / "run_metadata.json"
        with open(metadata_file, "w") as f:
            json.dump(metadata_with_reporting, f)

        generator = ReportGenerator(workdir=temp_workdir)
        generator.load_metadata()

        assert generator.metadata == metadata_with_reporting
        assert generator.report_config is not None
        assert generator.report_config.enabled is True
        assert generator.report_config.output_filename == "custom_report.html"
        assert generator.report_config.theme.style == "plotly_dark"

    def test_load_metadata_with_override(
        self, temp_workdir, metadata_with_reporting, override_reporting_config
    ):
        """Test that override config takes priority over metadata."""
        metadata_file = temp_workdir / "run_metadata.json"
        with open(metadata_file, "w") as f:
            json.dump(metadata_with_reporting, f)

        generator = ReportGenerator(
            workdir=temp_workdir,
            report_config=override_reporting_config,
        )
        generator.load_metadata()

        # Override should be preserved, not replaced by metadata
        assert generator.report_config == override_reporting_config
        assert generator.report_config.output_filename == "override_report.html"
        assert generator.report_config.theme.style == "plotly_white"


# ============================================================================
# Test Reporting Config Deserialization
# ============================================================================

class TestDeserializeReportingConfig:
    """Test _deserialize_reporting_config method."""

    def test_deserialize_full_config(self, temp_workdir, metadata_with_reporting):
        """Test deserializing complete reporting config."""
        generator = ReportGenerator(workdir=temp_workdir)

        config = generator._deserialize_reporting_config(
            metadata_with_reporting["reporting"]
        )

        assert isinstance(config, ReportingConfig)
        assert config.enabled is True
        assert config.output_filename == "custom_report.html"
        assert config.output_dir is None

        # Theme
        assert config.theme.style == "plotly_dark"
        assert config.theme.colors == ["#FF0000", "#00FF00"]
        assert config.theme.font_family == "Arial"

        # Sections
        assert config.sections.test_summary is True
        assert config.sections.best_results is False
        assert config.sections.variable_impact is True

        # Best results
        assert config.best_results.top_n == 10
        assert config.best_results.show_command is False

        # Plot defaults
        assert config.plot_defaults.height == 600
        assert config.plot_defaults.width == 800
        assert config.plot_defaults.margin == {"l": 50, "r": 50, "t": 50, "b": 50}

        # Metrics
        assert "bandwidth" in config.metrics
        assert len(config.metrics["bandwidth"].plots) == 1

        bandwidth_plot = config.metrics["bandwidth"].plots[0]
        assert bandwidth_plot.type == "line"
        assert bandwidth_plot.x_var == "block_size"
        assert bandwidth_plot.group_by == "nodes"
        assert bandwidth_plot.title == "Bandwidth Plot"

        # Default plots
        assert len(config.default_plots) == 1
        assert config.default_plots[0].type == "bar"
        assert config.default_plots[0].x_var == "nodes"

    def test_deserialize_minimal_config(self, temp_workdir):
        """Test deserializing minimal config with defaults."""
        generator = ReportGenerator(workdir=temp_workdir)

        minimal_data = {
            "enabled": True,
            "output_filename": "report.html",
        }

        config = generator._deserialize_reporting_config(minimal_data)

        assert config.enabled is True
        assert config.output_filename == "report.html"
        # Check defaults
        assert config.theme.style == "plotly_white"
        assert config.sections.test_summary is True
        assert config.best_results.top_n == 5
        assert config.metrics == {}
        assert config.default_plots == []

    def test_deserialize_with_output_dir(self, temp_workdir):
        """Test deserialization converts output_dir to Path."""
        generator = ReportGenerator(workdir=temp_workdir)

        data = {
            "enabled": True,
            "output_dir": "/tmp/reports",
        }

        config = generator._deserialize_reporting_config(data)

        assert config.output_dir == Path("/tmp/reports")

    def test_deserialize_plot_config(self, temp_workdir):
        """Test deserialization of PlotConfig objects."""
        generator = ReportGenerator(workdir=temp_workdir)

        data = {
            "enabled": True,
            "metrics": {
                "bandwidth": {
                    "plots": [
                        {
                            "type": "scatter",
                            "x_var": "nodes",
                            "y_var": "block_size",
                            "color_by": "bandwidth",
                            "colorscale": "Plasma",
                            "height": 400,
                        }
                    ]
                }
            }
        }

        config = generator._deserialize_reporting_config(data)

        plot = config.metrics["bandwidth"].plots[0]
        assert isinstance(plot, PlotConfig)
        assert plot.type == "scatter"
        assert plot.x_var == "nodes"
        assert plot.y_var == "block_size"
        assert plot.color_by == "bandwidth"
        assert plot.colorscale == "Plasma"
        assert plot.height == 400

    def test_deserialize_multiple_metrics(self, temp_workdir):
        """Test deserialization of multiple metric configs."""
        generator = ReportGenerator(workdir=temp_workdir)

        data = {
            "enabled": True,
            "metrics": {
                "bandwidth": {
                    "plots": [{"type": "bar", "x_var": "nodes"}]
                },
                "latency": {
                    "plots": [{"type": "line", "x_var": "block_size"}]
                },
                "iops": {
                    "plots": [
                        {"type": "scatter", "x_var": "nodes"},
                        {"type": "heatmap", "x_var": "nodes", "y_var": "block_size"},
                    ]
                },
            }
        }

        config = generator._deserialize_reporting_config(data)

        assert len(config.metrics) == 3
        assert "bandwidth" in config.metrics
        assert "latency" in config.metrics
        assert "iops" in config.metrics

        assert len(config.metrics["bandwidth"].plots) == 1
        assert len(config.metrics["latency"].plots) == 1
        assert len(config.metrics["iops"].plots) == 2


# ============================================================================
# Test Legacy Defaults Creation
# ============================================================================

class TestCreateLegacyDefaults:
    """Test _create_legacy_defaults method."""

    def test_create_legacy_defaults(self, temp_workdir):
        """Test creation of legacy default config."""
        generator = ReportGenerator(workdir=temp_workdir)
        config = generator._create_legacy_defaults()

        assert isinstance(config, ReportingConfig)
        assert config.enabled is False
        assert config.output_filename == "analysis_report.html"

        # Sections should all be True for backward compatibility
        assert config.sections.test_summary is True
        assert config.sections.best_results is True
        assert config.sections.variable_impact is True
        assert config.sections.parallel_coordinates is True
        assert config.sections.pareto_frontier is True
        assert config.sections.bayesian_evolution is True
        assert config.sections.custom_plots is True

        # Empty metrics and plots trigger legacy plot generation
        assert config.metrics == {}
        assert config.default_plots == []

        # Default theme
        assert config.theme.style == "plotly_white"
        assert config.theme.colors is None

        # Default best_results
        assert config.best_results.top_n == 5
        assert config.best_results.show_command is True

        # Default plot_defaults
        assert config.plot_defaults.height == 500
        assert config.plot_defaults.width is None


# ============================================================================
# Test Config Priority Logic
# ============================================================================

class TestConfigPriority:
    """Test config priority: override > metadata > legacy."""

    def test_priority_override_over_metadata(
        self, temp_workdir, metadata_with_reporting, override_reporting_config
    ):
        """Test that override config takes priority over metadata."""
        metadata_file = temp_workdir / "run_metadata.json"
        with open(metadata_file, "w") as f:
            json.dump(metadata_with_reporting, f)

        generator = ReportGenerator(
            workdir=temp_workdir,
            report_config=override_reporting_config,
        )
        generator.load_metadata()

        # Override should win
        assert generator.report_config.output_filename == "override_report.html"
        assert generator.report_config.theme.style == "plotly_white"
        assert generator.report_config.best_results.top_n == 3

    def test_priority_metadata_over_legacy(self, temp_workdir, metadata_with_reporting):
        """Test that metadata config takes priority over legacy defaults."""
        metadata_file = temp_workdir / "run_metadata.json"
        with open(metadata_file, "w") as f:
            json.dump(metadata_with_reporting, f)

        generator = ReportGenerator(workdir=temp_workdir)
        generator.load_metadata()

        # Metadata should win over legacy
        assert generator.report_config.enabled is True
        assert generator.report_config.output_filename == "custom_report.html"
        assert generator.report_config.theme.style == "plotly_dark"
        assert generator.report_config.sections.best_results is False

    def test_priority_legacy_when_no_metadata(self, temp_workdir, sample_metadata):
        """Test that legacy defaults are used when no reporting in metadata."""
        metadata_file = temp_workdir / "run_metadata.json"
        with open(metadata_file, "w") as f:
            json.dump(sample_metadata, f)

        generator = ReportGenerator(workdir=temp_workdir)
        generator.load_metadata()

        # Legacy defaults should be used
        assert generator.report_config.enabled is False
        assert generator.report_config.output_filename == "analysis_report.html"
        assert generator.report_config.metrics == {}


# ============================================================================
# Test Backward Compatibility
# ============================================================================

class TestBackwardCompatibility:
    """Test backward compatibility with old workdirs."""

    def test_old_workdir_without_reporting_metadata(self, temp_workdir, sample_metadata):
        """Test handling of workdirs created before reporting feature."""
        # Simulate old metadata without 'reporting' key
        metadata_file = temp_workdir / "run_metadata.json"
        with open(metadata_file, "w") as f:
            json.dump(sample_metadata, f)

        generator = ReportGenerator(workdir=temp_workdir)
        generator.load_metadata()

        # Should not crash and should create legacy config
        assert generator.report_config is not None
        assert generator.report_config.enabled is False
        assert generator.report_config.sections.custom_plots is True

    def test_old_workdir_with_null_reporting(self, temp_workdir, sample_metadata):
        """Test handling of metadata with reporting: null."""
        sample_metadata["reporting"] = None
        metadata_file = temp_workdir / "run_metadata.json"
        with open(metadata_file, "w") as f:
            json.dump(sample_metadata, f)

        generator = ReportGenerator(workdir=temp_workdir)
        generator.load_metadata()

        # Should create legacy defaults
        assert generator.report_config is not None
        assert generator.report_config.enabled is False

    def test_new_workdir_with_reporting(self, temp_workdir, metadata_with_reporting):
        """Test handling of new workdirs with full reporting config."""
        metadata_file = temp_workdir / "run_metadata.json"
        with open(metadata_file, "w") as f:
            json.dump(metadata_with_reporting, f)

        generator = ReportGenerator(workdir=temp_workdir)
        generator.load_metadata()

        # Should load from metadata
        assert generator.report_config.enabled is True
        assert generator.report_config.theme.style == "plotly_dark"
        assert "bandwidth" in generator.report_config.metrics


# ============================================================================
# Test Edge Cases
# ============================================================================

class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_deserialize_empty_metrics_dict(self, temp_workdir):
        """Test deserialization with empty metrics."""
        generator = ReportGenerator(workdir=temp_workdir)

        data = {
            "enabled": True,
            "metrics": {},
        }

        config = generator._deserialize_reporting_config(data)
        assert config.metrics == {}

    def test_deserialize_empty_default_plots(self, temp_workdir):
        """Test deserialization with empty default_plots."""
        generator = ReportGenerator(workdir=temp_workdir)

        data = {
            "enabled": True,
            "default_plots": [],
        }

        config = generator._deserialize_reporting_config(data)
        assert config.default_plots == []

    def test_deserialize_missing_optional_fields(self, temp_workdir):
        """Test deserialization with missing optional fields uses defaults."""
        generator = ReportGenerator(workdir=temp_workdir)

        data = {
            "enabled": True,
            # All other fields missing
        }

        config = generator._deserialize_reporting_config(data)

        # Should use all defaults
        assert config.output_filename == "analysis_report.html"
        assert config.theme.style == "plotly_white"
        assert config.sections.test_summary is True
        assert config.best_results.top_n == 5

    def test_deserialize_partial_theme(self, temp_workdir):
        """Test deserialization with partial theme data."""
        generator = ReportGenerator(workdir=temp_workdir)

        data = {
            "enabled": True,
            "theme": {
                "style": "plotly_dark",
                # colors and font_family missing
            }
        }

        config = generator._deserialize_reporting_config(data)

        assert config.theme.style == "plotly_dark"
        assert config.theme.colors is None  # Default
        assert config.theme.font_family == "Segoe UI, sans-serif"  # Default

    def test_deserialize_partial_sections(self, temp_workdir):
        """Test deserialization with partial sections data."""
        generator = ReportGenerator(workdir=temp_workdir)

        data = {
            "enabled": True,
            "sections": {
                "test_summary": False,
                # Other fields missing
            }
        }

        config = generator._deserialize_reporting_config(data)

        assert config.sections.test_summary is False
        assert config.sections.best_results is True  # Default
        assert config.sections.custom_plots is True  # Default

    def test_multiple_initializations(self, temp_workdir, metadata_with_reporting):
        """Test multiple load_metadata calls don't break state."""
        metadata_file = temp_workdir / "run_metadata.json"
        with open(metadata_file, "w") as f:
            json.dump(metadata_with_reporting, f)

        generator = ReportGenerator(workdir=temp_workdir)

        # Load twice
        generator.load_metadata()
        first_config = generator.report_config

        generator.load_metadata()
        second_config = generator.report_config

        # Should produce same config
        assert first_config.enabled == second_config.enabled
        assert first_config.theme.style == second_config.theme.style

    def test_path_types(self, temp_workdir):
        """Test that workdir can be string or Path."""
        # String path
        generator1 = ReportGenerator(workdir=str(temp_workdir))
        assert generator1.workdir == Path(temp_workdir)

        # Path object
        generator2 = ReportGenerator(workdir=temp_workdir)
        assert generator2.workdir == temp_workdir

    def test_deserialize_plot_with_all_none_optional_fields(self, temp_workdir):
        """Test deserializing plot config with many None values."""
        generator = ReportGenerator(workdir=temp_workdir)

        data = {
            "enabled": True,
            "metrics": {
                "bandwidth": {
                    "plots": [
                        {
                            "type": "bar",
                            "x_var": "nodes",
                            "y_var": None,
                            "z_metric": None,
                            "group_by": None,
                            "color_by": None,
                            "size_by": None,
                            "title": None,
                            "xaxis_label": None,
                            "yaxis_label": None,
                        }
                    ]
                }
            }
        }

        config = generator._deserialize_reporting_config(data)
        plot = config.metrics["bandwidth"].plots[0]

        assert plot.type == "bar"
        assert plot.x_var == "nodes"
        assert plot.y_var is None
        assert plot.z_metric is None
        assert plot.group_by is None
