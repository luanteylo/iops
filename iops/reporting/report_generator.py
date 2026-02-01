"""
IOPS Report Generator - Creates HTML reports with interactive plots.
"""

import base64
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

# Optional pyarrow for parquet support
try:
    import pyarrow
    PYARROW_AVAILABLE = True
except ImportError:
    PYARROW_AVAILABLE = False

# Optional kaleido for PDF export
try:
    import kaleido
    KALEIDO_AVAILABLE = True
except ImportError:
    KALEIDO_AVAILABLE = False

from iops.config.models import (
    ReportingConfig,
    ReportThemeConfig,
    PlotConfig,
    MetricPlotsConfig,
    SectionConfig,
    BestResultsConfig,
    PlotDefaultsConfig,
)


def _get_iops_version() -> str:
    """Load the IOPS version from the VERSION file."""
    version_file = Path(__file__).parent.parent / "VERSION"
    if version_file.exists():
        with version_file.open() as f:
            return f.read().strip()
    return "unknown"


def _get_logo_base64() -> Optional[str]:
    """Load the IOPS logo as a base64-encoded data URI."""
    logo_file = Path(__file__).parent.parent.parent / "logo.png"
    if logo_file.exists():
        try:
            with logo_file.open("rb") as f:
                logo_data = base64.b64encode(f.read()).decode("utf-8")
            return f"data:image/png;base64,{logo_data}"
        except Exception:
            return None
    return None


class ReportGenerator:
    """Generates HTML reports from IOPS benchmark results."""

    # Default Plotly config for interactive plots
    PLOTLY_CONFIG = {
        'displayModeBar': True,
        'scrollZoom': True,
        'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
        'displaylogo': False,
        'responsive': True,
    }

    # Default color palette - 24 distinguishable colors for automatic assignment
    # Combines colors from Plotly, D3, and custom selections for good contrast
    DEFAULT_COLOR_PALETTE = [
        '#3498db',  # Blue
        '#e74c3c',  # Red
        '#2ecc71',  # Green
        '#9b59b6',  # Purple
        '#f39c12',  # Orange
        '#1abc9c',  # Teal
        '#e91e63',  # Pink
        '#00bcd4',  # Cyan
        '#8bc34a',  # Light Green
        '#ff5722',  # Deep Orange
        '#673ab7',  # Deep Purple
        '#009688',  # Dark Teal
        '#ffc107',  # Amber
        '#795548',  # Brown
        '#607d8b',  # Blue Grey
        '#cddc39',  # Lime
        '#ff9800',  # Orange
        '#03a9f4',  # Light Blue
        '#4caf50',  # Green
        '#f44336',  # Red
        '#9c27b0',  # Purple
        '#00796b',  # Dark Cyan
        '#c2185b',  # Dark Pink
        '#5d4037',  # Dark Brown
    ]

    @classmethod
    def get_color_palette(cls, n_colors: int, user_colors: Optional[List[str]] = None) -> List[str]:
        """
        Get a color palette with n colors.

        If user provides colors, those are used (cycling if needed).
        Otherwise, uses the default palette, generating additional colors if n > 24.

        Args:
            n_colors: Number of colors needed
            user_colors: Optional user-defined color list

        Returns:
            List of n hex color strings
        """
        if user_colors:
            # Use user colors, cycling if needed
            base_colors = user_colors
        else:
            base_colors = cls.DEFAULT_COLOR_PALETTE

        if n_colors <= len(base_colors):
            return base_colors[:n_colors]

        # Need more colors than available - cycle through and adjust lightness
        colors = list(base_colors)
        cycle = 1
        while len(colors) < n_colors:
            # Cycle through base colors with slight variation
            for base_color in base_colors:
                if len(colors) >= n_colors:
                    break
                # Adjust the color slightly for each cycle
                adjusted = cls._adjust_color_lightness(base_color, 0.15 * cycle)
                colors.append(adjusted)
            cycle += 1

        return colors[:n_colors]

    @staticmethod
    def _adjust_color_lightness(hex_color: str, factor: float) -> str:
        """
        Adjust the lightness of a hex color.

        Args:
            hex_color: Color in hex format (#RRGGBB)
            factor: Positive = lighter, negative = darker

        Returns:
            Adjusted color in hex format
        """
        # Remove # if present
        hex_color = hex_color.lstrip('#')

        # Parse RGB
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)

        # Adjust (move towards white if factor > 0, towards black if < 0)
        if factor > 0:
            r = min(255, int(r + (255 - r) * factor))
            g = min(255, int(g + (255 - g) * factor))
            b = min(255, int(b + (255 - b) * factor))
        else:
            r = max(0, int(r * (1 + factor)))
            g = max(0, int(g * (1 + factor)))
            b = max(0, int(b * (1 + factor)))

        return f'#{r:02x}{g:02x}{b:02x}'

    def _get_user_colors(self) -> Optional[List[str]]:
        """
        Get user-defined colors from report config if available.

        Returns:
            List of color hex strings if user defined them, None otherwise
        """
        if self.report_config and self.report_config.theme and self.report_config.theme.colors:
            return self.report_config.theme.colors
        return None

    def __init__(
        self,
        workdir: Path,
        report_config: Optional[ReportingConfig] = None,
        export_plots: bool = False,
        plot_format: str = 'pdf'
    ):
        """
        Initialize report generator.

        Args:
            workdir: Path to the benchmark working directory (e.g., /path/to/run_001)
            report_config: Optional reporting configuration (overrides metadata config)
            export_plots: Whether to export plots as image files
            plot_format: Image format for exported plots (pdf, png, svg, jpg, webp)
        """
        self.workdir = Path(workdir)
        # Try new filename first, fall back to legacy for backward compatibility
        self.metadata_path = self.workdir / "__iops_run_metadata.json"
        if not self.metadata_path.exists():
            legacy_path = self.workdir / "run_metadata.json"
            if legacy_path.exists():
                self.metadata_path = legacy_path
        self.metadata: Optional[Dict[str, Any]] = None
        self.df: Optional[pd.DataFrame] = None
        self.report_config: Optional[ReportingConfig] = report_config
        self.export_plots: bool = export_plots
        self.plot_format: str = plot_format
        self.plots_dir: Optional[Path] = None
        self._plot_counter: int = 0

    def load_metadata(self):
        """Load runtime metadata and reporting configuration."""
        if not self.metadata_path.exists():
            raise FileNotFoundError(
                f"Metadata file not found: {self.metadata_path}\n"
                "Make sure you ran the benchmark with the latest version that saves metadata."
            )

        with open(self.metadata_path, 'r') as f:
            self.metadata = json.load(f)

        # Check version compatibility
        self.run_version = self.metadata.get('iops_version', 'unknown')
        self.report_version = _get_iops_version()
        self._check_version_compatibility()

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

    def _check_version_compatibility(self):
        """Check and warn about version mismatches between run and report generation."""
        if self.run_version == 'unknown':
            print(f"WARNING: Run metadata does not contain IOPS version info (created with older IOPS version)")
            return

        if self.run_version != self.report_version:
            # Parse major.minor versions for compatibility check
            try:
                run_parts = self.run_version.split('.')
                report_parts = self.report_version.split('.')
                run_major_minor = (int(run_parts[0]), int(run_parts[1]))
                report_major_minor = (int(report_parts[0]), int(report_parts[1]))

                if run_major_minor != report_major_minor:
                    print(f"WARNING: Version mismatch detected!")
                    print(f"  - Benchmark was run with IOPS v{self.run_version}")
                    print(f"  - Report is being generated with IOPS v{self.report_version}")
                    print(f"  Some features may not be compatible.")
            except (ValueError, IndexError):
                # Can't parse versions, just warn about difference
                print(f"WARNING: Version mismatch - run: v{self.run_version}, report: v{self.report_version}")

    def load_results(self):
        """Load benchmark results from the output file."""
        if self.metadata is None:
            raise ValueError("Metadata not loaded. Call load_metadata() first.")

        output_info = self.metadata['output']
        output_path = Path(output_info['path'])

        # Resolve relative paths against workdir (for portable workdirs)
        if not output_path.is_absolute():
            output_path = self.workdir / output_path

        if not output_path.exists():
            raise FileNotFoundError(f"Results file not found: {output_path}")

        # Load based on file type
        if output_info['type'] == 'csv':
            self.df = pd.read_csv(output_path)
        elif output_info['type'] == 'parquet':
            if not PYARROW_AVAILABLE:
                raise ImportError(
                    "pyarrow is required for parquet output. "
                    "Install it with: pip install pyarrow\n"
                    "Or install iops with parquet support: pip install iops-benchmark[parquet]"
                )
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
        2. Otherwise, use all swept variables that are numeric (int/float/bool)
        3. Exclude string variables by default (they don't plot well)
        """
        # Check if report_vars is explicitly specified
        report_vars = self.metadata['benchmark'].get('report_vars')

        if report_vars is not None:
            # Use explicitly specified variables
            return report_vars

        # Default: use numeric swept variables only (bool treated as 0/1)
        swept_vars = self._get_swept_vars()
        numeric_vars = []

        for var_name in swept_vars:
            var_type = self.metadata['variables'][var_name].get('type', '')
            if var_type in ['int', 'float', 'bool']:
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

    @staticmethod
    def _to_python_list(data):
        """
        Convert array-like data to Python list with native types.

        Plotly 6.x uses binary encoding (bdata/dtype) for numpy arrays which can
        cause blank plots in some browsers. Converting to plain Python lists with
        native Python types ensures compatibility.
        """
        import numpy as np

        # Convert to list first
        if hasattr(data, 'values'):
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
                    converted.append(item.item())
                elif isinstance(item, np.ndarray):
                    converted.append(item.tolist())
                else:
                    converted.append(item)
            return converted
        return result

    def _fig_to_html(self, fig: go.Figure, div_id: str = None, plot_name: str = None) -> str:
        """
        Convert a Plotly figure to HTML with standard config for interactivity.
        Also saves the figure as an image file if plots_dir is set.

        Args:
            fig: Plotly figure to convert
            div_id: Optional div ID for the plot
            plot_name: Optional name for the image file (without extension)

        Returns:
            HTML string with the plot
        """
        # Save as image if plots directory is configured and kaleido is available
        if self.plots_dir is not None and KALEIDO_AVAILABLE:
            self._plot_counter += 1
            if plot_name:
                # Sanitize plot name for filename
                safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in plot_name)
                image_filename = f"{self._plot_counter:03d}_{safe_name}.{self.plot_format}"
            else:
                image_filename = f"{self._plot_counter:03d}_plot.{self.plot_format}"

            image_path = self.plots_dir / image_filename
            try:
                fig.write_image(image_path, format=self.plot_format, width=1200, height=800)
            except Exception as e:
                import logging
                logging.getLogger(__name__).debug(f"Could not save {self.plot_format.upper()} plot: {e}")

        kwargs = {
            'full_html': False,
            'include_plotlyjs': False,
            'config': self.PLOTLY_CONFIG,
        }
        if div_id:
            kwargs['div_id'] = div_id
        return fig.to_html(**kwargs)

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
                # Coverage heatmap options
                row_vars=plot_data.get('row_vars'),
                col_var=plot_data.get('col_var'),
                aggregation=plot_data.get('aggregation', 'mean'),
                show_missing=plot_data.get('show_missing', True),
                sort_rows_by=plot_data.get('sort_rows_by', 'index'),
                sort_cols_by=plot_data.get('sort_cols_by', 'index'),
                sort_ascending=plot_data.get('sort_ascending', False),
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
            bayesian_evolution=data.get('sections', {}).get('bayesian_evolution', True),
            bayesian_parameter_evolution=data.get('sections', {}).get('bayesian_parameter_evolution', False),
            custom_plots=data.get('sections', {}).get('custom_plots', True),
        )

        best_results = BestResultsConfig(
            top_n=data.get('best_results', {}).get('top_n', 5),
            show_command=data.get('best_results', {}).get('show_command', True),
            min_samples=data.get('best_results', {}).get('min_samples', 1),
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
                bayesian_evolution=True,
                bayesian_parameter_evolution=False,  # Disabled by default
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

            # Use submission_time for wall-clock calculation (earliest submission to latest completion)
            submission_col = 'metadata.__submission_time'
            start_times = pd.to_datetime(df_executed.get(submission_col, pd.Series()), errors='coerce')
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

        Prefers duration_seconds from sysinfo (actual script execution time) over
        __job_start/__end timestamps. Falls back to __submission_time if __job_start
        is not available.

        Returns:
            Total core-hours or None if cannot be calculated
        """
        try:
            cores_expr = self.metadata['benchmark'].get('cores_expr')
            if not cores_expr:
                return None

            # Check for sysinfo duration_seconds column (preferred - accurate execution time)
            sysinfo_duration_col = 'metadata.__sysinfo.duration_seconds'
            has_sysinfo_duration = sysinfo_duration_col in self.df.columns

            # Parse timestamps as fallback
            # Prefer __job_start (actual job start) over __submission_time (includes queue wait)
            job_start_col = 'metadata.__job_start'
            submission_col = 'metadata.__submission_time'
            if job_start_col in self.df.columns:
                start_times = pd.to_datetime(self.df[job_start_col], errors='coerce')
                # Fall back to submission_time where job_start is missing
                if submission_col in self.df.columns:
                    submission_times = pd.to_datetime(self.df[submission_col], errors='coerce')
                    start_times = start_times.fillna(submission_times)
            else:
                start_times = pd.to_datetime(self.df.get(submission_col, pd.Series()), errors='coerce')
            end_times = pd.to_datetime(self.df['metadata.__end'], errors='coerce')

            # Calculate duration for each test in hours
            # Prefer sysinfo duration_seconds, fall back to timestamps
            if has_sysinfo_duration:
                # Use sysinfo duration_seconds where available, fall back to timestamps
                sysinfo_durations = pd.to_numeric(self.df[sysinfo_duration_col], errors='coerce')
                timestamp_durations = (end_times - start_times).dt.total_seconds()
                # Use sysinfo where valid, otherwise use timestamp duration
                durations_seconds = sysinfo_durations.fillna(timestamp_durations)
                durations_hours = durations_seconds / 3600.0
            else:
                # No sysinfo available, use timestamps
                if start_times.isna().all() or end_times.isna().all():
                    return None
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
                    duration_hours = durations_hours.iloc[idx]
                    if pd.notna(duration_hours):
                        core_hours = cores * duration_hours
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

        # Create plots directory for image exports (only if explicitly requested and kaleido is available)
        if self.export_plots:
            if KALEIDO_AVAILABLE:
                self.plots_dir = self.workdir / "__iops_plots"
                self.plots_dir.mkdir(exist_ok=True)
                self._plot_counter = 0
            else:
                import logging
                logging.getLogger(__name__).warning(
                    "Plot export requested but kaleido is not installed. "
                    "Install with: pip install iops-benchmark[plots]"
                )

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

        # System environment (if collected from compute nodes)
        sys_env_html = self._generate_system_environment_section()
        if sys_env_html:
            html_parts.append(sys_env_html)

        # Best configurations immediately after summary
        html_parts.append(self._generate_best_configs_section(metrics, report_vars))

        # Add search evolution section
        search_method = self.metadata['benchmark'].get('search_method', '').lower()
        if search_method == 'bayesian':
            html_parts.append(self._generate_bayesian_optimization_section(metrics, report_vars))
        elif search_method == 'random':
            html_parts.append(self._generate_random_search_section(metrics, report_vars))
        else:
            # Exhaustive or other search methods
            html_parts.append(self._generate_exhaustive_search_section(metrics, report_vars))

        # Add comprehensive variable analysis section
        html_parts.append(self._generate_variable_analysis_section(metrics, report_vars))

        # Custom plots defined by user in reporting config
        html_parts.append(self._generate_custom_plots_section(metrics, report_vars))

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
        logo_data_uri = _get_logo_base64()

        # Build logo HTML if available
        logo_html = ""
        if logo_data_uri:
            logo_html = f'<img src="{logo_data_uri}" alt="IOPS Logo" class="report-logo">'

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
        .report-header {{
            display: flex;
            align-items: center;
            gap: 20px;
            border-bottom: 3px solid #3498db;
            padding-bottom: 15px;
            margin-bottom: 20px;
        }}
        .report-logo {{
            height: 64px;
            width: auto;
        }}
        h1 {{
            color: #2c3e50;
            margin: 0;
            flex-grow: 1;
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
        .section-header td {{
            background-color: transparent;
            border-bottom: 2px solid #3498db;
            padding: 8px 0 0 0;
            height: 0;
            line-height: 0;
        }}
        details {{
            margin: 15px 0;
        }}
        details summary {{
            cursor: pointer;
            padding: 10px 15px;
            background-color: #f8f9fa;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-weight: 500;
            color: #34495e;
        }}
        details summary:hover {{
            background-color: #ecf0f1;
        }}
        details[open] summary {{
            border-bottom-left-radius: 0;
            border-bottom-right-radius: 0;
            border-bottom: none;
        }}
        details .details-content {{
            border: 1px solid #ddd;
            border-top: none;
            border-radius: 0 0 4px 4px;
            padding: 0;
        }}
        details .details-content table {{
            margin: 0;
            border: none;
        }}
        details .details-content table td,
        details .details-content table th {{
            border-left: none;
            border-right: none;
        }}
        details .details-content table tr:first-child td {{
            border-top: none;
        }}
        details .details-content table tr:last-child td {{
            border-bottom: none;
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
        /* Fullscreen overlay styles */
        .fullscreen-overlay {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background-color: rgba(255, 255, 255, 0.98);
            z-index: 9999;
            padding: 20px;
            box-sizing: border-box;
        }}
        .fullscreen-overlay.active {{
            display: block;
        }}
        .fullscreen-close {{
            position: absolute;
            top: 15px;
            right: 25px;
            font-size: 32px;
            cursor: pointer;
            color: #333;
            z-index: 10001;
            background: #f0f0f0;
            border: none;
            border-radius: 4px;
            padding: 5px 15px;
        }}
        .fullscreen-close:hover {{
            background: #e0e0e0;
        }}
        .fullscreen-plot {{
            width: 100%;
            height: calc(100vh - 60px);
            margin-top: 40px;
        }}
        /* Fullscreen button on plots */
        .plot-wrapper {{
            position: relative;
        }}
        .fullscreen-btn {{
            position: absolute;
            bottom: 10px;
            left: 10px;
            z-index: 100;
            background: rgba(240,240,240,0.95);
            border: 1px solid #ccc;
            border-radius: 4px;
            padding: 4px 8px;
            cursor: pointer;
            font-size: 12px;
            opacity: 0.7;
            transition: opacity 0.2s;
        }}
        .fullscreen-btn:hover {{
            background: #e0e0e0;
            opacity: 1;
        }}
    </style>
</head>
<body>
<div class="container">
    <div class="report-header">
        {logo_html}
        <h1>{benchmark_name} - Analysis Report</h1>
    </div>
    <div class="info-box">
        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p><strong>Benchmark Run:</strong> {timestamp}</p>
        <p><strong>Description:</strong> {self.metadata['benchmark'].get('description', 'N/A')}</p>
        <p><strong>Total Executions:</strong> {len(self.df)}</p>
    </div>
"""

    def _generate_summary_section(self, report_vars: List[str], metrics: List[str]) -> str:
        """Generate summary statistics section."""
        html = "<h2>Summary Statistics</h2>\n"

        # Gather all data needed for the overview
        benchmark_meta = self.metadata['benchmark']
        executor = benchmark_meta.get('executor', 'local')
        search_method = benchmark_meta.get('search_method', 'exhaustive')
        repetitions = benchmark_meta.get('repetitions', 1)
        total_rows = len(self.df)

        # Get planner stats and calculate combinations
        planner_stats = benchmark_meta.get('planner_stats') or {}
        total_search_space = planner_stats.get('total_space_size', 0)

        if 'execution.execution_id' in self.df.columns:
            combinations_tested = self.df['execution.execution_id'].nunique()
        else:
            combinations_tested = total_rows // repetitions if repetitions > 0 else total_rows

        # Check for cached results
        cached_count = 0
        if 'metadata.__cached' in self.df.columns:
            cached_count = (self.df['metadata.__cached'] == True).sum()

        # ========== EXECUTION OVERVIEW (always visible) ==========
        html += "<h3>Execution Overview</h3>\n<table>\n"
        html += "<tr><th>Metric</th><th>Value</th></tr>\n"

        # Benchmark Name
        html += f"<tr><td><strong>Benchmark Name</strong></td><td>{benchmark_meta.get('name', 'N/A')}</td></tr>\n"

        # Search Method (with seed if applicable)
        random_seed = benchmark_meta.get('random_seed')
        if search_method in ('bayesian', 'random') and random_seed is not None:
            html += f"<tr><td><strong>Search Method</strong></td><td>{search_method} (seed: {random_seed})</td></tr>\n"
        else:
            html += f"<tr><td><strong>Search Method</strong></td><td>{search_method}</td></tr>\n"

        if total_search_space > 0:
            html += f"<tr><td><strong>Total Space</strong></td><td>{total_search_space:,} parameter combinations</td></tr>\n"

        html += f"<tr><td><strong>Total Executions</strong></td><td>{combinations_tested} × {repetitions} = {total_rows}</td></tr>\n"

        # Runtime (essential)
        runtime_str = None
        if 'total_runtime_seconds' in benchmark_meta:
            total_runtime = benchmark_meta['total_runtime_seconds']
            if total_runtime < 60:
                runtime_str = f"{total_runtime:.1f}s"
            elif total_runtime < 3600:
                runtime_str = f"{total_runtime/60:.1f}m"
            else:
                runtime_str = f"{total_runtime/3600:.2f}h"
            html += f"<tr><td><strong>Total Runtime</strong></td><td>{runtime_str}</td></tr>\n"

        # Success rate (essential if there are failures)
        if 'metadata.__executor_status' in self.df.columns:
            status_counts = self.df['metadata.__executor_status'].value_counts()
            succeeded = status_counts.get('SUCCEEDED', 0)
            failed = status_counts.get('FAILED', 0)

            if failed > 0 or succeeded != total_rows:
                success_rate = (succeeded / total_rows * 100) if total_rows > 0 else 0
                html += f"<tr><td><strong>Success Rate</strong></td><td>{succeeded}/{total_rows} ({success_rate:.1f}%)</td></tr>\n"

        html += "</table>\n"

        # ========== METRICS OVERVIEW (always visible) ==========
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

        # ========== COLLAPSIBLE DETAILS ==========
        html += "<details>\n<summary>Execution Details</summary>\n"
        html += '<div class="details-content">\n<table>\n'
        html += "<tr><th>Metric</th><th>Value</th></tr>\n"

        # Environment details
        run_ver = getattr(self, 'run_version', 'unknown')
        report_ver = getattr(self, 'report_version', _get_iops_version())
        if run_ver != 'unknown':
            if run_ver != report_ver:
                html += f"<tr><td><strong>IOPS Version</strong></td><td>{run_ver} <em>(report: v{report_ver})</em></td></tr>\n"
            else:
                html += f"<tr><td><strong>IOPS Version</strong></td><td>{run_ver}</td></tr>\n"

        hostname = benchmark_meta.get('hostname')
        if hostname:
            html += f"<tr><td><strong>Hostname</strong></td><td>{hostname}</td></tr>\n"

        html += f"<tr><td><strong>Executor</strong></td><td>{executor}</td></tr>\n"

        # Detailed timing
        if 'benchmark_start_time' in benchmark_meta:
            start_time = benchmark_meta['benchmark_start_time']
            # Format ISO timestamp more readably
            if 'T' in str(start_time):
                start_time = str(start_time).replace('T', ' ').split('.')[0]
            html += f"<tr><td><strong>Start Time</strong></td><td>{start_time}</td></tr>\n"

        if 'benchmark_end_time' in benchmark_meta:
            end_time = benchmark_meta['benchmark_end_time']
            if 'T' in str(end_time):
                end_time = str(end_time).replace('T', ' ').split('.')[0]
            html += f"<tr><td><strong>End Time</strong></td><td>{end_time}</td></tr>\n"

        # Cached results
        if cached_count > 0:
            executed_count = total_rows - cached_count
            cache_rate = (cached_count / total_rows * 100) if total_rows > 0 else 0
            html += f"<tr><td><strong>Cached Results</strong></td><td>{cached_count} ({cache_rate:.1f}%)</td></tr>\n"
            html += f"<tr><td><strong>Actually Executed</strong></td><td>{executed_count}</td></tr>\n"

        # Average execution duration
        has_timing = 'metadata.__submission_time' in self.df.columns and 'metadata.__end' in self.df.columns
        if has_timing:
            execution_time, formatted_time = self._calculate_total_execution_time()
            if execution_time is not None:
                actual_executed = total_rows - cached_count if cached_count > 0 else total_rows
                if actual_executed > 0:
                    avg_duration = execution_time / actual_executed
                    if avg_duration < 60:
                        avg_duration_str = f"{avg_duration:.1f}s"
                    elif avg_duration < 3600:
                        avg_duration_str = f"{avg_duration / 60:.1f}m"
                    else:
                        avg_duration_str = f"{avg_duration / 3600:.1f}h"
                    html += f"<tr><td><strong>Avg Execution Duration</strong></td><td>{avg_duration_str}</td></tr>\n"

        # SLURM-specific timing
        has_slurm_timing = ('metadata.__job_start' in self.df.columns and
                           'metadata.__submission_time' in self.df.columns and
                           'metadata.__end' in self.df.columns)
        if executor == 'slurm' and has_slurm_timing:
            df_executed = self.df[self.df['metadata.__cached'] != True] if 'metadata.__cached' in self.df.columns else self.df

            if len(df_executed) > 0:
                submit_times = pd.to_datetime(df_executed['metadata.__submission_time'], errors='coerce')
                job_start_times = pd.to_datetime(df_executed['metadata.__job_start'], errors='coerce')
                end_times = pd.to_datetime(df_executed['metadata.__end'], errors='coerce')

                wait_times = (job_start_times - submit_times).dt.total_seconds()
                valid_wait = wait_times[~wait_times.isna()]

                if len(valid_wait) > 0:
                    avg_wait = valid_wait.mean()
                    if avg_wait < 60:
                        wait_str = f"{avg_wait:.1f}s"
                    elif avg_wait < 3600:
                        wait_str = f"{avg_wait/60:.1f}m"
                    else:
                        wait_str = f"{avg_wait/3600:.2f}h"
                    html += f"<tr><td><strong>Avg Queue Wait</strong></td><td>{wait_str}</td></tr>\n"

        # Core-hours
        cores_expr = self.metadata['benchmark'].get('cores_expr')
        if cores_expr:
            total_core_hours = self._calculate_total_core_hours()
            if total_core_hours is not None:
                html += f"<tr><td><strong>Total Core-Hours</strong></td><td>{total_core_hours:.2f}</td></tr>\n"

            avg_cores = self._calculate_average_cores()
            if avg_cores is not None:
                html += f"<tr><td><strong>Avg Cores per Execution</strong></td><td>{avg_cores:.1f}</td></tr>\n"

        html += "</table>\n</div>\n</details>\n"

        # Search Space (collapsible) - show ALL swept variables including strings
        html += "<details>\n<summary>Search Space</summary>\n"
        html += '<div class="details-content">\n<table>\n'
        html += "<tr><th>Variable</th><th>Type</th><th>Values</th></tr>\n"

        all_swept_vars = self._get_swept_vars()
        for var in all_swept_vars:
            col = self._get_var_column(var)
            var_info = self.metadata['variables'].get(var, {})
            var_type = var_info.get('type', 'unknown')
            if col in self.df.columns:
                unique_values = self.df[col].unique()
                # Sort if possible (strings and numbers)
                try:
                    unique_values = sorted(unique_values)
                except TypeError:
                    pass  # Mixed types, keep original order
                values_str = ", ".join(str(v) for v in unique_values)
            else:
                values_str = "N/A"
            html += f"<tr><td><strong>{var}</strong></td><td>{var_type}</td><td>{values_str}</td></tr>\n"

        html += "</table>\n</div>\n</details>\n"

        return html

    def _generate_system_environment_section(self) -> str:
        """
        Generate System Environment section showing compute node information.

        Displays information collected from compute nodes by the system probe:
        - Node hostnames
        - CPU model and core counts
        - Memory
        - Operating system
        - Parallel filesystems (Lustre, GPFS, BeeGFS, etc.)
        - InfiniBand/interconnect devices

        Returns:
            HTML string for the system environment section, or empty string if no data
        """
        sys_env = self.metadata.get('system_environment', {})
        if not sys_env:
            return ""

        html = "<h2>System Environment</h2>\n"
        html += "<p>Information collected from compute nodes during benchmark execution:</p>\n"

        # Summary table (collapsible)
        html += "<details>\n<summary>Hardware Summary</summary>\n"
        html += '<div class="details-content">\n<table>\n'
        html += "<tr><th>Property</th><th>Value</th></tr>\n"

        # Node count
        node_count = sys_env.get('node_count', 0)
        nodes = sys_env.get('nodes', [])
        if node_count > 0:
            if node_count <= 5:
                nodes_str = ', '.join(nodes)
            else:
                # Use expandable details element for long node lists
                nodes_str = (
                    f"<details><summary>{node_count} nodes (click to expand)</summary>"
                    f"<div style='margin-top: 5px;'>{', '.join(nodes)}</div></details>"
                )
            html += f"<tr><td><strong>Compute Nodes</strong></td><td>{nodes_str}</td></tr>\n"

        # CPU info
        cpu_model = sys_env.get('cpu_model')
        if cpu_model:
            if isinstance(cpu_model, list):
                cpu_model = ', '.join(cpu_model)
            html += f"<tr><td><strong>CPU Model</strong></td><td>{cpu_model}</td></tr>\n"

        cpu_cores = sys_env.get('cpu_cores_per_node')
        if cpu_cores:
            html += f"<tr><td><strong>CPU Cores/Node</strong></td><td>{cpu_cores}</td></tr>\n"

        # Memory
        memory = sys_env.get('memory_gb_per_node')
        if memory:
            html += f"<tr><td><strong>Memory/Node</strong></td><td>{memory} GB</td></tr>\n"

        # OS and Kernel
        os_name = sys_env.get('os')
        if os_name:
            if isinstance(os_name, list):
                os_name = ', '.join(os_name)
            html += f"<tr><td><strong>Operating System</strong></td><td>{os_name}</td></tr>\n"

        kernel = sys_env.get('kernel')
        if kernel:
            if isinstance(kernel, list):
                kernel = ', '.join(kernel)
            html += f"<tr><td><strong>Kernel</strong></td><td>{kernel}</td></tr>\n"

        html += "</table>\n</div>\n</details>\n"

        # Parallel Filesystems (collapsible)
        filesystems = sys_env.get('filesystems', [])
        if filesystems:
            html += "<details>\n<summary>Parallel Filesystems</summary>\n"
            html += '<div class="details-content">\n<table>\n'
            html += "<tr><th>Type</th><th>Mount Point</th></tr>\n"
            for fs in filesystems:
                if ':' in fs:
                    fs_type, mount = fs.split(':', 1)
                    html += f"<tr><td>{fs_type}</td><td>{mount}</td></tr>\n"
            html += "</table>\n</div>\n</details>\n"

        # Interconnect
        interconnect = sys_env.get('interconnect', [])
        if interconnect:
            html += "<h3>Interconnect</h3>\n"
            html += f"<p><strong>InfiniBand Devices:</strong> {', '.join(interconnect)}</p>\n"

        return html

    def _generate_best_configs_section(self, metrics: List[str], report_vars: List[str]) -> str:
        """Generate best configurations section."""
        top_n = self.report_config.best_results.top_n
        min_samples = self.report_config.best_results.min_samples

        html = "<h2>Best Configurations</h2>\n"
        html += f"<p>Top {top_n} configurations for each metric"
        if min_samples > 1:
            html += f" (minimum {min_samples} samples required)"
        html += ":</p>\n"

        var_cols = [self._get_var_column(v) for v in report_vars]

        for metric in metrics:
            metric_col = self._get_metric_column(metric)
            if metric_col not in self.df.columns:
                continue

            # Group by parameter combination and get mean
            group_cols = var_cols
            df_grouped = self.df.groupby(group_cols)[metric_col].agg(['mean', 'std', 'count']).reset_index()
            df_grouped.columns = report_vars + ['mean', 'std', 'count']

            # Filter by minimum samples
            df_filtered = df_grouped[df_grouped['count'] >= min_samples]

            if len(df_filtered) == 0:
                html += f"<details>\n<summary>Best for {metric}</summary>\n"
                html += f'<div class="details-content"><p><em>No configurations with at least {min_samples} samples found.</em></p></div>\n</details>\n'
                continue

            # Sort by mean (descending for most metrics, ascending for latency/time)
            ascending = 'latency' in metric.lower() or 'time' in metric.lower()
            df_top = df_filtered.sort_values('mean', ascending=ascending).head(top_n)

            html += f"<details>\n<summary>Best for {metric}</summary>\n"
            html += '<div class="details-content">\n<table>\n<tr><th>Rank</th>'
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

            html += "</table>\n</div>\n</details>\n"

        return html

    def _generate_bayesian_optimization_section(self, metrics: List[str], report_vars: List[str]) -> str:
        """Generate Bayesian optimization search evolution section."""
        html = "<h2>Bayesian Optimization Search Evolution</h2>\n"
        html += "<p>These plots show how the Bayesian optimization algorithm explored the parameter space "
        html += "and converged towards optimal configurations over successive iterations.</p>\n"

        # Get target metric from bayesian_config (support both old and new field names)
        bayesian_config = self.metadata['benchmark'].get('bayesian_config', {})
        target_metric = bayesian_config.get('objective_metric') or bayesian_config.get('target_metric')
        objective = bayesian_config.get('objective', 'minimize')
        n_initial_points = bayesian_config.get('n_initial_points', 5)
        n_iterations = bayesian_config.get('n_iterations', 20)
        acquisition_func = bayesian_config.get('acquisition_func', 'EI')
        base_estimator = bayesian_config.get('base_estimator', 'RF')
        xi = bayesian_config.get('xi', 0.01)
        kappa = bayesian_config.get('kappa', 1.96)

        if not target_metric:
            html += "<p><em>Warning: objective_metric not found in bayesian_config</em></p>\n"
            return html

        # Ensure we have execution_id for ordering
        if 'execution.execution_id' not in self.df.columns:
            html += "<p><em>Warning: execution_id not found in results</em></p>\n"
            return html

        # Get planner stats for search space info
        planner_stats = self.metadata['benchmark'].get('planner_stats') or {}
        total_space_size = planner_stats.get('total_space_size', 0)

        # Display Bayesian optimization configuration (collapsible)
        html += "<details>\n<summary>Optimization Configuration</summary>\n"
        html += '<div class="details-content">\n<table>\n'
        html += "<tr><th>Parameter</th><th>Value</th></tr>\n"
        html += f"<tr><td><strong>Objective Metric</strong></td><td>{target_metric} ({objective})</td></tr>\n"
        html += f"<tr><td><strong>Max Iterations</strong></td><td>{n_iterations}</td></tr>\n"
        html += f"<tr><td><strong>Initial Random Points</strong></td><td>{n_initial_points}</td></tr>\n"
        html += f"<tr><td><strong>Acquisition Function</strong></td><td>{acquisition_func}</td></tr>\n"
        html += f"<tr><td><strong>Surrogate Model</strong></td><td>{base_estimator}</td></tr>\n"
        if acquisition_func in ('EI', 'PI'):
            html += f"<tr><td><strong>Xi (exploration)</strong></td><td>{xi}</td></tr>\n"
        if acquisition_func == 'LCB':
            html += f"<tr><td><strong>Kappa (exploration)</strong></td><td>{kappa}</td></tr>\n"
        html += "</table>\n</div>\n</details>\n"

        # Display search space statistics if available (collapsible)
        if total_space_size > 0:
            # Use actual number of combinations tested from dataframe, not configured n_iterations
            # (may differ due to early stopping, convergence, etc.)
            actual_combinations_tested = self.df['execution.execution_id'].nunique()
            coverage_pct = (actual_combinations_tested / total_space_size) * 100
            savings_pct = 100 - coverage_pct
            combinations_saved = total_space_size - actual_combinations_tested

            html += "<details>\n<summary>Search Space Efficiency</summary>\n"
            html += '<div class="details-content">\n<table>\n'
            html += "<tr><th>Metric</th><th>Value</th></tr>\n"
            html += f"<tr><td><strong>Total Search Space</strong></td><td>{total_space_size:,} parameter combinations</td></tr>\n"
            html += f"<tr><td><strong>Combinations Tested</strong></td><td>{actual_combinations_tested:,} ({coverage_pct:.1f}% of space)</td></tr>\n"
            html += f"<tr><td><strong>Combinations Saved</strong></td><td>{combinations_saved:,} ({savings_pct:.1f}% reduction vs exhaustive)</td></tr>\n"
            html += "</table>\n</div>\n</details>\n"

        # Create plots
        # 1. Metric evolution over iterations
        html += "<h3>Metric Evolution</h3>\n"
        html += "<p>Shows how the target metric evolved as the algorithm explored different configurations. "
        html += "The best value found so far is highlighted.</p>\n"
        fig_metric_evolution = self._create_bayesian_metric_evolution_plot(
            target_metric, objective, n_initial_points, report_vars
        )
        html += f"<div>{self._fig_to_html(fig_metric_evolution, div_id='bayesian_metric_evolution', plot_name=f'bayesian_{target_metric}_evolution')}</div>\n"

        # 2. Parameter evolution over iterations (optional, disabled by default)
        if self.report_config.sections.bayesian_parameter_evolution:
            html += "<h3>Parameter Evolution</h3>\n"
            html += "<p>Shows which parameter values were explored at each iteration. "
            html += "Colors indicate the metric value achieved.</p>\n"
            fig_param_evolution = self._create_bayesian_parameter_evolution_plot(
                report_vars, target_metric, objective, n_initial_points
            )
            html += f"<div>{self._fig_to_html(fig_param_evolution, div_id='bayesian_param_evolution', plot_name='bayesian_parameter_evolution')}</div>\n"

        return html

    def _generate_random_search_section(self, metrics: List[str], report_vars: List[str]) -> str:
        """Generate random search exploration section."""
        html = "<h2>Random Search Exploration</h2>\n"
        html += "<p>This section shows the exploration behavior of the random search. "
        html += "Since random sampling has no optimization objective, both running maximum and minimum "
        html += "are displayed. Compare with Bayesian optimization to assess exploration efficiency.</p>\n"

        # Generate evolution plot for each metric
        for metric in metrics:
            html += f"<h3>{metric} Evolution</h3>\n"
            html += "<p>Shows metric values in execution order. Running max and min lines help visualize "
            html += "the range of values discovered over time.</p>\n"

            try:
                fig = self._create_random_metric_evolution_plot(metric, report_vars)
                html += f"<div>{self._fig_to_html(fig, div_id=f'random_evolution_{metric}', plot_name=f'random_{metric}_evolution')}</div>\n"
            except Exception as e:
                html += f'<p class="error">Error generating evolution plot for {metric}: {str(e)}</p>\n'

        return html

    def _create_random_metric_evolution_plot(self, metric: str, report_vars: List[str]) -> go.Figure:
        """
        Create plot showing metric evolution over random search iterations.

        Shows:
        - Observed metric values at each iteration
        - Running maximum (cumulative max)
        - Running minimum (cumulative min)
        - Variable values on hover

        This allows comparison with Bayesian optimization to assess exploration behavior.
        """
        metric_col = self._get_metric_column(metric)

        # Get variable columns
        var_cols = []
        for var in report_vars:
            col = self._get_var_column(var)
            if col in self.df.columns:
                var_cols.append((var, col))

        # Build aggregation dict - metric mean and first value for each variable
        agg_dict = {metric_col: 'mean'}
        for var_name, col in var_cols:
            agg_dict[col] = 'first'  # Variables are same for all reps of same execution

        # Group by execution_id and compute mean across repetitions
        df_grouped = self.df.groupby('execution.execution_id').agg(agg_dict).reset_index()
        df_grouped = df_grouped.sort_values('execution.execution_id')

        # Use normalized iteration numbers (1, 2, 3, ...) since execution IDs may have gaps
        execution_ids = self._to_python_list(df_grouped['execution.execution_id'].values)
        iterations = list(range(1, len(df_grouped) + 1))
        metric_values = self._to_python_list(df_grouped[metric_col].values)

        # Build hover text with variable values (include actual execution ID)
        hover_texts = []
        for i, (idx, row) in enumerate(df_grouped.iterrows()):
            hover_parts = [f"Iteration: {iterations[i]} (exec_id: {int(row['execution.execution_id'])})"]
            hover_parts.append(f"{metric}: {row[metric_col]:.4f}")
            hover_parts.append("")  # Empty line separator
            for var_name, col in var_cols:
                hover_parts.append(f"{var_name}: {row[col]}")
            hover_texts.append("<br>".join(hover_parts))

        # Compute running max and min
        running_max = self._to_python_list(pd.Series(metric_values).cummax().values)
        running_min = self._to_python_list(pd.Series(metric_values).cummin().values)

        # Create figure
        fig = go.Figure()

        # Observed values
        fig.add_trace(go.Scatter(
            x=iterations,
            y=metric_values,
            mode='markers+lines',
            name='Observed',
            marker=dict(size=10, color='#3498db', line=dict(width=1, color='white')),
            line=dict(color='lightgray', width=1),
            hovertemplate='%{text}<extra></extra>',
            text=hover_texts
        ))

        # Running maximum
        fig.add_trace(go.Scatter(
            x=iterations,
            y=running_max,
            mode='lines',
            name='Max so far',
            line=dict(color='#e74c3c', width=2, dash='dash'),
            hovertemplate='Iteration %{x}<br>Max: %{y:.4f}<extra></extra>'
        ))

        # Running minimum
        fig.add_trace(go.Scatter(
            x=iterations,
            y=running_min,
            mode='lines',
            name='Min so far',
            line=dict(color='#2ecc71', width=2, dash='dash'),
            hovertemplate='Iteration %{x}<br>Min: %{y:.4f}<extra></extra>'
        ))

        fig.update_layout(
            title=f'{metric} Evolution Over Random Iterations',
            xaxis_title='Iteration',
            yaxis_title=metric,
            hovermode='closest',
            template='plotly_white',
            showlegend=True,
            legend=dict(x=0.02, y=0.98, bgcolor='rgba(255,255,255,0.8)')
        )

        return fig

    def _generate_exhaustive_search_section(self, metrics: List[str], report_vars: List[str]) -> str:
        """Generate exhaustive search exploration section."""
        html = "<h2>Exhaustive Search Exploration</h2>\n"
        html += "<p>This section shows the exploration behavior of the exhaustive search. "
        html += "All parameter combinations are tested systematically. Running maximum and minimum "
        html += "lines show the range of values discovered over execution order.</p>\n"

        # Generate evolution plot for each metric
        for metric in metrics:
            html += f"<h3>{metric} Evolution</h3>\n"
            html += "<p>Shows metric values in execution order. Running max and min lines help visualize "
            html += "the range of values discovered over time.</p>\n"

            try:
                fig = self._create_exhaustive_metric_evolution_plot(metric, report_vars)
                html += f"<div>{self._fig_to_html(fig, div_id=f'exhaustive_evolution_{metric}', plot_name=f'exhaustive_{metric}_evolution')}</div>\n"
            except Exception as e:
                html += f'<p class="error">Error generating evolution plot for {metric}: {str(e)}</p>\n'

        return html

    def _create_exhaustive_metric_evolution_plot(self, metric: str, report_vars: List[str]) -> go.Figure:
        """
        Create plot showing metric evolution over exhaustive search iterations.

        Shows:
        - Observed metric values at each iteration
        - Running maximum (cumulative max)
        - Running minimum (cumulative min)
        - Variable values on hover

        This allows comparison with other search methods.
        """
        metric_col = self._get_metric_column(metric)

        # Get variable columns
        var_cols = []
        for var in report_vars:
            col = self._get_var_column(var)
            if col in self.df.columns:
                var_cols.append((var, col))

        # Build aggregation dict - metric mean and first value for each variable
        agg_dict = {metric_col: 'mean'}
        for var_name, col in var_cols:
            agg_dict[col] = 'first'  # Variables are same for all reps of same execution

        # Group by execution_id and compute mean across repetitions
        df_grouped = self.df.groupby('execution.execution_id').agg(agg_dict).reset_index()
        df_grouped = df_grouped.sort_values('execution.execution_id')

        # Use normalized execution numbers (1, 2, 3, ...) for consistent x-axis
        execution_ids = self._to_python_list(df_grouped['execution.execution_id'].values)
        iterations = list(range(1, len(df_grouped) + 1))
        metric_values = self._to_python_list(df_grouped[metric_col].values)

        # Build hover text with variable values (include actual execution ID)
        hover_texts = []
        for i, (idx, row) in enumerate(df_grouped.iterrows()):
            hover_parts = [f"Execution: {iterations[i]} (exec_id: {int(row['execution.execution_id'])})"]
            hover_parts.append(f"{metric}: {row[metric_col]:.4f}")
            hover_parts.append("")  # Empty line separator
            for var_name, col in var_cols:
                hover_parts.append(f"{var_name}: {row[col]}")
            hover_texts.append("<br>".join(hover_parts))

        # Compute running max and min
        running_max = self._to_python_list(pd.Series(metric_values).cummax().values)
        running_min = self._to_python_list(pd.Series(metric_values).cummin().values)

        # Create figure
        fig = go.Figure()

        # Observed values
        fig.add_trace(go.Scatter(
            x=iterations,
            y=metric_values,
            mode='markers+lines',
            name='Observed',
            marker=dict(size=10, color='#9b59b6', line=dict(width=1, color='white')),
            line=dict(color='lightgray', width=1),
            hovertemplate='%{text}<extra></extra>',
            text=hover_texts
        ))

        # Running maximum
        fig.add_trace(go.Scatter(
            x=iterations,
            y=running_max,
            mode='lines',
            name='Max so far',
            line=dict(color='#e74c3c', width=2, dash='dash'),
            hovertemplate='Execution %{x}<br>Max: %{y:.4f}<extra></extra>'
        ))

        # Running minimum
        fig.add_trace(go.Scatter(
            x=iterations,
            y=running_min,
            mode='lines',
            name='Min so far',
            line=dict(color='#2ecc71', width=2, dash='dash'),
            hovertemplate='Execution %{x}<br>Min: %{y:.4f}<extra></extra>'
        ))

        fig.update_layout(
            title=f'{metric} Evolution Over Exhaustive Search',
            xaxis_title='Execution',
            yaxis_title=metric,
            hovermode='closest',
            template='plotly_white',
            showlegend=True,
            legend=dict(x=0.02, y=0.98, bgcolor='rgba(255,255,255,0.8)')
        )

        return fig

    def _generate_custom_plots_section(self, metrics: List[str], report_vars: List[str]) -> str:
        """Generate custom plots section based on user-defined reporting config."""
        from iops.reporting.plots import create_plot

        # Check if any custom plots are defined
        has_any_plots = False
        for metric in metrics:
            if metric in self.report_config.metrics and len(self.report_config.metrics[metric].plots) > 0:
                has_any_plots = True
                break

        if not has_any_plots:
            return ""  # No custom plots defined, return empty

        html = '<div class="metric-section">\n'
        html += "<h2>Custom Metric Plots</h2>\n"
        html += "<p>User-defined plots from the reporting configuration.</p>\n"

        for metric in metrics:
            if metric not in self.report_config.metrics:
                continue

            metric_plots = self.report_config.metrics[metric].plots
            if not metric_plots:
                continue

            metric_col = self._get_metric_column(metric)
            if metric_col not in self.df.columns:
                html += f"<p>Metric '{metric}' not found in results.</p>\n"
                continue

            html += f"<h3>{metric}</h3>\n"

            for plot_config in metric_plots:
                # Handle per_variable plots
                if plot_config.per_variable:
                    for var in report_vars:
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
                            html += self._fig_to_html(fig, plot_name=f'{metric}_{var_config.type}_{var}')
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
                        html += self._fig_to_html(fig, plot_name=f'{metric}_{plot_config.type}')
                        html += '</div>\n'
                    except Exception as e:
                        html += f'<p class="error">Error generating {plot_config.type} plot: {str(e)}</p>\n'

        html += '</div>\n'
        return html

    def _create_bayesian_metric_evolution_plot(
        self, target_metric: str, objective: str, n_initial_points: int, report_vars: List[str]
    ) -> go.Figure:
        """
        Create plot showing metric evolution over Bayesian optimization iterations.

        Shows:
        - Observed metric values at each iteration
        - Running best (cumulative max/min)
        - Distinction between exploration and exploitation phases
        - Variable values on hover
        """
        metric_col = self._get_metric_column(target_metric)

        # Get variable columns
        var_cols = []
        for var in report_vars:
            col = self._get_var_column(var)
            if col in self.df.columns:
                var_cols.append((var, col))

        # Build aggregation dict - metric mean and first value for each variable
        agg_dict = {metric_col: 'mean'}
        for var_name, col in var_cols:
            agg_dict[col] = 'first'  # Variables are same for all reps of same execution

        # Group by execution_id and compute mean across repetitions
        df_grouped = self.df.groupby('execution.execution_id').agg(agg_dict).reset_index()
        df_grouped = df_grouped.sort_values('execution.execution_id')

        # Use normalized iteration numbers (1, 2, 3, ...) for consistent x-axis
        execution_ids = self._to_python_list(df_grouped['execution.execution_id'].values)
        iterations = list(range(1, len(df_grouped) + 1))
        metric_values = self._to_python_list(df_grouped[metric_col].values)

        # Build hover text with variable values (include actual execution ID)
        hover_texts = []
        for i, (idx, row) in enumerate(df_grouped.iterrows()):
            hover_parts = [f"Iteration: {iterations[i]} (exec_id: {int(row['execution.execution_id'])})"]
            hover_parts.append(f"{target_metric}: {row[metric_col]:.4f}")
            hover_parts.append("")  # Empty line separator
            for var_name, col in var_cols:
                hover_parts.append(f"{var_name}: {row[col]}")
            hover_texts.append("<br>".join(hover_parts))

        # Compute running best
        if objective == 'maximize':
            running_best = self._to_python_list(pd.Series(metric_values).cummax().values)
        else:
            running_best = self._to_python_list(pd.Series(metric_values).cummin().values)

        # Create figure with two traces
        fig = go.Figure()

        # Observed values with phase coloring (blue for exploration, green for exploitation)
        colors = ['#3498db' if i < n_initial_points else '#2ecc71' for i in range(len(iterations))]

        fig.add_trace(go.Scatter(
            x=iterations,
            y=metric_values,
            mode='markers+lines',
            name='Observed',
            marker=dict(size=10, color=colors, line=dict(width=1, color='white')),
            line=dict(color='lightgray', width=1),
            hovertemplate='%{text}<extra></extra>',
            text=hover_texts
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

        # Use normalized iteration numbers (1, 2, 3, ...) for consistent x-axis
        iterations = list(range(1, len(df_grouped) + 1))
        metric_values = self._to_python_list(df_grouped[metric_col].values)

        # Create subplots - one per parameter
        n_params = len(report_vars)
        fig = make_subplots(
            rows=n_params, cols=1,
            subplot_titles=[f'{var} Evolution' for var in report_vars],
            vertical_spacing=0.15 / max(n_params, 1)
        )

        for idx, var in enumerate(report_vars, 1):
            var_col = self._get_var_column(var)
            param_values = self._to_python_list(df_grouped[var_col].values)

            # Get unique sorted values for this parameter
            unique_values = self._to_python_list(sorted(df_grouped[var_col].unique()))

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

        # Get color palette for the series
        series_values = sorted(df_grouped[var2_col].unique())
        user_colors = self._get_user_colors()
        colors = self.get_color_palette(len(series_values), user_colors)

        for idx, val2 in enumerate(series_values):
            df_slice = df_grouped[df_grouped[var2_col] == val2].sort_values(var1_col)

            # Map var1 values to categorical strings
            x_slice = [str(x) for x in df_slice[var1_col]]

            fig.add_trace(go.Scatter(
                x=x_slice,
                y=df_slice[metric_col],
                mode='lines+markers',
                name=f'{var2}={val2}',
                marker=dict(size=10, color=colors[idx]),
                line=dict(color=colors[idx])
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

    def _generate_variable_analysis_section(self, metrics: List[str], report_vars: List[str]) -> str:
        """
        Generate variable analysis section with key visualizations.

        This section provides:
        1. Parallel coordinates plot for multidimensional patterns
        2. Variable importance/contribution analysis
        """
        show_parallel = self.report_config.sections.parallel_coordinates
        show_impact = self.report_config.sections.variable_impact

        # Skip entire section if both are disabled
        if not show_parallel and not show_impact:
            return ""

        html = '<div class="metric-section">\n'
        html += "<h2>Variable Analysis & Relationships</h2>\n"
        html += "<p>Analysis of how variables relate to performance metrics.</p>\n"

        # 1. Parallel coordinates plot
        if show_parallel:
            html += "<h3>Parallel Coordinates Plot</h3>\n"
            html += "<p>Visualizes all variables simultaneously. Each line represents one configuration, "
            html += "colored by performance. Patterns and clusters reveal optimal parameter combinations.</p>\n"

            for metric in metrics:
                fig_parallel = self._create_parallel_coordinates(metric, report_vars)
                if fig_parallel is not None:
                    html += '<div class="plot-container">\n'
                    html += self._fig_to_html(fig_parallel, plot_name=f'parallel_coordinates_{metric}')
                    html += '</div>\n'

        # 2. Variable impact analysis
        if show_impact:
            html += "<h3>Variable Impact on Performance</h3>\n"
            html += "<div class='info-box'>\n"
            html += "<p><strong>Statistical Method:</strong> Variance decomposition analysis</p>\n"
            html += "<p>The impact score quantifies the proportion of total variance in the performance metric that is explained by each variable. "
            html += "For each variable, the metric values are grouped by the variable's levels, and the between-group variance is computed. "
            html += "The impact score is calculated as:</p>\n"
            html += "<p style='text-align: center; font-family: monospace; background-color: #f8f8f8; padding: 10px; margin: 10px 0;'>"
            html += "Impact = σ²_between / σ²_total</p>\n"
            html += "<p>where σ²_between is the variance of group means (weighted by group size) and σ²_total is the overall variance of the metric. "
            html += "This measure is analogous to the R² coefficient in regression or the eta-squared (η²) effect size in ANOVA. "
            html += "Values range from 0 (no effect) to 1 (variable fully determines the metric).</p>\n"
            html += "</div>\n"

            for metric in metrics:
                fig_impact = self._create_variable_impact_plot(metric, report_vars)
                if fig_impact is not None:
                    html += '<div class="plot-container">\n'
                    html += self._fig_to_html(fig_impact, plot_name=f'variable_impact_{metric}')
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

            # Filter out rows with NaN metric values
            df_corr = df_corr[df_corr[metric_col].notna()]

            if len(df_corr) == 0:
                return None

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

            # Filter out rows with NaN metric values
            df_clean = self.df[self.df[metric_col].notna()].copy()

            if len(df_clean) == 0:
                return None

            # Group by variables and compute mean metric
            df_grouped = df_clean.groupby(var_cols)[metric_col].mean().reset_index()

            # Prepare dimensions for parallel coordinates
            dimensions = []

            for var in report_vars:
                var_col = self._get_var_column(var)
                dimensions.append(dict(
                    label=var,
                    values=self._to_python_list(df_grouped[var_col])
                ))

            # Add metric as the last dimension and for coloring
            metric_values = self._to_python_list(df_grouped[metric_col])
            dimensions.append(dict(
                label=metric,
                values=metric_values
            ))

            fig = go.Figure(data=go.Parcoords(
                line=dict(
                    color=metric_values,
                    colorscale='Viridis',
                    showscale=True,
                    cmin=min(metric_values),
                    cmax=max(metric_values),
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

            # Filter out rows with NaN metric values
            df_clean = self.df[self.df[metric_col].notna()].copy()

            if len(df_clean) == 0:
                # No valid data points
                return None

            impacts = []
            for var in report_vars:
                var_col = self._get_var_column(var)

                # Group by this variable
                groups = df_clean.groupby(var_col)[metric_col].apply(list)

                # Calculate between-group and within-group variance
                overall_mean = df_clean[metric_col].mean()

                # Between-group variance
                between_var = sum(
                    len(group) * (np.mean(group) - overall_mean) ** 2
                    for group in groups
                ) / len(df_clean)

                # Total variance
                total_var = df_clean[metric_col].var()

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

            # Filter out rows with NaN metric values
            df_clean = self.df[self.df[metric_col].notna()].copy()

            if len(df_clean) == 0:
                return None

            # Group by variables and compute mean metric
            df_grouped = df_clean.groupby(var_cols)[metric_col].mean().reset_index()

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
        run_ver = getattr(self, 'run_version', 'unknown')
        report_ver = getattr(self, 'report_version', _get_iops_version())

        if run_ver != 'unknown' and run_ver != report_ver:
            version_info = f"Run: v{run_ver} | Report: v{report_ver}"
        else:
            version_info = f"v{report_ver}"

        return f"""
    <div class="footer">
        <p>Generated by IOPS {version_info} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
</div>

<!-- Fullscreen overlay -->
<div id="fullscreen-overlay" class="fullscreen-overlay">
    <button class="fullscreen-close" onclick="closeFullscreen()">&times;</button>
    <div id="fullscreen-plot" class="fullscreen-plot"></div>
</div>

<script>
// Fullscreen functionality for Plotly plots
document.addEventListener('DOMContentLoaded', function() {{
    // Find all plotly graph divs and wrap them with fullscreen button
    const plotlyDivs = document.querySelectorAll('.plotly-graph-div');
    plotlyDivs.forEach(function(plotDiv, index) {{
        // Create wrapper if not already wrapped
        if (!plotDiv.parentElement.classList.contains('plot-wrapper')) {{
            const wrapper = document.createElement('div');
            wrapper.className = 'plot-wrapper';
            plotDiv.parentElement.insertBefore(wrapper, plotDiv);
            wrapper.appendChild(plotDiv);

            // Add fullscreen button
            const btn = document.createElement('button');
            btn.className = 'fullscreen-btn';
            btn.innerHTML = '&#x26F6; Fullscreen';
            btn.onclick = function() {{ openFullscreen(plotDiv); }};
            wrapper.appendChild(btn);
        }}
    }});
}});

function openFullscreen(plotDiv) {{
    const overlay = document.getElementById('fullscreen-overlay');
    const fullscreenPlot = document.getElementById('fullscreen-plot');

    // Get the original plot data and layout
    const originalData = plotDiv.data;
    const originalLayout = JSON.parse(JSON.stringify(plotDiv.layout));

    // Adjust layout for fullscreen
    originalLayout.autosize = true;
    delete originalLayout.height;
    delete originalLayout.width;

    // Create the fullscreen plot
    Plotly.newPlot(fullscreenPlot, originalData, originalLayout, {{
        displayModeBar: true,
        scrollZoom: true,
        displaylogo: false,
        responsive: true
    }});

    // Show overlay
    overlay.classList.add('active');
    document.body.style.overflow = 'hidden';

    // Trigger resize to fit
    Plotly.Plots.resize(fullscreenPlot);
}}

function closeFullscreen() {{
    const overlay = document.getElementById('fullscreen-overlay');
    const fullscreenPlot = document.getElementById('fullscreen-plot');

    overlay.classList.remove('active');
    document.body.style.overflow = '';

    // Clear the fullscreen plot
    Plotly.purge(fullscreenPlot);
}}

// Close fullscreen on Escape key
document.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') {{
        closeFullscreen();
    }}
}});
</script>

</body>
</html>
"""


def generate_report_from_workdir(
    workdir: Path,
    output_path: Optional[Path] = None,
    report_config: Optional[ReportingConfig] = None,
    export_plots: bool = False,
    plot_format: str = 'pdf'
) -> Path:
    """
    Convenience function to generate report from a workdir.

    Args:
        workdir: Path to benchmark working directory
        output_path: Optional custom output path
        report_config: Optional reporting configuration (overrides metadata config)
        export_plots: Whether to export plots as image files
        plot_format: Image format for exported plots (pdf, png, svg, jpg, webp)

    Returns:
        Path to generated HTML report
    """
    generator = ReportGenerator(
        workdir,
        report_config=report_config,
        export_plots=export_plots,
        plot_format=plot_format
    )
    generator.load_metadata()
    generator.load_results()
    return generator.generate_report(output_path)
