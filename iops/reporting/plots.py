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

    @staticmethod
    def _to_list(data):
        """
        Convert array-like data to Python list to avoid Plotly 6.x binary encoding.

        Plotly 6.x uses binary encoding (bdata/dtype) for numpy arrays which can
        cause blank plots in some browsers. Converting to plain Python lists with
        native Python types ensures compatibility.

        Args:
            data: Array-like data (numpy array, pandas Series, or list)

        Returns:
            Python list with native Python types (int, float)
        """
        import numpy as np

        # Convert to list first
        if hasattr(data, 'values'):
            # pandas Series or DataFrame column
            result = data.values.tolist()
        elif hasattr(data, 'tolist'):
            result = data.tolist()
        else:
            result = list(data) if hasattr(data, '__iter__') else data

        # Ensure all elements are native Python types (not numpy scalars)
        if isinstance(result, list):
            converted = []
            for item in result:
                if isinstance(item, (np.integer, np.floating)):
                    converted.append(item.item())  # Convert numpy scalar to Python native
                elif isinstance(item, np.ndarray):
                    converted.append(item.tolist())
                else:
                    converted.append(item)
            return converted
        return result

    def _get_column(self, name: str) -> str:
        """
        Get column name, checking both metrics and variables.

        Args:
            name: Name to look up (could be variable or metric)

        Returns:
            Column name (e.g., "vars.nodes" or "metrics.bandwidth")

        Raises:
            ValueError: If column is not found in either vars or metrics
        """
        # Check if it's a metric
        metric_col = self._get_metric_column(name)
        if metric_col in self.df.columns:
            return metric_col

        # Check if it's a variable
        var_col = self._get_var_column(name)
        if var_col in self.df.columns:
            return var_col

        # Not found in either
        raise ValueError(
            f"'{name}' not found in variables or metrics. "
            f"Available columns: {', '.join(self.df.columns)}"
        )


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
            error_y = dict(type='data', array=self._to_list(df_grouped['std']))

        fig.add_trace(go.Bar(
            x=x_values,
            y=self._to_list(df_grouped['mean']),
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
                    y=self._to_list(df_slice[metric_col]),
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
                y=self._to_list(df_grouped[metric_col]),
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

        # Get x column (can be variable or metric)
        x_col = self._get_column(x_var)

        # Determine y column
        if y_var:
            # 2D scatter - y can be variable or metric
            y_col = self._get_column(y_var)
            y_title = y_var
        else:
            # Scatter metric vs x_var
            y_col = self._get_metric_column(self.metric)
            y_title = self.metric

        # Determine color column (can be variable or metric)
        color_col = self._get_column(color_by)

        # Determine which columns are variables (for grouping)
        # and which are metrics (for aggregation)
        group_cols = []
        agg_cols = []

        for col in [x_col, y_col, color_col]:
            if col.startswith('vars.'):
                if col not in group_cols:
                    group_cols.append(col)
            elif col.startswith('metrics.'):
                if col not in agg_cols:
                    agg_cols.append(col)

        # Aggregate: group by variables and take mean of metrics
        if group_cols and agg_cols:
            # Have both variables and metrics - need to group and aggregate
            df_grouped = self.df.groupby(group_cols)[agg_cols].mean().reset_index()
        elif group_cols:
            # Only variables - just get unique combinations
            df_grouped = self.df[group_cols].drop_duplicates().reset_index(drop=True)
        elif agg_cols:
            # Only metrics - take overall mean
            df_grouped = pd.DataFrame({col: [self.df[col].mean()] for col in agg_cols})
        else:
            # Shouldn't happen, but handle it
            df_grouped = self.df[[x_col, y_col, color_col]].copy()

        # Create scatter plot
        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=self._to_list(df_grouped[x_col]),
            y=self._to_list(df_grouped[y_col]),
            mode='markers',
            marker=dict(
                size=12,
                color=self._to_list(df_grouped[color_col]),
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
            z=self._to_list(df_pivot.values),
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
                y=self._to_list(df_subset[metric_col]),
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
                y=self._to_list(df_subset[metric_col]),
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
            x=self._to_list(df_pivot.columns),
            y=self._to_list(df_pivot.index),
            z=self._to_list(df_pivot.values),
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


@register_plot("execution_scatter")
class ExecutionScatterPlot(BasePlot):
    """Scatter plot showing metric value for each execution, with all variables on hover."""

    def generate(self) -> go.Figure:
        metric_col = self._get_metric_column(self.metric)

        # Check if we have execution ID column
        if 'execution.execution_id' in self.df.columns:
            id_col = 'execution.execution_id'
        else:
            # Fall back to using row index as test ID
            id_col = None

        # Identify all swept variable columns
        var_cols = []
        var_names = []
        for col in self.df.columns:
            if col.startswith('vars.'):
                var_name = col.replace('vars.', '')
                var_cols.append(col)
                var_names.append(var_name)

        # Build hover text with all variables
        hover_texts = []
        for idx, row in self.df.iterrows():
            text_parts = []
            # Add test ID
            if id_col:
                text_parts.append(f"Test ID: {row[id_col]}")
            else:
                text_parts.append(f"Test #: {idx}")
            # Add metric value
            text_parts.append(f"{self.metric}: {row[metric_col]:.4f}")
            # Add all variables
            text_parts.append("")  # Empty line separator
            for var_col, var_name in zip(var_cols, var_names):
                if var_col in self.df.columns:
                    val = row[var_col]
                    # Format based on type
                    if isinstance(val, float):
                        text_parts.append(f"{var_name}: {val:.4g}")
                    else:
                        text_parts.append(f"{var_name}: {val}")
            hover_texts.append("<br>".join(text_parts))

        # X values: execution ID or index
        if id_col:
            x_values = self._to_list(self.df[id_col])
        else:
            x_values = list(range(len(self.df)))

        y_values = self._to_list(self.df[metric_col])

        # Create scatter plot
        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=x_values,
            y=y_values,
            mode='markers',
            marker=dict(
                size=10,
                color=y_values,
                colorscale=self.config.colorscale,
                showscale=True,
                colorbar=dict(title=self.metric),
                line=dict(width=1, color='white'),
            ),
            text=hover_texts,
            hovertemplate='%{text}<extra></extra>',
        ))

        fig.update_layout(
            title=self._get_title(f"{self.metric} per Execution"),
            xaxis_title=self._get_xaxis_label("Test ID"),
            yaxis_title=self._get_yaxis_label(self.metric),
            hovermode='closest',
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
                values=self._to_list(df_grouped[col]),
            ))

        # Add metric as final dimension
        dimensions.append(dict(
            label=self.metric,
            values=self._to_list(df_grouped[metric_col]),
        ))

        fig = go.Figure(data=go.Parcoords(
            line=dict(
                color=self._to_list(df_grouped[metric_col]),
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


@register_plot("coverage_heatmap")
class CoverageHeatmapPlot(BasePlot):
    """Multi-variable coverage heatmap showing parameter space exploration."""

    def generate(self) -> go.Figure:
        metric_col = self._get_metric_column(self.metric)

        # Get all swept variable columns
        all_var_cols = []
        all_var_names = []
        for col in self.df.columns:
            if col.startswith('vars.'):
                var_name = col.replace('vars.', '')
                all_var_cols.append(col)
                all_var_names.append(var_name)

        if len(all_var_cols) == 0:
            raise ValueError("No swept variables found in dataframe")

        # Determine row_vars and col_var (both required)
        row_vars = self.config.row_vars
        col_var = self.config.col_var

        if not row_vars or not col_var:
            raise ValueError(
                "Coverage heatmap requires both 'row_vars' and 'col_var' to be specified. "
                f"\nAvailable variables: {', '.join(all_var_names)}"
                f"\nExample:"
                f"\n  row_vars: ['nodes', 'processes_per_node']"
                f"\n  col_var: 'transfer_size_kb'"
            )

        # Validate variables exist
        for var in row_vars:
            if var not in all_var_names:
                raise ValueError(f"Row variable '{var}' not found in swept variables")
        if col_var not in all_var_names:
            raise ValueError(f"Column variable '{col_var}' not found in swept variables")

        # Get column names
        row_cols = [self._get_var_column(v) for v in row_vars]
        col_col = self._get_var_column(col_var)

        # Group by all variables and aggregate
        group_cols = row_cols + [col_col]
        agg_func = self.config.aggregation

        # Map aggregation string to pandas function
        agg_map = {
            'mean': 'mean',
            'median': 'median',
            'count': 'count',
            'std': 'std',
            'min': 'min',
            'max': 'max',
        }

        if agg_func not in agg_map:
            raise ValueError(
                f"Unknown aggregation '{agg_func}'. "
                f"Valid options: {', '.join(agg_map.keys())}"
            )

        df_grouped = self.df.groupby(group_cols)[metric_col].agg(agg_map[agg_func]).reset_index()

        # Check grouped data size for debugging
        expected_max_rows = 1
        for col in group_cols:
            expected_max_rows *= self.df[col].nunique()

        if len(df_grouped) > expected_max_rows * 1.1:  # Allow 10% tolerance
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Unexpected groupby size: {len(df_grouped)} rows (expected ~{expected_max_rows}). "
                f"This may indicate data issues or unexpected duplicate combinations."
            )

        # Create pivot table with multi-index
        if len(row_cols) > 1:
            # Multi-level row index
            df_pivot = df_grouped.pivot_table(
                index=row_cols,
                columns=col_col,
                values=metric_col,
                dropna=False
            )
        else:
            # Single-level row index
            df_pivot = df_grouped.pivot(
                index=row_cols[0],
                columns=col_col,
                values=metric_col
            )

        # Sort rows
        if self.config.sort_rows_by == "values":
            # Sort rows by mean of their values (across all columns)
            row_means = df_pivot.mean(axis=1, skipna=True)

            if isinstance(df_pivot.index, pd.MultiIndex):
                # Hierarchical sorting: sort each level by its group's mean performance
                # This creates better organization: first var sorted, then second var within each first var group, etc.
                sort_keys = []

                for level_idx in range(len(df_pivot.index.levels)):
                    # For each level, calculate the mean performance of each group at this level
                    # Group by all levels up to and including this one
                    groupby_levels = list(range(level_idx + 1))

                    # Calculate mean for each group (transform maintains original index)
                    group_means = row_means.groupby(level=groupby_levels).transform('mean')
                    sort_keys.append(group_means)

                # Create DataFrame with all sort keys for stable multi-level sorting
                sort_df = pd.DataFrame(
                    {f'sort_key_{i}': key for i, key in enumerate(sort_keys)},
                    index=df_pivot.index
                )

                # Sort by all keys in hierarchical order
                sort_order = sort_df.sort_values(
                    by=[f'sort_key_{i}' for i in range(len(sort_keys))],
                    ascending=self.config.sort_ascending
                ).index

                df_pivot = df_pivot.loc[sort_order]
            else:
                # Single-level index: simple row mean sort
                df_pivot = df_pivot.loc[row_means.sort_values(ascending=self.config.sort_ascending).index]
        else:
            # Sort by index (variable values)
            df_pivot = df_pivot.sort_index()

        # Sort columns
        if self.config.sort_cols_by == "values":
            # Sort columns by mean of their values (across all rows)
            col_means = df_pivot.mean(axis=0, skipna=True)
            df_pivot = df_pivot[col_means.sort_values(ascending=self.config.sort_ascending).index]
        else:
            # Sort by index (variable values)
            df_pivot = df_pivot.sort_index(axis=1)

        # Check pivot table size and apply safety limits
        n_rows, n_cols = df_pivot.shape
        pivot_size = n_rows * n_cols

        # Hard limit to prevent memory issues
        MAX_CELLS = 100000
        if pivot_size > MAX_CELLS:
            # Build cardinality info
            cardinality_info = ', '.join(
                f"{col.replace('vars.', '')}={self.df[col].nunique()}"
                for col in group_cols
            )
            raise ValueError(
                f"Coverage heatmap pivot table too large ({n_rows} rows × {n_cols} cols = {pivot_size:,} cells, max: {MAX_CELLS:,}). "
                f"\nSpecified: row_vars={row_vars}, col_var={col_var}"
                f"\nActual cardinalities: {cardinality_info}"
                f"\nThis usually means:"
                f"\n  1. Variables have more unique values than expected (check your data)"
                f"\n  2. You need to specify fewer/different variables"
                f"\n  3. There may be data contamination from other swept variables"
                f"\nTry reducing to 2-3 variables total, or use multiple smaller heatmaps."
            )
        elif pivot_size > 10000:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Coverage heatmap creating large pivot table ({n_rows} rows × {n_cols} cols = {pivot_size:,} cells). "
                f"Performance may be slow. Consider reducing variables."
            )

        # Build heatmap data
        # For multi-index, we need to format the labels
        if isinstance(df_pivot.index, pd.MultiIndex):
            # Format multi-index as tuples for hover text (optimized list comprehension)
            y_labels = [self._format_multiindex_label(idx, row_vars) for idx in df_pivot.index]
        else:
            y_labels = [str(y) for y in df_pivot.index]

        x_labels = [str(x) for x in df_pivot.columns]
        z_values = df_pivot.values

        # Build hover text with variable names and values (optimized)
        # Pre-format row variable text for each row
        if isinstance(df_pivot.index, pd.MultiIndex):
            row_texts = [
                "<br>".join(f"{var_name}: {var_val}" for var_name, var_val in zip(row_vars, y_idx))
                for y_idx in df_pivot.index
            ]
        else:
            row_texts = [f"{row_vars[0]}: {y_idx}" for y_idx in df_pivot.index]

        # Build hover text matrix efficiently
        hover_texts = []
        for i, row_text in enumerate(row_texts):
            hover_row = [
                f"{row_text}<br>{col_var}: {x_val}<br>{self.metric}: {'N/A' if pd.isna(z_values[i, j]) else f'{z_values[i, j]:.4f}'}"
                for j, x_val in enumerate(df_pivot.columns)
            ]
            hover_texts.append(hover_row)

        # Create heatmap
        fig = go.Figure()

        # Customize colorscale to handle NaN if show_missing is True
        colorscale = self.config.colorscale
        nan_mask = pd.isna(z_values)
        if self.config.show_missing and nan_mask.any():
            # Use a custom colorscale that shows NaN differently
            # Replace NaN with a very negative value for visualization
            z_display = z_values.copy()
            # Set NaN to value below minimum for distinct color
            min_val = pd.Series(z_values[~nan_mask]).min() if (~nan_mask).any() else 0
            z_display[nan_mask] = min_val - abs(min_val) * 0.1 - 1
        else:
            z_display = z_values

        # Convert z_display to list to avoid Plotly 6.x binary encoding (bdata/dtype)
        # which can cause blank heatmaps in some browsers
        z_list = z_display.tolist() if hasattr(z_display, 'tolist') else z_display

        fig.add_trace(go.Heatmap(
            x=x_labels,
            y=y_labels,
            z=z_list,
            colorscale=colorscale,
            colorbar=dict(title=f"{self.metric}<br>({agg_func})"),
            text=hover_texts,
            hovertemplate='%{text}<extra></extra>',
        ))

        # Build title
        if len(row_vars) > 1:
            row_vars_str = ", ".join(row_vars)
            default_title = f"{self.metric} Coverage: [{row_vars_str}] × {col_var}"
        else:
            default_title = f"{self.metric} Coverage: {row_vars[0]} × {col_var}"

        fig.update_layout(
            title=self._get_title(default_title),
            xaxis_title=self._get_xaxis_label(col_var),
            yaxis_title=self._get_yaxis_label(", ".join(row_vars)),
            xaxis=dict(type='category', side='bottom'),
            yaxis=dict(type='category', autorange='reversed'),  # Top to bottom
        )

        return self._apply_theme(fig)

    def _format_multiindex_label(self, idx_tuple, var_names):
        """
        Format a multi-index tuple as a readable label.

        Args:
            idx_tuple: Tuple of index values
            var_names: List of variable names corresponding to the tuple

        Returns:
            Formatted string label
        """
        parts = [f"{name}={val}" for name, val in zip(var_names, idx_tuple)]
        return ", ".join(parts)


# ============================================================================
# Utility Functions
# ============================================================================

def get_available_plot_types():
    """Get list of registered plot types."""
    return sorted(_PLOT_REGISTRY.keys())
