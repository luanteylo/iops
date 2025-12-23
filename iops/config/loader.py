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
    ExecutorOptionsConfig,
    VarConfig,
    SweepConfig,
    ConstraintConfig,
    CommandConfig,
    ScriptConfig,
    PostConfig,
    ParserConfig,
    MetricConfig,
    OutputConfig,
    OutputSinkConfig,
    RoundConfig,
    RoundSearchConfig,
    ReportingConfig,
    ReportThemeConfig,
    PlotConfig,
    MetricPlotsConfig,
    SectionConfig,
    BestResultsConfig,
    PlotDefaultsConfig,
)
from iops.results.validation import validate_parser_script


# ----------------- Helper functions ----------------- #

def _expand_path(p: str) -> Path:
    """Expand environment variables and user paths, then resolve to absolute path."""
    return Path(os.path.expandvars(p)).expanduser().resolve()


def _load_script_content(content: str, config_dir: Path) -> str:
    """
    Load script content from inline text or file path.

    If content looks like a file path and the file exists, reads and returns file contents.
    Otherwise, returns the content as-is (inline script).

    Args:
        content: Either inline script text or a file path
        config_dir: Directory containing the YAML config (for relative paths)

    Returns:
        Script content (either from file or inline)
    """
    if not content or not isinstance(content, str):
        return content

    content = content.strip()

    # Heuristic: if it's a single line without newlines and looks like a path
    if "\n" not in content and ("{" not in content or content.count("{") < 3):
        # Try to interpret as file path
        try:
            # Try relative to config directory first
            script_path = config_dir / content
            if script_path.is_file():
                with open(script_path, "r", encoding="utf-8") as f:
                    return f.read()

            # Try absolute path
            abs_path = Path(content).expanduser()
            if abs_path.is_file():
                with open(abs_path, "r", encoding="utf-8") as f:
                    return f.read()
        except Exception:
            pass  # Not a valid file path, treat as inline content

    # Return as inline content
    return content


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

    # Get config directory for resolving relative script paths
    config_dir = config_path.parent

    # ---- benchmark ----
    b = data["benchmark"]
    # if search method is not defined, we will execute all test cases (exhaustive)

    # Parse executor_options if present
    executor_options = None
    if "executor_options" in b and b["executor_options"] is not None:
        eo = b["executor_options"]
        executor_options = ExecutorOptionsConfig(
            commands=eo.get("commands")
        )

    benchmark = BenchmarkConfig(
        name=b["name"],
        description=b.get("description"),
        workdir=_expand_path(b["workdir"]),
        repetitions=b.get("repetitions", 1),
        sqlite_db=_expand_path(b["sqlite_db"]) if "sqlite_db" in b else None,
        search_method=b.get("search_method", "exhaustive"),
        executor=b.get("executor", "slurm"),
        executor_options=executor_options,
        random_seed=b.get("random_seed", 42),
        cache_exclude_vars=b.get("cache_exclude_vars", []),
        exhaustive_vars=b.get("exhaustive_vars"),
        max_core_hours=b.get("max_core_hours"),
        cores_expr=b.get("cores_expr"),
        estimated_time_seconds=b.get("estimated_time_seconds"),
        report_vars=b.get("report_vars"),
        bayesian_config=b.get("bayesian_config"),
        random_config=b.get("random_config")
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
        # Load script_template (inline or from file)
        script_template = _load_script_content(s["script_template"], config_dir)

        # optional post
        post_block = s.get("post")
        post_cfg = None
        if post_block is not None:
            # YAML: post: { script: "..." }  OR post: \n  script: |
            post_script = post_block.get("script")
            if post_script:
                post_script = _load_script_content(post_script, config_dir)
            post_cfg = PostConfig(script=post_script)

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
            # Load parser_script (inline or from file)
            parser_script = parser_block.get("parser_script")
            if parser_script:
                parser_script = _load_script_content(parser_script, config_dir)

            parser_cfg = ParserConfig(
                file=parser_block["file"],
                metrics=metrics_cfg,
                parser_script=parser_script,
            )

        scripts.append(
            ScriptConfig(
                name=s["name"],
                submit=s["submit"],
                script_template=script_template,
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
                search=search_cfg,
            )
        )

    # Parse constraints (optional section)
    constraints_data = data.get("constraints", [])
    constraints = []
    for idx, c_data in enumerate(constraints_data):
        if not isinstance(c_data, dict):
            raise ConfigValidationError(f"constraints[{idx}] must be a dictionary")

        constraints.append(ConstraintConfig(
            name=c_data.get("name", f"constraint_{idx}"),
            rule=c_data["rule"],  # required
            violation_policy=c_data.get("violation_policy", "skip"),
            description=c_data.get("description"),
        ))

    # ---- reporting (optional) ----
    reporting_cfg = None
    if "reporting" in data and data["reporting"] is not None:
        reporting_cfg = _parse_reporting_config(data["reporting"])

    cfg = GenericBenchmarkConfig(
        benchmark=benchmark,
        vars=vars_cfg,
        constraints=constraints,
        command=command,
        scripts=scripts,
        output=output,
        rounds=rounds_cfg,
        reporting=reporting_cfg,
    )

    validate_generic_config(cfg)
    create_workdir(cfg, logger)  # logger can be None here
    return cfg


def _parse_reporting_config(data: Dict[str, Any]) -> ReportingConfig:
    """
    Parse reporting configuration dictionary into ReportingConfig dataclass.

    Args:
        data: Dictionary containing reporting configuration

    Returns:
        ReportingConfig instance

    Raises:
        ConfigValidationError: If configuration is invalid
    """
    # Parse theme (optional)
    theme_cfg = ReportThemeConfig()
    if "theme" in data and data["theme"] is not None:
        theme_data = data["theme"]
        theme_cfg = ReportThemeConfig(
            style=theme_data.get("style", "plotly_white"),
            colors=theme_data.get("colors"),
            font_family=theme_data.get("font_family", "Segoe UI, Tahoma, Geneva, Verdana, sans-serif"),
        )

    # Parse sections (optional)
    sections_cfg = SectionConfig()
    if "sections" in data and data["sections"] is not None:
        sections_data = data["sections"]
        sections_cfg = SectionConfig(
            test_summary=sections_data.get("test_summary", True),
            best_results=sections_data.get("best_results", True),
            variable_impact=sections_data.get("variable_impact", True),
            parallel_coordinates=sections_data.get("parallel_coordinates", True),
            pareto_frontier=sections_data.get("pareto_frontier", True),
            bayesian_evolution=sections_data.get("bayesian_evolution", True),
            custom_plots=sections_data.get("custom_plots", True),
        )

    # Parse best_results config (optional)
    best_results_cfg = BestResultsConfig()
    if "best_results" in data and data["best_results"] is not None:
        br_data = data["best_results"]
        best_results_cfg = BestResultsConfig(
            top_n=br_data.get("top_n", 5),
            show_command=br_data.get("show_command", True),
        )

    # Parse plot_defaults (optional)
    plot_defaults_cfg = PlotDefaultsConfig()
    if "plot_defaults" in data and data["plot_defaults"] is not None:
        pd_data = data["plot_defaults"]
        plot_defaults_cfg = PlotDefaultsConfig(
            height=pd_data.get("height", 500),
            width=pd_data.get("width"),
            margin=pd_data.get("margin"),
        )

    # Parse per-metric plots (optional)
    metrics_cfg: Dict[str, MetricPlotsConfig] = {}
    if "metrics" in data and data["metrics"] is not None:
        for metric_name, metric_data in data["metrics"].items():
            if metric_data is None or "plots" not in metric_data:
                continue

            plots = []
            for plot_data in metric_data["plots"]:
                plot_cfg = PlotConfig(
                    type=plot_data["type"],
                    x_var=plot_data.get("x_var"),
                    y_var=plot_data.get("y_var"),
                    z_metric=plot_data.get("z_metric"),
                    group_by=plot_data.get("group_by"),
                    color_by=plot_data.get("color_by"),
                    size_by=plot_data.get("size_by"),
                    title=plot_data.get("title"),
                    xaxis_label=plot_data.get("xaxis_label"),
                    yaxis_label=plot_data.get("yaxis_label"),
                    colorscale=plot_data.get("colorscale", "Viridis"),
                    show_error_bars=plot_data.get("show_error_bars", True),
                    show_outliers=plot_data.get("show_outliers", True),
                    height=plot_data.get("height"),
                    width=plot_data.get("width"),
                    per_variable=plot_data.get("per_variable", False),
                    include_metric=plot_data.get("include_metric", True),
                )
                plots.append(plot_cfg)

            metrics_cfg[metric_name] = MetricPlotsConfig(plots=plots)

    # Parse default_plots (optional)
    default_plots = []
    if "default_plots" in data and data["default_plots"] is not None:
        for plot_data in data["default_plots"]:
            plot_cfg = PlotConfig(
                type=plot_data["type"],
                x_var=plot_data.get("x_var"),
                y_var=plot_data.get("y_var"),
                z_metric=plot_data.get("z_metric"),
                group_by=plot_data.get("group_by"),
                color_by=plot_data.get("color_by"),
                size_by=plot_data.get("size_by"),
                title=plot_data.get("title"),
                xaxis_label=plot_data.get("xaxis_label"),
                yaxis_label=plot_data.get("yaxis_label"),
                colorscale=plot_data.get("colorscale", "Viridis"),
                show_error_bars=plot_data.get("show_error_bars", True),
                show_outliers=plot_data.get("show_outliers", True),
                height=plot_data.get("height"),
                width=plot_data.get("width"),
                per_variable=plot_data.get("per_variable", False),
                include_metric=plot_data.get("include_metric", True),
            )
            default_plots.append(plot_cfg)

    # Parse output_dir (optional)
    output_dir = None
    if "output_dir" in data and data["output_dir"] is not None:
        output_dir = _expand_path(data["output_dir"])

    return ReportingConfig(
        enabled=data.get("enabled", False),
        output_dir=output_dir,
        output_filename=data.get("output_filename", "analysis_report.html"),
        theme=theme_cfg,
        sections=sections_cfg,
        best_results=best_results_cfg,
        metrics=metrics_cfg,
        default_plots=default_plots,
        plot_defaults=plot_defaults_cfg,
    )


def load_report_config(config_path: Path) -> ReportingConfig:
    """
    Load standalone report configuration YAML file.

    Expected structure:
        reporting:
          enabled: true
          metrics:
            ...

    Args:
        config_path: Path to report configuration YAML file

    Returns:
        ReportingConfig instance

    Raises:
        ConfigValidationError: If configuration is invalid or missing 'reporting' section
    """
    with open(config_path, "r") as f:
        data = yaml.safe_load(f)

    if "reporting" not in data:
        raise ConfigValidationError(
            "Report config file must have 'reporting' section"
        )

    return _parse_reporting_config(data["reporting"])


# ----------------- Validation functions ----------------- #

def validate_yaml_config(config_path: Path) -> List[str]:
    """
    Validate a YAML configuration file and return a list of all errors found.

    This function attempts to load and validate the configuration file,
    catching all errors and returning them as a list. If the configuration
    is valid, an empty list is returned.

    Args:
        config_path: Path to the YAML configuration file

    Returns:
        List of error messages (empty if valid)
    """
    errors: List[str] = []

    # Check if file exists
    if not config_path.exists():
        errors.append(f"Configuration file not found: {config_path}")
        return errors

    if not config_path.is_file():
        errors.append(f"Path is not a file: {config_path}")
        return errors

    # Try to load and parse the YAML
    try:
        with open(config_path, "r") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        errors.append(f"YAML syntax error: {e}")
        return errors
    except Exception as e:
        errors.append(f"Failed to read configuration file: {e}")
        return errors

    if data is None:
        errors.append("Configuration file is empty")
        return errors

    if not isinstance(data, dict):
        errors.append("Configuration file must contain a YAML dictionary")
        return errors

    # Get config directory for resolving relative script paths
    config_dir = config_path.parent

    # Validate required top-level sections
    required_sections = ["benchmark", "vars", "command", "scripts", "output"]
    for section in required_sections:
        if section not in data:
            errors.append(f"Missing required section: '{section}'")

    if errors:
        return errors

    # Try to parse and validate the configuration
    try:
        # ---- benchmark ----
        b = data["benchmark"]

        # Check required benchmark fields
        if "name" not in b:
            errors.append("benchmark.name is required")
        if "workdir" not in b:
            errors.append("benchmark.workdir is required")

        # Validate workdir if present
        if "workdir" in b:
            try:
                workdir = _expand_path(b["workdir"])
                if not workdir.exists():
                    errors.append(f"benchmark.workdir does not exist: {workdir}")
                elif not workdir.is_dir():
                    errors.append(f"benchmark.workdir is not a directory: {workdir}")
            except Exception as e:
                errors.append(f"Invalid benchmark.workdir path: {e}")

        # Validate repetitions
        if "repetitions" in b:
            reps = b["repetitions"]
            if not isinstance(reps, int) or reps < 1:
                errors.append("benchmark.repetitions must be an integer >= 1")

        # Validate search_method
        if "search_method" in b:
            method = b["search_method"]
            if method not in ("greedy", "bayesian", "exhaustive"):
                errors.append(f"benchmark.search_method must be one of: greedy, bayesian, exhaustive (got '{method}')")

        # Validate executor
        if "executor" in b:
            executor = b["executor"]
            if executor not in ("slurm", "local"):
                errors.append(f"benchmark.executor must be one of: slurm, local (got '{executor}')")

    except KeyError as e:
        errors.append(f"Missing required benchmark field: {e}")
    except Exception as e:
        errors.append(f"Error validating benchmark section: {e}")

    # ---- vars ----
    try:
        vars_data = data.get("vars", {})
        if not vars_data:
            errors.append("At least one variable must be defined in 'vars'")

        for name, cfg in vars_data.items():
            if not isinstance(cfg, dict):
                errors.append(f"var '{name}' must be a dictionary")
                continue

            if "type" not in cfg:
                errors.append(f"var '{name}' is missing required field 'type'")

            has_sweep = "sweep" in cfg and cfg["sweep"] is not None
            has_expr = "expr" in cfg and cfg["expr"] is not None

            if not has_sweep and not has_expr:
                errors.append(f"var '{name}' must define either a 'sweep' or an 'expr'")

            if has_sweep and has_expr:
                errors.append(f"var '{name}' cannot have both 'sweep' and 'expr'")

            if has_sweep:
                sweep = cfg["sweep"]
                if not isinstance(sweep, dict):
                    errors.append(f"var '{name}' sweep must be a dictionary")
                    continue

                if "mode" not in sweep:
                    errors.append(f"var '{name}' sweep is missing required field 'mode'")
                    continue

                mode = sweep["mode"]
                if mode == "range":
                    if "start" not in sweep:
                        errors.append(f"var '{name}' with mode 'range' is missing 'start'")
                    if "end" not in sweep:
                        errors.append(f"var '{name}' with mode 'range' is missing 'end'")
                    if "step" not in sweep:
                        errors.append(f"var '{name}' with mode 'range' is missing 'step'")

                    if "step" in sweep and sweep["step"] == 0:
                        errors.append(f"var '{name}' with mode 'range' cannot have step=0")

                elif mode == "list":
                    if "values" not in sweep:
                        errors.append(f"var '{name}' with mode 'list' is missing 'values'")
                    elif not sweep["values"]:
                        errors.append(f"var '{name}' with mode 'list' must have non-empty 'values'")
                else:
                    errors.append(f"var '{name}' has invalid sweep.mode='{mode}' (must be 'range' or 'list')")

    except Exception as e:
        errors.append(f"Error validating vars section: {e}")

    # ---- constraints ----
    try:
        constraints_data = data.get("constraints", [])
        if constraints_data is not None:
            if not isinstance(constraints_data, list):
                errors.append("'constraints' must be a list")
            else:
                for idx, constraint in enumerate(constraints_data):
                    if not isinstance(constraint, dict):
                        errors.append(f"constraints[{idx}] must be a dictionary")
                        continue

                    # Required fields
                    if "rule" not in constraint:
                        errors.append(f"constraints[{idx}] missing required field 'rule'")

                    # Validate violation_policy
                    policy = constraint.get("violation_policy", "skip")
                    if policy not in ["skip", "error", "warn"]:
                        errors.append(
                            f"constraints[{idx}].violation_policy must be 'skip', 'error', or 'warn', got '{policy}'"
                        )

    except Exception as e:
        errors.append(f"Error validating constraints section: {e}")

    # ---- command ----
    try:
        command_data = data.get("command", {})
        if not isinstance(command_data, dict):
            errors.append("'command' section must be a dictionary")
        elif "template" not in command_data:
            errors.append("command.template is required")
        elif not command_data["template"] or not str(command_data["template"]).strip():
            errors.append("command.template must not be empty")

    except Exception as e:
        errors.append(f"Error validating command section: {e}")

    # ---- scripts ----
    try:
        scripts_data = data.get("scripts", [])
        if not scripts_data:
            errors.append("At least one script must be defined in 'scripts'")

        if not isinstance(scripts_data, list):
            errors.append("'scripts' section must be a list")
        else:
            for idx, s in enumerate(scripts_data):
                if not isinstance(s, dict):
                    errors.append(f"scripts[{idx}] must be a dictionary")
                    continue

                script_name = s.get("name", f"script[{idx}]")

                if "name" not in s:
                    errors.append(f"scripts[{idx}] is missing required field 'name'")

                if "submit" not in s:
                    errors.append(f"script '{script_name}' is missing required field 'submit'")

                if "script_template" not in s:
                    errors.append(f"script '{script_name}' is missing required field 'script_template'")
                elif not s["script_template"] or not str(s["script_template"]).strip():
                    errors.append(f"script '{script_name}' must have a non-empty script_template")

                # Validate post block if present
                if "post" in s and s["post"] is not None:
                    post = s["post"]
                    if not isinstance(post, dict):
                        errors.append(f"script '{script_name}' post must be a dictionary")
                    elif "script" not in post or not post["script"] or not str(post["script"]).strip():
                        errors.append(f"script '{script_name}' has a 'post' block but empty or missing 'script'")

                # Validate parser block if present
                if "parser" in s and s["parser"] is not None:
                    parser = s["parser"]
                    if not isinstance(parser, dict):
                        errors.append(f"script '{script_name}' parser must be a dictionary")
                        continue

                    if "file" not in parser or not parser["file"] or not str(parser["file"]).strip():
                        errors.append(f"script '{script_name}' parser.file is required and must not be empty")

                    if "parser_script" not in parser or not parser["parser_script"] or not str(parser["parser_script"]).strip():
                        errors.append(f"script '{script_name}' parser.parser_script is required and must not be empty")
                    else:
                        # Load parser script content if it's a file reference
                        parser_script = _load_script_content(parser["parser_script"], config_dir)
                        ok, err = validate_parser_script(parser_script)
                        if not ok:
                            errors.append(f"script '{script_name}' has invalid parser_script: {err}")

                    if "metrics" not in parser or not parser["metrics"]:
                        errors.append(f"script '{script_name}' parser.metrics is required and must be non-empty")
                    elif isinstance(parser["metrics"], list):
                        for m_idx, metric in enumerate(parser["metrics"]):
                            if not isinstance(metric, dict):
                                errors.append(f"script '{script_name}' parser.metrics[{m_idx}] must be a dictionary")
                            elif "name" not in metric:
                                errors.append(f"script '{script_name}' parser.metrics[{m_idx}] is missing 'name'")

    except Exception as e:
        errors.append(f"Error validating scripts section: {e}")

    # ---- output ----
    try:
        output_data = data.get("output", {})
        if not isinstance(output_data, dict):
            errors.append("'output' section must be a dictionary")
        elif "sink" not in output_data:
            errors.append("output.sink is required")
        else:
            sink = output_data["sink"]
            if not isinstance(sink, dict):
                errors.append("output.sink must be a dictionary")
            else:
                if "type" not in sink:
                    errors.append("output.sink.type is required")
                elif sink["type"] not in ("csv", "parquet", "sqlite"):
                    errors.append(f"output.sink.type must be one of: csv, parquet, sqlite (got '{sink['type']}')")

                if "path" not in sink or not sink["path"] or not str(sink["path"]).strip():
                    errors.append("output.sink.path is required and must not be empty")

                if "mode" in sink and sink["mode"] not in ("append", "overwrite"):
                    errors.append(f"output.sink.mode must be 'append' or 'overwrite' (got '{sink['mode']}')")

                if "include" in sink and sink["include"] and "exclude" in sink and sink["exclude"]:
                    errors.append("output.sink cannot define both 'include' and 'exclude'")

                if "type" in sink and sink["type"] == "sqlite":
                    if "table" not in sink or not sink["table"] or not str(sink["table"]).strip():
                        errors.append("output.sink.table is required and must not be empty when type=sqlite")

    except Exception as e:
        errors.append(f"Error validating output section: {e}")

    # ---- rounds (optional) ----
    try:
        rounds_data = data.get("rounds", [])
        if rounds_data:
            if not isinstance(rounds_data, list):
                errors.append("'rounds' section must be a list")
            else:
                for idx, rnd in enumerate(rounds_data):
                    if not isinstance(rnd, dict):
                        errors.append(f"rounds[{idx}] must be a dictionary")
                        continue

                    round_name = rnd.get("name", f"round[{idx}]")

                    if "name" not in rnd or not rnd["name"]:
                        errors.append(f"rounds[{idx}] must have a non-empty 'name'")

                    if "sweep_vars" not in rnd or not rnd["sweep_vars"]:
                        errors.append(f"round '{round_name}' must define a non-empty 'sweep_vars' list")
                    elif isinstance(rnd["sweep_vars"], list):
                        # Check if sweep_vars reference valid vars
                        vars_data = data.get("vars", {})
                        for vname in rnd["sweep_vars"]:
                            if vname not in vars_data:
                                errors.append(f"round '{round_name}' references unknown sweep var '{vname}'")

                    if "fixed_overrides" in rnd and isinstance(rnd["fixed_overrides"], dict):
                        vars_data = data.get("vars", {})
                        for vname in rnd["fixed_overrides"].keys():
                            if vname not in vars_data:
                                errors.append(f"round '{round_name}' fixed_overrides references unknown var '{vname}'")

                    if "search" not in rnd or rnd["search"] is None:
                        errors.append(f"round '{round_name}' must define a 'search' block")
                    elif isinstance(rnd["search"], dict):
                        search = rnd["search"]
                        if "metric" not in search or not search["metric"]:
                            errors.append(f"round '{round_name}' search.metric is required and must not be empty")

                        if "objective" not in search:
                            errors.append(f"round '{round_name}' search.objective is required")
                        elif search["objective"] not in ("max", "min"):
                            errors.append(f"round '{round_name}' search.objective must be 'max' or 'min' (got '{search['objective']}')")

    except Exception as e:
        errors.append(f"Error validating rounds section: {e}")

    return errors


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
    # search_method: exhaustive, random, bayesian, or greedy (optional)
    if cfg.benchmark.search_method is not None:
        if cfg.benchmark.search_method not in ("exhaustive", "random", "bayesian", "greedy"):
            raise ConfigValidationError(
                "benchmark.search_method must be one of: exhaustive, random, bayesian, greedy"
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

        # search block is required for multi-round optimization
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
