"""
IOPS Report Generator - Creates HTML reports with interactive plots.
"""

import json
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from jinja2 import Template

from iops.config.models import (
    ReportingConfig,
    ReportThemeConfig,
    PlotConfig,
    MetricPlotsConfig,
    SectionConfig,
    BestResultsConfig,
    PlotDefaultsConfig,
)


class ReportGenerator:
    """Generates HTML reports from IOPS benchmark results."""

    def __init__(self, workdir: Path, report_config: Optional[ReportingConfig] = None):
        """
        Initialize report generator.

        Args:
            workdir: Path to the benchmark working directory (e.g., /path/to/run_001)
            report_config: Optional reporting configuration (overrides metadata config)
        """
        self.workdir = Path(workdir)
        self.metadata_path = self.workdir / "run_metadata.json"
        self.metadata: Optional[Dict[str, Any]] = None
        self.df: Optional[pd.DataFrame] = None
        self.report_config: Optional[ReportingConfig] = report_config

    def load_metadata(self):
        """Load runtime metadata and reporting configuration."""
        if not self.metadata_path.exists():
            raise FileNotFoundError(
                f"Metadata file not found: {self.metadata_path}\n"
                "Make sure you ran the benchmark with the latest version that saves metadata."
            )

        with open(self.metadata_path, 'r') as f:
            self.metadata = json.load(f)

        # Load reporting config with priority: override > metadata > legacy defaults
        if self.report_config is None:
            if 'reporting' in self.metadata and self.metadata['reporting'] is not None:
                # Modern metadata: load reporting config
                self.report_config = self._deserialize_reporting_config(
                    self.metadata['reporting']
                )
            else:
                # Legacy metadata: use defaults matching old behavior
                self.report_config = self._create_legacy_defaults()

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

        # Validate and filter metrics to only those available in results
        self._validate_and_filter_metrics()

    def _validate_and_filter_metrics(self):
        """
        Validate that metrics in metadata exist in results and filter out missing ones.

        This handles cases where:
        - Metrics were added to config after a run was executed
        - Parser returned None for a metric (doesn't create column)
        - Configuration was updated but old results are being analyzed
        """
        import logging
        logger = logging.getLogger(__name__)

        # Get available metric columns from results
        available_metrics = set([
            col.replace('metrics.', '')
            for col in self.df.columns
            if col.startswith('metrics.')
        ])

        # Get declared metrics from metadata
        declared_metrics = set([m['name'] for m in self.metadata['metrics']])

        # Identify missing metrics
        missing_metrics = declared_metrics - available_metrics

        if missing_metrics:
            # Log warning about missing metrics
            logger.warning(
                f"Metrics declared in metadata but not found in results (will be skipped): "
                f"{sorted(missing_metrics)}"
            )
            logger.info(
                f"Generating report with {len(available_metrics)} of "
                f"{len(declared_metrics)} declared metrics"
            )

            # Filter metadata to only include available metrics
            self.metadata['metrics'] = [
                m for m in self.metadata['metrics']
                if m['name'] in available_metrics
            ]

            # Filter reporting config to skip plots for missing metrics
            if self.report_config and self.report_config.metrics:
                # Remove metric configurations for missing metrics
                filtered_metrics = {
                    metric_name: metric_config
                    for metric_name, metric_config in self.report_config.metrics.items()
                    if metric_name in available_metrics
                }
                self.report_config.metrics = filtered_metrics

                # Log which plot configurations were removed
                removed_metrics = set(self.report_config.metrics.keys()) - set(filtered_metrics.keys())
                if removed_metrics:
                    logger.warning(
                        f"Removed plot configurations for missing metrics: {sorted(removed_metrics)}"
                    )

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

    def _render_command(self, var_values: Dict[str, Any]) -> str:
        """
        Render the command template with given variable values.

        Args:
            var_values: Dictionary mapping variable names to their values

        Returns:
            Rendered command string
        """
        try:
            command_template = self.metadata['command']['template']
            template = Template(command_template)
            rendered = template.render(**var_values)
            return rendered.strip()
        except Exception as e:
            return f"[Error rendering command: {e}]"

    def _deserialize_reporting_config(self, data: Dict[str, Any]) -> ReportingConfig:
        """Deserialize reporting config from metadata JSON."""
        def deserialize_plot(plot_data):
            return PlotConfig(
                type=plot_data['type'],
                x_var=plot_data.get('x_var'),
                y_var=plot_data.get('y_var'),
                z_metric=plot_data.get('z_metric'),
                group_by=plot_data.get('group_by'),
                color_by=plot_data.get('color_by'),
                size_by=plot_data.get('size_by'),
                title=plot_data.get('title'),
                xaxis_label=plot_data.get('xaxis_label'),
                yaxis_label=plot_data.get('yaxis_label'),
                colorscale=plot_data.get('colorscale', 'Viridis'),
                show_error_bars=plot_data.get('show_error_bars', True),
                show_outliers=plot_data.get('show_outliers', True),
                height=plot_data.get('height'),
                width=plot_data.get('width'),
                per_variable=plot_data.get('per_variable', False),
                include_metric=plot_data.get('include_metric', True),
            )

        theme = ReportThemeConfig(
            style=data.get('theme', {}).get('style', 'plotly_white'),
            colors=data.get('theme', {}).get('colors'),
            font_family=data.get('theme', {}).get('font_family', 'Segoe UI, sans-serif'),
        )

        sections = SectionConfig(
            test_summary=data.get('sections', {}).get('test_summary', True),
            best_results=data.get('sections', {}).get('best_results', True),
            variable_impact=data.get('sections', {}).get('variable_impact', True),
            parallel_coordinates=data.get('sections', {}).get('parallel_coordinates', True),
            pareto_frontier=data.get('sections', {}).get('pareto_frontier', True),
            bayesian_evolution=data.get('sections', {}).get('bayesian_evolution', True),
            custom_plots=data.get('sections', {}).get('custom_plots', True),
        )

        best_results = BestResultsConfig(
            top_n=data.get('best_results', {}).get('top_n', 5),
            show_command=data.get('best_results', {}).get('show_command', True),
        )

        plot_defaults = PlotDefaultsConfig(
            height=data.get('plot_defaults', {}).get('height', 500),
            width=data.get('plot_defaults', {}).get('width'),
            margin=data.get('plot_defaults', {}).get('margin'),
        )

        metrics = {}
        for metric_name, metric_data in data.get('metrics', {}).items():
            plots = [deserialize_plot(p) for p in metric_data.get('plots', [])]
            metrics[metric_name] = MetricPlotsConfig(plots=plots)

        default_plots = [deserialize_plot(p) for p in data.get('default_plots', [])]

        output_dir = None
        if data.get('output_dir'):
            output_dir = Path(data['output_dir'])

        return ReportingConfig(
            enabled=data.get('enabled', False),
            output_dir=output_dir,
            output_filename=data.get('output_filename', 'analysis_report.html'),
            theme=theme,
            sections=sections,
            best_results=best_results,
            metrics=metrics,
            default_plots=default_plots,
            plot_defaults=plot_defaults,
        )

    def _create_legacy_defaults(self) -> ReportingConfig:
        """Create default config matching legacy behavior for old workdirs."""
        return ReportingConfig(
            enabled=False,  # Wasn't auto-generated before
            sections=SectionConfig(
                test_summary=True,
                best_results=True,
                variable_impact=True,
                parallel_coordinates=True,
                pareto_frontier=True,
                bayesian_evolution=True,
                custom_plots=True,  # Will use legacy plots
            ),
            metrics={},  # Empty triggers legacy plot generation
            default_plots=[],  # Empty triggers legacy plots
            theme=ReportThemeConfig(),
            best_results=BestResultsConfig(),
            plot_defaults=PlotDefaultsConfig(),
        )

    def _calculate_total_execution_time(self) -> tuple[Optional[float], Optional[str]]:
        """
        Calculate total execution time from first test start to last test end.
        Excludes cached results to avoid mixing timestamps from different runs.

        Returns:
            Tuple of (seconds, formatted_string) or (None, None) if timestamps unavailable
        """
        try:
            # Filter out cached results (they have timestamps from previous runs)
            df_executed = self.df.copy()
            if 'metadata.__cached' in df_executed.columns:
                df_executed = df_executed[df_executed['metadata.__cached'] != True]

            # If all results were cached, we can't calculate execution time for this run
            if len(df_executed) == 0:
                return None, None

            start_times = pd.to_datetime(df_executed['metadata.__start'], errors='coerce')
            end_times = pd.to_datetime(df_executed['metadata.__end'], errors='coerce')

            if start_times.isna().all() or end_times.isna().all():
                return None, None

            first_start = start_times.min()
            last_end = end_times.max()

            total_seconds = (last_end - first_start).total_seconds()

            # Format as human-readable
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            seconds = int(total_seconds % 60)

            if hours > 0:
                formatted = f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                formatted = f"{minutes}m {seconds}s"
            else:
                formatted = f"{seconds}s"

            return total_seconds, formatted

        except Exception as e:
            return None, None

    def _calculate_total_core_hours(self) -> Optional[float]:
        """
        Calculate total core-hours consumed by all tests.

        Returns:
            Total core-hours or None if cannot be calculated
        """
        try:
            cores_expr = self.metadata['benchmark'].get('cores_expr')
            if not cores_expr:
                return None

            # Parse timestamps
            start_times = pd.to_datetime(self.df['metadata.__start'], errors='coerce')
            end_times = pd.to_datetime(self.df['metadata.__end'], errors='coerce')

            if start_times.isna().all() or end_times.isna().all():
                return None

            # Calculate duration for each test
            durations_hours = (end_times - start_times).dt.total_seconds() / 3600.0

            # Calculate cores for each test using cores_expr
            template = Template(cores_expr)
            total_core_hours = 0.0

            for idx, row in self.df.iterrows():
                # Extract variable values for this row
                var_values = {}
                for var_name in self.metadata['variables'].keys():
                    col = self._get_var_column(var_name)
                    if col in self.df.columns:
                        var_values[var_name] = row[col]

                # Render cores expression
                try:
                    cores_str = template.render(**var_values)
                    cores = eval(cores_str)  # Safe here as we control the template
                    core_hours = cores * durations_hours.iloc[idx]
                    total_core_hours += core_hours
                except Exception:
                    continue

            return total_core_hours

        except Exception as e:
            return None

    def _calculate_average_cores(self) -> Optional[float]:
        """
        Calculate average number of cores used per test.

        Returns:
            Average cores or None if cannot be calculated
        """
        try:
            cores_expr = self.metadata['benchmark'].get('cores_expr')
            if not cores_expr:
                return None

            template = Template(cores_expr)
            total_cores = 0
            count = 0

            for idx, row in self.df.iterrows():
                # Extract variable values for this row
                var_values = {}
                for var_name in self.metadata['variables'].keys():
                    col = self._get_var_column(var_name)
                    if col in self.df.columns:
                        var_values[var_name] = row[col]

                # Render cores expression
                try:
                    cores_str = template.render(**var_values)
                    cores = eval(cores_str)  # Safe here as we control the template
                    total_cores += cores
                    count += 1
                except Exception:
                    continue

            return total_cores / count if count > 0 else None

        except Exception as e:
            return None

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

        # Summary statistics first
        html_parts.append(self._generate_summary_section(report_vars, metrics))

        # Best configurations immediately after summary
        html_parts.append(self._generate_best_configs_section(metrics, report_vars))

        # Add Pareto frontier section if we have multiple metrics
        if len(metrics) >= 2:
            html_parts.append(self._generate_pareto_section(metrics, report_vars))

        # Add Bayesian optimization section if applicable (before plots)
        search_method = self.metadata['benchmark'].get('search_method', '').lower()
        if search_method == 'bayesian':
            html_parts.append(self._generate_bayesian_optimization_section(metrics, report_vars))

        # Add comprehensive variable analysis section
        html_parts.append(self._generate_variable_analysis_section(metrics, report_vars))

        # All detailed plots at the end
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
        .error {{
            background-color: #fee;
            border: 1px solid #fcc;
            border-radius: 4px;
            padding: 10px;
            margin: 10px 0;
            color: #c33;
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

        # Execution Overview
        html += "<h3>Execution Overview</h3>\n<table>\n"
        html += "<tr><th>Metric</th><th>Value</th></tr>\n"

        # Benchmark metadata
        benchmark_meta = self.metadata['benchmark']
        html += f"<tr><td><strong>Benchmark Name</strong></td><td>{benchmark_meta.get('name', 'N/A')}</td></tr>\n"

        # Hostname (if available)
        hostname = benchmark_meta.get('hostname')
        if hostname:
            html += f"<tr><td><strong>Hostname</strong></td><td>{hostname}</td></tr>\n"

        # Executor type
        executor = benchmark_meta.get('executor', 'local')
        html += f"<tr><td><strong>Executor</strong></td><td>{executor}</td></tr>\n"

        # Search method
        search_method = benchmark_meta.get('search_method', 'exhaustive')
        html += f"<tr><td><strong>Search Method</strong></td><td>{search_method}</td></tr>\n"

        # Benchmark timing (if available, prefer detailed timing over legacy timestamp)
        if 'benchmark_start_time' in benchmark_meta and 'benchmark_end_time' in benchmark_meta:
            start_time = benchmark_meta['benchmark_start_time']
            end_time = benchmark_meta['benchmark_end_time']
            html += f"<tr><td><strong>Benchmark Start Time</strong></td><td>{start_time}</td></tr>\n"
            html += f"<tr><td><strong>Benchmark End Time</strong></td><td>{end_time}</td></tr>\n"

            if 'total_runtime_seconds' in benchmark_meta:
                total_runtime = benchmark_meta['total_runtime_seconds']
                if total_runtime < 60:
                    runtime_str = f"{total_runtime:.1f}s"
                elif total_runtime < 3600:
                    runtime_str = f"{total_runtime/60:.1f}m ({total_runtime:.1f}s)"
                else:
                    runtime_str = f"{total_runtime/3600:.2f}h ({total_runtime/60:.1f}m)"
                html += f"<tr><td><strong>Total Benchmark Runtime</strong></td><td>{runtime_str}</td></tr>\n"
        elif 'timestamp' in benchmark_meta:
            # Fallback to legacy timestamp if detailed timing not available
            html += f"<tr><td><strong>Benchmark Started</strong></td><td>{benchmark_meta['timestamp']}</td></tr>\n"

        # Report generation timestamp
        report_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        html += f"<tr><td><strong>Report Generated</strong></td><td>{report_timestamp}</td></tr>\n"

        html += "</table>\n"

        # Test Execution Statistics
        html += "<h3>Test Execution Statistics</h3>\n<table>\n"
        html += "<tr><th>Metric</th><th>Value</th></tr>\n"

        # Total tests
        total_tests = len(self.df)
        html += f"<tr><td><strong>Total Parameter Combinations</strong></td><td>{total_tests}</td></tr>\n"

        # Success rate (if status column exists)
        if 'metadata.__executor_status' in self.df.columns:
            status_counts = self.df['metadata.__executor_status'].value_counts()
            succeeded = status_counts.get('SUCCEEDED', 0)
            failed = status_counts.get('FAILED', 0)
            cancelled = status_counts.get('CANCELLED', 0)

            success_rate = (succeeded / total_tests * 100) if total_tests > 0 else 0
            html += f"<tr><td><strong>Success Rate</strong></td><td>{succeeded}/{total_tests} ({success_rate:.1f}%)</td></tr>\n"

            if failed > 0:
                html += f"<tr><td><strong>Failed Tests</strong></td><td>{failed}</td></tr>\n"
            if cancelled > 0:
                html += f"<tr><td><strong>Cancelled Tests</strong></td><td>{cancelled}</td></tr>\n"

        # Check for cached results
        cached_count = 0
        if 'metadata.__cached' in self.df.columns:
            cached_count = (self.df['metadata.__cached'] == True).sum()
            if cached_count > 0:
                executed_count = total_tests - cached_count
                cache_rate = (cached_count / total_tests * 100) if total_tests > 0 else 0
                html += f"<tr><td><strong>Cached Results</strong></td><td>{cached_count} ({cache_rate:.1f}%)</td></tr>\n"
                html += f"<tr><td><strong>Executed Tests</strong></td><td>{executed_count}</td></tr>\n"

        # Execution time
        if 'metadata.__start' in self.df.columns and 'metadata.__end' in self.df.columns:
            execution_time, formatted_time = self._calculate_total_execution_time()
            if execution_time is not None:
                exec_time_label = "Total Execution Time" + (" (executed tests only)" if cached_count > 0 else "")
                html += f"<tr><td><strong>{exec_time_label}</strong></td><td>{formatted_time}</td></tr>\n"

                # Average test duration
                executed_count = total_tests - cached_count if cached_count > 0 else total_tests
                if executed_count > 0:
                    avg_duration = execution_time / executed_count
                    if avg_duration < 60:
                        avg_duration_str = f"{avg_duration:.1f}s"
                    elif avg_duration < 3600:
                        avg_duration_str = f"{avg_duration / 60:.1f}m"
                    else:
                        avg_duration_str = f"{avg_duration / 3600:.1f}h"
                    html += f"<tr><td><strong>Average Test Duration</strong></td><td>{avg_duration_str}</td></tr>\n"

        # SLURM-specific timing: Wait time and walltime
        if executor == 'slurm' and '__job_start' in self.df.columns and 'metadata.__start' in self.df.columns and 'metadata.__end' in self.df.columns:
            # Calculate wait time (submit to job start) and walltime (submit to completion)
            df_executed = self.df[self.df['metadata.__cached'] != True] if 'metadata.__cached' in self.df.columns else self.df

            if len(df_executed) > 0:
                submit_times = pd.to_datetime(df_executed['metadata.__start'], errors='coerce')
                job_start_times = pd.to_datetime(df_executed['__job_start'], errors='coerce')
                end_times = pd.to_datetime(df_executed['metadata.__end'], errors='coerce')

                # Calculate wait times and walltimes
                wait_times = (job_start_times - submit_times).dt.total_seconds()
                walltimes = (end_times - submit_times).dt.total_seconds()
                runtimes = (end_times - job_start_times).dt.total_seconds()

                # Filter out NaN values
                valid_wait = wait_times[~wait_times.isna()]
                valid_wall = walltimes[~walltimes.isna()]
                valid_run = runtimes[~runtimes.isna()]

                if len(valid_wait) > 0:
                    avg_wait = valid_wait.mean()
                    total_wait = valid_wait.sum()
                    if avg_wait < 60:
                        wait_str = f"{avg_wait:.1f}s"
                    elif avg_wait < 3600:
                        wait_str = f"{avg_wait/60:.1f}m"
                    else:
                        wait_str = f"{avg_wait/3600:.2f}h"
                    html += f"<tr><td><strong>Average Queue Wait Time</strong></td><td>{wait_str}</td></tr>\n"

                if len(valid_wall) > 0:
                    avg_wall = valid_wall.mean()
                    if avg_wall < 60:
                        wall_str = f"{avg_wall:.1f}s"
                    elif avg_wall < 3600:
                        wall_str = f"{avg_wall/60:.1f}m"
                    else:
                        wall_str = f"{avg_wall/3600:.2f}h"
                    html += f"<tr><td><strong>Average Walltime (per test)</strong></td><td>{wall_str}</td></tr>\n"

                if len(valid_run) > 0:
                    avg_run = valid_run.mean()
                    if avg_run < 60:
                        run_str = f"{avg_run:.1f}s"
                    elif avg_run < 3600:
                        run_str = f"{avg_run/60:.1f}m"
                    else:
                        run_str = f"{avg_run/3600:.2f}h"
                    html += f"<tr><td><strong>Average Execution Time (per test)</strong></td><td>{run_str}</td></tr>\n"

        # Core-hours (if cores_expr is defined)
        cores_expr = self.metadata['benchmark'].get('cores_expr')
        if cores_expr:
            total_core_hours = self._calculate_total_core_hours()
            if total_core_hours is not None:
                html += f"<tr><td><strong>Total Core-Hours</strong></td><td>{total_core_hours:.2f}</td></tr>\n"

                # Average cores per test
                avg_cores = self._calculate_average_cores()
                if avg_cores is not None:
                    html += f"<tr><td><strong>Average Cores per Test</strong></td><td>{avg_cores:.1f}</td></tr>\n"

        html += "</table>\n"

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
                # Get all variable values from the results dataframe
                var_values = {}
                for var_name in self.metadata['variables'].keys():
                    var_col = self._get_var_column(var_name)
                    if var_col in self.df.columns:
                        # Find a matching row in the original dataframe
                        mask = True
                        for report_var in report_vars:
                            col = self._get_var_column(report_var)
                            mask = mask & (self.df[col] == row[report_var])
                        matching_rows = self.df[mask]
                        if len(matching_rows) > 0:
                            var_values[var_name] = matching_rows.iloc[0][var_col]

                # Render command with all variables
                rendered_command = self._render_command(var_values)

                html += f"<tr><td rowspan='2'>{idx}</td>"
                for var in report_vars:
                    html += f"<td>{row[var]}</td>"
                html += f"<td><strong>{row['mean']:.4f}</strong></td>"
                html += f"<td>{row['std']:.4f}</td>"
                html += f"<td>{int(row['count'])}</td></tr>\n"

                # Add command row
                html += f"<tr><td colspan='{len(report_vars) + 3}' style='background-color: #f0f0f0; font-family: monospace; font-size: 0.9em; padding: 8px;'>"
                html += f"<strong>Command:</strong> {rendered_command}</td></tr>\n"

            html += "</table>\n"

        return html

    def _generate_bayesian_optimization_section(self, metrics: List[str], report_vars: List[str]) -> str:
        """Generate Bayesian optimization search evolution section."""
        html = "<h2>Bayesian Optimization Search Evolution</h2>\n"
        html += "<p>These plots show how the Bayesian optimization algorithm explored the parameter space "
        html += "and converged towards optimal configurations over successive iterations.</p>\n"

        # Get target metric from bayesian_config
        bayesian_config = self.metadata['benchmark'].get('bayesian_config', {})
        target_metric = bayesian_config.get('target_metric')
        objective = bayesian_config.get('objective', 'maximize')
        n_initial_points = bayesian_config.get('n_initial_points', 5)

        if not target_metric:
            html += "<p><em>Warning: target_metric not found in bayesian_config</em></p>\n"
            return html

        # Ensure we have execution_id for ordering
        if 'execution.execution_id' not in self.df.columns:
            html += "<p><em>Warning: execution_id not found in results</em></p>\n"
            return html

        html += f"<div class='info-box'>\n"
        html += f"<p><strong>Target Metric:</strong> {target_metric} ({objective})</p>\n"
        html += f"<p><strong>Initial Exploration:</strong> First {n_initial_points} iterations (random sampling)</p>\n"
        html += f"<p><strong>Bayesian Optimization:</strong> Subsequent iterations (guided by surrogate model)</p>\n"
        html += "</div>\n"

        # Create plots
        # 1. Metric evolution over iterations
        html += "<h3>Metric Evolution</h3>\n"
        html += "<p>Shows how the target metric evolved as the algorithm explored different configurations. "
        html += "The best value found so far is highlighted.</p>\n"
        fig_metric_evolution = self._create_bayesian_metric_evolution_plot(
            target_metric, objective, n_initial_points
        )
        html += f"<div>{fig_metric_evolution.to_html(include_plotlyjs=False, div_id='bayesian_metric_evolution')}</div>\n"

        # 2. Parameter evolution over iterations
        html += "<h3>Parameter Evolution</h3>\n"
        html += "<p>Shows which parameter values were explored at each iteration. "
        html += "Colors indicate the metric value achieved.</p>\n"
        fig_param_evolution = self._create_bayesian_parameter_evolution_plot(
            report_vars, target_metric, objective, n_initial_points
        )
        html += f"<div>{fig_param_evolution.to_html(include_plotlyjs=False, div_id='bayesian_param_evolution')}</div>\n"

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
            # Get all variable values for command rendering
            var_values = {}
            for var_name in self.metadata['variables'].keys():
                var_col = self._get_var_column(var_name)
                if var_col in self.df.columns:
                    # Find matching row
                    mask = True
                    for report_var in report_vars:
                        col = self._get_var_column(report_var)
                        mask = mask & (self.df[col] == row[col])
                    matching_rows = self.df[mask]
                    if len(matching_rows) > 0:
                        var_values[var_name] = matching_rows.iloc[0][var_col]

            rendered_command = self._render_command(var_values)

            html += f"<tr><td rowspan='2'>{idx}</td>"
            for var_col in var_cols:
                html += f"<td>{row[var_col]}</td>"
            for metric_col in metric_cols:
                html += f"<td><strong>{row[metric_col]:.4f}</strong></td>"
            html += "</tr>\n"

            # Add command row
            num_cols = len(report_vars) + len(metrics)
            html += f"<tr><td colspan='{num_cols}' style='background-color: #f0f0f0; font-family: monospace; font-size: 0.9em; padding: 8px;'>"
            html += f"<strong>Command:</strong> {rendered_command}</td></tr>\n"

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

        # Check if custom plots are defined for this metric
        has_custom_plots = metric in self.report_config.metrics and len(self.report_config.metrics[metric].plots) > 0
        has_default_plots = len(self.report_config.default_plots) > 0

        if has_custom_plots:
            # Use custom plots from config
            html += self._generate_custom_plots(metric, self.report_config.metrics[metric].plots, swept_vars)
        elif has_default_plots:
            # Use default plots from config
            html += self._generate_custom_plots(metric, self.report_config.default_plots, swept_vars)
        else:
            # Fall back to legacy plot generation
            html += self._generate_legacy_plots(metric, swept_vars)

        html += '</div>\n'
        return html

    def _generate_custom_plots(self, metric: str, plot_configs: List[PlotConfig], swept_vars: List[str]) -> str:
        """Generate plots using the plot factory from plot configs."""
        from iops.reporting.plots import create_plot

        html = ""

        for plot_config in plot_configs:
            # Handle per_variable plots (generate one plot per swept variable)
            if plot_config.per_variable:
                for var in swept_vars:
                    # Create a modified config for this specific variable
                    var_config = PlotConfig(
                        type=plot_config.type,
                        x_var=var,
                        y_var=plot_config.y_var,
                        z_metric=plot_config.z_metric,
                        group_by=plot_config.group_by,
                        color_by=plot_config.color_by,
                        title=plot_config.title or f"{metric} vs {var}",
                        xaxis_label=plot_config.xaxis_label,
                        yaxis_label=plot_config.yaxis_label,
                        colorscale=plot_config.colorscale,
                        show_error_bars=plot_config.show_error_bars,
                        show_outliers=plot_config.show_outliers,
                        height=plot_config.height,
                        width=plot_config.width,
                        per_variable=False,
                    )

                    try:
                        plot = create_plot(
                            plot_type=var_config.type,
                            df=self.df,
                            metric=metric,
                            plot_config=var_config,
                            theme=self.report_config.theme,
                            var_column_fn=self._get_var_column,
                            metric_column_fn=self._get_metric_column,
                        )
                        fig = plot.generate()
                        html += '<div class="plot-container">\n'
                        html += fig.to_html(full_html=False, include_plotlyjs=False)
                        html += '</div>\n'
                    except Exception as e:
                        html += f'<p class="error">Error generating {var_config.type} plot for {var}: {str(e)}</p>\n'
            else:
                # Single plot
                try:
                    plot = create_plot(
                        plot_type=plot_config.type,
                        df=self.df,
                        metric=metric,
                        plot_config=plot_config,
                        theme=self.report_config.theme,
                        var_column_fn=self._get_var_column,
                        metric_column_fn=self._get_metric_column,
                    )
                    fig = plot.generate()
                    html += '<div class="plot-container">\n'
                    html += fig.to_html(full_html=False, include_plotlyjs=False)
                    html += '</div>\n'
                except Exception as e:
                    html += f'<p class="error">Error generating {plot_config.type} plot: {str(e)}</p>\n'

        return html

    def _generate_legacy_plots(self, metric: str, swept_vars: List[str]) -> str:
        """Generate plots using legacy hardcoded logic (for backward compatibility)."""
        html = ""

        # 1. Bar plots - one for each variable
        html += "<h3>Bar Plots by Variable</h3>\n"
        for var in swept_vars:
            fig = self._create_bar_plot(metric, var)
            html += '<div class="plot-container">\n'
            html += fig.to_html(full_html=False, include_plotlyjs=False)
            html += '</div>\n'

        # 2. Line plots - one for each variable, grouped by others
        if len(swept_vars) >= 2:
            html += "<h3>Line Plots with Grouping</h3>\n"
            for i, var in enumerate(swept_vars):
                # For each variable, create line plot grouped by the next variable (cyclically)
                group_var = swept_vars[(i + 1) % len(swept_vars)]
                fig = self._create_line_plot(metric, var, group_var)
                html += '<div class="plot-container">\n'
                html += fig.to_html(full_html=False, include_plotlyjs=False)
                html += '</div>\n'

        # 3. Heatmap if we have exactly 2 swept variables
        if len(swept_vars) == 2:
            html += "<h3>Heatmap</h3>\n"
            fig = self._create_heatmap(metric, swept_vars[0], swept_vars[1])
            html += '<div class="plot-container">\n'
            html += fig.to_html(full_html=False, include_plotlyjs=False)
            html += '</div>\n'

        return html

    def _create_bayesian_metric_evolution_plot(
        self, target_metric: str, objective: str, n_initial_points: int
    ) -> go.Figure:
        """
        Create plot showing metric evolution over Bayesian optimization iterations.

        Shows:
        - Observed metric values at each iteration
        - Running best (cumulative max/min)
        - Distinction between exploration and exploitation phases
        """
        metric_col = self._get_metric_column(target_metric)

        # Group by execution_id and compute mean across repetitions
        df_grouped = self.df.groupby('execution.execution_id').agg({
            metric_col: 'mean'
        }).reset_index()
        df_grouped = df_grouped.sort_values('execution.execution_id')

        iterations = df_grouped['execution.execution_id'].values
        metric_values = df_grouped[metric_col].values

        # Compute running best
        if objective == 'maximize':
            running_best = pd.Series(metric_values).cummax().values
        else:
            running_best = pd.Series(metric_values).cummin().values

        # Create figure with two traces
        fig = go.Figure()

        # Observed values with phase coloring
        colors = ['#3498db' if i < n_initial_points else '#2ecc71' for i in range(len(iterations))]

        fig.add_trace(go.Scatter(
            x=iterations,
            y=metric_values,
            mode='markers+lines',
            name='Observed',
            marker=dict(size=10, color=colors, line=dict(width=1, color='white')),
            line=dict(color='lightgray', width=1),
            hovertemplate='Iteration %{x}<br>' + target_metric + ': %{y:.4f}<extra></extra>'
        ))

        # Running best
        fig.add_trace(go.Scatter(
            x=iterations,
            y=running_best,
            mode='lines',
            name=f'Best so far ({objective})',
            line=dict(color='#e74c3c', width=3, dash='dash'),
            hovertemplate='Iteration %{x}<br>Best: %{y:.4f}<extra></extra>'
        ))

        # Add vertical line at end of exploration phase
        if n_initial_points > 0 and n_initial_points < len(iterations):
            fig.add_vline(
                x=n_initial_points,
                line=dict(color='orange', width=2, dash='dot'),
                annotation_text='End of Random Exploration',
                annotation_position='top'
            )

        fig.update_layout(
            title=f'{target_metric} Evolution Over Iterations',
            xaxis_title='Iteration',
            yaxis_title=target_metric,
            hovermode='closest',
            template='plotly_white',
            showlegend=True,
            legend=dict(x=0.02, y=0.98, bgcolor='rgba(255,255,255,0.8)')
        )

        return fig

    def _create_bayesian_parameter_evolution_plot(
        self, report_vars: List[str], target_metric: str, objective: str, n_initial_points: int
    ) -> go.Figure:
        """
        Create subplot showing evolution of each parameter over iterations.

        Each parameter gets its own subplot showing values explored over time,
        colored by the metric value achieved.
        """
        metric_col = self._get_metric_column(target_metric)

        # Group by execution_id and compute mean across repetitions
        agg_dict = {metric_col: 'mean'}
        for var in report_vars:
            var_col = self._get_var_column(var)
            agg_dict[var_col] = 'first'  # Parameters should be same for all repetitions

        df_grouped = self.df.groupby('execution.execution_id').agg(agg_dict).reset_index()
        df_grouped = df_grouped.sort_values('execution.execution_id')

        iterations = df_grouped['execution.execution_id'].values
        metric_values = df_grouped[metric_col].values

        # Create subplots - one per parameter
        n_params = len(report_vars)
        fig = make_subplots(
            rows=n_params, cols=1,
            subplot_titles=[f'{var} Evolution' for var in report_vars],
            vertical_spacing=0.15 / max(n_params, 1)
        )

        for idx, var in enumerate(report_vars, 1):
            var_col = self._get_var_column(var)
            param_values = df_grouped[var_col].values

            # Get unique sorted values for this parameter
            unique_values = sorted(df_grouped[var_col].unique())

            fig.add_trace(
                go.Scatter(
                    x=iterations,
                    y=param_values,
                    mode='markers+lines',
                    marker=dict(
                        size=10,
                        color=metric_values,
                        colorscale='Viridis',
                        showscale=(idx == 1),  # Only show colorbar for first subplot
                        colorbar=dict(
                            title=target_metric,
                            x=1.1
                        ),
                        line=dict(width=1, color='white')
                    ),
                    line=dict(color='lightgray', width=1),
                    name=var,
                    showlegend=False,
                    hovertemplate=f'{var}: %{{y}}<br>{target_metric}: %{{marker.color:.4f}}<extra></extra>'
                ),
                row=idx, col=1
            )

            # Add vertical line at end of exploration phase
            if n_initial_points > 0 and n_initial_points < len(iterations):
                fig.add_vline(
                    x=n_initial_points,
                    line=dict(color='orange', width=1, dash='dot'),
                    row=idx, col=1
                )

            # Update y-axis to show only tested values
            fig.update_yaxes(
                tickmode='array',
                tickvals=unique_values,
                ticktext=[str(v) for v in unique_values],
                row=idx, col=1
            )

        fig.update_xaxes(title_text='Iteration', row=n_params, col=1)
        fig.update_layout(
            height=250 * n_params,
            title_text='Parameter Values Explored Over Iterations',
            showlegend=False,
            template='plotly_white',
            hovermode='closest'
        )

        return fig

    def _create_bayesian_2d_space_plot(
        self, report_vars: List[str], target_metric: str, objective: str, n_initial_points: int
    ) -> go.Figure:
        """
        Create 2D scatter plot showing exploration of parameter space.

        Only works when exactly 2 parameters are swept.
        Shows sequence of exploration with iteration numbers.
        """
        if len(report_vars) != 2:
            # Return empty figure if not exactly 2 parameters
            return go.Figure()

        var1, var2 = report_vars
        var1_col = self._get_var_column(var1)
        var2_col = self._get_var_column(var2)
        metric_col = self._get_metric_column(target_metric)

        # Group by execution_id and compute mean across repetitions
        df_grouped = self.df.groupby('execution.execution_id').agg({
            var1_col: 'first',
            var2_col: 'first',
            metric_col: 'mean'
        }).reset_index()
        df_grouped = df_grouped.sort_values('execution.execution_id')

        iterations = df_grouped['execution.execution_id'].values
        var1_values = df_grouped[var1_col].values
        var2_values = df_grouped[var2_col].values
        metric_values = df_grouped[metric_col].values

        # Split into exploration and exploitation phases
        exploration_mask = iterations <= n_initial_points

        fig = go.Figure()

        # Exploration phase (random)
        if exploration_mask.any():
            fig.add_trace(go.Scatter(
                x=var1_values[exploration_mask],
                y=var2_values[exploration_mask],
                mode='markers+text',
                marker=dict(
                    size=15,
                    color=metric_values[exploration_mask],
                    colorscale='Viridis',
                    showscale=True,
                    colorbar=dict(title=target_metric),
                    line=dict(width=2, color='white'),
                    symbol='circle'
                ),
                text=[str(i) for i in iterations[exploration_mask]],
                textposition='middle center',
                textfont=dict(size=8, color='white'),
                name='Exploration',
                hovertemplate=f'{var1}: %{{x}}<br>{var2}: %{{y}}<br>{target_metric}: %{{marker.color:.4f}}<br>Iteration: %{{text}}<extra></extra>'
            ))

        # Exploitation phase (Bayesian-guided)
        exploitation_mask = ~exploration_mask
        if exploitation_mask.any():
            fig.add_trace(go.Scatter(
                x=var1_values[exploitation_mask],
                y=var2_values[exploitation_mask],
                mode='markers+text',
                marker=dict(
                    size=15,
                    color=metric_values[exploitation_mask],
                    colorscale='Viridis',
                    showscale=False,
                    line=dict(width=2, color='orange'),
                    symbol='diamond'
                ),
                text=[str(i) for i in iterations[exploitation_mask]],
                textposition='middle center',
                textfont=dict(size=8, color='white'),
                name='Optimization',
                hovertemplate=f'{var1}: %{{x}}<br>{var2}: %{{y}}<br>{target_metric}: %{{marker.color:.4f}}<br>Iteration: %{{text}}<extra></extra>'
            ))

        # Add lines connecting sequential iterations
        fig.add_trace(go.Scatter(
            x=var1_values,
            y=var2_values,
            mode='lines',
            line=dict(color='lightgray', width=1),
            showlegend=False,
            hoverinfo='skip'
        ))

        # Get unique values for axes
        unique_var1 = sorted(self.df[var1_col].unique())
        unique_var2 = sorted(self.df[var2_col].unique())

        fig.update_layout(
            title=f'2D Parameter Space Exploration<br><sub>Circles = Exploration, Diamonds = Optimization</sub>',
            xaxis_title=var1,
            yaxis_title=var2,
            hovermode='closest',
            template='plotly_white',
            showlegend=True,
            legend=dict(x=0.02, y=0.98, bgcolor='rgba(255,255,255,0.8)')
        )

        # Set categorical axes to show only tested values
        fig.update_xaxes(
            tickmode='array',
            tickvals=unique_var1,
            ticktext=[str(v) for v in unique_var1]
        )
        fig.update_yaxes(
            tickmode='array',
            tickvals=unique_var2,
            ticktext=[str(v) for v in unique_var2]
        )

        return fig

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

    def _generate_variable_analysis_section(self, metrics: List[str], report_vars: List[str]) -> str:
        """
        Generate variable analysis section with key visualizations.

        This section provides:
        1. Parallel coordinates plot for multidimensional patterns
        2. Variable importance/contribution analysis
        """
        html = '<div class="metric-section">\n'
        html += "<h2>Variable Analysis & Relationships</h2>\n"
        html += "<p>Analysis of how variables relate to performance metrics.</p>\n"

        # 1. Parallel coordinates plot
        html += "<h3>Parallel Coordinates Plot</h3>\n"
        html += "<p>Visualizes all variables simultaneously. Each line represents one configuration, "
        html += "colored by performance. Patterns and clusters reveal optimal parameter combinations.</p>\n"

        for metric in metrics:
            fig_parallel = self._create_parallel_coordinates(metric, report_vars)
            if fig_parallel is not None:
                html += '<div class="plot-container">\n'
                html += fig_parallel.to_html(full_html=False, include_plotlyjs=False)
                html += '</div>\n'

        # 2. Variable impact analysis
        html += "<h3>Variable Impact on Performance</h3>\n"
        html += "<p>Shows how much each variable affects the performance metric based on variance analysis.</p>\n"

        for metric in metrics:
            fig_impact = self._create_variable_impact_plot(metric, report_vars)
            if fig_impact is not None:
                html += '<div class="plot-container">\n'
                html += fig_impact.to_html(full_html=False, include_plotlyjs=False)
                html += '</div>\n'

        html += '</div>\n'
        return html

    def _create_correlation_matrix(self, metric: str, report_vars: List[str]) -> Optional[go.Figure]:
        """Create correlation matrix heatmap for variables and metric."""
        try:
            metric_col = self._get_metric_column(metric)
            var_cols = [self._get_var_column(v) for v in report_vars]

            # Get relevant columns
            cols_to_analyze = var_cols + [metric_col]
            df_corr = self.df[cols_to_analyze].copy()

            # Group by variables and compute mean metric
            df_grouped = df_corr.groupby(var_cols)[metric_col].mean().reset_index()

            # Compute correlation matrix
            corr_matrix = df_grouped.corr()

            # Create labels
            labels = report_vars + [metric]

            # Create heatmap
            fig = go.Figure(data=go.Heatmap(
                z=corr_matrix.values,
                x=labels,
                y=labels,
                colorscale='RdBu',
                zmid=0,
                zmin=-1,
                zmax=1,
                text=corr_matrix.values,
                texttemplate='%{text:.3f}',
                textfont={"size": 10},
                colorbar=dict(title='Correlation'),
                hovertemplate='%{x} vs %{y}<br>Correlation: %{z:.3f}<extra></extra>'
            ))

            fig.update_layout(
                title=f'Correlation Matrix - {metric}',
                xaxis_title='Variables',
                yaxis_title='Variables',
                template='plotly_white',
                height=500,
                width=600
            )

            return fig
        except Exception as e:
            return None

    def _create_parallel_coordinates(self, metric: str, report_vars: List[str]) -> Optional[go.Figure]:
        """Create parallel coordinates plot."""
        try:
            metric_col = self._get_metric_column(metric)
            var_cols = [self._get_var_column(v) for v in report_vars]

            # Group by variables and compute mean metric
            df_grouped = self.df.groupby(var_cols)[metric_col].mean().reset_index()

            # Prepare dimensions for parallel coordinates
            dimensions = []

            for var in report_vars:
                var_col = self._get_var_column(var)
                dimensions.append(dict(
                    label=var,
                    values=df_grouped[var_col]
                ))

            # Add metric as the last dimension and for coloring
            dimensions.append(dict(
                label=metric,
                values=df_grouped[metric_col]
            ))

            fig = go.Figure(data=go.Parcoords(
                line=dict(
                    color=df_grouped[metric_col],
                    colorscale='Viridis',
                    showscale=True,
                    cmin=df_grouped[metric_col].min(),
                    cmax=df_grouped[metric_col].max(),
                    colorbar=dict(title=metric)
                ),
                dimensions=dimensions
            ))

            fig.update_layout(
                title=f'Parallel Coordinates - All Variables vs {metric}',
                template='plotly_white',
                height=600
            )

            return fig
        except Exception as e:
            return None

    def _create_variable_impact_plot(self, metric: str, report_vars: List[str]) -> Optional[go.Figure]:
        """
        Create bar plot showing impact of each variable on metric.

        Impact is measured as the ratio of between-group variance to total variance
        for each variable (similar to ANOVA F-statistic concept).
        """
        try:
            metric_col = self._get_metric_column(metric)

            impacts = []
            for var in report_vars:
                var_col = self._get_var_column(var)

                # Group by this variable
                groups = self.df.groupby(var_col)[metric_col].apply(list)

                # Calculate between-group and within-group variance
                overall_mean = self.df[metric_col].mean()

                # Between-group variance
                between_var = sum(
                    len(group) * (np.mean(group) - overall_mean) ** 2
                    for group in groups
                ) / len(self.df)

                # Total variance
                total_var = self.df[metric_col].var()

                # Impact score (R-squared like measure)
                impact = between_var / total_var if total_var > 0 else 0
                impacts.append(impact)

            # Sort by impact
            sorted_indices = sorted(range(len(impacts)), key=lambda i: impacts[i], reverse=True)
            sorted_vars = [report_vars[i] for i in sorted_indices]
            sorted_impacts = [impacts[i] for i in sorted_indices]

            # Create bar plot
            fig = go.Figure(data=go.Bar(
                x=sorted_vars,
                y=sorted_impacts,
                marker=dict(
                    color=sorted_impacts,
                    colorscale='Viridis',
                    showscale=True,
                    colorbar=dict(title='Impact Score')
                ),
                text=[f'{v:.3f}' for v in sorted_impacts],
                textposition='outside'
            ))

            fig.update_layout(
                title=f'Variable Impact on {metric}<br><sub>Higher values indicate stronger influence on performance</sub>',
                xaxis_title='Variable',
                yaxis_title='Impact Score (Variance Explained)',
                yaxis=dict(range=[0, max(sorted_impacts) * 1.2]),
                template='plotly_white',
                height=500
            )

            return fig
        except Exception as e:
            return None

    def _create_scatter_matrix(self, metric: str, report_vars: List[str]) -> Optional[go.Figure]:
        """Create scatter matrix showing pairwise variable relationships."""
        try:
            import numpy as np

            metric_col = self._get_metric_column(metric)
            var_cols = [self._get_var_column(v) for v in report_vars]

            # Group by variables and compute mean metric
            df_grouped = self.df.groupby(var_cols)[metric_col].mean().reset_index()

            # Limit to first 4 variables if more exist (to keep plot manageable)
            display_vars = report_vars[:4] if len(report_vars) > 4 else report_vars
            display_var_cols = [self._get_var_column(v) for v in display_vars]

            n_vars = len(display_vars)

            # Create subplots
            fig = make_subplots(
                rows=n_vars, cols=n_vars,
                subplot_titles=[f'{v1} vs {v2}' if i != j else f'{v1} distribution'
                               for i, v1 in enumerate(display_vars)
                               for j, v2 in enumerate(display_vars)],
                vertical_spacing=0.05,
                horizontal_spacing=0.05
            )

            # Add scatter plots
            for i, var1 in enumerate(display_vars, 1):
                var1_col = self._get_var_column(var1)
                for j, var2 in enumerate(display_vars, 1):
                    var2_col = self._get_var_column(var2)

                    if i == j:
                        # Diagonal: histogram
                        fig.add_trace(
                            go.Histogram(
                                x=df_grouped[var1_col],
                                name=var1,
                                showlegend=False,
                                marker=dict(color='lightblue')
                            ),
                            row=i, col=j
                        )
                    else:
                        # Off-diagonal: scatter plot
                        fig.add_trace(
                            go.Scatter(
                                x=df_grouped[var2_col],
                                y=df_grouped[var1_col],
                                mode='markers',
                                marker=dict(
                                    size=10,
                                    color=df_grouped[metric_col],
                                    colorscale='Viridis',
                                    showscale=(i == 1 and j == n_vars),  # Show colorbar once
                                    colorbar=dict(
                                        title=metric,
                                        x=1.1
                                    ) if (i == 1 and j == n_vars) else None,
                                    line=dict(width=0.5, color='white')
                                ),
                                showlegend=False,
                                hovertemplate=f'{var2}: %{{x}}<br>{var1}: %{{y}}<br>{metric}: %{{marker.color:.2f}}<extra></extra>'
                            ),
                            row=i, col=j
                        )

                    # Update axes labels
                    if j == 1:
                        fig.update_yaxes(title_text=var1, row=i, col=j)
                    if i == n_vars:
                        fig.update_xaxes(title_text=var2, row=i, col=j)

            fig.update_layout(
                title=f'Pairwise Variable Relationships - Colored by {metric}',
                template='plotly_white',
                height=250 * n_vars,
                showlegend=False
            )

            return fig
        except Exception as e:
            return None

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


def generate_report_from_workdir(
    workdir: Path,
    output_path: Optional[Path] = None,
    report_config: Optional[ReportingConfig] = None
) -> Path:
    """
    Convenience function to generate report from a workdir.

    Args:
        workdir: Path to benchmark working directory
        output_path: Optional custom output path
        report_config: Optional reporting configuration (overrides metadata config)

    Returns:
        Path to generated HTML report
    """
    generator = ReportGenerator(workdir, report_config=report_config)
    generator.load_metadata()
    generator.load_results()
    return generator.generate_report(output_path)
