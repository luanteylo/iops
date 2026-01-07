"""Report configuration template generation for IOPS.

This module provides functions for:
- Serializing ReportingConfig to JSON-serializable dictionaries
- Generating report_config.yaml templates for user customization
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from iops.config.models import (
        GenericBenchmarkConfig,
        ReportingConfig,
        VarConfig,
        ScriptConfig,
    )


def _serialize_plot_config(plot_cfg) -> Dict[str, Any]:
    """Serialize a PlotConfig to dict."""
    return {
        "type": plot_cfg.type,
        "x_var": plot_cfg.x_var,
        "y_var": plot_cfg.y_var,
        "z_metric": plot_cfg.z_metric,
        "group_by": plot_cfg.group_by,
        "color_by": plot_cfg.color_by,
        "size_by": plot_cfg.size_by,
        "title": plot_cfg.title,
        "xaxis_label": plot_cfg.xaxis_label,
        "yaxis_label": plot_cfg.yaxis_label,
        "colorscale": plot_cfg.colorscale,
        "show_error_bars": plot_cfg.show_error_bars,
        "show_outliers": plot_cfg.show_outliers,
        "height": plot_cfg.height,
        "width": plot_cfg.width,
        "per_variable": plot_cfg.per_variable,
        "include_metric": plot_cfg.include_metric,
    }


def serialize_reporting_config(reporting: "ReportingConfig") -> Optional[Dict[str, Any]]:
    """
    Serialize ReportingConfig to JSON-serializable dict.

    Args:
        reporting: ReportingConfig object to serialize

    Returns:
        Dictionary representation of the config, or None if reporting is None
    """
    if not reporting:
        return None

    return {
        "enabled": reporting.enabled,
        "output_dir": str(reporting.output_dir) if reporting.output_dir else None,
        "output_filename": reporting.output_filename,
        "theme": {
            "style": reporting.theme.style,
            "colors": reporting.theme.colors,
            "font_family": reporting.theme.font_family,
        },
        "sections": {
            "test_summary": reporting.sections.test_summary,
            "best_results": reporting.sections.best_results,
            "variable_impact": reporting.sections.variable_impact,
            "parallel_coordinates": reporting.sections.parallel_coordinates,
            "pareto_frontier": reporting.sections.pareto_frontier,
            "bayesian_evolution": reporting.sections.bayesian_evolution,
            "custom_plots": reporting.sections.custom_plots,
        },
        "best_results": {
            "top_n": reporting.best_results.top_n,
            "show_command": reporting.best_results.show_command,
        },
        "plot_defaults": {
            "height": reporting.plot_defaults.height,
            "width": reporting.plot_defaults.width,
            "margin": reporting.plot_defaults.margin,
        },
        "metrics": {
            metric_name: {
                "plots": [_serialize_plot_config(p) for p in metric_plots.plots]
            }
            for metric_name, metric_plots in reporting.metrics.items()
        },
        "default_plots": [_serialize_plot_config(p) for p in reporting.default_plots],
    }


def _get_swept_vars(vars_config: Dict[str, "VarConfig"]) -> List[str]:
    """Get list of swept variable names."""
    return [name for name, var in vars_config.items() if var.sweep is not None]


def _get_all_metrics(scripts: List["ScriptConfig"]) -> List[str]:
    """Get list of all metric names from scripts."""
    metrics = []
    for script in scripts:
        if script.parser and script.parser.metrics:
            metrics.extend([m.name for m in script.parser.metrics])
    return metrics


def _create_clean_report_config(
    reporting: "ReportingConfig",
    scripts: List["ScriptConfig"],
) -> Dict[str, Any]:
    """
    Create a clean, editable version of the user's reporting config.

    Includes what they specified + suggestions for expansion based on execution.

    Args:
        reporting: User's ReportingConfig
        scripts: List of script configs (to extract metrics)

    Returns:
        Dictionary with clean config suitable for YAML output
    """
    # Start with user's settings
    config = {
        "enabled": reporting.enabled,
        "output_filename": reporting.output_filename,
    }

    # Add output_dir only if specified
    if reporting.output_dir:
        config["output_dir"] = str(reporting.output_dir)

    # Theme (only include if non-default)
    if (reporting.theme.style != "plotly_white" or
        reporting.theme.colors or
        reporting.theme.font_family != "Segoe UI, sans-serif"):
        theme = {"style": reporting.theme.style}
        if reporting.theme.colors:
            theme["colors"] = reporting.theme.colors
        if reporting.theme.font_family != "Segoe UI, sans-serif":
            theme["font_family"] = reporting.theme.font_family
        config["theme"] = theme

    # Sections (only include if not all True)
    sections_dict = {
        "test_summary": reporting.sections.test_summary,
        "best_results": reporting.sections.best_results,
        "variable_impact": reporting.sections.variable_impact,
        "custom_plots": reporting.sections.custom_plots,
    }
    if not all(sections_dict.values()):
        config["sections"] = sections_dict

    # User's metric configs
    if reporting.metrics:
        metrics_config = {}
        for metric_name, metric_plots_config in reporting.metrics.items():
            plots = []
            for plot_cfg in metric_plots_config.plots:
                plot_dict = {"type": plot_cfg.type}
                if plot_cfg.x_var:
                    plot_dict["x_var"] = plot_cfg.x_var
                if plot_cfg.y_var:
                    plot_dict["y_var"] = plot_cfg.y_var
                if plot_cfg.group_by:
                    plot_dict["group_by"] = plot_cfg.group_by
                if plot_cfg.title:
                    plot_dict["title"] = plot_cfg.title
                if plot_cfg.colorscale != "Viridis":
                    plot_dict["colorscale"] = plot_cfg.colorscale
                plots.append(plot_dict)
            metrics_config[metric_name] = {"plots": plots}
        config["metrics"] = metrics_config

    # Get metrics from execution to suggest expansions
    all_metrics = _get_all_metrics(scripts)

    # Add suggestions for metrics not yet configured
    unconfigured_metrics = [m for m in all_metrics if m not in reporting.metrics.keys()]
    if unconfigured_metrics:
        config["_suggestions"] = {
            "unconfigured_metrics": unconfigured_metrics,
            "hint": "Add plot configurations for these metrics to customize their visualizations"
        }

    # Default plots
    if reporting.default_plots:
        default_plots = []
        for plot_cfg in reporting.default_plots:
            plot_dict = {"type": plot_cfg.type}
            if plot_cfg.per_variable:
                plot_dict["per_variable"] = plot_cfg.per_variable
            if plot_cfg.show_error_bars:
                plot_dict["show_error_bars"] = plot_cfg.show_error_bars
            default_plots.append(plot_dict)
        config["default_plots"] = default_plots

    return config


def _generate_default_report_config(
    vars_config: Dict[str, "VarConfig"],
    scripts: List["ScriptConfig"],
) -> Dict[str, Any]:
    """
    Generate a smart report config template based on execution.

    Args:
        vars_config: Variable configurations
        scripts: Script configurations

    Returns:
        Dictionary with generated config template
    """
    swept_vars = _get_swept_vars(vars_config)
    metrics = _get_all_metrics(scripts)

    # Build template - colors are auto-generated (24 distinct colors)
    # Users can override by adding: colors: ["#hex1", "#hex2", ...]
    template = {
        "enabled": False,  # User must opt-in
        "output_filename": "analysis_report.html",
        "theme": {
            "style": "plotly_white",
        },
        "sections": {
            "test_summary": True,
            "best_results": True,
            "variable_impact": True,
            "custom_plots": True,
        },
    }

    # Add metric-specific plot examples if we have metrics
    if metrics and swept_vars:
        template["metrics"] = {}

        # Add examples for first metric
        first_metric = metrics[0]
        plots = []

        # Line plot if we have variables
        if len(swept_vars) >= 1:
            line_plot = {
                "type": "line",
                "x_var": swept_vars[0],
            }
            if len(swept_vars) >= 2:
                line_plot["group_by"] = swept_vars[1]
            plots.append(line_plot)

        # Heatmap if we have 2+ variables
        if len(swept_vars) >= 2:
            plots.append({
                "type": "heatmap",
                "x_var": swept_vars[0],
                "y_var": swept_vars[1],
            })

        template["metrics"][first_metric] = {"plots": plots}

        # Add comment about other metrics
        if len(metrics) > 1:
            template["_comment"] = f"Add plot configs for other metrics: {', '.join(metrics[1:])}"

    # Add default plots
    template["default_plots"] = [
        {
            "type": "bar",
            "per_variable": True,
            "show_error_bars": True,
        }
    ]

    return template


def save_report_config_template(
    cfg: "GenericBenchmarkConfig",
    output_path: Optional[Path] = None,
    logger: Optional[logging.Logger] = None,
) -> Optional[Path]:
    """
    Save a report_config.yaml template to workdir for easy report regeneration.

    If user provided reporting config, saves a clean version they can expand.
    Otherwise, generates a smart template based on detected metrics and variables.

    Args:
        cfg: The benchmark configuration
        output_path: Path to save the template (defaults to workdir/report_config.yaml)
        logger: Optional logger for status messages

    Returns:
        Path to the saved template, or None if saving failed
    """
    import yaml

    if logger is None:
        logger = logging.getLogger(__name__)

    if output_path is None:
        output_path = cfg.benchmark.workdir / "report_config.yaml"

    try:
        if cfg.reporting:
            # User provided config - create clean version they can expand
            config_dict = _create_clean_report_config(cfg.reporting, cfg.scripts)
            has_user_config = True
        else:
            # Generate smart template based on execution
            config_dict = _generate_default_report_config(cfg.vars, cfg.scripts)
            has_user_config = False

        # Get swept variables and metrics for reference comments
        swept_vars = _get_swept_vars(cfg.vars)
        all_metrics = _get_all_metrics(cfg.scripts)

        # Wrap in reporting section
        yaml_content = {"reporting": config_dict}

        with open(output_path, 'w') as f:
            # Add header comment
            f.write("# IOPS Report Configuration\n")
            f.write("# This file was auto-generated based on your benchmark execution.\n")
            f.write("# Edit and use with: iops --analyze <workdir> --report-config report_config.yaml\n")
            f.write("#\n")
            if has_user_config:
                f.write("# This config is based on your provided reporting settings.\n")
                f.write("# You can expand it by adding more plot types or customizing existing ones.\n")
            else:
                f.write("# This config is a template based on your benchmark metrics and variables.\n")
                f.write("# Customize the plots and settings, then set enabled: true to auto-generate reports.\n")
            f.write("#\n")
            f.write("# Documentation: https://lgouveia.gitlabpages.inria.fr/iops/user-guide/reporting/\n")
            f.write("#\n")

            # Add reference section for available variables and metrics
            f.write("# ============================================================================\n")
            f.write("# AVAILABLE VARIABLES AND METRICS (for use in plot configurations)\n")
            f.write("# ============================================================================\n")
            f.write("#\n")

            if swept_vars:
                f.write("# Swept Variables (use for x_var, y_var, group_by, color_by):\n")
                for var in swept_vars:
                    var_type = cfg.vars[var].type
                    f.write(f"#   - {var} ({var_type})\n")
                f.write("#\n")
            else:
                f.write("# No swept variables detected\n")
                f.write("#\n")

            if all_metrics:
                f.write("# Metrics (use for configuring plots):\n")
                for metric in all_metrics:
                    f.write(f"#   - {metric}\n")
                f.write("#\n")
            else:
                f.write("# No metrics detected\n")
                f.write("#\n")

            f.write("# Plot Types Available:\n")
            f.write("#   - bar, line, scatter, heatmap, box, violin, surface_3d\n")
            f.write("#   - parallel_coordinates, execution_scatter, coverage_heatmap\n")
            f.write("#\n")
            f.write("# Colors:\n")
            f.write("#   - 24 distinct colors are auto-generated by default\n")
            f.write("#   - To customize, add under theme: colors: [\"#hex1\", \"#hex2\", ...]\n")
            f.write("#\n")
            f.write("# ============================================================================\n")
            f.write("\n")

            yaml.dump(yaml_content, f, default_flow_style=False, sort_keys=False, indent=2)

        logger.info(f"Report config template saved: {output_path.relative_to(cfg.benchmark.workdir.parent)}")
        return output_path

    except Exception as e:
        logger.debug(f"Failed to save report config template: {e}")
        return None
