# iops/config/loader.py

"""Configuration loading and validation for IOPS benchmarks."""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple, Optional
from pathlib import Path
import ast
import re
import yaml
import os

from jinja2 import Environment, TemplateSyntaxError

# Optional pyarrow for parquet support
try:
    import pyarrow
    PYARROW_AVAILABLE = True
except ImportError:
    PYARROW_AVAILABLE = False

from iops.config.models import (
    ConfigValidationError,
    GenericBenchmarkConfig,
    BenchmarkConfig,
    ExecutorOptionsConfig,
    RandomSamplingConfig,
    BayesianConfig,
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
    ReportingConfig,
    ReportThemeConfig,
    PlotConfig,
    MetricPlotsConfig,
    SectionConfig,
    BestResultsConfig,
    PlotDefaultsConfig,
)


# ----------------- Helper functions ----------------- #

def _expand_path(p: str) -> Path:
    """Expand environment variables and user paths, then resolve to absolute path."""
    return Path(os.path.expandvars(p)).expanduser().resolve()


# Jinja2 environment for template validation (matches matrix.py settings)
_jinja_env = Environment(
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


def _validate_jinja_template(
    template: str,
    field_name: str,
) -> Tuple[bool, Optional[str]]:
    """
    Validate Jinja2 template syntax without rendering.

    Args:
        template: The template string to validate
        field_name: Name of the field for error messages (e.g., "command.template")

    Returns:
        (True, None) if valid
        (False, error_message) if invalid with helpful guidance
    """
    if not template or not isinstance(template, str):
        return True, None  # Empty templates are handled elsewhere

    try:
        _jinja_env.parse(template)
        return True, None
    except TemplateSyntaxError as e:
        # Build helpful error message
        error_msg = f"Jinja2 syntax error in '{field_name}': {e.message}"

        # Add line info if available
        if e.lineno:
            error_msg += f" (line {e.lineno})"

        # Detect common mistake: missing spaces in {% %} tags
        # Pattern matches {%word without space after {%
        missing_space_pattern = r'\{%[a-zA-Z]|\{%-[a-zA-Z]|[a-zA-Z]%\}|[a-zA-Z]-%\}'
        if re.search(missing_space_pattern, template):
            error_msg += (
                "\n  HINT: Spaces are REQUIRED inside {% %} control tags."
                "\n  Correct: {% if condition %} ... {% endif %}"
                "\n  Wrong:   {%if condition%} ... {%endif%}"
            )

        # Detect unclosed variable tags {{ without }}
        unclosed_var_pattern = r'\{\{[^}]*$|\{\{[^}]*[^}]\n'
        if re.search(unclosed_var_pattern, template) or (template.count('{{') > template.count('}}')):
            error_msg += (
                "\n  HINT: Unclosed variable tag detected."
                "\n  Correct: {{ variable }}"
                "\n  Wrong:   {{ variable"
            )

        # Detect unclosed block tags - check for common blocks without matching end
        block_starts = re.findall(r'\{%\s*(if|for|block|macro)\b', template)
        block_ends = re.findall(r'\{%\s*end(if|for|block|macro)\b', template)
        if len(block_starts) > len(block_ends):
            error_msg += (
                "\n  HINT: Unclosed block tag detected (missing {% end... %})."
                "\n  Every {% if %} needs {% endif %}"
                "\n  Every {% for %} needs {% endfor %}"
            )

        # Detect wrong comparison operator (= instead of ==)
        wrong_equals_pattern = r'\{%\s*if\s+[^%]*[^=!<>]=[^=][^%]*%\}'
        if re.search(wrong_equals_pattern, template):
            error_msg += (
                "\n  HINT: Use '==' for comparison, not '='."
                "\n  Correct: {% if value == 'test' %}"
                "\n  Wrong:   {% if value = 'test' %}"
            )

        # Detect undefined filter (common ones users might mistype)
        undefined_filter_match = re.search(r'\|\s*(\w+)', template)
        if undefined_filter_match and 'undefined' in e.message.lower():
            filter_name = undefined_filter_match.group(1)
            error_msg += (
                f"\n  HINT: Filter '{filter_name}' may not exist."
                "\n  Common filters: default, upper, lower, int, float, round, abs"
                "\n  Example: {{ value | default('fallback') }}"
            )

        # Show the problematic part of the template if we can identify it
        if e.lineno and '\n' in template:
            lines = template.split('\n')
            if 0 < e.lineno <= len(lines):
                problem_line = lines[e.lineno - 1].strip()
                if len(problem_line) > 80:
                    problem_line = problem_line[:77] + "..."
                error_msg += f"\n  Problem line: {problem_line}"

        return False, error_msg


def validate_parser_script(
    script: str,
    *,
    require_parse_fn: bool = True,
    parse_fn_name: str = "parse",
) -> Tuple[bool, Optional[str]]:
    """
    Validate a parser_script using AST parsing (no execution).

    Returns:
        (True, None) if valid
        (False, error_message) if invalid
    """
    if not isinstance(script, str) or not script.strip():
        return False, "parser_script is empty or not a string"

    try:
        tree = ast.parse(script, filename="<parser_script>", mode="exec")
    except SyntaxError as e:
        line = (e.text or "").rstrip("\n")
        caret = ""
        if e.offset and e.offset > 0:
            caret = " " * (e.offset - 1) + "^"

        msg = (
            f"Syntax error in parser_script:\n"
            f"  Line {e.lineno}, column {e.offset}\n"
            f"  {line}\n"
            f"  {caret}\n"
            f"  {e.msg}"
        )
        return False, msg

    if require_parse_fn:
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == parse_fn_name:
                return True, None

        return (
            False,
            f"parser_script must define a top-level function "
            f"`def {parse_fn_name}(file_path):`"
        )

    return True, None


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
        "benchmark.cache_file",
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


def create_workdir(cfg: GenericBenchmarkConfig, logger, dry_run: bool = False) -> None:
    """
    Creates a new RUN directory under the configured base workdir.

    Layout:
      <base_workdir>/run_<id>/       (normal execution)
      <base_workdir>/dryrun_<id>/    (dry-run mode)
        ├── logs/
        └── runs/

    Updates cfg.benchmark.workdir to point to the new run directory.

    Args:
        cfg: The benchmark configuration
        logger: Logger instance
        dry_run: If True, use 'dryrun_' prefix instead of 'run_'
    """
    base_workdir = cfg.benchmark.workdir

    base_workdir.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Base work directory: {base_workdir}")

    # Determine prefix based on mode
    prefix = "dryrun_" if dry_run else "run_"

    # Find existing directories with this prefix
    run_dirs = [
        d for d in base_workdir.iterdir()
        if d.is_dir()
        and d.name.startswith(prefix)
        and d.name.split("_", 1)[1].isdigit()
    ]

    next_id = max((int(d.name.split("_", 1)[1]) for d in run_dirs), default=0) + 1

    run_root = base_workdir / f"{prefix}{next_id:03d}"
    run_root.mkdir(parents=True, exist_ok=True)

    # Standard subfolders
    (run_root / "runs").mkdir(parents=True, exist_ok=True)
    (run_root / "logs").mkdir(parents=True, exist_ok=True)

    logger.debug(f"Created run root: {run_root}")

    # Update cfg.workdir to this run root (stable during execution)
    cfg.benchmark.workdir = run_root


def _is_bash_compatible(script_template: str, submit_cmd: str) -> bool:
    """
    Check if the script execution environment is bash-compatible.

    The system probe requires bash features (e.g., [[ ]], =~, process substitution).
    This method checks if the submit command and/or shebang indicate bash will be used.

    Args:
        script_template: The script content (to check shebang)
        submit_cmd: The command used to submit/run the script

    Returns:
        True if bash-compatible, False otherwise
    """
    submit_lower = submit_cmd.lower().strip()

    # Explicit bash in submit command → always OK (bash ignores shebang)
    if 'bash' in submit_lower:
        return True

    # Explicit sh as submit command → never OK
    if submit_lower == 'sh':
        return False

    # For other commands (sbatch, srun, wrappers), check the shebang
    first_line = script_template.split('\n')[0].strip() if script_template else ''
    if first_line.startswith('#!'):
        # Has shebang - check if it explicitly uses non-bash shell
        if '/sh' in first_line or 'env sh' in first_line:
            if 'bash' not in first_line:
                return False

    # No shebang or bash shebang → assume OK
    return True


def check_system_probe_compatibility(cfg: GenericBenchmarkConfig, logger) -> None:
    """
    Check if system probe is compatible with the configured scripts.

    If any script uses a non-bash shell and collect_system_info is enabled,
    disable it and warn the user.

    Args:
        cfg: The configuration object (may be modified)
        logger: Logger instance for warnings
    """
    if not cfg.benchmark.collect_system_info:
        return  # Already disabled, nothing to check

    incompatible_scripts = []
    for script in cfg.scripts:
        if not _is_bash_compatible(script.script_template, script.submit):
            incompatible_scripts.append(script.name)

    if incompatible_scripts:
        cfg.benchmark.collect_system_info = False
        if logger:
            logger.warning(
                f"System probe disabled: non-bash shell detected in script(s): {incompatible_scripts}. "
                f"The probe requires bash features. Set collect_system_info: false to silence this warning."
            )


# ----------------- Main loading function ----------------- #

def _validate_structure(config_path: Path) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """
    Validate the basic structure of a YAML configuration file.

    This performs minimal validation:
    - File exists and is readable
    - Valid YAML syntax
    - Required top-level sections present

    Args:
        config_path: Path to the YAML configuration file

    Returns:
        Tuple of (data, errors):
            - data: Parsed YAML dict if successful, None if errors
            - errors: List of error messages (empty if valid)
    """
    errors: List[str] = []

    # Check file exists
    if not config_path.exists():
        return None, [f"Configuration file not found: {config_path}"]

    if not config_path.is_file():
        return None, [f"Path is not a file: {config_path}"]

    # Try to load YAML
    try:
        with open(config_path, "r") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return None, [f"YAML syntax error: {e}"]
    except Exception as e:
        return None, [f"Failed to read configuration file: {e}"]

    if data is None:
        return None, ["Configuration file is empty"]

    if not isinstance(data, dict):
        return None, ["Configuration file must contain a YAML dictionary"]

    # Check required sections
    required_sections = ["benchmark", "vars", "command", "scripts", "output"]
    for section in required_sections:
        if section not in data:
            errors.append(f"Missing required section: '{section}'")

    if errors:
        return None, errors

    return data, []


def _parse_to_config(data: Dict[str, Any], config_dir: Path) -> GenericBenchmarkConfig:
    """
    Parse a YAML data dictionary into a GenericBenchmarkConfig object.

    This performs parsing only, not semantic validation. Validation is done
    separately by validate_generic_config().

    Args:
        data: Parsed YAML dictionary
        config_dir: Directory containing the config file (for resolving relative paths)

    Returns:
        GenericBenchmarkConfig object (not yet validated)

    Raises:
        KeyError: If required fields are missing
        ConfigValidationError: If data structure is invalid (e.g., constraints not a list)
    """
    # ---- benchmark ----
    b = data["benchmark"]

    # Parse executor_options if present
    executor_options = None
    if "executor_options" in b and b["executor_options"] is not None:
        eo = b["executor_options"]
        executor_options = ExecutorOptionsConfig(
            commands=eo.get("commands"),
            poll_interval=eo.get("poll_interval"),
        )

    # Parse random_config if present (validation done in validate_generic_config)
    random_config = None
    search_method = b.get("search_method", "exhaustive")
    if "random_config" in b and b["random_config"] is not None:
        rc = b["random_config"]
        percentage = rc.get("percentage")
        # Clamp percentage > 1.0 to 1.0
        if percentage is not None and percentage > 1.0:
            percentage = 1.0
        random_config = RandomSamplingConfig(
            n_samples=rc.get("n_samples"),
            percentage=percentage,
            fallback_to_exhaustive=rc.get("fallback_to_exhaustive", True),
        )

    # Parse bayesian_config if present (validation done in validate_generic_config)
    bayesian_config = None
    if "bayesian_config" in b and b["bayesian_config"] is not None:
        bc = b["bayesian_config"]
        xi = bc.get("xi", 0.01)
        kappa = bc.get("kappa", 1.96)
        bayesian_config = BayesianConfig(
            n_initial_points=bc.get("n_initial_points", 5),
            n_iterations=bc.get("n_iterations", 20),
            acquisition_func=bc.get("acquisition_func", "EI"),
            base_estimator=bc.get("base_estimator", "RF"),
            xi=float(xi) if isinstance(xi, (int, float)) else xi,
            kappa=float(kappa) if isinstance(kappa, (int, float)) else kappa,
            objective=bc.get("objective", "maximize"),
            objective_metric=bc.get("objective_metric"),
            fallback_to_exhaustive=bc.get("fallback_to_exhaustive", True),
        )

    benchmark = BenchmarkConfig(
        name=b["name"],
        description=b.get("description"),
        workdir=_expand_path(b["workdir"]),
        repetitions=b.get("repetitions", 1),
        cache_file=_expand_path(b["cache_file"]) if "cache_file" in b else None,
        search_method=search_method,
        executor=b.get("executor", "slurm"),
        executor_options=executor_options,
        random_seed=b.get("random_seed", 42),
        cache_exclude_vars=b.get("cache_exclude_vars", []),
        exhaustive_vars=b.get("exhaustive_vars"),
        max_core_hours=b.get("max_core_hours"),
        cores_expr=b.get("cores_expr"),
        estimated_time_seconds=b.get("estimated_time_seconds"),
        report_vars=b.get("report_vars"),
        bayesian_config=bayesian_config,
        random_config=random_config,
        collect_system_info=b.get("collect_system_info", True),
        track_executions=b.get("track_executions", True),
        create_folders_upfront=b.get("create_folders_upfront", False),
    )

    # ---- vars ----
    vars_cfg: Dict[str, VarConfig] = {}
    for name, cfg in data.get("vars", {}).items():
        sweep_cfg = None
        if "sweep" in cfg:
            s = cfg["sweep"]
            # Normalize scalar values to a list (user-friendly: values: 2 -> values: [2])
            values = s.get("values")
            if values is not None and not isinstance(values, list):
                values = [values]
            sweep_cfg = SweepConfig(
                mode=s["mode"],
                start=s.get("start"),
                end=s.get("end"),
                step=s.get("step"),
                values=values,
            )
        vars_cfg[name] = VarConfig(
            type=cfg["type"],
            sweep=sweep_cfg,
            expr=cfg.get("expr"),
            when=cfg.get("when"),
            default=cfg.get("default"),
        )

    # ---- command ----
    c = data["command"]
    command = CommandConfig(
        template=c["template"],
        metadata=c.get("metadata", {}),
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

    return GenericBenchmarkConfig(
        benchmark=benchmark,
        vars=vars_cfg,
        constraints=constraints,
        command=command,
        scripts=scripts,
        output=output,
        reporting=reporting_cfg,
    )


def load_generic_config(config_path: Path, logger, dry_run: bool = False) -> GenericBenchmarkConfig:
    """
    Load and parse a YAML configuration file into a GenericBenchmarkConfig object.

    This is the main entry point for loading configurations. It:
    1. Validates structure (file exists, valid YAML, required sections)
    2. Parses into config objects
    3. Validates semantics (single source of truth: validate_generic_config)
    4. Creates workdir

    Args:
        config_path: Path to the YAML configuration file
        logger: Logger instance for debug messages
        dry_run: If True, create 'dryrun_' folders instead of 'run_' folders

    Returns:
        Validated GenericBenchmarkConfig object with workdir created

    Raises:
        ConfigValidationError: If configuration is invalid
    """
    # 1. Structural validation
    data, errors = _validate_structure(config_path)
    if errors:
        raise ConfigValidationError("\n".join(errors))

    # 2. Parse to config object
    config_dir = config_path.parent
    cfg = _parse_to_config(data, config_dir)

    # 3. Semantic validation (single source of truth)
    validate_generic_config(cfg)

    # 4. Create workdir (side effect)
    create_workdir(cfg, logger, dry_run=dry_run)

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
            min_samples=br_data.get("min_samples", 1),
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
                    row_vars=plot_data.get("row_vars"),
                    col_var=plot_data.get("col_var"),
                    aggregation=plot_data.get("aggregation", "mean"),
                    show_missing=plot_data.get("show_missing", True),
                    sort_rows_by=plot_data.get("sort_rows_by", "index"),
                    sort_cols_by=plot_data.get("sort_cols_by", "index"),
                    sort_ascending=plot_data.get("sort_ascending", False),
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
                row_vars=plot_data.get("row_vars"),
                col_var=plot_data.get("col_var"),
                aggregation=plot_data.get("aggregation", "mean"),
                show_missing=plot_data.get("show_missing", True),
                sort_rows_by=plot_data.get("sort_rows_by", "index"),
                sort_cols_by=plot_data.get("sort_cols_by", "index"),
                sort_ascending=plot_data.get("sort_ascending", False),
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

    This function uses the same validation logic as load_generic_config() but
    collects errors instead of raising exceptions. It delegates to:
    1. _validate_structure() for structural validation
    2. _parse_to_config() for parsing
    3. validate_generic_config() for semantic validation

    Args:
        config_path: Path to the YAML configuration file

    Returns:
        List of error messages (empty if valid)
    """
    errors: List[str] = []

    # 1. Structural validation (file exists, valid YAML, required sections)
    data, struct_errors = _validate_structure(config_path)
    if struct_errors:
        return struct_errors

    # 2. Try to parse into config object
    config_dir = config_path.parent
    try:
        cfg = _parse_to_config(data, config_dir)
    except KeyError as e:
        errors.append(f"Missing required field: {e}")
        return errors
    except ConfigValidationError as e:
        errors.append(str(e))
        return errors
    except Exception as e:
        errors.append(f"Error parsing configuration: {e}")
        return errors

    # 3. Semantic validation (single source of truth)
    try:
        validate_generic_config(cfg)
    except ConfigValidationError as e:
        errors.append(str(e))

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

    # search_method: exhaustive, random, or bayesian
    if cfg.benchmark.search_method is not None:
        if cfg.benchmark.search_method not in ("exhaustive", "random", "bayesian"):
            raise ConfigValidationError(
                "benchmark.search_method must be one of: exhaustive, random, bayesian"
            )

    # executor validation
    if cfg.benchmark.executor not in ("slurm", "local"):
        raise ConfigValidationError(
            f"benchmark.executor must be one of: slurm, local (got '{cfg.benchmark.executor}')"
        )

    # random_config validation (required when search_method is "random")
    if cfg.benchmark.search_method == "random":
        rc = cfg.benchmark.random_config
        if rc is None:
            raise ConfigValidationError(
                "random_config is required when search_method is 'random'"
            )
        if rc.n_samples is not None and rc.percentage is not None:
            raise ConfigValidationError(
                "random_config: cannot specify both 'n_samples' and 'percentage'. Choose one."
            )
        if rc.n_samples is None and rc.percentage is None:
            raise ConfigValidationError(
                "random_config: must specify either 'n_samples' or 'percentage'"
            )
        if rc.n_samples is not None and rc.n_samples < 1:
            raise ConfigValidationError(
                f"random_config.n_samples must be a positive integer (got '{rc.n_samples}')"
            )
        if rc.percentage is not None and rc.percentage <= 0:
            raise ConfigValidationError(
                f"random_config.percentage must be a positive number (got '{rc.percentage}')"
            )

    # bayesian_config validation (required when search_method is "bayesian")
    if cfg.benchmark.search_method == "bayesian":
        bc = cfg.benchmark.bayesian_config
        if bc is None:
            raise ConfigValidationError(
                "bayesian_config is required when search_method is 'bayesian'"
            )
        if not bc.objective_metric:
            raise ConfigValidationError(
                "bayesian_config.objective_metric is required"
            )
        if bc.n_initial_points is not None and bc.n_initial_points < 1:
            raise ConfigValidationError(
                f"bayesian_config.n_initial_points must be a positive integer (got '{bc.n_initial_points}')"
            )
        if bc.n_iterations is not None and bc.n_iterations < 1:
            raise ConfigValidationError(
                f"bayesian_config.n_iterations must be a positive integer (got '{bc.n_iterations}')"
            )
        if bc.acquisition_func not in ("EI", "PI", "LCB"):
            raise ConfigValidationError(
                f"bayesian_config.acquisition_func must be one of: EI, PI, LCB (got '{bc.acquisition_func}')"
            )
        if bc.base_estimator not in ("RF", "GP", "ET", "GBRT"):
            raise ConfigValidationError(
                f"bayesian_config.base_estimator must be one of: RF, GP, ET, GBRT (got '{bc.base_estimator}')"
            )
        if bc.objective not in ("minimize", "maximize"):
            raise ConfigValidationError(
                f"bayesian_config.objective must be one of: minimize, maximize (got '{bc.objective}')"
            )

    # ---- vars ----
    if not cfg.vars:
        raise ConfigValidationError("At least one variable must be defined in 'vars'")

    valid_var_types = ("int", "float", "str", "bool")
    for name, v in cfg.vars.items():
        # Validate var type
        if v.type not in valid_var_types:
            raise ConfigValidationError(
                f"var '{name}' has invalid type '{v.type}'. Must be one of: {valid_var_types}"
            )

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

        # Validate conditional variable fields (when and default)
        if v.when is not None:
            if v.sweep is None:
                raise ConfigValidationError(
                    f"var '{name}' has 'when' but no 'sweep' - 'when' is only valid for swept variables"
                )
            if v.expr is not None:
                raise ConfigValidationError(
                    f"var '{name}' cannot have both 'when' and 'expr'"
                )
            if v.default is None:
                raise ConfigValidationError(
                    f"var '{name}' has 'when' but no 'default' - 'default' is required when 'when' is specified"
                )
            # Validate Jinja2 syntax in when expression
            ok, err = _validate_jinja_template(v.when, f"vars['{name}'].when")
            if not ok:
                raise ConfigValidationError(err)

        if v.default is not None and v.when is None:
            raise ConfigValidationError(
                f"var '{name}' has 'default' but no 'when' - 'default' is only used with conditional variables"
            )

        # Validate Jinja2 syntax in expr (if present)
        if v.expr:
            ok, err = _validate_jinja_template(v.expr, f"vars['{name}'].expr")
            if not ok:
                raise ConfigValidationError(err)

    # ---- variable reference lists ----
    def validate_var_list(field_name: str, var_list) -> None:
        if var_list is None:
            return
        invalid_vars = [v for v in var_list if v not in cfg.vars]
        if invalid_vars:
            raise ConfigValidationError(
                f"benchmark.{field_name} contains undefined variables: {invalid_vars}. "
                f"Available variables: {sorted(cfg.vars.keys())}"
            )

    validate_var_list("cache_exclude_vars", cfg.benchmark.cache_exclude_vars)
    validate_var_list("exhaustive_vars", cfg.benchmark.exhaustive_vars)

    # ---- constraints ----
    for idx, constraint in enumerate(cfg.constraints):
        if not constraint.rule or not constraint.rule.strip():
            raise ConfigValidationError(
                f"constraints[{idx}] ('{constraint.name}') must have a non-empty 'rule'"
            )
        if constraint.violation_policy not in ("skip", "error", "warn"):
            raise ConfigValidationError(
                f"constraints[{idx}].violation_policy must be 'skip', 'error', or 'warn' "
                f"(got '{constraint.violation_policy}')"
            )

    # ---- command ----
    if not cfg.command.template.strip():
        raise ConfigValidationError("command.template must not be empty")

    # Validate Jinja2 syntax in command.template
    ok, err = _validate_jinja_template(cfg.command.template, "command.template")
    if not ok:
        raise ConfigValidationError(err)

    # ---- scripts ----
    if not cfg.scripts:
        raise ConfigValidationError("At least one script must be defined in 'scripts'")

    for s in cfg.scripts:
        if not s.script_template.strip():
            raise ConfigValidationError(
                f"script '{s.name}' must have a non-empty script_template"
            )

        # Validate Jinja2 syntax in script_template
        ok, err = _validate_jinja_template(s.script_template, f"scripts['{s.name}'].script_template")
        if not ok:
            raise ConfigValidationError(err)

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

    if sink.type == "parquet" and not PYARROW_AVAILABLE:
        raise ConfigValidationError(
            "pyarrow is required for parquet output. "
            "Install it with: pip install pyarrow\n"
            "Or install iops with parquet support: pip install iops-benchmark[parquet]"
        )

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

    # ---- report_vars validation ----
    if cfg.benchmark.report_vars:
        invalid_vars = [v for v in cfg.benchmark.report_vars if v not in cfg.vars]
        if invalid_vars:
            raise ConfigValidationError(
                f"benchmark.report_vars contains undefined variables: {invalid_vars}. "
                f"Available variables: {sorted(cfg.vars.keys())}"
            )

    # ---- bayesian_config validation ----
    if cfg.benchmark.bayesian_config and cfg.benchmark.bayesian_config.objective_metric:
        # Collect all valid metric names from scripts' parser sections
        valid_metrics = set()
        for script in cfg.scripts:
            if script.parser and script.parser.metrics:
                for metric in script.parser.metrics:
                    valid_metrics.add(metric.name)

        objective_metric = cfg.benchmark.bayesian_config.objective_metric
        if objective_metric not in valid_metrics:
            raise ConfigValidationError(
                f"bayesian_config.objective_metric '{objective_metric}' is not a valid metric. "
                f"Available metrics from parser: {sorted(valid_metrics)}"
            )
