# iops/config/loader.py

"""Configuration loading and validation for IOPS benchmarks."""

from __future__ import annotations

from typing import Any, Dict, List, Set
from pathlib import Path
import yaml
import os

from iops.config.models import (
    ConfigValidationError,
    GenericBenchmarkConfig,
    BenchmarkConfig,
    VarConfig,
    SweepConfig,
    CommandConfig,
    ScriptConfig,
    PostConfig,
    ParserConfig,
    MetricConfig,
    OutputConfig,
    OutputSinkConfig,
    RoundConfig,
    RoundSearchConfig,
)
from iops.results.validation import validate_parser_script


# ----------------- Helper functions ----------------- #

def _expand_path(p: str) -> Path:
    """Expand environment variables and user paths, then resolve to absolute path."""
    return Path(os.path.expandvars(p)).expanduser().resolve()


def _collect_allowed_output_fields(cfg: GenericBenchmarkConfig) -> Set[str]:
    """
    Collect all valid field names that can be used in output include/exclude lists.

    Returns a set of allowed dotted field names like 'vars.nodes', 'metrics.bwMiB', etc.
    """
    allowed: Set[str] = set()

    # --- benchmark.* ---
    allowed.update({
        "benchmark.name",
        "benchmark.description",
        "benchmark.workdir",
        "benchmark.repetitions",
        "benchmark.sqlite_db",
        "benchmark.search_method",
        "benchmark.executor",
        "benchmark.random_seed",
    })

    # --- execution.* (decide the contract) ---
    allowed.update({
        "execution.execution_id",
        "execution.repetition",
        "execution.repetitions",
        "execution.workdir",
        "execution.execution_dir",
        "execution.round_name",
        "execution.round_index",
    })

    # --- round.* ---
    allowed.update({
        "round.name",
        "round.index",
        "round.repetitions",
    })

    # --- vars.<name> ---
    for vname in cfg.vars.keys():
        allowed.add(f"vars.{vname}")
        # optional shorthand support
        allowed.add(vname)

    # --- metadata.<key> from command.metadata ---
    for k in (cfg.command.metadata or {}).keys():
        allowed.add(f"metadata.{k}")
        # optional shorthand support
        allowed.add(k)

    # --- metrics.<name> from script parser metrics ---
    # If you have multiple scripts, union them all
    for s in cfg.scripts:
        if s.parser is None:
            continue
        for m in (s.parser.metrics or []):
            allowed.add(f"metrics.{m.name}")
            # optional shorthand support
            allowed.add(m.name)

    return allowed


def _validate_output_field_list(
    cfg: GenericBenchmarkConfig,
    fields: list[str],
    where: str,
) -> None:
    """
    Validate that all fields in the list are valid output field names.

    Raises ConfigValidationError if any field is invalid.
    """
    allowed = _collect_allowed_output_fields(cfg)

    bad: list[str] = []
    for f in fields:
        if not isinstance(f, str) or not f.strip():
            bad.append(str(f))
            continue
        if f not in allowed:
            bad.append(f)

    if bad:
        # helpful suggestions (simple prefix match)
        suggestions = []
        for b in bad[:10]:
            pref = b.split(".")[0]
            close = sorted([a for a in allowed if a.startswith(pref + ".")])[:10]
            if close:
                suggestions.append(f"- '{b}': did you mean one of {close}?")

        hint = "\n".join(suggestions)
        raise ConfigValidationError(
            f"{where} contains unknown field(s): {bad}\n"
            f"Allowed examples: {sorted(list(allowed))[:25]}...\n"
            f"{hint}"
        )


def create_workdir(cfg: GenericBenchmarkConfig, logger) -> None:
    """
    Creates a new RUN directory under the configured base workdir.

    Layout:
      <base_workdir>/run_<id>/
        ├── logs/
        └── runs/

    Updates cfg.benchmark.workdir to point to the new run directory.
    """
    base_workdir = cfg.benchmark.workdir

    base_workdir.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Base work directory: {base_workdir}")

    # Find existing run directories
    run_dirs = [
        d for d in base_workdir.iterdir()
        if d.is_dir()
        and d.name.startswith("run_")
        and d.name.split("_", 1)[1].isdigit()
    ]

    next_id = max((int(d.name.split("_", 1)[1]) for d in run_dirs), default=0) + 1

    run_root = base_workdir / f"run_{next_id:03d}"
    run_root.mkdir(parents=True, exist_ok=True)

    # Standard subfolders
    (run_root / "runs").mkdir(parents=True, exist_ok=True)
    (run_root / "logs").mkdir(parents=True, exist_ok=True)

    logger.debug(f"Created run root: {run_root}")

    # Update cfg.workdir to this run root (stable during execution)
    cfg.benchmark.workdir = run_root


# ----------------- Main loading function ----------------- #

def load_generic_config(config_path: Path, logger) -> GenericBenchmarkConfig:
    """
    Load and parse a YAML configuration file into a GenericBenchmarkConfig object.

    Args:
        config_path: Path to the YAML configuration file
        logger: Logger instance for debug messages

    Returns:
        Validated GenericBenchmarkConfig object with workdir created

    Raises:
        ConfigValidationError: If configuration is invalid
    """
    with open(config_path, "r") as f:
        data = yaml.safe_load(f)

    # ---- benchmark ----
    b = data["benchmark"]
    # if search method is not defined, we will execute all test cases (exhaustive)

    benchmark = BenchmarkConfig(
        name=b["name"],
        description=b.get("description"),
        workdir=_expand_path(b["workdir"]),
        repetitions=b.get("repetitions", 1),
        sqlite_db=_expand_path(b["sqlite_db"]) if "sqlite_db" in b else None,
        search_method=b.get("search_method", "exhaustive"),
        executor=b.get("executor", "slurm"),
        random_seed=b.get("random_seed", 42)
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
    out = data["output"]["sink"]
    output = OutputConfig(
        sink=OutputSinkConfig(
            type=out["type"],
            path=out["path"],
            mode=out.get("mode", "append"),
            include=out.get("include", []) or [],
            exclude=out.get("exclude", []) or [],
            table=out.get("table", "results"),
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
    create_workdir(cfg, logger)  # logger can be None here
    return cfg


# ----------------- Validation function ----------------- #

def validate_generic_config(cfg: GenericBenchmarkConfig) -> None:
    """
    Validate a GenericBenchmarkConfig object.

    Raises ConfigValidationError if any validation check fails.
    """
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
            if not s.parser.file or not str(s.parser.file).strip():
                raise ConfigValidationError(
                    f"script '{s.name}' parser.file must not be empty"
                )

            if s.parser.parser_script is None or not s.parser.parser_script.strip():
                raise ConfigValidationError(
                    f"script '{s.name}' parser.parser_script must not be empty"
                )

            ok, err = validate_parser_script(s.parser.parser_script)
            if not ok:
                raise ConfigValidationError(
                    f"script '{s.name}' has invalid parser_script:\n{err}"
                )

            if not s.parser.metrics:
                raise ConfigValidationError(
                    f"script '{s.name}' parser.metrics must be non-empty "
                    f"(positional mapping requires metric names)"
                )

    # ---- output ----
    sink = cfg.output.sink

    if sink.type not in ("csv", "parquet", "sqlite"):
        raise ConfigValidationError("output.sink.type must be one of: csv, parquet, sqlite")

    if not sink.path or not str(sink.path).strip():
        raise ConfigValidationError("output.sink.path must not be empty")

    if sink.mode not in ("append", "overwrite"):
        raise ConfigValidationError("output.sink.mode must be append or overwrite")

    if sink.include and sink.exclude:
        raise ConfigValidationError("output.sink cannot define both 'include' and 'exclude'")

    # Validate that requested fields exist in config (static check)
    if sink.include:
        _validate_output_field_list(cfg, sink.include, "output.sink.include")
    if sink.exclude:
        _validate_output_field_list(cfg, sink.exclude, "output.sink.exclude")

    if sink.type == "sqlite":
        if not sink.table or not str(sink.table).strip():
            raise ConfigValidationError("output.sink.table must not be empty when type=sqlite")

    # ---- rounds (optional) ----
    # If no rounds: that's fine, you can keep current "single global matrix" behaviour.
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
