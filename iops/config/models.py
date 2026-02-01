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
class AllocationConfig:
    """
    Configuration for SLURM single-allocation mode.

    In single-allocation mode, all tests run within ONE SLURM allocation instead of
    submitting individual jobs per test. This reduces job submission overhead and is
    useful for HPC systems with job limits or queue wait times.

    The user provides SBATCH directives and setup code in `allocation_script`. IOPS will:
    - Add shebang if not provided
    - Add job-name, output, and error directives
    - Generate an execution script that runs all tests sequentially

    Allocation Modes:
        - "per-test" (default): Each test is submitted as a separate SLURM job
        - "single": Pre-generates an execution script that runs all tests sequentially
          within a single allocation, reducing per-test overhead from ~5-30s to ~100ms

    Attributes:
        mode: Allocation mode - "single" or "per-test" (default)
        allocation_script: SBATCH directives + setup code (required when mode="single")
        test_timeout: Per-test timeout in seconds for single-allocation mode (default: 3600)

    Example (single-allocation mode):
        slurm_options:
          allocation:
            mode: "single"
            test_timeout: 300  # 5 minutes per test
            allocation_script: |
              #SBATCH --nodes=8
              #SBATCH --time=02:00:00
              #SBATCH --partition=compute
              #SBATCH --exclusive

              module purge
              module load mpi/openmpi/4.0.1

              # Any setup that runs once before all tests

    In single-allocation mode:
    - allocation_script contains SBATCH directives AND setup (modules, env vars)
    - script_template contains the srun command with Jinja2 variables
    - User controls srun directly in script_template (no automatic MPI wrapping)
    """
    mode: str = "per-test"  # "single" or "per-test"
    allocation_script: Optional[str] = None
    test_timeout: int = 3600  # Per-test timeout in seconds for single-allocation mode


@dataclass
class SlurmOptionsConfig:
    """
    SLURM executor configuration options.

    Override commands used for job management, configure polling, or enable single-allocation mode.
    Commands are templates that support {job_id} placeholder for dynamic substitution.
    This is useful when running on systems with command wrappers or custom SLURM installations.

    Example with default SLURM commands:
        slurm_options:
          commands:
            submit: "sbatch"                                      # Default submit (per-script override)
            status: "squeue -j {job_id} --noheader --format=%T"  # Job status query
            info: "scontrol show job {job_id}"                   # Job information
            cancel: "scancel {job_id}"                           # Job cancellation
          poll_interval: 30                                       # Status check interval (seconds)

    Example with wrapper and custom flags:
        slurm_options:
          commands:
            submit: "lrms-wrapper sbatch"
            status: "lrms-wrapper -r {job_id} --custom-format"   # Custom flags
            info: "lrms-wrapper info {job_id}"
            cancel: "lrms-wrapper kill {job_id}"
          poll_interval: 10                                       # Check status every 10 seconds

    Example with single-allocation mode:
        slurm_options:
          allocation:
            mode: "single"
            test_timeout: 300
            allocation_script: |
              #SBATCH --nodes=8
              #SBATCH --time=02:00:00
              #SBATCH --partition=batch
              #SBATCH --account=myaccount

              module purge
              module load mpi/openmpi/4.0.1

    Placeholders:
        {job_id} - Replaced with the SLURM job ID at runtime

    Note: The submit command specified here is a default. Individual scripts can override
    it by specifying their own submit command in scripts[].submit.
    """
    commands: Optional[Dict[str, str]] = None
    poll_interval: Optional[int] = None  # Polling interval in seconds for SLURM job status checks
    allocation: Optional[AllocationConfig] = None  # Single-allocation mode configuration


@dataclass
class RandomSamplingConfig:
    """
    Configuration for random sampling search method.

    Must specify exactly one of n_samples or percentage.

    Attributes:
        n_samples: Explicit number of samples to take from parameter space
        percentage: Fraction of parameter space to sample (0.0-1.0)
        fallback_to_exhaustive: If True and n_samples >= total space, use exhaustive search
    """
    n_samples: Optional[int] = None
    percentage: Optional[float] = None
    fallback_to_exhaustive: bool = True


@dataclass
class BayesianConfig:
    """
    Configuration for Bayesian optimization search method.

    Bayesian optimization uses a surrogate model to guide the search toward
    optimal parameter configurations based on previous results.

    Default values are based on empirical testing across multiple seeds and
    iteration counts. With 20 iterations (~7% of search space), Bayesian
    optimization achieves ~90% of optimal vs ~79% for random search.

    Attributes:
        n_initial_points: Number of random initial samples before optimization starts.
            Default: 5 (provides enough initial exploration before guided search)
        n_iterations: Total number of parameter configurations to evaluate.
            Default: 20 (sufficient for most search spaces)
        acquisition_func: Acquisition function to select next point:
            - "EI": Expected Improvement (default) - balanced exploration/exploitation
            - "PI": Probability of Improvement - more exploitative
            - "LCB": Lower Confidence Bound - configurable via kappa
        base_estimator: Surrogate model type:
            - "RF": Random Forest (default) - most consistent results, lower variance
            - "GP": Gaussian Process - best for continuous, struggles with categorical
            - "ET": Extra Trees - similar to RF, slightly higher variance
            - "GBRT": Gradient Boosted Regression Trees
        xi: Exploration-exploitation trade-off for EI/PI.
            Default: 0.01 (good balance, not too greedy)
        kappa: Exploration parameter for LCB (default: 1.96)
            Higher values favor exploration
        objective: Optimization direction - "minimize" or "maximize" (default: "minimize")
        objective_metric: Metric name to optimize (required)
        fallback_to_exhaustive: If True and n_iterations >= total space, use exhaustive search.
            Default: True
        early_stop_on_convergence: If True, stop when optimizer converges instead of
            falling back to random sampling. Default: False (better final results without
            early stopping; use convergence_patience and xi_boost_factor if enabled)
        convergence_patience: Number of consecutive convergence events before early stopping.
            When convergence is detected, xi is boosted to encourage exploration.
            Default: 3 (only used when early_stop_on_convergence is True)
        xi_boost_factor: Multiplier for xi when convergence is detected.
            Default: 5.0 (helps escape local optima when stuck)
    """
    n_initial_points: int = 5
    n_iterations: int = 20
    acquisition_func: Literal["EI", "PI", "LCB"] = "EI"
    base_estimator: Literal["RF", "GP", "ET", "GBRT"] = "RF"
    xi: float = 0.01
    kappa: float = 1.96
    objective: Literal["minimize", "maximize"] = "minimize"
    objective_metric: Optional[str] = None
    fallback_to_exhaustive: bool = True
    early_stop_on_convergence: bool = False
    convergence_patience: int = 3
    xi_boost_factor: float = 5.0


@dataclass
class ProbesConfig:
    """
    Configuration for IOPS probes (system monitoring and execution tracking).

    Probes are optional features that collect additional information during execution.
    All probes are enabled by default except resource_sampling which requires explicit opt-in.

    Attributes:
        system_snapshot: Collect system info (hostname, CPU, memory, etc.) from compute nodes.
            Corresponds to deprecated field: collect_system_info
        execution_index: Write execution metadata files for 'iops find' command.
            Corresponds to deprecated field: track_executions
        resource_sampling: Enable resource tracing (CPU/memory sampling during execution).
            Corresponds to deprecated field: trace_resources
        sampling_interval: Sampling interval in seconds for resource tracing.
            Corresponds to deprecated field: trace_interval
    """
    system_snapshot: bool = True      # Was: collect_system_info
    execution_index: bool = True      # Was: track_executions
    resource_sampling: bool = False   # Was: trace_resources
    sampling_interval: float = 1.0    # Was: trace_interval


@dataclass
class BenchmarkConfig:
    name: str
    description: Optional[str]
    workdir: Path
    repetitions: Optional[int] = 1        # global default (can be ignored if rounds have their own)
    cache_file: Optional[Path] = None
    search_method: Optional[str] = None  # e.g., "greedy", "exhaustive", etc.
    executor: Optional[str] = "slurm"  # e.g., "local", "slurm", etc.
    slurm_options: Optional[SlurmOptionsConfig] = None  # SLURM-specific configuration (commands, polling, allocation)
    random_seed: Optional[int] = None  # seed for any random operations
    cache_exclude_vars: Optional[List[str]] = None  # variables to exclude from cache hash
    exhaustive_vars: Optional[List[str]] = None  # variables to exhaustively test for each search point
    max_core_hours: Optional[float] = None  # Budget limit in core-hours
    cores_expr: Optional[str] = None  # Jinja expression to compute cores (e.g., "{{ nodes * ppn }}")
    estimated_time_seconds: Optional[float] = None  # Estimated execution time per test (for dry-run)
    report_vars: Optional[List[str]] = None  # Variables to include in analysis reports (default: all numeric swept vars)
    bayesian_config: Optional[BayesianConfig] = None  # Bayesian optimization configuration
    random_config: Optional[RandomSamplingConfig] = None  # Random sampling configuration
    probes: Optional[ProbesConfig] = None  # Probe configuration (new nested format)
    # Deprecated fields (use probes.* instead) - will be removed in 3.7.0
    collect_system_info: bool = True  # DEPRECATED: use probes.system_snapshot
    track_executions: bool = True  # DEPRECATED: use probes.execution_index
    create_folders_upfront: bool = False  # Create all exec folders at start (enables SKIPPED status visibility)
    trace_resources: bool = False  # DEPRECATED: use probes.resource_sampling
    trace_interval: float = 1.0  # DEPRECATED: use probes.sampling_interval


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
    when: Optional[str] = None  # condition for conditional variables
    default: Optional[Any] = None  # value when condition is false


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
    labels: Dict[str, Any]
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
    script_template: str
    post: Optional[PostConfig] = None      # optional
    parser: Optional[ParserConfig] = None  # optional


@dataclass
class OutputSinkConfig:
    type: Literal["csv", "parquet", "sqlite"]
    path: str
    exclude: List[str] = field(default_factory=list)
    table: str = "results"  # sqlite only

    resolved_path: Optional[Path] = None


@dataclass
class OutputConfig:
    sink: OutputSinkConfig


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
    type: Literal["line", "bar", "scatter", "box", "violin", "heatmap", "surface_3d", "parallel_coordinates", "execution_scatter", "coverage_heatmap"]

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

    # Coverage heatmap options
    row_vars: Optional[List[str]] = None  # Variables for row multi-index
    col_var: Optional[str] = None  # Variable for columns
    aggregation: str = "mean"  # Aggregation function: mean, median, count, std, min, max
    show_missing: bool = True  # Highlight NaN values with distinct color
    sort_rows_by: str = "index"  # Sort rows by: "index" (variable values) or "values" (metric values)
    sort_cols_by: str = "index"  # Sort columns by: "index" (variable values) or "values" (metric values)
    sort_ascending: bool = False  # Sort direction for "values" mode (False = highest values first)


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
    bayesian_evolution: bool = True
    bayesian_parameter_evolution: bool = False  # Disabled by default (verbose with many params)
    custom_plots: bool = True


@dataclass
class BestResultsConfig:
    """Configuration for best results section."""
    top_n: int = 5
    show_command: bool = True
    min_samples: int = 1  # Minimum number of samples required to consider a configuration


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
    reporting: Optional[ReportingConfig] = None
