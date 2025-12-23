# iops/config/models.py

"""Configuration data models for IOPS benchmark definitions."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal
from dataclasses import dataclass, field
from pathlib import Path


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""
    pass


# ----------------- Core blocks ----------------- #

@dataclass
class ExecutorOptionsConfig:
    """
    Executor-specific configuration options.

    For SLURM executor, you can override the commands used for job management.
    Commands are templates that support {job_id} placeholder for dynamic substitution.
    This is useful when running on systems with command wrappers or custom SLURM installations.

    Example with default SLURM commands:
        executor_options:
          commands:
            submit: "sbatch"                                      # Default submit (per-script override)
            status: "squeue -j {job_id} --noheader --format=%T"  # Job status query
            info: "scontrol show job {job_id}"                   # Job information
            cancel: "scancel {job_id}"                           # Job cancellation
          poll_interval: 30                                       # Status check interval (seconds)

    Example with wrapper and custom flags:
        executor_options:
          commands:
            submit: "lrms-wrapper sbatch"
            status: "lrms-wrapper -r {job_id} --custom-format"   # Custom flags
            info: "lrms-wrapper info {job_id}"
            cancel: "lrms-wrapper kill {job_id}"
          poll_interval: 10                                       # Check status every 10 seconds

    Placeholders:
        {job_id} - Replaced with the SLURM job ID at runtime

    Note: The submit command specified here is a default. Individual scripts can override
    it by specifying their own submit command in scripts[].submit.
    """
    commands: Optional[Dict[str, str]] = None
    poll_interval: Optional[int] = None  # Polling interval in seconds for SLURM job status checks


@dataclass
class BenchmarkConfig:
    name: str
    description: Optional[str]
    workdir: Path
    repetitions: Optional[int] = 1        # global default (can be ignored if rounds have their own)
    sqlite_db: Optional[Path] = None
    search_method: Optional[str] = None  # e.g., "greedy", "exhaustive", etc.
    executor: Optional[str] = "slurm"  # e.g., "local", "slurm", etc.
    executor_options: Optional[ExecutorOptionsConfig] = None  # executor-specific configuration
    random_seed: Optional[int] = None  # seed for any random operations
    cache_exclude_vars: Optional[List[str]] = None  # variables to exclude from cache hash
    exhaustive_vars: Optional[List[str]] = None  # variables to exhaustively test for each search point
    max_core_hours: Optional[float] = None  # Budget limit in core-hours
    cores_expr: Optional[str] = None  # Jinja expression to compute cores (e.g., "{{ nodes * ppn }}")
    estimated_time_seconds: Optional[float] = None  # Estimated execution time per test (for dry-run)
    report_vars: Optional[List[str]] = None  # Variables to include in analysis reports (default: all numeric swept vars)
    bayesian_config: Optional[Dict[str, Any]] = None  # Bayesian optimization configuration
    random_config: Optional[Dict[str, Any]] = None  # Random sampling configuration


@dataclass
class SweepConfig:
    mode: Literal["range", "list"]
    # range
    start: Optional[int] = None
    end: Optional[int] = None
    step: Optional[int] = None
    # list
    values: Optional[List[Any]] = None


@dataclass
class VarConfig:
    type: str                 # "int", "float", "str", etc.
    sweep: Optional[SweepConfig] = None
    expr: Optional[str] = None  # for derived vars


@dataclass
class ConstraintConfig:
    """A validation constraint on parameter combinations."""
    name: str                                                   # Unique constraint identifier
    rule: str                                                   # Python expression returning bool
    violation_policy: Literal["skip", "error", "warn"] = "skip"  # Action on violation
    description: Optional[str] = None                           # Human-readable description


@dataclass
class CommandConfig:
    template: str
    metadata: Dict[str, Any]
    env: Dict[str, str]


@dataclass
class PostConfig:
    # whole `post` block is optional;
    # if present, `script` can be empty (your choice)
    script: Optional[str] = None


@dataclass
class MetricConfig:
    name: str
    path: Optional[str] = None  # e.g. JSON path, optional if parser_script handles it


@dataclass
class ParserConfig:
    file: str
    metrics: List[MetricConfig]
    # parser_script is optional
    parser_script: Optional[str] = None


@dataclass
class ScriptConfig:
    name: str
    submit: str
    script_template: str
    post: Optional[PostConfig] = None      # optional
    parser: Optional[ParserConfig] = None  # optional


@dataclass
class OutputSinkConfig:
    type: Literal["csv", "parquet", "sqlite"]
    path: str
    mode: Literal["append", "overwrite"] = "append"
    include: List[str] = field(default_factory=list)
    exclude: List[str] = field(default_factory=list)
    table: str = "results"  # sqlite only

    resolved_path: Optional[Path] = None


@dataclass
class OutputConfig:
    sink: OutputSinkConfig


# ----------------- Rounds blocks ----------------- #

@dataclass
class RoundSearchConfig:
    """
    Search definition inside a round.

    Example in YAML:

      search:
        metric: "write_bandwidth"
        objective: "max"   # max | min
        # select: "best"   # optional, future extension
    """
    metric: str
    objective: Literal["max", "min"]
    select: Optional[str] = None  # e.g., "best", "top_k", etc. (optional / future use)


@dataclass
class RoundConfig:
    """
    One optimization / search round.

    YAML example:

      - name: "nodes_sweep"
        description: "Find best nodes by write bandwidth."
        sweep_vars: ["nodes"]
        fixed_overrides:
          block_size_mb: 16
          processes_per_node: 16
        search:
          metric: "write_bandwidth"
          objective: "max"

    Note: repetitions are global (benchmark.repetitions), not per-round.
    """
    name: str
    description: Optional[str]
    sweep_vars: List[str] = field(default_factory=list)
    fixed_overrides: Dict[str, Any] = field(default_factory=dict)
    search: RoundSearchConfig | None = None


# ----------------- Reporting blocks ----------------- #

@dataclass
class ReportThemeConfig:
    """Theming options for report generation."""
    style: str = "plotly_white"
    colors: Optional[List[str]] = None
    font_family: str = "Segoe UI, Tahoma, Geneva, Verdana, sans-serif"


@dataclass
class PlotConfig:
    """Configuration for a single plot."""
    type: Literal["line", "bar", "scatter", "box", "violin", "heatmap", "surface_3d", "parallel_coordinates"]

    # Variable selection
    x_var: Optional[str] = None
    y_var: Optional[str] = None  # For scatter, surface_3d
    z_metric: Optional[str] = None  # For heatmap, surface_3d

    # Grouping/coloring
    group_by: Optional[str] = None
    color_by: Optional[str] = None
    size_by: Optional[str] = None

    # Labels & titles
    title: Optional[str] = None
    xaxis_label: Optional[str] = None
    yaxis_label: Optional[str] = None

    # Plot-specific options
    colorscale: str = "Viridis"
    show_error_bars: bool = True
    show_outliers: bool = True  # For box plots

    # Sizing
    height: Optional[int] = None
    width: Optional[int] = None

    # Special flags
    per_variable: bool = False  # Generate one plot per swept variable
    include_metric: bool = True  # For parallel_coordinates


@dataclass
class MetricPlotsConfig:
    """Plot configurations for a specific metric."""
    plots: List[PlotConfig] = field(default_factory=list)


@dataclass
class SectionConfig:
    """Which sections to include in report."""
    test_summary: bool = True
    best_results: bool = True
    variable_impact: bool = True
    parallel_coordinates: bool = True
    pareto_frontier: bool = True
    bayesian_evolution: bool = True
    custom_plots: bool = True


@dataclass
class BestResultsConfig:
    """Configuration for best results section."""
    top_n: int = 5
    show_command: bool = True


@dataclass
class PlotDefaultsConfig:
    """Default sizing and margins for plots."""
    height: int = 500
    width: Optional[int] = None
    margin: Optional[Dict[str, int]] = None


@dataclass
class ReportingConfig:
    """Complete reporting configuration."""
    enabled: bool = False
    output_dir: Optional[Path] = None
    output_filename: str = "analysis_report.html"

    theme: ReportThemeConfig = field(default_factory=ReportThemeConfig)
    sections: SectionConfig = field(default_factory=SectionConfig)
    best_results: BestResultsConfig = field(default_factory=BestResultsConfig)

    metrics: Dict[str, MetricPlotsConfig] = field(default_factory=dict)
    default_plots: List[PlotConfig] = field(default_factory=list)

    plot_defaults: PlotDefaultsConfig = field(default_factory=PlotDefaultsConfig)


@dataclass
class GenericBenchmarkConfig:
    benchmark: BenchmarkConfig
    vars: Dict[str, VarConfig]
    command: CommandConfig
    scripts: List[ScriptConfig]
    output: OutputConfig
    constraints: List[ConstraintConfig] = field(default_factory=list)
    rounds: List[RoundConfig] = field(default_factory=list)
    reporting: Optional[ReportingConfig] = None
