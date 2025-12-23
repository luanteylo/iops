"""Plot generation abstractions for IOPS reports."""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable
import plotly.graph_objects as go
import pandas as pd

from iops.config.models import PlotConfig, ReportThemeConfig


# ============================================================================
# Base Plot Class
# ============================================================================

class BasePlot(ABC):
    """Abstract base class for all plot types."""

    def __init__(
        self,
        df: pd.DataFrame,
        metric: str,
        plot_config: PlotConfig,
        theme: ReportThemeConfig,
        var_column_fn: Callable[[str], str],
        metric_column_fn: Callable[[str], str],
    ):
        """
        Initialize base plot.

        Args:
            df: DataFrame containing benchmark results
            metric: Metric name to plot
            plot_config: Plot configuration
            theme: Theme configuration
            var_column_fn: Function to get variable column name (e.g., "vars.nodes")
            metric_column_fn: Function to get metric column name (e.g., "metrics.bandwidth")
        """
        self.df = df
        self.metric = metric
        self.config = plot_config
        self.theme = theme
        self._get_var_column = var_column_fn
        self._get_metric_column = metric_column_fn

    @abstractmethod
    def generate(self) -> go.Figure:
        """Generate the plot and return Plotly figure."""
        pass

    def _apply_theme(self, fig: go.Figure) -> go.Figure:
        """Apply theme settings to figure."""
        fig.update_layout(
            template=self.theme.style,
            font_family=self.theme.font_family,
            height=self.config.height or self.theme.style == "plotly_white" and 500 or 500,
            width=self.config.width,
        )

        if self.theme.colors:
            fig.update_layout(colorway=self.theme.colors)

        return fig

    def _get_title(self, default: str) -> str:
        """Get plot title (custom or default)."""
        return self.config.title or default

    def _get_xaxis_label(self, default: str) -> str:
        """Get x-axis label (custom or default)."""
        return self.config.xaxis_label or default

    def _get_yaxis_label(self, default: str) -> str:
        """Get y-axis label (custom or default)."""
        return self.config.yaxis_label or default


# ============================================================================
# Registry Pattern
# ============================================================================

_PLOT_REGISTRY: Dict[str, type] = {}


def register_plot(plot_type: str):
    """
    Decorator to register plot implementations.

    Usage:
        @register_plot("bar")
        class BarPlot(BasePlot):
            ...
    """
    def decorator(cls):
        _PLOT_REGISTRY[plot_type] = cls
        return cls
    return decorator


def create_plot(plot_type: str, **kwargs) -> BasePlot:
    """
    Factory function to create plot instances.

    Args:
        plot_type: Type of plot to create (e.g., "bar", "line", "scatter")
        **kwargs: Arguments to pass to plot constructor

    Returns:
        Plot instance

    Raises:
        ValueError: If plot type is not registered
    """
    if plot_type not in _PLOT_REGISTRY:
        available = ", ".join(sorted(_PLOT_REGISTRY.keys()))
        raise ValueError(
            f"Unknown plot type: '{plot_type}'. Available types: {available}"
        )
    return _PLOT_REGISTRY[plot_type](**kwargs)


# ============================================================================
# Core Plot Implementations
# ============================================================================

@register_plot("bar")
class BarPlot(BasePlot):
    """Bar plot with error bars showing mean and standard deviation."""

    def generate(self) -> go.Figure:
        x_var = self.config.x_var
        if not x_var:
            raise ValueError("BarPlot requires x_var")

        var_col = self._get_var_column(x_var)
        metric_col = self._get_metric_column(self.metric)

        # Group by variable and aggregate
        df_grouped = self.df.groupby(var_col)[metric_col].agg(['mean', 'std']).reset_index()
        df_grouped = df_grouped.sort_values(var_col)

        # Convert x values to strings for categorical axis
        x_values = [str(x) for x in df_grouped[var_col]]

        fig = go.Figure()

        # Add error bars if requested
        error_y = None
        if self.config.show_error_bars and 'std' in df_grouped.columns:
            error_y = dict(type='data', array=df_grouped['std'])

        fig.add_trace(go.Bar(
            x=x_values,
            y=df_grouped['mean'],
            error_y=error_y,
            name=self.metric,
            text=[f'{v:.2f}' for v in df_grouped['mean']],
            textposition='outside',
        ))

        fig.update_layout(
            title=self._get_title(f"{self.metric} vs {x_var}"),
            xaxis_title=self._get_xaxis_label(x_var),
            yaxis_title=self._get_yaxis_label(self.metric),
            xaxis=dict(type='category'),
            showlegend=False,
        )

        return self._apply_theme(fig)


@register_plot("line")
class LinePlot(BasePlot):
    """Line plot with optional grouping by another variable."""

    def generate(self) -> go.Figure:
        x_var = self.config.x_var
        group_var = self.config.group_by

        if not x_var:
            raise ValueError("LinePlot requires x_var")

        var_col = self._get_var_column(x_var)
        metric_col = self._get_metric_column(self.metric)

        fig = go.Figure()

        if group_var:
            # Line plot with grouping
            group_col = self._get_var_column(group_var)
            df_grouped = self.df.groupby([var_col, group_col])[metric_col].mean().reset_index()

            # Get all x values for consistent axis
            all_x_values = sorted(df_grouped[var_col].unique())
            x_strings = [str(x) for x in all_x_values]

            # Create a trace for each group value
            for val in sorted(df_grouped[group_col].unique()):
                df_slice = df_grouped[df_grouped[group_col] == val].sort_values(var_col)
                x_slice = [str(x) for x in df_slice[var_col]]

                fig.add_trace(go.Scatter(
                    x=x_slice,
                    y=df_slice[metric_col],
                    mode='lines+markers',
                    name=f'{group_var}={val}',
                    marker=dict(size=10),
                    line=dict(width=2),
                ))

            fig.update_xaxes(
                type='category',
                categoryorder='array',
                categoryarray=x_strings,
            )

            title_suffix = f" (grouped by {group_var})"
        else:
            # Simple line plot without grouping
            df_grouped = self.df.groupby(var_col)[metric_col].mean().reset_index().sort_values(var_col)
            x_values = [str(x) for x in df_grouped[var_col]]

            fig.add_trace(go.Scatter(
                x=x_values,
                y=df_grouped[metric_col],
                mode='lines+markers',
                marker=dict(size=10),
                line=dict(width=2),
            ))

            fig.update_xaxes(type='category')
            title_suffix = ""

        fig.update_layout(
            title=self._get_title(f"{self.metric} vs {x_var}{title_suffix}"),
            xaxis_title=self._get_xaxis_label(x_var),
            yaxis_title=self._get_yaxis_label(self.metric),
            hovermode='x unified',
        )

        return self._apply_theme(fig)


@register_plot("scatter")
class ScatterPlot(BasePlot):
    """Scatter plot with optional color/size mapping."""

    def generate(self) -> go.Figure:
        x_var = self.config.x_var
        y_var = self.config.y_var
        color_by = self.config.color_by or self.metric

        if not x_var:
            raise ValueError("ScatterPlot requires x_var")

        x_col = self._get_var_column(x_var)

        # Determine y column
        if y_var:
            # 2D scatter of two variables
            y_col = self._get_var_column(y_var)
            y_title = y_var
        else:
            # Scatter metric vs x_var
            y_col = self._get_metric_column(self.metric)
            y_title = self.metric

        # Determine color column
        if color_by == self.metric or (not y_var and color_by == self.config.y_var):
            color_col = self._get_metric_column(self.metric)
        else:
            color_col = self._get_var_column(color_by)

        # Group and aggregate
        group_cols = [x_col]
        if y_var:
            group_cols.append(y_col)

        # Aggregate to get mean values
        df_grouped = self.df.groupby(group_cols)[color_col].mean().reset_index()

        # Create scatter plot
        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=df_grouped[x_col],
            y=df_grouped[y_col],
            mode='markers',
            marker=dict(
                size=12,
                color=df_grouped[color_col],
                colorscale=self.config.colorscale,
                showscale=True,
                colorbar=dict(title=color_by),
                line=dict(width=1, color='white'),
            ),
            text=df_grouped.apply(
                lambda row: f"{x_var}: {row[x_col]}<br>{y_title}: {row[y_col]:.4f}<br>{color_by}: {row[color_col]:.4f}",
                axis=1
            ),
            hovertemplate='%{text}<extra></extra>',
        ))

        fig.update_layout(
            title=self._get_title(f"{y_title} vs {x_var}"),
            xaxis_title=self._get_xaxis_label(x_var),
            yaxis_title=self._get_yaxis_label(y_title),
            showlegend=False,
        )

        return self._apply_theme(fig)


@register_plot("heatmap")
class HeatmapPlot(BasePlot):
    """2D heatmap visualization of metric across two variables."""

    def generate(self) -> go.Figure:
        x_var = self.config.x_var
        y_var = self.config.y_var
        z_metric = self.config.z_metric or self.metric

        if not x_var or not y_var:
            raise ValueError("HeatmapPlot requires both x_var and y_var")

        x_col = self._get_var_column(x_var)
        y_col = self._get_var_column(y_var)
        z_col = self._get_metric_column(z_metric)

        # Group and aggregate
        df_grouped = self.df.groupby([x_col, y_col])[z_col].mean().reset_index()

        # Pivot for heatmap
        df_pivot = df_grouped.pivot(index=y_col, columns=x_col, values=z_col)

        # Sort indices and columns
        df_pivot = df_pivot.sort_index().sort_index(axis=1)

        fig = go.Figure()

        fig.add_trace(go.Heatmap(
            x=[str(x) for x in df_pivot.columns],
            y=[str(y) for y in df_pivot.index],
            z=df_pivot.values,
            colorscale=self.config.colorscale,
            colorbar=dict(title=z_metric),
            hovertemplate=f'{x_var}: %{{x}}<br>{y_var}: %{{y}}<br>{z_metric}: %{{z:.4f}}<extra></extra>',
        ))

        fig.update_layout(
            title=self._get_title(f"{z_metric} Heatmap"),
            xaxis_title=self._get_xaxis_label(x_var),
            yaxis_title=self._get_yaxis_label(y_var),
            xaxis=dict(type='category'),
            yaxis=dict(type='category'),
        )

        return self._apply_theme(fig)


@register_plot("box")
class BoxPlot(BasePlot):
    """Box plot showing distribution statistics with optional outliers."""

    def generate(self) -> go.Figure:
        x_var = self.config.x_var

        if not x_var:
            raise ValueError("BoxPlot requires x_var")

        x_col = self._get_var_column(x_var)
        metric_col = self._get_metric_column(self.metric)

        # Get unique values of x_var for separate boxes
        unique_x = sorted(self.df[x_col].unique())

        fig = go.Figure()

        for x_val in unique_x:
            df_subset = self.df[self.df[x_col] == x_val]

            fig.add_trace(go.Box(
                y=df_subset[metric_col],
                name=str(x_val),
                boxpoints='outliers' if self.config.show_outliers else False,
                marker=dict(size=4),
                line=dict(width=2),
            ))

        fig.update_layout(
            title=self._get_title(f"{self.metric} Distribution by {x_var}"),
            xaxis_title=self._get_xaxis_label(x_var),
            yaxis_title=self._get_yaxis_label(self.metric),
            showlegend=False,
        )

        return self._apply_theme(fig)


@register_plot("violin")
class ViolinPlot(BasePlot):
    """Violin plot showing distribution with kernel density estimation."""

    def generate(self) -> go.Figure:
        x_var = self.config.x_var

        if not x_var:
            raise ValueError("ViolinPlot requires x_var")

        x_col = self._get_var_column(x_var)
        metric_col = self._get_metric_column(self.metric)

        # Get unique values of x_var for separate violins
        unique_x = sorted(self.df[x_col].unique())

        fig = go.Figure()

        for x_val in unique_x:
            df_subset = self.df[self.df[x_col] == x_val]

            fig.add_trace(go.Violin(
                y=df_subset[metric_col],
                name=str(x_val),
                box_visible=True,
                meanline_visible=True,
                line=dict(width=2),
            ))

        fig.update_layout(
            title=self._get_title(f"{self.metric} Distribution by {x_var}"),
            xaxis_title=self._get_xaxis_label(x_var),
            yaxis_title=self._get_yaxis_label(self.metric),
            showlegend=False,
        )

        return self._apply_theme(fig)


@register_plot("surface_3d")
class Surface3DPlot(BasePlot):
    """3D surface plot for visualizing metric across two variables."""

    def generate(self) -> go.Figure:
        x_var = self.config.x_var
        y_var = self.config.y_var
        z_metric = self.config.z_metric or self.metric

        if not x_var or not y_var:
            raise ValueError("Surface3DPlot requires both x_var and y_var")

        x_col = self._get_var_column(x_var)
        y_col = self._get_var_column(y_var)
        z_col = self._get_metric_column(z_metric)

        # Group and aggregate
        df_grouped = self.df.groupby([x_col, y_col])[z_col].mean().reset_index()

        # Pivot for 3D surface
        df_pivot = df_grouped.pivot(index=y_col, columns=x_col, values=z_col)

        # Sort indices and columns
        df_pivot = df_pivot.sort_index().sort_index(axis=1)

        fig = go.Figure()

        fig.add_trace(go.Surface(
            x=df_pivot.columns,
            y=df_pivot.index,
            z=df_pivot.values,
            colorscale=self.config.colorscale,
            colorbar=dict(title=z_metric),
            hovertemplate=f'{x_var}: %{{x}}<br>{y_var}: %{{y}}<br>{z_metric}: %{{z:.4f}}<extra></extra>',
        ))

        fig.update_layout(
            title=self._get_title(f"{z_metric} 3D Surface"),
            scene=dict(
                xaxis_title=self._get_xaxis_label(x_var),
                yaxis_title=self._get_yaxis_label(y_var),
                zaxis_title=z_metric,
            ),
        )

        return self._apply_theme(fig)


@register_plot("parallel_coordinates")
class ParallelCoordinatesPlot(BasePlot):
    """Parallel coordinates plot for multi-dimensional data visualization."""

    def generate(self) -> go.Figure:
        # Get all swept variables (or use all numeric variables if not specified)
        var_cols = []
        var_names = []

        # Identify swept variables from column names
        for col in self.df.columns:
            if col.startswith('vars.'):
                var_name = col.replace('vars.', '')
                # Only include numeric variables
                if pd.api.types.is_numeric_dtype(self.df[col]):
                    var_cols.append(col)
                    var_names.append(var_name)

        # Add the metric
        metric_col = self._get_metric_column(self.metric)
        if metric_col not in self.df.columns:
            raise ValueError(f"Metric column '{metric_col}' not found")

        # Group by parameter combinations and get mean
        df_grouped = self.df.groupby(var_cols)[metric_col].mean().reset_index()

        # Build dimensions for parallel coordinates
        dimensions = []

        for col, name in zip(var_cols, var_names):
            dimensions.append(dict(
                label=name,
                values=df_grouped[col],
            ))

        # Add metric as final dimension
        dimensions.append(dict(
            label=self.metric,
            values=df_grouped[metric_col],
        ))

        fig = go.Figure(data=go.Parcoords(
            line=dict(
                color=df_grouped[metric_col],
                colorscale=self.config.colorscale,
                showscale=True,
                colorbar=dict(title=self.metric),
            ),
            dimensions=dimensions
        ))

        fig.update_layout(
            title=self._get_title(f"Parallel Coordinates: {self.metric}"),
        )

        return self._apply_theme(fig)


# ============================================================================
# Utility Functions
# ============================================================================

def get_available_plot_types():
    """Get list of registered plot types."""
    return sorted(_PLOT_REGISTRY.keys())
