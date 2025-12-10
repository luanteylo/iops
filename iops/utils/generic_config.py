# iops/utils/generic_config.py

from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal
from dataclasses import dataclass, field
from pathlib import Path
import yaml
import os


class ConfigValidationError(Exception):
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
    type: str
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
class OutputCSVConfig:
    path: str
    include: List[str]


@dataclass
class OutputConfig:
    csv: OutputCSVConfig


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
        repetitions: 3
        search:
          metric: "write_bandwidth"
          objective: "max"
        propagate:
          vars: ["nodes"]
    """
    name: str
    description: Optional[str]
    sweep_vars: List[str] = field(default_factory=list)
    fixed_overrides: Dict[str, Any] = field(default_factory=dict)
    repetitions: Optional[int] = None
    search: RoundSearchConfig | None = None


@dataclass
class GenericBenchmarkConfig:
    benchmark: BenchmarkConfig
    vars: Dict[str, VarConfig]
    command: CommandConfig
    scripts: List[ScriptConfig]
    output: OutputConfig
    rounds: List[RoundConfig] = field(default_factory=list)  # <-- NEW


# ----------------- helpers ----------------- #

def _expand_path(p: str) -> Path:
    return Path(os.path.expandvars(p)).expanduser().resolve()


def load_generic_config(config_path: Path) -> GenericBenchmarkConfig:
    with open(config_path, "r") as f:
        data = yaml.safe_load(f)

    # ---- benchmark ----
    b = data["benchmark"]
    # if search method is not define, we will execute all test cases (exhaustive)

    benchmark = BenchmarkConfig(
        name=b["name"],
        description=b.get("description"),
        workdir=_expand_path(b["workdir"]),
        repetitions=b.get("repetitions", 1),
        sqlite_db=_expand_path(b["sqlite_db"]) if "sqlite_db" in b else None,
        search_method=b.get("search_method", "exhaustive"),
        executor=b.get("executor", "slurm")
    )

    # ---- vars ----
    vars_cfg: Dict[str, VarConfig] = {}
    for name, cfg in data.get("vars", {}).items():
        sweep_cfg = None
        if "sweep" in cfg:
            s = cfg["sweep"]
            sweep_cfg = SweepConfig(
                mode=s["mode"],
                start=s.get("start"),
                end=s.get("end"),
                step=s.get("step"),
                values=s.get("values"),
            )
        vars_cfg[name] = VarConfig(
            type=cfg["type"],
            sweep=sweep_cfg,
            expr=cfg.get("expr"),
        )

    # ---- command ----
    c = data["command"]
    command = CommandConfig(
        template=c["template"],
        metadata=c.get("metadata", {}),
        env=c.get("env", {}),
    )

    # ---- scripts ----
    scripts: List[ScriptConfig] = []
    for s in data.get("scripts", []):
        # optional post
        post_block = s.get("post")
        post_cfg = None
        if post_block is not None:
            # YAML: post: { script: "..." }  OR post: \n  script: |
            post_cfg = PostConfig(script=post_block.get("script"))

        # optional parser
        parser_block = s.get("parser")
        parser_cfg = None
        if parser_block is not None:
            metrics_cfg = [
                MetricConfig(
                    name=m["name"],
                    path=m.get("path"),
                )
                for m in parser_block.get("metrics", [])
            ]
            parser_cfg = ParserConfig(
                type=parser_block["type"],
                file=parser_block["file"],
                metrics=metrics_cfg,
                parser_script=parser_block.get("parser_script"),
            )

        scripts.append(
            ScriptConfig(
                name=s["name"],             
                submit=s["submit"],
                script_template=s["script_template"],
                post=post_cfg,
                parser=parser_cfg,
            )
        )

    # ---- output ----
    out = data["output"]["csv"]
    output = OutputConfig(
        csv=OutputCSVConfig(
            path=out["path"],
            include=out["include"],
        )
    )

    # ---- rounds (optional) ----
    rounds_cfg: List[RoundConfig] = []
    for r in data.get("rounds", []):
        # search block (required for each round)
        search_block = r.get("search")
        search_cfg: RoundSearchConfig | None = None
        if search_block is not None:
            search_cfg = RoundSearchConfig(
                metric=search_block["metric"],
                objective=search_block["objective"],
                select=search_block.get("select"),
            )

        rounds_cfg.append(
            RoundConfig(
                name=r["name"],
                description=r.get("description"),
                sweep_vars=r.get("sweep_vars", []),
                fixed_overrides=r.get("fixed_overrides", {}),
                repetitions=r.get("repetitions"),
                search=search_cfg,
            )
        )

    cfg = GenericBenchmarkConfig(
        benchmark=benchmark,
        vars=vars_cfg,
        command=command,
        scripts=scripts,
        output=output,
        rounds=rounds_cfg,
    )

    validate_generic_config(cfg)
    return cfg


def validate_generic_config(cfg: GenericBenchmarkConfig) -> None:
    # ---- benchmark ----
    if not cfg.benchmark.workdir.exists():
        raise ConfigValidationError(
            f"benchmark.workdir does not exist: {cfg.benchmark.workdir}"
        )
    if not cfg.benchmark.workdir.is_dir():
        raise ConfigValidationError("benchmark.workdir must be a directory")
    if cfg.benchmark.repetitions is not None and cfg.benchmark.repetitions < 1:
        raise ConfigValidationError("benchmark.repetitions must be >= 1")
    # search_method: greedy or bayesian or exhaustive (optional)
    if cfg.benchmark.search_method is not None:
        if cfg.benchmark.search_method not in ("greedy", "bayesian", "exhaustive"):
            raise ConfigValidationError(
                "benchmark.search_method must be one of: greedy, bayesian, exhaustive"
            )



    # ---- vars ----
    if not cfg.vars:
        raise ConfigValidationError("At least one variable must be defined in 'vars'")

    for name, v in cfg.vars.items():
        if v.sweep is None and v.expr is None:
            raise ConfigValidationError(
                f"var '{name}' must define either a 'sweep' or an 'expr'"
            )
        if v.sweep is not None and v.expr is not None:
            raise ConfigValidationError(
                f"var '{name}' cannot have both 'sweep' and 'expr'"
            )

        if v.sweep:
            if v.sweep.mode == "range":
                if (
                    v.sweep.start is None
                    or v.sweep.end is None
                    or v.sweep.step is None
                ):
                    raise ConfigValidationError(
                        f"var '{name}' with mode 'range' must have start, end, and step"
                    )
                if v.sweep.step == 0:
                    raise ConfigValidationError(
                        f"var '{name}' with mode 'range' cannot have step=0"
                    )
            elif v.sweep.mode == "list":
                if not v.sweep.values:
                    raise ConfigValidationError(
                        f"var '{name}' with mode 'list' must have non-empty 'values'"
                    )
            else:
                raise ConfigValidationError(
                    f"var '{name}' has invalid sweep.mode='{v.sweep.mode}'"
                )

    # ---- command ----
    if not cfg.command.template.strip():
        raise ConfigValidationError("command.template must not be empty")

    # ---- scripts ----
    if not cfg.scripts:
        raise ConfigValidationError("At least one script must be defined in 'scripts'")

    for s in cfg.scripts:
        if not s.script_template.strip():
            raise ConfigValidationError(
                f"script '{s.name}' must have a non-empty script_template"
            )

        # post is OPTIONAL – only validate if present
        if s.post is not None:
            if not s.post.script or not s.post.script.strip():
                raise ConfigValidationError(
                    f"script '{s.name}' has a 'post' block but empty 'script'"
                )

        # parser is OPTIONAL – only validate if present
        if s.parser is not None:
            if not s.parser.type:
                raise ConfigValidationError(
                    f"script '{s.name}' parser.type must not be empty"
                )
            if not s.parser.file:
                raise ConfigValidationError(
                    f"script '{s.name}' parser.file must not be empty"
                )
            if not s.parser.metrics and s.parser.parser_script is None:
                raise ConfigValidationError(
                    f"script '{s.name}' parser must define either metrics or parser_script"
                )
            if s.parser.parser_script is not None and not s.parser.parser_script.strip():
                raise ConfigValidationError(
                    f"script '{s.name}' parser.parser_script is empty"
                )

    # ---- output ----
    if not cfg.output.csv.path:
        raise ConfigValidationError("output.csv.path must not be empty")
    if not cfg.output.csv.include:
        raise ConfigValidationError("output.csv.include must not be empty")

    # ---- rounds (optional) ----
    # If no rounds: that's fine, you can keep current “single global matrix” behaviour.
    for rnd in cfg.rounds:
        if not rnd.name:
            raise ConfigValidationError("Each round must have a non-empty 'name'")

        # sweep_vars: at least one var if you define the round
        if not rnd.sweep_vars:
            raise ConfigValidationError(
                f"round '{rnd.name}' must define a non-empty 'sweep_vars' list"
            )

        # sweep_vars must all exist in cfg.vars
        for vname in rnd.sweep_vars:
            if vname not in cfg.vars:
                raise ConfigValidationError(
                    f"round '{rnd.name}' references unknown sweep var '{vname}'"
                )

        # fixed_overrides vars must exist in cfg.vars as well
        for vname in rnd.fixed_overrides.keys():
            if vname not in cfg.vars:
                raise ConfigValidationError(
                    f"round '{rnd.name}' fixed_overrides references unknown var '{vname}'"
                )

        # repetitions per round (optional, but if present must be >=1)
        if rnd.repetitions is not None and rnd.repetitions < 1:
            raise ConfigValidationError(
                f"round '{rnd.name}' repetitions must be >= 1"
            )

        # search block is strongly recommended / basically required
        if rnd.search is None:
            raise ConfigValidationError(
                f"round '{rnd.name}' must define a 'search' block"
            )

        if not rnd.search.metric:
            raise ConfigValidationError(
                f"round '{rnd.name}' search.metric must not be empty"
            )

        if rnd.search.objective not in ("max", "min"):
            raise ConfigValidationError(
                f"round '{rnd.name}' search.objective must be 'max' or 'min'"
            )   