"""
IOPS Report Generator - Creates HTML reports with interactive plots.
"""

import json
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime


class ReportGenerator:
    """Generates HTML reports from IOPS benchmark results."""

    def __init__(self, workdir: Path):
        """
        Initialize report generator.

        Args:
            workdir: Path to the benchmark working directory (e.g., /path/to/run_001)
        """
        self.workdir = Path(workdir)
        self.metadata_path = self.workdir / "run_metadata.json"
        self.metadata: Optional[Dict[str, Any]] = None
        self.df: Optional[pd.DataFrame] = None

    def load_metadata(self):
        """Load runtime metadata."""
        if not self.metadata_path.exists():
            raise FileNotFoundError(
                f"Metadata file not found: {self.metadata_path}\n"
                "Make sure you ran the benchmark with the latest version that saves metadata."
            )

        with open(self.metadata_path, 'r') as f:
            self.metadata = json.load(f)

    def load_results(self):
        """Load benchmark results from the output file."""
        if self.metadata is None:
            raise ValueError("Metadata not loaded. Call load_metadata() first.")

        output_info = self.metadata['output']
        output_path = Path(output_info['path'])

        if not output_path.exists():
            raise FileNotFoundError(f"Results file not found: {output_path}")

        # Load based on file type
        if output_info['type'] == 'csv':
            self.df = pd.read_csv(output_path)
        elif output_info['type'] == 'parquet':
            self.df = pd.read_parquet(output_path)
        elif output_info['type'] == 'sqlite':
            import sqlite3
            conn = sqlite3.connect(output_path)
            table = output_info['table'] or 'results'
            self.df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
            conn.close()
        else:
            raise ValueError(f"Unsupported output type: {output_info['type']}")

        # Filter only successful executions
        if 'metadata.__executor_status' in self.df.columns:
            self.df = self.df[self.df['metadata.__executor_status'] == 'SUCCEEDED'].copy()

    def _get_swept_vars(self) -> List[str]:
        """Get list of variables that were swept."""
        swept_vars = []
        for var_name, var_info in self.metadata['variables'].items():
            if var_info.get('swept', False):
                swept_vars.append(var_name)
        return swept_vars

    def _get_report_vars(self) -> List[str]:
        """
        Get list of variables to use for report generation.

        Priority:
        1. Use report_vars from benchmark config if specified
        2. Otherwise, use all swept variables that are numeric (int/float)
        3. Exclude string variables by default (they don't plot well)
        """
        # Check if report_vars is explicitly specified
        report_vars = self.metadata['benchmark'].get('report_vars')

        if report_vars is not None:
            # Use explicitly specified variables
            return report_vars

        # Default: use numeric swept variables only
        swept_vars = self._get_swept_vars()
        numeric_vars = []

        for var_name in swept_vars:
            var_type = self.metadata['variables'][var_name].get('type', '')
            if var_type in ['int', 'float']:
                numeric_vars.append(var_name)

        return numeric_vars

    def _get_metrics(self) -> List[str]:
        """Get list of metrics."""
        return [m['name'] for m in self.metadata['metrics']]

    def _get_var_column(self, var_name: str) -> str:
        """Get the column name for a variable in the dataframe."""
        return f'vars.{var_name}'

    def _get_metric_column(self, metric_name: str) -> str:
        """Get the column name for a metric in the dataframe."""
        return f'metrics.{metric_name}'

    def _compute_pareto_frontier(self, metrics: List[str], objectives: Dict[str, str], report_vars: List[str]) -> pd.DataFrame:
        """
        Compute Pareto frontier for multiple metrics.

        Args:
            metrics: List of metric names to consider
            objectives: Dict mapping metric name to objective ('maximize' or 'minimize')
            report_vars: List of variables to group by

        Returns:
            DataFrame with Pareto-optimal configurations
        """
        if self.df is None:
            return pd.DataFrame()

        var_cols = [self._get_var_column(v) for v in report_vars]
        metric_cols = [self._get_metric_column(m) for m in metrics]

        # Group by parameter combination and get mean of metrics
        df_grouped = self.df.groupby(var_cols)[metric_cols].mean().reset_index()

        # Normalize metrics based on objectives
        df_normalized = df_grouped.copy()
        for metric in metrics:
            col = self._get_metric_column(metric)
            if objectives.get(metric, 'maximize') == 'minimize':
                # For minimization, negate the values
                df_normalized[col] = -df_normalized[col]

        # Find Pareto frontier
        is_pareto = pd.Series([True] * len(df_normalized))

        for i in range(len(df_normalized)):
            if not is_pareto[i]:
                continue

            for j in range(len(df_normalized)):
                if i == j or not is_pareto[j]:
                    continue

                # Check if j dominates i
                dominates = True
                strictly_better = False

                for col in metric_cols:
                    val_i = df_normalized.iloc[i][col]
                    val_j = df_normalized.iloc[j][col]

                    if val_j < val_i:
                        dominates = False
                        break
                    elif val_j > val_i:
                        strictly_better = True

                if dominates and strictly_better:
                    is_pareto[i] = False
                    break

        return df_grouped[is_pareto].reset_index(drop=True)

    def generate_report(self, output_path: Optional[Path] = None) -> Path:
        """
        Generate complete HTML report with all plots.

        Args:
            output_path: Path for output HTML file. If None, uses workdir/analysis_report.html

        Returns:
            Path to generated HTML file
        """
        if self.metadata is None or self.df is None:
            raise ValueError("Load metadata and results first")

        if output_path is None:
            output_path = self.workdir / "analysis_report.html"

        # Get report variables and metrics
        report_vars = self._get_report_vars()
        metrics = self._get_metrics()

        if not report_vars:
            raise ValueError("No report variables found. Either specify report_vars in config or ensure you have numeric swept variables.")
        if not metrics:
            raise ValueError("No metrics found in metadata")

        # Build HTML report
        html_parts = []
        html_parts.append(self._generate_header())
        html_parts.append(self._generate_summary_section(report_vars, metrics))
        html_parts.append(self._generate_best_configs_section(metrics, report_vars))

        # Add Pareto frontier section if we have multiple metrics
        if len(metrics) >= 2:
            html_parts.append(self._generate_pareto_section(metrics, report_vars))

        # Generate plots for each metric
        for metric in metrics:
            html_parts.append(self._generate_metric_section(metric, report_vars))

        html_parts.append(self._generate_footer())

        # Combine and save
        html_content = "\n".join(html_parts)
        with open(output_path, 'w') as f:
            f.write(html_content)

        return output_path

    def _generate_header(self) -> str:
        """Generate HTML header."""
        benchmark_name = self.metadata['benchmark']['name']
        timestamp = self.metadata['benchmark']['timestamp']

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{benchmark_name} - Analysis Report</title>
    <script src="https://cdn.plot.ly/plotly-2.26.0.min.js"></script>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            border-radius: 8px;
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 40px;
            border-bottom: 2px solid #95a5a6;
            padding-bottom: 8px;
        }}
        h3 {{
            color: #555;
            margin-top: 25px;
        }}
        .info-box {{
            background-color: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            margin: 20px 0;
        }}
        .info-box p {{
            margin: 5px 0;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 20px 0;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 12px;
            text-align: left;
        }}
        th {{
            background-color: #3498db;
            color: white;
        }}
        tr:nth-child(even) {{
            background-color: #f9f9f9;
        }}
        tr:hover {{
            background-color: #f5f5f5;
        }}
        .plot-container {{
            margin: 30px 0;
        }}
        .metric-section {{
            margin-top: 50px;
            padding-top: 30px;
            border-top: 3px solid #e0e0e0;
        }}
        .footer {{
            margin-top: 50px;
            text-align: center;
            color: #95a5a6;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
<div class="container">
    <h1>{benchmark_name} - Analysis Report</h1>
    <div class="info-box">
        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p><strong>Benchmark Run:</strong> {timestamp}</p>
        <p><strong>Description:</strong> {self.metadata['benchmark'].get('description', 'N/A')}</p>
        <p><strong>Total Tests:</strong> {len(self.df)}</p>
    </div>
"""

    def _generate_summary_section(self, report_vars: List[str], metrics: List[str]) -> str:
        """Generate summary statistics section."""
        html = "<h2>Summary Statistics</h2>\n"

        # Variable ranges
        html += "<h3>Report Variables</h3>\n<table>\n"
        html += "<tr><th>Variable</th><th>Type</th><th>Values</th></tr>\n"

        for var in report_vars:
            col = self._get_var_column(var)
            var_info = self.metadata['variables'][var]
            var_type = var_info['type']
            unique_values = sorted(self.df[col].unique())
            values_str = ", ".join(str(v) for v in unique_values)
            html += f"<tr><td><strong>{var}</strong></td><td>{var_type}</td><td>{values_str}</td></tr>\n"

        html += "</table>\n"

        # Metric statistics
        html += "<h3>Metrics Overview</h3>\n<table>\n"
        html += "<tr><th>Metric</th><th>Min</th><th>Max</th><th>Mean</th><th>Std Dev</th></tr>\n"

        for metric in metrics:
            col = self._get_metric_column(metric)
            if col in self.df.columns:
                stats = self.df[col].describe()
                html += f"<tr><td><strong>{metric}</strong></td>"
                html += f"<td>{stats['min']:.4f}</td>"
                html += f"<td>{stats['max']:.4f}</td>"
                html += f"<td>{stats['mean']:.4f}</td>"
                html += f"<td>{stats['std']:.4f}</td></tr>\n"

        html += "</table>\n"

        return html

    def _generate_best_configs_section(self, metrics: List[str], report_vars: List[str]) -> str:
        """Generate best configurations section."""
        html = "<h2>Best Configurations</h2>\n"
        html += "<p>Top 5 configurations for each metric:</p>\n"

        var_cols = [self._get_var_column(v) for v in report_vars]

        for metric in metrics:
            metric_col = self._get_metric_column(metric)
            if metric_col not in self.df.columns:
                continue

            html += f"<h3>Best for {metric}</h3>\n"

            # Group by parameter combination and get mean
            group_cols = var_cols
            df_grouped = self.df.groupby(group_cols)[metric_col].agg(['mean', 'std', 'count']).reset_index()
            df_grouped.columns = report_vars + ['mean', 'std', 'count']

            # Sort by mean (descending for most metrics, ascending for latency/time)
            ascending = 'latency' in metric.lower() or 'time' in metric.lower()
            df_top = df_grouped.sort_values('mean', ascending=ascending).head(5)

            html += "<table>\n<tr><th>Rank</th>"
            for var in report_vars:
                html += f"<th>{var}</th>"
            html += f"<th>{metric} (mean)</th><th>Std Dev</th><th>Samples</th></tr>\n"

            for idx, (i, row) in enumerate(df_top.iterrows(), 1):
                html += f"<tr><td>{idx}</td>"
                for var in report_vars:
                    html += f"<td>{row[var]}</td>"
                html += f"<td><strong>{row['mean']:.4f}</strong></td>"
                html += f"<td>{row['std']:.4f}</td>"
                html += f"<td>{int(row['count'])}</td></tr>\n"

            html += "</table>\n"

        return html

    def _generate_pareto_section(self, metrics: List[str], report_vars: List[str]) -> str:
        """Generate Pareto frontier analysis section."""
        html = "<h2>Pareto Frontier Analysis</h2>\n"
        html += "<p>The Pareto frontier shows configurations where you cannot improve one metric without degrading another. "
        html += "These are the optimal trade-off points when optimizing multiple objectives.</p>\n"

        # Determine objectives automatically
        objectives = {}
        for metric in metrics:
            # Common patterns for metrics to minimize
            if any(keyword in metric.lower() for keyword in ['latency', 'time', 'duration', 'delay', 'overhead']):
                objectives[metric] = 'minimize'
            else:
                objectives[metric] = 'maximize'

        html += "<h3>Objectives</h3>\n<ul>\n"
        for metric in metrics:
            obj = objectives[metric]
            icon = "↓" if obj == "minimize" else "↑"
            html += f"<li><strong>{metric}</strong>: {obj} {icon}</li>\n"
        html += "</ul>\n"

        # Compute Pareto frontier
        pareto_df = self._compute_pareto_frontier(metrics, objectives, report_vars)

        if len(pareto_df) == 0:
            html += "<p>No Pareto-optimal configurations found.</p>\n"
            return html

        html += f"<h3>Pareto-Optimal Configurations ({len(pareto_df)} found)</h3>\n"

        # Table of Pareto-optimal configs
        var_cols = [self._get_var_column(v) for v in report_vars]
        metric_cols = [self._get_metric_column(m) for m in metrics]

        html += "<table>\n<tr><th>Rank</th>"
        for var in report_vars:
            html += f"<th>{var}</th>"
        for metric in metrics:
            html += f"<th>{metric}</th>"
        html += "</tr>\n"

        for idx, (i, row) in enumerate(pareto_df.iterrows(), 1):
            html += f"<tr><td>{idx}</td>"
            for var_col in var_cols:
                html += f"<td>{row[var_col]}</td>"
            for metric_col in metric_cols:
                html += f"<td><strong>{row[metric_col]:.4f}</strong></td>"
            html += "</tr>\n"

        html += "</table>\n"

        # Generate Pareto plots (2D scatter plots for pairs of metrics)
        if len(metrics) >= 2:
            html += "<h3>Pareto Frontier Visualization</h3>\n"

            # Create plots for first two metrics (most common case)
            fig = self._create_pareto_plot(metrics[0], metrics[1], objectives, report_vars)
            html += '<div class="plot-container">\n'
            html += fig.to_html(full_html=False, include_plotlyjs=False)
            html += '</div>\n'

            # If we have 3+ metrics, create additional pairwise plots
            if len(metrics) >= 3:
                fig2 = self._create_pareto_plot(metrics[0], metrics[2], objectives, report_vars)
                html += '<div class="plot-container">\n'
                html += fig2.to_html(full_html=False, include_plotlyjs=False)
                html += '</div>\n'

        return html

    def _generate_metric_section(self, metric: str, swept_vars: List[str]) -> str:
        """Generate plots section for a specific metric."""
        html = f'<div class="metric-section">\n'
        html += f"<h2>Analysis: {metric}</h2>\n"

        metric_col = self._get_metric_column(metric)
        if metric_col not in self.df.columns:
            html += f"<p>Metric '{metric}' not found in results.</p>\n"
            html += "</div>\n"
            return html

        # 1. Bar plot of mean values by first swept variable
        if len(swept_vars) >= 1:
            fig = self._create_bar_plot(metric, swept_vars[0])
            html += '<div class="plot-container">\n'
            html += fig.to_html(full_html=False, include_plotlyjs=False)
            html += '</div>\n'

        # 2. Line plot if we have 2+ swept variables
        if len(swept_vars) >= 2:
            fig = self._create_line_plot(metric, swept_vars[0], swept_vars[1])
            html += '<div class="plot-container">\n'
            html += fig.to_html(full_html=False, include_plotlyjs=False)
            html += '</div>\n'

        # 3. Heatmap if we have exactly 2 swept variables
        if len(swept_vars) == 2:
            fig = self._create_heatmap(metric, swept_vars[0], swept_vars[1])
            html += '<div class="plot-container">\n'
            html += fig.to_html(full_html=False, include_plotlyjs=False)
            html += '</div>\n'

        # 4. 3D scatter if we have 3 swept variables
        if len(swept_vars) >= 3:
            fig = self._create_3d_scatter(metric, swept_vars[0], swept_vars[1], swept_vars[2])
            html += '<div class="plot-container">\n'
            html += fig.to_html(full_html=False, include_plotlyjs=False)
            html += '</div>\n'

        html += '</div>\n'
        return html

    def _create_bar_plot(self, metric: str, var: str) -> go.Figure:
        """Create bar plot of metric vs variable."""
        metric_col = self._get_metric_column(metric)
        var_col = self._get_var_column(var)

        df_grouped = self.df.groupby(var_col)[metric_col].agg(['mean', 'std']).reset_index()
        df_grouped = df_grouped.sort_values(var_col)

        # Convert x values to strings to ensure categorical axis
        x_values = [str(x) for x in df_grouped[var_col]]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=x_values,
            y=df_grouped['mean'],
            error_y=dict(type='data', array=df_grouped['std']),
            name=metric,
            text=[f'{v:.2f}' for v in df_grouped['mean']],
            textposition='outside'
        ))

        fig.update_layout(
            title=f"{metric} vs {var}",
            xaxis_title=var,
            yaxis_title=metric,
            template='plotly_white',
            height=500,
            xaxis=dict(type='category')  # Force categorical axis
        )

        return fig

    def _create_line_plot(self, metric: str, var1: str, var2: str) -> go.Figure:
        """Create line plot with multiple series."""
        metric_col = self._get_metric_column(metric)
        var1_col = self._get_var_column(var1)
        var2_col = self._get_var_column(var2)

        df_grouped = self.df.groupby([var1_col, var2_col])[metric_col].mean().reset_index()

        fig = go.Figure()

        # Get sorted unique values for consistent ordering
        all_var1_values = sorted(df_grouped[var1_col].unique())
        x_values = [str(x) for x in all_var1_values]

        for val2 in sorted(df_grouped[var2_col].unique()):
            df_slice = df_grouped[df_grouped[var2_col] == val2].sort_values(var1_col)

            # Map var1 values to categorical strings
            x_slice = [str(x) for x in df_slice[var1_col]]

            fig.add_trace(go.Scatter(
                x=x_slice,
                y=df_slice[metric_col],
                mode='lines+markers',
                name=f'{var2}={val2}',
                marker=dict(size=10)
            ))

        fig.update_layout(
            title=f"{metric} vs {var1} (grouped by {var2})",
            xaxis_title=var1,
            yaxis_title=metric,
            template='plotly_white',
            height=500,
            hovermode='x unified',
            xaxis=dict(
                type='category',
                categoryorder='array',
                categoryarray=x_values
            )
        )

        return fig

    def _create_heatmap(self, metric: str, var1: str, var2: str) -> go.Figure:
        """Create heatmap for 2D parameter space."""
        metric_col = self._get_metric_column(metric)
        var1_col = self._get_var_column(var1)
        var2_col = self._get_var_column(var2)

        pivot = self.df.groupby([var1_col, var2_col])[metric_col].mean().reset_index().pivot(
            index=var2_col, columns=var1_col, values=metric_col
        )

        # Convert to strings for categorical axes
        x_labels = [str(x) for x in sorted(pivot.columns)]
        y_labels = [str(y) for y in sorted(pivot.index)]

        # Reindex to ensure proper ordering
        pivot = pivot.reindex(index=sorted(pivot.index), columns=sorted(pivot.columns))

        fig = go.Figure(data=go.Heatmap(
            z=pivot.values,
            x=x_labels,
            y=y_labels,
            colorscale='Viridis',
            hovertemplate=f'{var1}=%{{x}}<br>{var2}=%{{y}}<br>{metric}=%{{z:.4f}}<extra></extra>',
            colorbar=dict(title=metric)
        ))

        fig.update_layout(
            title=f"Heatmap: {metric} by {var1} and {var2}",
            xaxis_title=var1,
            yaxis_title=var2,
            template='plotly_white',
            height=500,
            xaxis=dict(type='category'),
            yaxis=dict(type='category')
        )

        return fig

    def _create_3d_scatter(self, metric: str, var1: str, var2: str, var3: str) -> go.Figure:
        """Create 3D scatter plot for 3 variables."""
        metric_col = self._get_metric_column(metric)
        var1_col = self._get_var_column(var1)
        var2_col = self._get_var_column(var2)
        var3_col = self._get_var_column(var3)

        df_grouped = self.df.groupby([var1_col, var2_col, var3_col])[metric_col].mean().reset_index()

        # Get unique values for each axis
        var1_vals = sorted(df_grouped[var1_col].unique())
        var2_vals = sorted(df_grouped[var2_col].unique())
        var3_vals = sorted(df_grouped[var3_col].unique())

        fig = go.Figure(data=go.Scatter3d(
            x=df_grouped[var1_col],
            y=df_grouped[var2_col],
            z=df_grouped[var3_col],
            mode='markers',
            marker=dict(
                size=10,
                color=df_grouped[metric_col],
                colorscale='Viridis',
                showscale=True,
                colorbar=dict(title=metric)
            ),
            text=[f'{metric}: {v:.4f}' for v in df_grouped[metric_col]],
            hovertemplate=f'{var1}=%{{x}}<br>{var2}=%{{y}}<br>{var3}=%{{z}}<br>%{{text}}<extra></extra>'
        ))

        fig.update_layout(
            title=f"3D Scatter: {metric} by {var1}, {var2}, {var3}",
            scene=dict(
                xaxis=dict(
                    title=var1,
                    tickmode='array',
                    tickvals=var1_vals,
                    ticktext=[str(v) for v in var1_vals]
                ),
                yaxis=dict(
                    title=var2,
                    tickmode='array',
                    tickvals=var2_vals,
                    ticktext=[str(v) for v in var2_vals]
                ),
                zaxis=dict(
                    title=var3,
                    tickmode='array',
                    tickvals=var3_vals,
                    ticktext=[str(v) for v in var3_vals]
                )
            ),
            template='plotly_white',
            height=600
        )

        return fig

    def _create_pareto_plot(self, metric1: str, metric2: str, objectives: Dict[str, str], report_vars: List[str]) -> go.Figure:
        """Create 2D Pareto frontier plot."""
        metric1_col = self._get_metric_column(metric1)
        metric2_col = self._get_metric_column(metric2)

        var_cols = [self._get_var_column(v) for v in report_vars]

        # Get all configurations grouped by parameters
        df_grouped = self.df.groupby(var_cols)[[metric1_col, metric2_col]].mean().reset_index()

        # Compute Pareto frontier
        pareto_df = self._compute_pareto_frontier([metric1, metric2], objectives, report_vars)

        # Merge to identify which points are on frontier
        merge_cols = var_cols
        df_with_pareto = df_grouped.merge(
            pareto_df[merge_cols].assign(_is_pareto=True),
            on=merge_cols,
            how='left'
        )
        df_with_pareto['_is_pareto'] = df_with_pareto['_is_pareto'].fillna(False)

        # Create hover text with parameter values
        hover_text = []
        for _, row in df_with_pareto.iterrows():
            text_parts = [f"{var}: {row[self._get_var_column(var)]}" for var in report_vars]
            text_parts.append(f"{metric1}: {row[metric1_col]:.4f}")
            text_parts.append(f"{metric2}: {row[metric2_col]:.4f}")
            hover_text.append("<br>".join(text_parts))

        fig = go.Figure()

        # Non-Pareto points
        df_non_pareto = df_with_pareto[~df_with_pareto['_is_pareto']]
        if len(df_non_pareto) > 0:
            fig.add_trace(go.Scatter(
                x=df_non_pareto[metric1_col],
                y=df_non_pareto[metric2_col],
                mode='markers',
                name='Non-optimal',
                marker=dict(size=10, color='lightgray', opacity=0.6),
                text=[hover_text[i] for i in df_non_pareto.index],
                hovertemplate='%{text}<extra></extra>'
            ))

        # Pareto points
        df_pareto_plot = df_with_pareto[df_with_pareto['_is_pareto']]
        if len(df_pareto_plot) > 0:
            # Sort for line connection
            if objectives.get(metric1, 'maximize') == 'maximize':
                df_pareto_plot = df_pareto_plot.sort_values(metric1_col)
            else:
                df_pareto_plot = df_pareto_plot.sort_values(metric1_col, ascending=False)

            fig.add_trace(go.Scatter(
                x=df_pareto_plot[metric1_col],
                y=df_pareto_plot[metric2_col],
                mode='markers+lines',
                name='Pareto Frontier',
                marker=dict(size=14, color='red', symbol='star'),
                line=dict(color='red', width=2, dash='dash'),
                text=[hover_text[i] for i in df_pareto_plot.index],
                hovertemplate='%{text}<extra></extra>'
            ))

        # Add axis labels with objectives
        obj1 = objectives.get(metric1, 'maximize')
        obj2 = objectives.get(metric2, 'maximize')
        icon1 = "↑" if obj1 == "maximize" else "↓"
        icon2 = "↑" if obj2 == "maximize" else "↓"

        fig.update_layout(
            title=f"Pareto Frontier: {metric1} vs {metric2}",
            xaxis_title=f"{metric1} ({obj1} {icon1})",
            yaxis_title=f"{metric2} ({obj2} {icon2})",
            template='plotly_white',
            height=600,
            hovermode='closest',
            showlegend=True
        )

        return fig

    def _generate_footer(self) -> str:
        """Generate HTML footer."""
        return f"""
    <div class="footer">
        <p>Generated by IOPS Analysis Tool - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
</div>
</body>
</html>
"""


def generate_report_from_workdir(workdir: Path, output_path: Optional[Path] = None) -> Path:
    """
    Convenience function to generate report from a workdir.

    Args:
        workdir: Path to benchmark working directory
        output_path: Optional custom output path

    Returns:
        Path to generated HTML report
    """
    generator = ReportGenerator(workdir)
    generator.load_metadata()
    generator.load_results()
    return generator.generate_report(output_path)
