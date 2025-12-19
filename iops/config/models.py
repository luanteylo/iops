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
class BenchmarkConfig:
    name: str
    description: Optional[str]
    workdir: Path
    repetitions: Optional[int] = 1        # global default (can be ignored if rounds have their own)
    sqlite_db: Optional[Path] = None
    search_method: Optional[str] = None  # e.g., "greedy", "exhaustive", etc.
    executor: Optional[str] = "slurm"  # e.g., "local", "slurm", etc.
    random_seed: Optional[int] = None  # seed for any random operations
    cache_exclude_vars: Optional[List[str]] = None  # variables to exclude from cache hash
    max_core_hours: Optional[float] = None  # Budget limit in core-hours
    cores_expr: Optional[str] = None  # Jinja expression to compute cores (e.g., "{{ nodes * ppn }}")
    estimated_time_seconds: Optional[float] = None  # Estimated execution time per test (for dry-run)
    report_vars: Optional[List[str]] = None  # Variables to include in analysis reports (default: all numeric swept vars)
    bayesian_config: Optional[Dict[str, Any]] = None  # Bayesian optimization configuration


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


@dataclass
class GenericBenchmarkConfig:
    benchmark: BenchmarkConfig
    vars: Dict[str, VarConfig]
    command: CommandConfig
    scripts: List[ScriptConfig]
    output: OutputConfig
    rounds: List[RoundConfig] = field(default_factory=list)
