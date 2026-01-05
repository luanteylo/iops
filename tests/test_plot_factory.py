"""Unit tests for IOPS plot factory and plot generation."""

import pytest
import pandas as pd
import plotly.graph_objects as go
from unittest.mock import Mock, patch

from iops.config.models import PlotConfig, ReportThemeConfig
from iops.reporting.plots import (
    BasePlot,
    register_plot,
    create_plot,
    get_available_plot_types,
    BarPlot,
    LinePlot,
    ScatterPlot,
    HeatmapPlot,
    ExecutionScatterPlot,
    CoverageHeatmapPlot,
    _PLOT_REGISTRY,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_df():
    """Create sample DataFrame for plot testing."""
    return pd.DataFrame({
        'vars.nodes': [1, 1, 2, 2, 4, 4, 1, 1, 2, 2, 4, 4],
        'vars.block_size': [4, 4, 4, 4, 4, 4, 8, 8, 8, 8, 8, 8],
        'vars.transfer_size': [1, 1, 2, 2, 2, 2, 2, 2, 4, 4, 4, 4],
        'metrics.bandwidth': [100, 105, 150, 155, 200, 210, 120, 125, 180, 185, 240, 250],
        'metrics.latency': [10, 9.5, 7, 6.8, 5, 4.9, 9, 8.8, 6.5, 6.3, 4.5, 4.3],
        'metrics.iops': [1000, 1050, 1500, 1550, 2000, 2100, 1200, 1250, 1800, 1850, 2400, 2500],
    })


@pytest.fixture
def default_theme():
    """Create default theme configuration."""
    return ReportThemeConfig()


@pytest.fixture
def custom_theme():
    """Create custom theme configuration."""
    return ReportThemeConfig(
        style="plotly_dark",
        colors=["#FF0000", "#00FF00", "#0000FF"],
        font_family="Arial, sans-serif",
    )


@pytest.fixture
def var_column_fn():
    """Function to get variable column name."""
    return lambda var: f"vars.{var}"


@pytest.fixture
def metric_column_fn():
    """Function to get metric column name."""
    return lambda metric: f"metrics.{metric}"


@pytest.fixture
def plot_kwargs(sample_df, default_theme, var_column_fn, metric_column_fn):
    """Common kwargs for plot creation."""
    return {
        "df": sample_df,
        "metric": "bandwidth",
        "theme": default_theme,
        "var_column_fn": var_column_fn,
        "metric_column_fn": metric_column_fn,
    }


# ============================================================================
# Test Registry Pattern
# ============================================================================

class TestPlotRegistry:
    """Test plot registry pattern and factory function."""

    def test_register_plot_decorator(self):
        """Test that @register_plot decorator registers plot classes."""
        # Verify that built-in plots are registered
        assert "bar" in _PLOT_REGISTRY
        assert "line" in _PLOT_REGISTRY
        assert "scatter" in _PLOT_REGISTRY
        assert "heatmap" in _PLOT_REGISTRY

        assert _PLOT_REGISTRY["bar"] == BarPlot
        assert _PLOT_REGISTRY["line"] == LinePlot
        assert _PLOT_REGISTRY["scatter"] == ScatterPlot
        assert _PLOT_REGISTRY["heatmap"] == HeatmapPlot

    def test_create_plot_bar(self, plot_kwargs):
        """Test creating a bar plot via factory."""
        plot_config = PlotConfig(type="bar", x_var="nodes")
        plot = create_plot("bar", plot_config=plot_config, **plot_kwargs)

        assert isinstance(plot, BarPlot)
        assert isinstance(plot, BasePlot)
        assert plot.metric == "bandwidth"

    def test_create_plot_line(self, plot_kwargs):
        """Test creating a line plot via factory."""
        plot_config = PlotConfig(type="line", x_var="block_size")
        plot = create_plot("line", plot_config=plot_config, **plot_kwargs)

        assert isinstance(plot, LinePlot)
        assert plot.metric == "bandwidth"

    def test_create_plot_scatter(self, plot_kwargs):
        """Test creating a scatter plot via factory."""
        plot_config = PlotConfig(type="scatter", x_var="nodes", y_var="block_size")
        plot = create_plot("scatter", plot_config=plot_config, **plot_kwargs)

        assert isinstance(plot, ScatterPlot)

    def test_create_plot_heatmap(self, plot_kwargs):
        """Test creating a heatmap via factory."""
        plot_config = PlotConfig(type="heatmap", x_var="nodes", y_var="block_size")
        plot = create_plot("heatmap", plot_config=plot_config, **plot_kwargs)

        assert isinstance(plot, HeatmapPlot)

    def test_create_plot_invalid_type(self, plot_kwargs):
        """Test that invalid plot type raises ValueError."""
        plot_config = PlotConfig(type="invalid_type")

        with pytest.raises(ValueError) as exc_info:
            create_plot("invalid_type", plot_config=plot_config, **plot_kwargs)

        error_msg = str(exc_info.value)
        assert "Unknown plot type: 'invalid_type'" in error_msg
        assert "Available types:" in error_msg

    def test_get_available_plot_types(self):
        """Test get_available_plot_types returns sorted list."""
        available = get_available_plot_types()

        assert isinstance(available, list)
        assert len(available) >= 4  # At minimum: bar, line, scatter, heatmap
        assert "bar" in available
        assert "line" in available
        assert "scatter" in available
        assert "heatmap" in available

        # Verify it's sorted
        assert available == sorted(available)

    def test_custom_plot_registration(self):
        """Test registering a custom plot type."""
        @register_plot("custom_test")
        class CustomTestPlot(BasePlot):
            def generate(self):
                return go.Figure()

        assert "custom_test" in _PLOT_REGISTRY
        assert _PLOT_REGISTRY["custom_test"] == CustomTestPlot

        # Clean up
        del _PLOT_REGISTRY["custom_test"]


# ============================================================================
# Test Base Plot Class
# ============================================================================

class TestBasePlot:
    """Test BasePlot abstract base class functionality."""

    def test_base_plot_initialization(self, plot_kwargs):
        """Test BasePlot initialization with all parameters."""
        plot_config = PlotConfig(type="bar", x_var="nodes")

        # Can't instantiate abstract class, use concrete BarPlot
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        assert plot.df is plot_kwargs["df"]
        assert plot.metric == "bandwidth"
        assert plot.config == plot_config
        assert plot.theme == plot_kwargs["theme"]
        assert plot._get_var_column("nodes") == "vars.nodes"
        assert plot._get_metric_column("bandwidth") == "metrics.bandwidth"

    def test_apply_theme_default(self, plot_kwargs):
        """Test _apply_theme with default theme."""
        plot_config = PlotConfig(type="bar", x_var="nodes")
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        fig = go.Figure()
        themed_fig = plot._apply_theme(fig)

        # Template is set (Plotly expands template name to full object)
        assert themed_fig.layout.template is not None
        assert themed_fig.layout.font.family == "Segoe UI, Tahoma, Geneva, Verdana, sans-serif"

    def test_apply_theme_custom(self, plot_kwargs, custom_theme):
        """Test _apply_theme with custom theme."""
        plot_kwargs["theme"] = custom_theme
        plot_config = PlotConfig(type="bar", x_var="nodes", height=600, width=800)
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        fig = go.Figure()
        themed_fig = plot._apply_theme(fig)

        assert themed_fig.layout.template is not None
        assert themed_fig.layout.font.family == "Arial, sans-serif"
        assert themed_fig.layout.height == 600
        assert themed_fig.layout.width == 800
        assert list(themed_fig.layout.colorway) == ["#FF0000", "#00FF00", "#0000FF"]

    def test_get_title_custom(self, plot_kwargs):
        """Test _get_title with custom title."""
        plot_config = PlotConfig(type="bar", x_var="nodes", title="Custom Title")
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        assert plot._get_title("Default Title") == "Custom Title"

    def test_get_title_default(self, plot_kwargs):
        """Test _get_title with no custom title."""
        plot_config = PlotConfig(type="bar", x_var="nodes")
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        assert plot._get_title("Default Title") == "Default Title"

    def test_get_axis_labels_custom(self, plot_kwargs):
        """Test custom axis labels."""
        plot_config = PlotConfig(
            type="bar",
            x_var="nodes",
            xaxis_label="Number of Nodes",
            yaxis_label="Bandwidth (MB/s)",
        )
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        assert plot._get_xaxis_label("nodes") == "Number of Nodes"
        assert plot._get_yaxis_label("bandwidth") == "Bandwidth (MB/s)"

    def test_get_axis_labels_default(self, plot_kwargs):
        """Test default axis labels."""
        plot_config = PlotConfig(type="bar", x_var="nodes")
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        assert plot._get_xaxis_label("nodes") == "nodes"
        assert plot._get_yaxis_label("bandwidth") == "bandwidth"


# ============================================================================
# Test BarPlot
# ============================================================================

class TestBarPlot:
    """Test BarPlot implementation."""

    def test_bar_plot_generation(self, plot_kwargs):
        """Test basic bar plot generation."""
        plot_config = PlotConfig(type="bar", x_var="nodes")
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert isinstance(fig.data[0], go.Bar)

        # Check data aggregation (mean values)
        bar_trace = fig.data[0]
        assert len(bar_trace.x) == 3  # 3 unique node values: 1, 2, 4

    def test_bar_plot_with_error_bars(self, plot_kwargs):
        """Test bar plot with error bars enabled."""
        plot_config = PlotConfig(type="bar", x_var="nodes", show_error_bars=True)
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()
        bar_trace = fig.data[0]

        assert bar_trace.error_y is not None
        assert bar_trace.error_y['type'] == 'data'

    def test_bar_plot_without_error_bars(self, plot_kwargs):
        """Test bar plot with error bars disabled."""
        plot_config = PlotConfig(type="bar", x_var="nodes", show_error_bars=False)
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()
        bar_trace = fig.data[0]

        # When error bars are disabled, error_y will be None (passed to constructor)
        # Plotly returns empty ErrorY object, check there's no array data
        if bar_trace.error_y is not None:
            # Should have no array data
            assert not hasattr(bar_trace.error_y, 'array') or bar_trace.error_y.array is None

    def test_bar_plot_missing_x_var(self, plot_kwargs):
        """Test that BarPlot raises error when x_var is missing."""
        plot_config = PlotConfig(type="bar")  # No x_var
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        with pytest.raises(ValueError) as exc_info:
            plot.generate()

        assert "BarPlot requires x_var" in str(exc_info.value)

    def test_bar_plot_custom_labels(self, plot_kwargs):
        """Test bar plot with custom labels."""
        plot_config = PlotConfig(
            type="bar",
            x_var="nodes",
            title="Bandwidth by Node Count",
            xaxis_label="Nodes",
            yaxis_label="Bandwidth (MB/s)",
        )
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        assert fig.layout.title.text == "Bandwidth by Node Count"
        assert fig.layout.xaxis.title.text == "Nodes"
        assert fig.layout.yaxis.title.text == "Bandwidth (MB/s)"

    def test_bar_plot_data_aggregation(self, plot_kwargs):
        """Test that bar plot correctly aggregates data by mean."""
        plot_config = PlotConfig(type="bar", x_var="nodes")
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()
        bar_trace = fig.data[0]

        # For nodes=1: (100, 105, 120, 125) -> mean ~ 112.5
        # For nodes=2: (150, 155, 180, 185) -> mean ~ 167.5
        # For nodes=4: (200, 210, 240, 250) -> mean ~ 225
        y_values = list(bar_trace.y)
        assert len(y_values) == 3
        assert y_values[0] == pytest.approx(112.5, abs=0.1)
        assert y_values[1] == pytest.approx(167.5, abs=0.1)
        assert y_values[2] == pytest.approx(225.0, abs=0.1)


# ============================================================================
# Test LinePlot
# ============================================================================

class TestLinePlot:
    """Test LinePlot implementation."""

    def test_line_plot_generation_no_grouping(self, plot_kwargs):
        """Test line plot without grouping."""
        plot_config = PlotConfig(type="line", x_var="block_size")
        plot = LinePlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert isinstance(fig.data[0], go.Scatter)
        assert fig.data[0].mode == 'lines+markers'

    def test_line_plot_with_grouping(self, plot_kwargs):
        """Test line plot with group_by parameter."""
        plot_config = PlotConfig(type="line", x_var="block_size", group_by="nodes")
        plot = LinePlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        # Should have one trace per node value (1, 2, 4) = 3 traces
        assert len(fig.data) == 3
        for trace in fig.data:
            assert isinstance(trace, go.Scatter)
            assert trace.mode == 'lines+markers'

        # Check trace names
        trace_names = [trace.name for trace in fig.data]
        assert "nodes=1" in trace_names
        assert "nodes=2" in trace_names
        assert "nodes=4" in trace_names

    def test_line_plot_missing_x_var(self, plot_kwargs):
        """Test that LinePlot raises error when x_var is missing."""
        plot_config = PlotConfig(type="line")  # No x_var
        plot = LinePlot(plot_config=plot_config, **plot_kwargs)

        with pytest.raises(ValueError) as exc_info:
            plot.generate()

        assert "LinePlot requires x_var" in str(exc_info.value)

    def test_line_plot_title_with_grouping(self, plot_kwargs):
        """Test line plot title includes grouping info."""
        plot_config = PlotConfig(type="line", x_var="block_size", group_by="nodes")
        plot = LinePlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        assert "grouped by nodes" in fig.layout.title.text

    def test_line_plot_title_without_grouping(self, plot_kwargs):
        """Test line plot title without grouping info."""
        plot_config = PlotConfig(type="line", x_var="block_size")
        plot = LinePlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        assert "grouped by" not in fig.layout.title.text
        assert "bandwidth vs block_size" in fig.layout.title.text

    def test_line_plot_data_sorted(self, plot_kwargs):
        """Test that line plot data is sorted by x variable."""
        plot_config = PlotConfig(type="line", x_var="block_size")
        plot = LinePlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()
        trace = fig.data[0]

        # X values should be sorted: 4, 8
        x_values = [str(x) for x in trace.x]
        assert x_values == ['4', '8']


# ============================================================================
# Test ScatterPlot
# ============================================================================

class TestScatterPlot:
    """Test ScatterPlot implementation."""

    def test_scatter_plot_generation(self, plot_kwargs):
        """Test basic scatter plot generation."""
        plot_config = PlotConfig(type="scatter", x_var="nodes", y_var="block_size")
        plot = ScatterPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert isinstance(fig.data[0], go.Scatter)
        assert fig.data[0].mode == 'markers'

    def test_scatter_plot_with_color_mapping(self, plot_kwargs):
        """Test scatter plot with color_by parameter."""
        plot_config = PlotConfig(
            type="scatter",
            x_var="nodes",
            y_var="block_size",
            color_by="bandwidth",
        )
        plot = ScatterPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()
        scatter_trace = fig.data[0]

        # Plotly expands colorscale names to tuples, so check it exists
        assert scatter_trace.marker.colorscale is not None
        assert scatter_trace.marker.showscale is True
        assert scatter_trace.marker.colorbar.title.text == "bandwidth"

    def test_scatter_plot_custom_colorscale(self, plot_kwargs):
        """Test scatter plot with custom colorscale."""
        plot_config = PlotConfig(
            type="scatter",
            x_var="nodes",
            y_var="block_size",
            colorscale="Plasma",
        )
        plot = ScatterPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()
        scatter_trace = fig.data[0]

        # Plotly may expand colorscale names to tuples
        assert scatter_trace.marker.colorscale is not None

    def test_scatter_plot_missing_x_var(self, plot_kwargs):
        """Test that ScatterPlot raises error when x_var is missing."""
        plot_config = PlotConfig(type="scatter", y_var="block_size")  # No x_var
        plot = ScatterPlot(plot_config=plot_config, **plot_kwargs)

        with pytest.raises(ValueError) as exc_info:
            plot.generate()

        assert "ScatterPlot requires x_var" in str(exc_info.value)

    def test_scatter_plot_metric_vs_variable(self, plot_kwargs):
        """Test scatter plot of metric vs variable (no y_var)."""
        plot_config = PlotConfig(type="scatter", x_var="nodes")
        plot = ScatterPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        # Should plot metric (bandwidth) on y-axis
        assert "bandwidth" in fig.layout.yaxis.title.text

    def test_scatter_plot_two_variables(self, plot_kwargs):
        """Test scatter plot of two variables."""
        plot_config = PlotConfig(type="scatter", x_var="nodes", y_var="block_size")
        plot = ScatterPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        assert "nodes" in fig.layout.xaxis.title.text
        assert "block_size" in fig.layout.yaxis.title.text

    def test_scatter_plot_metric_in_y_var(self, plot_kwargs):
        """Test scatter plot with metric in y_var."""
        plot_config = PlotConfig(type="scatter", x_var="nodes", y_var="bandwidth")
        plot = ScatterPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        # Should plot bandwidth metric on y-axis
        assert "bandwidth" in fig.layout.yaxis.title.text
        assert isinstance(fig.data[0], go.Scatter)

    def test_scatter_plot_metric_in_color_by(self, plot_kwargs):
        """Test scatter plot with metric in color_by (variable plot)."""
        plot_config = PlotConfig(
            type="scatter",
            x_var="nodes",
            y_var="block_size",
            color_by="latency"
        )
        plot = ScatterPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        scatter_trace = fig.data[0]
        # Verify colorbar shows the metric name
        assert scatter_trace.marker.colorbar.title.text == "latency"

    def test_scatter_plot_variable_in_color_by(self, plot_kwargs):
        """Test scatter plot with variable in color_by."""
        plot_config = PlotConfig(
            type="scatter",
            x_var="nodes",
            color_by="transfer_size"
        )
        plot = ScatterPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        scatter_trace = fig.data[0]
        # Verify colorbar shows the variable name
        assert scatter_trace.marker.colorbar.title.text == "transfer_size"


# ============================================================================
# Test HeatmapPlot
# ============================================================================

class TestHeatmapPlot:
    """Test HeatmapPlot implementation."""

    def test_heatmap_plot_generation(self, plot_kwargs):
        """Test basic heatmap generation."""
        plot_config = PlotConfig(type="heatmap", x_var="block_size", y_var="nodes")
        plot = HeatmapPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert isinstance(fig.data[0], go.Heatmap)

    def test_heatmap_missing_x_var(self, plot_kwargs):
        """Test that HeatmapPlot raises error when x_var is missing."""
        plot_config = PlotConfig(type="heatmap", y_var="nodes")  # No x_var
        plot = HeatmapPlot(plot_config=plot_config, **plot_kwargs)

        with pytest.raises(ValueError) as exc_info:
            plot.generate()

        assert "HeatmapPlot requires both x_var and y_var" in str(exc_info.value)

    def test_heatmap_missing_y_var(self, plot_kwargs):
        """Test that HeatmapPlot raises error when y_var is missing."""
        plot_config = PlotConfig(type="heatmap", x_var="block_size")  # No y_var
        plot = HeatmapPlot(plot_config=plot_config, **plot_kwargs)

        with pytest.raises(ValueError) as exc_info:
            plot.generate()

        assert "HeatmapPlot requires both x_var and y_var" in str(exc_info.value)

    def test_heatmap_with_custom_z_metric(self, plot_kwargs):
        """Test heatmap with custom z_metric (not default)."""
        plot_config = PlotConfig(
            type="heatmap",
            x_var="block_size",
            y_var="nodes",
            z_metric="latency",
        )
        plot = HeatmapPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()
        heatmap_trace = fig.data[0]

        assert "latency" in heatmap_trace.colorbar.title.text

    def test_heatmap_custom_colorscale(self, plot_kwargs):
        """Test heatmap with custom colorscale."""
        plot_config = PlotConfig(
            type="heatmap",
            x_var="block_size",
            y_var="nodes",
            colorscale="Hot",
        )
        plot = HeatmapPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()
        heatmap_trace = fig.data[0]

        # Plotly may expand colorscale names to tuples
        assert heatmap_trace.colorscale is not None

    def test_heatmap_data_aggregation(self, plot_kwargs):
        """Test that heatmap correctly aggregates and pivots data."""
        plot_config = PlotConfig(type="heatmap", x_var="block_size", y_var="nodes")
        plot = HeatmapPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()
        heatmap_trace = fig.data[0]

        # Should have data for 2 x-values (4, 8) and 3 y-values (1, 2, 4)
        assert len(heatmap_trace.x) == 2  # block_size: 4, 8
        assert len(heatmap_trace.y) == 3  # nodes: 1, 2, 4
        # z is a list of lists (converted from numpy to avoid Plotly 6.x binary encoding)
        assert len(heatmap_trace.z) == 3  # 3 rows
        assert len(heatmap_trace.z[0]) == 2  # 2 columns


# ============================================================================
# Test Theme Application
# ============================================================================

class TestThemeApplication:
    """Test theme application across different plot types."""

    def test_theme_applied_to_bar_plot(self, plot_kwargs, custom_theme):
        """Test custom theme is applied to bar plot."""
        plot_kwargs["theme"] = custom_theme
        plot_config = PlotConfig(type="bar", x_var="nodes")
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        assert fig.layout.template is not None
        assert fig.layout.font.family == "Arial, sans-serif"
        assert list(fig.layout.colorway) == ["#FF0000", "#00FF00", "#0000FF"]

    def test_theme_applied_to_line_plot(self, plot_kwargs, custom_theme):
        """Test custom theme is applied to line plot."""
        plot_kwargs["theme"] = custom_theme
        plot_config = PlotConfig(type="line", x_var="block_size")
        plot = LinePlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        assert fig.layout.template is not None
        assert fig.layout.font.family == "Arial, sans-serif"

    def test_theme_applied_to_scatter_plot(self, plot_kwargs, custom_theme):
        """Test custom theme is applied to scatter plot."""
        plot_kwargs["theme"] = custom_theme
        plot_config = PlotConfig(type="scatter", x_var="nodes")
        plot = ScatterPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        assert fig.layout.template is not None

    def test_theme_applied_to_heatmap(self, plot_kwargs, custom_theme):
        """Test custom theme is applied to heatmap."""
        plot_kwargs["theme"] = custom_theme
        plot_config = PlotConfig(type="heatmap", x_var="block_size", y_var="nodes")
        plot = HeatmapPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        assert fig.layout.template is not None


# ============================================================================
# Test Edge Cases
# ============================================================================

class TestPlotEdgeCases:
    """Test edge cases and error handling."""

    def test_plot_with_empty_dataframe(self, plot_kwargs):
        """Test plot generation with empty DataFrame."""
        plot_kwargs["df"] = pd.DataFrame(columns=['vars.nodes', 'metrics.bandwidth'])
        plot_config = PlotConfig(type="bar", x_var="nodes")
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        # Should not crash, but may produce empty plot
        fig = plot.generate()
        assert isinstance(fig, go.Figure)

    def test_plot_with_single_data_point(self, plot_kwargs):
        """Test plot generation with single data point."""
        plot_kwargs["df"] = pd.DataFrame({
            'vars.nodes': [1],
            'metrics.bandwidth': [100],
        })
        plot_config = PlotConfig(type="bar", x_var="nodes")
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()
        assert isinstance(fig, go.Figure)
        assert len(fig.data[0].x) == 1

    def test_plot_with_missing_column(self, plot_kwargs):
        """Test plot with missing column in DataFrame."""
        # Remove bandwidth column
        plot_kwargs["df"] = plot_kwargs["df"].drop(columns=['metrics.bandwidth'])
        plot_config = PlotConfig(type="bar", x_var="nodes")
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        # Should raise KeyError when trying to access missing column
        with pytest.raises(KeyError):
            plot.generate()

    def test_line_plot_multiple_groups(self, plot_kwargs):
        """Test line plot with multiple group values."""
        plot_config = PlotConfig(type="line", x_var="block_size", group_by="nodes")
        plot = LinePlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        # Should have 3 traces (for nodes=1, 2, 4)
        assert len(fig.data) == 3

    def test_scatter_with_default_color(self, plot_kwargs):
        """Test scatter plot uses metric as default color."""
        plot_config = PlotConfig(type="scatter", x_var="nodes", y_var="block_size")
        plot = ScatterPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()
        # Default color_by should be the metric (bandwidth)
        assert fig.data[0].marker.colorbar is not None

    def test_plot_height_width_custom(self, plot_kwargs):
        """Test custom height and width are applied."""
        plot_config = PlotConfig(type="bar", x_var="nodes", height=700, width=900)
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        assert fig.layout.height == 700
        assert fig.layout.width == 900

    def test_plot_height_width_none(self, plot_kwargs):
        """Test that None height/width uses theme defaults."""
        plot_config = PlotConfig(type="bar", x_var="nodes")
        plot = BarPlot(plot_config=plot_config, **plot_kwargs)

        fig = plot.generate()

        # Height should be set, width can be None
        assert fig.layout.height is not None
        # Width None is allowed by Plotly (auto-sizing)


# ============================================================================
# Test Execution Scatter Plot
# ============================================================================

class TestExecutionScatterPlot:
    """Test execution scatter plot generation."""

    @pytest.fixture
    def sample_df_with_exec_id(self):
        """Create sample DataFrame with execution.execution_id column."""
        return pd.DataFrame({
            'execution.execution_id': [1, 2, 3, 4, 5, 6],
            'vars.nodes': [1, 2, 4, 1, 2, 4],
            'vars.block_size': [4, 4, 4, 8, 8, 8],
            'metrics.bandwidth': [100, 150, 200, 120, 180, 240],
            'metrics.latency': [10, 7, 5, 9, 6.5, 4.5],
        })

    def test_execution_scatter_is_registered(self):
        """Test that execution_scatter plot is registered."""
        assert "execution_scatter" in _PLOT_REGISTRY
        assert _PLOT_REGISTRY["execution_scatter"] == ExecutionScatterPlot

    def test_execution_scatter_with_exec_id(self, sample_df_with_exec_id, default_theme, var_column_fn, metric_column_fn):
        """Test execution scatter plot with execution.execution_id column."""
        plot_config = PlotConfig(type="execution_scatter")
        plot = ExecutionScatterPlot(
            df=sample_df_with_exec_id,
            metric="bandwidth",
            plot_config=plot_config,
            theme=default_theme,
            var_column_fn=var_column_fn,
            metric_column_fn=metric_column_fn,
        )

        fig = plot.generate()

        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 1
        assert isinstance(fig.data[0], go.Scatter)
        # Check x values are execution IDs
        assert list(fig.data[0].x) == [1, 2, 3, 4, 5, 6]
        # Check y values are metric values
        assert list(fig.data[0].y) == [100, 150, 200, 120, 180, 240]
        # Check title
        assert "bandwidth" in fig.layout.title.text.lower()
        assert "execution" in fig.layout.title.text.lower()

    def test_execution_scatter_without_exec_id(self, default_theme, var_column_fn, metric_column_fn):
        """Test execution scatter plot falls back to index when no execution ID."""
        df_no_exec_id = pd.DataFrame({
            'vars.nodes': [1, 2, 4, 1, 2, 4],
            'vars.block_size': [4, 4, 4, 8, 8, 8],
            'metrics.bandwidth': [100, 150, 200, 120, 180, 240],
        })

        plot_config = PlotConfig(type="execution_scatter")
        plot = ExecutionScatterPlot(
            df=df_no_exec_id,
            metric="bandwidth",
            plot_config=plot_config,
            theme=default_theme,
            var_column_fn=var_column_fn,
            metric_column_fn=metric_column_fn,
        )

        fig = plot.generate()

        assert isinstance(fig, go.Figure)
        # Check x values are sequential indices
        assert list(fig.data[0].x) == [0, 1, 2, 3, 4, 5]

    def test_execution_scatter_hover_includes_vars(self, sample_df_with_exec_id, default_theme, var_column_fn, metric_column_fn):
        """Test that hover text includes all variable values."""
        plot_config = PlotConfig(type="execution_scatter")
        plot = ExecutionScatterPlot(
            df=sample_df_with_exec_id,
            metric="bandwidth",
            plot_config=plot_config,
            theme=default_theme,
            var_column_fn=var_column_fn,
            metric_column_fn=metric_column_fn,
        )

        fig = plot.generate()

        # Check hover text contains variable information
        hover_text = fig.data[0].text[0]  # First point
        assert "Test ID: 1" in hover_text
        assert "bandwidth" in hover_text
        assert "nodes" in hover_text
        assert "block_size" in hover_text

    def test_execution_scatter_marker_color(self, sample_df_with_exec_id, default_theme, var_column_fn, metric_column_fn):
        """Test that markers are colored by metric value."""
        plot_config = PlotConfig(type="execution_scatter")
        plot = ExecutionScatterPlot(
            df=sample_df_with_exec_id,
            metric="bandwidth",
            plot_config=plot_config,
            theme=default_theme,
            var_column_fn=var_column_fn,
            metric_column_fn=metric_column_fn,
        )

        fig = plot.generate()

        # Check marker coloring
        assert fig.data[0].marker.colorscale is not None
        assert fig.data[0].marker.showscale is True
        assert fig.data[0].marker.colorbar is not None

    def test_execution_scatter_via_factory(self, sample_df_with_exec_id, default_theme, var_column_fn, metric_column_fn):
        """Test creating execution_scatter plot via factory function."""
        plot_config = PlotConfig(type="execution_scatter")
        plot = create_plot(
            plot_type="execution_scatter",
            df=sample_df_with_exec_id,
            metric="bandwidth",
            plot_config=plot_config,
            theme=default_theme,
            var_column_fn=var_column_fn,
            metric_column_fn=metric_column_fn,
        )

        assert isinstance(plot, ExecutionScatterPlot)
        fig = plot.generate()
        assert isinstance(fig, go.Figure)


# ============================================================================
# Test Coverage Heatmap Plot
# ============================================================================

class TestCoverageHeatmapPlot:
    """Test coverage heatmap plot generation."""

    def test_coverage_heatmap_is_registered(self):
        """Test that coverage_heatmap plot is registered."""
        assert "coverage_heatmap" in _PLOT_REGISTRY
        assert _PLOT_REGISTRY["coverage_heatmap"] == CoverageHeatmapPlot

    def test_coverage_heatmap_requires_row_col(self, sample_df, default_theme, var_column_fn, metric_column_fn):
        """Test coverage heatmap requires both row_vars and col_var."""
        plot_config = PlotConfig(type="coverage_heatmap")
        plot = CoverageHeatmapPlot(
            df=sample_df,
            metric="bandwidth",
            plot_config=plot_config,
            theme=default_theme,
            var_column_fn=var_column_fn,
            metric_column_fn=metric_column_fn,
        )

        # Should raise error when row_vars and col_var are not specified
        with pytest.raises(ValueError) as exc_info:
            plot.generate()

        assert "requires both 'row_vars' and 'col_var'" in str(exc_info.value)

    def test_coverage_heatmap_manual_row_col(self, sample_df, default_theme, var_column_fn, metric_column_fn):
        """Test coverage heatmap with manually specified row_vars and col_var."""
        plot_config = PlotConfig(
            type="coverage_heatmap",
            row_vars=["nodes", "block_size"],
            col_var="transfer_size",
        )
        plot = CoverageHeatmapPlot(
            df=sample_df,
            metric="bandwidth",
            plot_config=plot_config,
            theme=default_theme,
            var_column_fn=var_column_fn,
            metric_column_fn=metric_column_fn,
        )

        fig = plot.generate()

        assert isinstance(fig, go.Figure)
        assert isinstance(fig.data[0], go.Heatmap)
        # Check that title includes the correct variables
        assert "nodes" in fig.layout.title.text
        assert "transfer_size" in fig.layout.title.text

    def test_coverage_heatmap_aggregation_mean(self, sample_df, default_theme, var_column_fn, metric_column_fn):
        """Test coverage heatmap with mean aggregation."""
        plot_config = PlotConfig(
            type="coverage_heatmap",
            row_vars=["nodes"],
            col_var="block_size",
            aggregation="mean",
        )
        plot = CoverageHeatmapPlot(
            df=sample_df,
            metric="bandwidth",
            plot_config=plot_config,
            theme=default_theme,
            var_column_fn=var_column_fn,
            metric_column_fn=metric_column_fn,
        )

        fig = plot.generate()

        assert isinstance(fig, go.Figure)
        heatmap_trace = fig.data[0]
        assert "mean" in heatmap_trace.colorbar.title.text

    def test_coverage_heatmap_aggregation_count(self, sample_df, default_theme, var_column_fn, metric_column_fn):
        """Test coverage heatmap with count aggregation."""
        plot_config = PlotConfig(
            type="coverage_heatmap",
            row_vars=["nodes"],
            col_var="block_size",
            aggregation="count",
        )
        plot = CoverageHeatmapPlot(
            df=sample_df,
            metric="bandwidth",
            plot_config=plot_config,
            theme=default_theme,
            var_column_fn=var_column_fn,
            metric_column_fn=metric_column_fn,
        )

        fig = plot.generate()

        assert isinstance(fig, go.Figure)
        heatmap_trace = fig.data[0]
        assert "count" in heatmap_trace.colorbar.title.text

    def test_coverage_heatmap_invalid_aggregation(self, sample_df, default_theme, var_column_fn, metric_column_fn):
        """Test that invalid aggregation raises ValueError."""
        plot_config = PlotConfig(
            type="coverage_heatmap",
            row_vars=["nodes"],
            col_var="block_size",
            aggregation="invalid",
        )
        plot = CoverageHeatmapPlot(
            df=sample_df,
            metric="bandwidth",
            plot_config=plot_config,
            theme=default_theme,
            var_column_fn=var_column_fn,
            metric_column_fn=metric_column_fn,
        )

        with pytest.raises(ValueError) as exc_info:
            plot.generate()

        assert "Unknown aggregation" in str(exc_info.value)
        assert "invalid" in str(exc_info.value)

    def test_coverage_heatmap_multi_index_labels(self, sample_df, default_theme, var_column_fn, metric_column_fn):
        """Test that multi-index labels are formatted correctly."""
        plot_config = PlotConfig(
            type="coverage_heatmap",
            row_vars=["nodes", "block_size"],
            col_var="transfer_size",
        )
        plot = CoverageHeatmapPlot(
            df=sample_df,
            metric="bandwidth",
            plot_config=plot_config,
            theme=default_theme,
            var_column_fn=var_column_fn,
            metric_column_fn=metric_column_fn,
        )

        fig = plot.generate()

        # Check that y-axis labels contain both variables
        heatmap_trace = fig.data[0]
        y_labels = heatmap_trace.y
        # Labels should be formatted like "nodes=1, block_size=4"
        assert any("nodes=" in str(label) for label in y_labels)

    def test_coverage_heatmap_with_nan_values(self, default_theme, var_column_fn, metric_column_fn):
        """Test coverage heatmap handles missing data (NaN)."""
        # Create DataFrame with missing combinations
        df_with_gaps = pd.DataFrame({
            'vars.nodes': [1, 1, 2, 2, 4],  # Missing nodes=4, block_size=8
            'vars.block_size': [4, 8, 4, 8, 4],
            'metrics.bandwidth': [100, 120, 150, 180, 200],
        })

        plot_config = PlotConfig(
            type="coverage_heatmap",
            row_vars=["nodes"],
            col_var="block_size",
            show_missing=True,
        )
        plot = CoverageHeatmapPlot(
            df=df_with_gaps,
            metric="bandwidth",
            plot_config=plot_config,
            theme=default_theme,
            var_column_fn=var_column_fn,
            metric_column_fn=metric_column_fn,
        )

        fig = plot.generate()

        assert isinstance(fig, go.Figure)
        # Should not crash with NaN values
        heatmap_trace = fig.data[0]
        assert heatmap_trace.z is not None

    def test_coverage_heatmap_hover_text(self, sample_df, default_theme, var_column_fn, metric_column_fn):
        """Test that hover text includes all variable values."""
        plot_config = PlotConfig(
            type="coverage_heatmap",
            row_vars=["nodes"],
            col_var="block_size",
        )
        plot = CoverageHeatmapPlot(
            df=sample_df,
            metric="bandwidth",
            plot_config=plot_config,
            theme=default_theme,
            var_column_fn=var_column_fn,
            metric_column_fn=metric_column_fn,
        )

        fig = plot.generate()

        # Check hover text format
        heatmap_trace = fig.data[0]
        hover_text = heatmap_trace.text
        assert hover_text is not None
        # Should be a 2D array of hover texts
        assert len(hover_text) > 0
        # First hover text should contain variable names
        first_hover = hover_text[0][0]
        assert "nodes" in first_hover
        assert "block_size" in first_hover
        assert "bandwidth" in first_hover

    def test_coverage_heatmap_via_factory(self, sample_df, default_theme, var_column_fn, metric_column_fn):
        """Test creating coverage_heatmap via factory function."""
        plot_config = PlotConfig(
            type="coverage_heatmap",
            row_vars=["nodes"],
            col_var="block_size",
        )
        plot = create_plot(
            plot_type="coverage_heatmap",
            df=sample_df,
            metric="bandwidth",
            plot_config=plot_config,
            theme=default_theme,
            var_column_fn=var_column_fn,
            metric_column_fn=metric_column_fn,
        )

        assert isinstance(plot, CoverageHeatmapPlot)
        fig = plot.generate()
        assert isinstance(fig, go.Figure)

    def test_coverage_heatmap_invalid_row_var(self, sample_df, default_theme, var_column_fn, metric_column_fn):
        """Test that invalid row_var raises ValueError."""
        plot_config = PlotConfig(
            type="coverage_heatmap",
            row_vars=["invalid_var"],
            col_var="block_size",
        )
        plot = CoverageHeatmapPlot(
            df=sample_df,
            metric="bandwidth",
            plot_config=plot_config,
            theme=default_theme,
            var_column_fn=var_column_fn,
            metric_column_fn=metric_column_fn,
        )

        with pytest.raises(ValueError) as exc_info:
            plot.generate()

        assert "invalid_var" in str(exc_info.value)
        assert "not found" in str(exc_info.value)

    def test_coverage_heatmap_invalid_col_var(self, sample_df, default_theme, var_column_fn, metric_column_fn):
        """Test that invalid col_var raises ValueError."""
        plot_config = PlotConfig(
            type="coverage_heatmap",
            row_vars=["nodes"],
            col_var="invalid_var",
        )
        plot = CoverageHeatmapPlot(
            df=sample_df,
            metric="bandwidth",
            plot_config=plot_config,
            theme=default_theme,
            var_column_fn=var_column_fn,
            metric_column_fn=metric_column_fn,
        )

        with pytest.raises(ValueError) as exc_info:
            plot.generate()

        assert "invalid_var" in str(exc_info.value)
        assert "not found" in str(exc_info.value)
