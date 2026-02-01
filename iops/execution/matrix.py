from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple, Optional

import itertools
import math

from jinja2 import Environment, StrictUndefined

from iops.config.models import (
    GenericBenchmarkConfig,
    VarConfig,
    ParserConfig,
    MetricConfig,
    ConfigValidationError,
)
from iops.execution.constraints import (
    filter_execution_matrix,
    classify_constraints,
    check_constraints_for_vars,
)


# ----------------- Jinja helpers ----------------- #

_jinja_env = Environment(
    undefined=StrictUndefined,
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


def _render_template(template: str, context: Dict[str, Any]) -> str:
    """
    Render a Jinja2 template string with the given context.
    """
    tmpl = _jinja_env.from_string(template)
    return tmpl.render(**context)


# ----------------- type helpers ----------------- #

def _cast_value(type_name: str, value: Any) -> Any:
    """
    Cast a value according to the var 'type' in YAML.
    Supported types: int, float, str, bool.
    Fallback: return as-is.
    """
    if value is None:
        return None

    if type_name == "int":
        return int(value)
    if type_name == "float":
        return float(value)
    if type_name == "str":
        return str(value)
    if type_name == "bool":
        # treat "true"/"false" strings as bools
        if isinstance(value, str):
            lv = value.lower()
            if lv in {"true", "yes", "1"}:
                return True
            if lv in {"false", "no", "0"}:
                return False
        return bool(value)

    # unknown type, just return
    return value


def _eval_expr(expr: str, vartype: str, context: Dict[str, Any]) -> Any:
    """
    Evaluate a derived variable expression.

    Heuristic:
    - If the expression contains '{{' or '}}', treat it as a Jinja template.
    - Otherwise, treat it as a Python arithmetic expression evaluated
      with 'context' as local vars.
    """
    expr = expr.strip()

    # Jinja-style expression or string var
    if "{{" in expr or "}}" in expr or vartype == "str":
        rendered = _render_template(expr, context)
        return _cast_value(vartype, rendered)

    # Arithmetic-style expression
    # Restrict builtins for safety
    allowed_funcs = {
        "min": min,
        "max": max,
        "abs": abs,
        "round": round,
        "floor": math.floor,
        "ceil": math.ceil,
        "int": int,
        "float": float,
    }
    try:
        val = eval(expr, {"__builtins__": {}}, {**allowed_funcs, **context})
    except Exception as e:
        raise ConfigValidationError(f"Error evaluating expr='{expr}': {e}") from e

    return _cast_value(vartype, val)


# ----------------- sweep helpers ----------------- #

def _build_sweep_values(name: str, vcfg: VarConfig) -> List[Any]:
    """
    From a VarConfig with a 'sweep', return the list of values for this var.

    Note: Input validation (sweep existence, mode, range params, step!=0, non-empty values)
    is handled by loader.py's validate_generic_config(). This function assumes valid input.
    """
    mode = vcfg.sweep.mode
    if mode == "range":
        values = list(
            range(
                vcfg.sweep.start,
                vcfg.sweep.end + (1 if vcfg.sweep.step > 0 else -1),
                vcfg.sweep.step,
            )
        )
        return [_cast_value(vcfg.type, v) for v in values]

    else:  # mode == "list"
        return [_cast_value(vcfg.type, v) for v in vcfg.sweep.values]


# ----------------- Conditional variable helpers ----------------- #

def _extract_variable_references(expr: str) -> Set[str]:
    """
    Extract variable names referenced in a when expression.

    Handles both Jinja2-style ({{ var }}) and Python-style (var) references.
    """
    refs: Set[str] = set()

    # Find Jinja-style references: {{ var }} or {{ var.attr }}
    jinja_pattern = r'\{\{\s*(\w+)'
    refs.update(re.findall(jinja_pattern, expr))

    # Parse as Python expression for direct variable references
    try:
        tree = ast.parse(expr, mode='eval')
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                refs.add(node.id)
    except SyntaxError:
        pass  # Not valid Python, rely on Jinja matches

    # Filter out known functions/builtins
    builtins = {
        'min', 'max', 'abs', 'round', 'floor', 'ceil',
        'int', 'float', 'str', 'bool',
        'True', 'False', 'true', 'false', 'None',
        'and', 'or', 'not', 'in',
    }
    return refs - builtins


def _topological_sort_variables(
    vars_cfg: Dict[str, VarConfig]
) -> List[str]:
    """
    Topologically sort variables so dependencies come before dependents.

    Only considers swept variables. Variables with `when` clauses depend
    on the variables referenced in their `when` expression.

    Returns:
        List of variable names in dependency order

    Raises:
        ConfigValidationError: If circular dependency detected
    """
    # Build dependency graph from when expressions
    dependencies: Dict[str, Set[str]] = {}
    for name, vcfg in vars_cfg.items():
        if vcfg.when:
            deps = _extract_variable_references(vcfg.when)
            # Only include dependencies that are actually in our variable set
            dependencies[name] = deps & set(vars_cfg.keys())
        else:
            dependencies[name] = set()

    # Kahn's algorithm for topological sort
    in_degree = {name: 0 for name in vars_cfg}
    for name, deps in dependencies.items():
        in_degree[name] = len(deps)

    # Start with variables that have no dependencies
    queue = [name for name, deg in in_degree.items() if deg == 0]
    result: List[str] = []

    while queue:
        node = queue.pop(0)
        result.append(node)

        # Reduce in-degree for variables that depend on this one
        for name, deps in dependencies.items():
            if node in deps:
                in_degree[name] -= 1
                if in_degree[name] == 0:
                    queue.append(name)

    if len(result) != len(vars_cfg):
        remaining = set(vars_cfg.keys()) - set(result)
        raise ConfigValidationError(
            f"Circular dependency detected in conditional variables: {remaining}"
        )

    return result


def _evaluate_when_condition(when_expr: str, context: Dict[str, Any]) -> bool:
    """
    Evaluate a when condition against current variable values.

    Uses the same restricted eval pattern as constraint evaluation.

    Args:
        when_expr: The condition expression (Python-style)
        context: Dictionary of variable values

    Returns:
        Boolean result of the condition

    Raises:
        ConfigValidationError: If evaluation fails
    """
    allowed_funcs = {
        "min": min,
        "max": max,
        "abs": abs,
        "round": round,
        "floor": math.floor,
        "ceil": math.ceil,
        "int": int,
        "float": float,
    }

    try:
        result = eval(when_expr, {"__builtins__": {}}, {**allowed_funcs, **context})
        return bool(result)
    except Exception as e:
        raise ConfigValidationError(f"Error evaluating 'when={when_expr}': {e}")


# ----------------- Execution instance ----------------- #

@dataclass
class ExecutionInstance:
    """
    Fully materialized instance of a benchmark execution.

    IMPORTANT:
    - All Jinja rendering is done lazily via @property.
    - The planner is allowed to modify at runtime:
        * self.base_vars (for swept/fixed vars)
        * self.workdir
        * self.metadata (e.g., metadata["repetition"], metrics, etc.)
      and all properties (command, script_text, derived vars, etc.)
      will re-render using the current state.
    """

    execution_id: int

    # Optional: per-instance default repetition index (0- or 1-based, as you prefer)
    # The planner can still override via metadata["repetition"].
    repetition: int = 0

    repetitions: int = 1
    execution_dir: Optional[Path] = None

    # Benchmark-level
    benchmark_name: str = ""
    benchmark_description: Optional[str] = None
    workdir: Optional[Path] = None
    log_dir: Optional[Path] = None

    # Variables:
    #   - base_vars: swept and fixed scalar vars (no expr).
    #   - derived_var_cfgs: name -> (expr, vartype) for derived vars.
    base_vars: Dict[str, Any] = field(default_factory=dict)
    derived_var_cfgs: Dict[str, Tuple[str, str]] = field(default_factory=dict)

    # Exhaustive variables tracking (for planners to group instances)
    exhaustive_var_names: List[str] = field(default_factory=list)  # Names of exhaustive variables
    search_var_names: List[str] = field(default_factory=list)  # Names of search variables

    # Runtime metadata (for planner / execution use, e.g. "repetition", "result", etc.)
    # This is NOT templated; it is just data that can be used in the Jinja context.
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Optional: cache file path (if you want it here)
    cache_file: Path | None = None

    # ---------- Template fields (stored from cfg, rendered lazily) ---------- #

    # Command template and env/labels templates
    command_template: str = ""
    env_templates: Dict[str, Any] = field(default_factory=dict)
    labels_templates: Dict[str, Any] = field(default_factory=dict)

    # Script metadata
    script_name: str = ""
    script_template: str = ""
    script_file : Optional[Path] = None

    # Optional post-processing script template
    post_script_template: str | None = None
    post_script_file : Optional[Path] = None

    # Parser template (with possibly templated .file)
    parser_template: ParserConfig | None = None

    # Output configuration (template + selection)
    output_path_template: str | None = None
    output_type: str = "parquet"   # csv | parquet | sqlite
    output_table: str = "results"  # sqlite only

    output_exclude: List[str] = field(default_factory=list)

   

    # ---------- Internal helpers for vars & context ---------- #

    def _base_context_for_vars(self) -> Dict[str, Any]:
        """
        Context used when computing derived vars.
        Does NOT include the final 'vars' mapping yet.
        """
        ctx: Dict[str, Any] = {
            "benchmark": {
                "name": self.benchmark_name,
                "description": self.benchmark_description,
                "workdir": str(self.workdir),
                "execution_dir": str(self.execution_dir)
            },
            "workdir": str(self.workdir),
            "log_dir": str(self.log_dir) if self.log_dir else None,
            "execution_dir": str(self.execution_dir),
            "execution_id": self.execution_id,
            "repetitions": self.repetitions,
            "os_env": dict(os.environ),
        }

        # metadata (dynamic, including repetition, results, etc.)
        ctx["metadata"] = self.metadata

        # convenience: expose repetition
        # metadata["repetition"] overrides the instance-level repetition field
        if "repetition" in self.metadata:
            ctx["repetition"] = self.metadata["repetition"]
        else:
            ctx["repetition"] = self.repetition

        return ctx

    def _compute_all_vars(self) -> Dict[str, Any]:
        """
        Compute full vars dict = base_vars + derived vars, lazily.

        Derived vars can depend on:
        - benchmark/workdir/execution_id
        - base_vars
        - previously computed derived vars (in definition order)
        - metadata (including repetition)
        """
        ctx0 = self._base_context_for_vars()
        all_vars: Dict[str, Any] = dict(self.base_vars)

        # derived_var_cfgs preserves insertion order (from build_execution_matrix)
        # Note: expr validation is handled by loader.py's validate_generic_config()
        for name, (expr, vartype) in self.derived_var_cfgs.items():
            val = _eval_expr(expr, vartype, {**ctx0, **all_vars})
            all_vars[name] = val

        return all_vars

    def _render_context(self) -> Dict[str, Any]:
        """
        Build the full context used for all Jinja rendering.

        This context includes:
        - benchmark.* information
        - workdir
        - log_dir
        - execution_id
        - execution_dir
        - repetitions
        - flattened vars ({{ my_var }})
        - vars mapping ({{ vars.my_var }})
        - metadata
        - repetition (from metadata or instance field)
        - os_env: system environment variables ({{ os_env.PATH }}, etc.)
        """
        ctx0 = self._base_context_for_vars()
        all_vars = self._compute_all_vars()

        ctx: Dict[str, Any] = {
            **ctx0,
            **all_vars,
        }
        ctx["vars"] = all_vars
        ctx["os_env"] = dict(os.environ)

        return ctx

    # ---------- Exposed vars property (read-only union) ---------- #

    @property
    def vars(self) -> Dict[str, Any]:
        """
        Public view of all variables (base + derived), evaluated lazily.
        """
        return self._compute_all_vars()

    def get_search_point(self) -> tuple:
        """
        Get a tuple of search variable values for grouping instances.
        This excludes exhaustive variables and only includes search vars.
        Used by planners to group instances that belong to the same search point.
        """
        if not self.search_var_names:
            # No search vars defined (e.g., all vars are exhaustive or not using exhaustive_vars)
            # Return a tuple of all base vars for backward compatibility
            return tuple(sorted((k, v) for k, v in self.base_vars.items()))

        # Return tuple of search var values in consistent order
        return tuple(self.base_vars.get(name) for name in sorted(self.search_var_names))

    # ---------- Lazy-rendered properties ---------- #

    @property
    def command(self) -> str:
        """
        Render the command from command_template and the current context.
        """
        if not self.command_template:
            return ""
        ctx = self._render_context()
        return _render_template(self.command_template, ctx)

    @property
    def env(self) -> Dict[str, str]:
        """
        Render the environment variables from env_templates and the current context.
        """
        ctx = self._render_context()
        rendered: Dict[str, str] = {}
        for k, v in self.env_templates.items():
            if isinstance(v, str):
                rendered[k] = _render_template(v, ctx)
            else:
                rendered[k] = str(v)
        return rendered

    @property
    def command_labels(self) -> Dict[str, Any]:
        """
        Render user-defined labels from labels_templates.
        These go into the 'labels.*' namespace in output.
        """
        ctx = self._render_context()
        rendered: Dict[str, Any] = {}
        for k, v in self.labels_templates.items():
            if isinstance(v, str):
                rendered[k] = _render_template(v, ctx)
            else:
                rendered[k] = v
        return rendered

    @property
    def output_path(self) -> Optional[Path]:
        """
        Render the output sink path from output_path_template.
        For sqlite, this is the DB file path.
        """
        if not self.output_path_template:
            return None
        ctx = self._render_context()
        path_str = _render_template(self.output_path_template, ctx)
        return Path(path_str)


    @property
    def script_text(self) -> str:
        """
        Render the main script text from script_template, using:
        - {{ vars.* }}
        - {{ command }}
        - {{ command_env }}
        - {{ command_labels }}
        - plus the standard context.
        """
        if not self.script_template:
            return ""

        base_ctx = self._render_context()

        # Provide command object with "template" attribute = rendered command
        command_obj = type("CmdObj", (), {})()
        setattr(command_obj, "template", self.command)

        script_ctx = {
            **base_ctx,
            "vars": self.vars,
            "command": command_obj,
            "command_env": self.env,
            "command_labels": self.command_labels,
        }

        return _render_template(self.script_template, script_ctx)

    @property
    def post_script(self) -> Optional[str]:
        """
        Render the optional post-processing script (if any).
        """
        if not self.post_script_template:
            return None

        base_ctx = self._render_context()

        command_obj = type("CmdObj", (), {})()
        setattr(command_obj, "template", self.command)

        script_ctx = {
            **base_ctx,
            "vars": self.vars,
            "command": command_obj,
            "command_env": self.env,
            "command_labels": self.command_labels,
        }

        return _render_template(self.post_script_template, script_ctx)

    @property
    def parser(self) -> Optional[ParserConfig]:
        """
        Build (and render) a ParserConfig from parser_template.
        Only 'file' is treated as templated; metrics paths are taken as-is.
        """
        if self.parser_template is None:
            return None

        ctx = self._render_context()

        file_template = self.parser_template.file
        if isinstance(file_template, str):
            file_rendered = _render_template(file_template, ctx)
        else:
            file_rendered = str(file_template)

        metrics: List[MetricConfig] = []
        for m in self.parser_template.metrics:
            metrics.append(MetricConfig(name=m.name, path=m.path))

        return ParserConfig(           
            file=file_rendered,
            metrics=metrics,
            parser_script=self.parser_template.parser_script,
        )

    # ---------- Human-readable representations ---------- #

    def short_label(self) -> str:
        """
        Small helper for logging/debugging.
        """
        return f"{self.benchmark_name}#{self.execution_id}"

    def __str__(self) -> str:
        """
        Human-friendly summary of this execution.
        Suitable for INFO-level logs.
        """
        lines: list[str] = []

        lines.append(70 * "-")

        # Header
        lines.append(f"Execution #{self.execution_id}/{self.repetition} — {self.benchmark_name}")
        
        lines.append(f"Workdir  : {self.workdir}")
        lines.append(f"Execution Dir : {self.execution_dir}")

        # Vars (sorted for stability)
        vars_map = self.vars
        if vars_map:
            vars_str = ", ".join(
                f"{k}={vars_map[k]!r}"
                for k in sorted(vars_map)
            )
            lines.append(f"Vars: {vars_str}")

        # Command (compact, rendered lazily)
        cmd = self.command.replace("\n", " ").strip()
        if cmd:
            lines.append(f"Command: {cmd}")

        # Script info
        lines.append(
            f"Script   : {self.script_name} "
            f"(file={self.script_file})"
        )
        # post script
        if self.post_script_template:
            lines.append(f"Post-script: {self.post_script_file}")
            

        # Repetitions
        lines.append(f"Repeats: {self.repetitions}")

        # Labels (rendered)
        effective_labels = self.command_labels
        if effective_labels:
            label_items = ", ".join(f"{k}={v!r}" for k, v in effective_labels.items())
            lines.append(f"Labels: {label_items}")

        # Output
        if self.output_path:
            extra = f", table={self.output_table}" if self.output_type == "sqlite" else ""
            lines.append(
                f"Output: type={self.output_type}, path={self.output_path}{extra}"
            )
            if self.output_exclude:
                lines.append(f"Output fields (exclude): {', '.join(self.output_exclude)}")
            else:
                lines.append("Output fields: default (all)")


        # Parser
        parser_obj = self.parser
        if parser_obj:
            metric_names = [m.name for m in parser_obj.metrics]
            metrics_str = ", ".join(metric_names) 
            lines.append(
                f"Parser: file={parser_obj.file}, metrics={metrics_str}"
            )

        lines.append(70 * "-")

        return "\n".join(lines)

    def describe(self) -> str:
        """
        Concise representation for DEBUG logs.
        Shows metadata only - no script/command content (check execution_dir for files).
        """
        sep_start = sep_end = "#" * 80
        sep = "-" * 80
        lines: list[str] = [
            sep_start,
            f"Execution #{self.execution_id}",
            f"Benchmark : {self.benchmark_name}",
            f"Workdir   : {self.workdir}",
            f"Execution Dir: {self.execution_dir}",
            f"Repetitions: {self.repetition}/{self.repetitions}",
            f"Cache File: {self.cache_file}",
            sep,
            "Variables:",
        ]

        vars_map = self.vars
        for k in sorted(vars_map):
            lines.append(f"  {k} = {vars_map[k]!r}")

        # Show script summary only (check execution_dir for actual content)
        script_lines = self.script_text.strip().split('\n') if self.script_text else []
        lines.extend([
            sep,
            f"Script ({self.script_name}): {len(script_lines)} lines",
        ])

        if self.post_script:
            post_lines = self.post_script.strip().split('\n')
            lines.append(f"Post-script: {len(post_lines)} lines")

        env_rendered = self.env
        if env_rendered:
            lines.append(f"Environment: {len(env_rendered)} variables")

        effective_labels = self.command_labels
        if effective_labels:
            lines.append(f"Labels: {len(effective_labels)} defined")

        if self.output_path:
            lines.extend([
                sep,
                f"Output type : {self.output_type}",
                f"Output path : {self.output_path}",
            ])
            if self.output_type == "sqlite":
                lines.append(f"Output table: {self.output_table}")

            if self.output_exclude:
                lines.append(f"Fields (exclude): {', '.join(self.output_exclude)}")
            else:
                lines.append("Fields: default (all)")


        parser_obj = self.parser
        if parser_obj:
            lines.extend([
                sep,
                "Parser:",
                f"  file        : {parser_obj.file}",
                "  metrics     :",
            ])
            for m in parser_obj.metrics:
                lines.append(f"    - {m.name} @ {m.path}")
            if parser_obj.parser_script:
                parser_lines = parser_obj.parser_script.strip().split('\n')
                lines.append(f"  parser_script: {len(parser_lines)} lines")

        lines.append(sep_end)

        return "\n".join(lines)


# ----------------- Single instance creator ----------------- #

def _create_execution_instance(
    cfg: GenericBenchmarkConfig,
    base_vars: Dict[str, Any],
    execution_id: int,
    script_index: int = 0,
    search_var_names: Optional[List[str]] = None,
    exhaustive_var_names: Optional[List[str]] = None,
) -> Tuple[ExecutionInstance, bool, List[Tuple[Any, str]]]:
    """
    Create a single ExecutionInstance from explicit variable values and validate constraints.

    This is useful for:
    - Bayesian optimization (create instance for optimizer-suggested parameters)
    - Testing specific parameter combinations
    - Any case where you want to create an instance without building the full matrix

    The function creates the instance and validates it against constraints in one step,
    ensuring all variable processing (including derived vars) is done before constraint
    checking.

    Args:
        cfg: The benchmark configuration
        base_vars: Dictionary of base variable values (swept variables)
        execution_id: The execution ID to assign
        script_index: Which script to use (default 0, first script)
        search_var_names: Names of search variables (for grouping). If None, all base_vars are search vars.
        exhaustive_var_names: Names of exhaustive variables. If None, empty list.

    Returns:
        Tuple of (instance, is_valid, violations):
        - instance: ExecutionInstance with all templates set up for lazy rendering
        - is_valid: True if all constraints pass (or only have "warn" policy)
        - violations: List of (constraint, message) tuples for any violations

    Raises:
        IndexError: If script_index is out of range
        ConfigValidationError: If configuration is invalid
    """
    if script_index >= len(cfg.scripts):
        raise IndexError(
            f"script_index {script_index} out of range (only {len(cfg.scripts)} scripts defined)"
        )

    script_cfg = cfg.scripts[script_index]
    repetitions = max(1, int(getattr(cfg.benchmark, "repetitions", 1) or 1))

    # Apply 'when' clause logic: if a variable has a 'when' condition that evaluates
    # to False, override its value with the default. This ensures conditional variables
    # are handled correctly even when the planner suggests invalid combinations.
    adjusted_vars = dict(base_vars)
    for name, vcfg in cfg.vars.items():
        if vcfg.when and name in adjusted_vars:
            if not _evaluate_when_condition(vcfg.when, adjusted_vars):
                # Condition is false, use default value
                adjusted_vars[name] = _cast_value(vcfg.type, vcfg.default)
    base_vars = adjusted_vars

    # Build derived var configs from cfg.vars
    # Note: expr validation is handled by loader.py's validate_generic_config()
    derived_var_cfgs: Dict[str, Tuple[str, str]] = {}
    for name, vcfg in cfg.vars.items():
        if vcfg.sweep is None and vcfg.expr is not None:
            derived_var_cfgs[name] = (vcfg.expr, vcfg.type)

    # Command/env/labels templates from cfg
    command_template = cfg.command.template
    env_templates = dict(cfg.command.env) if cfg.command.env else {}
    labels_templates = dict(cfg.command.labels) if cfg.command.labels else {}

    # Output sink templates
    output_path_template = cfg.output.sink.path
    output_type = cfg.output.sink.type
    output_table = cfg.output.sink.table
    output_exclude = list(cfg.output.sink.exclude)

    # Script template
    script_template = script_cfg.script_template

    # Optional post script template
    post_script_template = None
    if script_cfg.post and script_cfg.post.script:
        post_script_template = script_cfg.post.script

    # Parser template (store as-is; we'll render .file lazily)
    parser_template: ParserConfig | None = None
    if script_cfg.parser is not None:
        metrics: List[MetricConfig] = []
        for m in script_cfg.parser.metrics:
            metrics.append(MetricConfig(name=m.name, path=m.path))

        parser_template = ParserConfig(
            file=script_cfg.parser.file,
            metrics=metrics,
            parser_script=script_cfg.parser.parser_script,
        )

    instance = ExecutionInstance(
        execution_id=execution_id,
        repetition=0,  # planner will set metadata["repetition"] per run
        repetitions=repetitions,
        benchmark_name=cfg.benchmark.name,
        benchmark_description=cfg.benchmark.description,
        workdir=cfg.benchmark.workdir,
        log_dir=cfg.benchmark.workdir / "logs" if cfg.benchmark.workdir else None,
        cache_file=getattr(cfg.benchmark, "cache_file", None),
        base_vars=base_vars,
        derived_var_cfgs=derived_var_cfgs,
        exhaustive_var_names=exhaustive_var_names or [],
        search_var_names=search_var_names or list(base_vars.keys()),
        metadata={},
        command_template=command_template,
        env_templates=env_templates,
        labels_templates=labels_templates,
        script_name=script_cfg.name,
        script_template=script_template,
        post_script_template=post_script_template,
        parser_template=parser_template,
        output_path_template=output_path_template,
        output_type=output_type,
        output_table=output_table,
        output_exclude=output_exclude,
    )

    # Validate constraints using computed vars (base + derived)
    if not cfg.constraints:
        return instance, True, []

    is_valid, violations = check_constraints_for_vars(instance.vars, cfg.constraints)
    return instance, is_valid, violations


# ----------------- Main builder ----------------- #

def build_execution_matrix(
    cfg: GenericBenchmarkConfig,
    start_execution_id: int = 0,
) -> Tuple[List[ExecutionInstance], List[ExecutionInstance]]:
    """
    Build the Cartesian product of swept variables and return lists of
    ExecutionInstance objects (kept and skipped).

    IMPORTANT:
    - No Jinja rendering is done here.
      All templates (command, metadata, scripts, parser, CSV path,
      and derived variable expressions) are stored in the ExecutionInstance
      and rendered lazily via @property.

    Behaviour:
    - Sweep over all vars that have a `sweep` defined.
    - repetitions is 1 by default (or benchmark.repetitions if present).

    Returns:
        (kept_instances, skipped_instances):
            - kept_instances: Instances that passed constraint filtering
            - skipped_instances: Instances skipped due to constraint violations
              (with metadata: __skipped, __skip_reason, __skip_message)
    """

    # ----------------- split vars ----------------- #
    swept_vars: List[Tuple[str, VarConfig]] = []
    derived_vars: List[Tuple[str, VarConfig]] = []

    repetitions = max(1, int(getattr(cfg.benchmark, "repetitions", 1) or 1))

    # Get exhaustive vars from benchmark config
    exhaustive_var_names = set(cfg.benchmark.exhaustive_vars or [])

    # Classify variables:
    for name, v in cfg.vars.items():
        # Derived variable: has expr and no sweep
        if v.sweep is None and v.expr is not None:
            derived_vars.append((name, v))
            continue

        # Swept variable: has sweep defined
        if v.sweep is not None:
            swept_vars.append((name, v))

    if not swept_vars:
        raise ConfigValidationError(
            "No swept variables defined – at least one "
            "'vars.*.sweep' is required."
        )

    # ----------------- partition swept vars into search and exhaustive ----------------- #

    search_vars: List[Tuple[str, VarConfig]] = []
    exhaustive_swept_vars: List[Tuple[str, VarConfig]] = []

    for name, vcfg in swept_vars:
        if name in exhaustive_var_names:
            exhaustive_swept_vars.append((name, vcfg))
        else:
            search_vars.append((name, vcfg))

    # Validate that all exhaustive_vars are actually swept
    for name in exhaustive_var_names:
        if name not in [n for n, _ in swept_vars]:
            raise ConfigValidationError(
                f"Variable '{name}' is listed in exhaustive_vars but is not swept."
            )

    # If no search vars (all swept vars are exhaustive), treat as normal exhaustive search
    if not search_vars:
        search_vars = exhaustive_swept_vars
        exhaustive_swept_vars = []

    # ----------------- build sweep products ----------------- #

    # Check if any conditional variables exist
    has_conditional = any(v.when for _, v in swept_vars)

    # Prepare variable name lists for ExecutionInstance
    search_names = [name for name, _ in search_vars]
    exhaustive_names = [name for name, _ in exhaustive_swept_vars]

    if has_conditional:
        # ----------------- Iterative building for conditional variables ----------------- #

        # Get all swept variable configs for topological sort
        swept_var_cfgs = {name: vcfg for name, vcfg in swept_vars}

        # Topologically sort to ensure dependencies are processed first
        sorted_var_names = _topological_sort_variables(swept_var_cfgs)

        # Build combinations iteratively
        combinations: List[Dict[str, Any]] = [{}]

        for name in sorted_var_names:
            vcfg = swept_var_cfgs[name]
            values = _build_sweep_values(name, vcfg)
            if not values:
                raise ConfigValidationError(f"Variable '{name}' produced an empty sweep.")

            new_combinations: List[Dict[str, Any]] = []

            if vcfg.when:
                # Conditional variable: evaluate condition for each combination
                for combo in combinations:
                    if _evaluate_when_condition(vcfg.when, combo):
                        # Condition true: expand with all sweep values
                        for val in values:
                            new_combinations.append({**combo, name: val})
                    else:
                        # Condition false: use default value
                        default_val = _cast_value(vcfg.type, vcfg.default)
                        new_combinations.append({**combo, name: default_val})
            else:
                # Unconditional variable: standard Cartesian expansion
                for combo in combinations:
                    for val in values:
                        new_combinations.append({**combo, name: val})

            combinations = new_combinations

        # Deduplicate combinations (conditional vars may create duplicates)
        seen: set = set()
        unique_combinations: List[Dict[str, Any]] = []
        for combo in combinations:
            key = tuple(sorted(combo.items()))
            if key not in seen:
                seen.add(key)
                unique_combinations.append(combo)

        combinations = unique_combinations

    else:
        # ----------------- Standard Cartesian product (no conditional vars) ----------------- #

        # Build search space (variables that the planner optimizes over)
        search_value_lists: List[Tuple[str, List[Any]]] = []
        for name, vcfg in search_vars:
            values = _build_sweep_values(name, vcfg)
            if not values:
                raise ConfigValidationError(f"Variable '{name}' produced an empty sweep.")
            search_value_lists.append((name, values))

        search_values_product = itertools.product(
            *[vals for _, vals in search_value_lists]
        )

        # Build exhaustive space (variables fully expanded for each search point)
        exhaustive_value_lists: List[Tuple[str, List[Any]]] = []
        for name, vcfg in exhaustive_swept_vars:
            values = _build_sweep_values(name, vcfg)
            if not values:
                raise ConfigValidationError(f"Exhaustive variable '{name}' produced an empty sweep.")
            exhaustive_value_lists.append((name, values))

        # If there are exhaustive vars, build their product; otherwise single empty combination
        if exhaustive_value_lists:
            exhaustive_values_product = list(itertools.product(
                *[vals for _, vals in exhaustive_value_lists]
            ))
        else:
            exhaustive_values_product = [()]  # Single empty combination

        # Build all combinations
        combinations = []
        for search_combo in search_values_product:
            search_assignment = dict(zip(search_names, search_combo))
            for exhaustive_combo in exhaustive_values_product:
                exhaustive_assignment = dict(zip(exhaustive_names, exhaustive_combo)) if exhaustive_names else {}
                combinations.append({**search_assignment, **exhaustive_assignment})

    # ----------------- classify constraints for early/late evaluation ----------------- #

    # Get names of swept and derived variables
    swept_var_names_set = {name for name, _ in swept_vars}
    derived_var_names_set = {name for name, _ in derived_vars}

    # Classify constraints:
    # - early_constraints: only reference swept variables (can filter before derived eval)
    # - late_constraints: reference derived variables (must filter after derived eval)
    early_constraints: List = []
    late_constraints: List = []

    if cfg.constraints:
        early_constraints, late_constraints = classify_constraints(
            cfg.constraints,
            swept_var_names_set,
            derived_var_names_set,
        )

    # ----------------- apply early constraints to filter combinations ----------------- #

    import logging
    logger = logging.getLogger(__name__)

    early_skipped_count = 0
    if early_constraints:
        valid_combinations = []
        for combo in combinations:
            is_valid, violations = check_constraints_for_vars(combo, early_constraints)
            if is_valid:
                valid_combinations.append(combo)
            else:
                early_skipped_count += 1
                # Log at debug level (can be many)
                logger.debug(
                    f"Early constraint filter: skipping combination {combo}"
                )

        combinations = valid_combinations

        if early_skipped_count > 0:
            logger.info(
                f"Early constraint filtering: {early_skipped_count} combinations skipped "
                f"before evaluating derived expressions"
            )

    # ----------------- build ExecutionInstance objects ----------------- #

    executions: List[ExecutionInstance] = []
    exec_id = start_execution_id

    for base_vars in combinations:
        # For each script, build an ExecutionInstance
        for script_idx in range(len(cfg.scripts)):
            exec_id += 1

            exec_instance, _, _ = _create_execution_instance(
                cfg=cfg,
                base_vars=base_vars,
                execution_id=exec_id,
                script_index=script_idx,
                search_var_names=search_names,
                exhaustive_var_names=exhaustive_names,
            )
            # Note: constraint validation is ignored here because build_execution_matrix
            # handles early constraints before instance creation and late constraints
            # after all instances are built via filter_execution_matrix

            executions.append(exec_instance)

    # ----------------- apply late constraints (may use derived vars) ----------------- #

    skipped_instances: List[ExecutionInstance] = []
    if late_constraints:
        executions, skipped_instances, violations = filter_execution_matrix(
            executions,
            late_constraints,
            logger
        )

        # Log summary of late constraint filtering
        if violations:
            skipped_count = sum(1 for v in violations if v.violation_policy == "skip")
            warned_count = sum(1 for v in violations if v.violation_policy == "warn")
            logger.info(
                f"Late constraint filtering complete: {len(executions)} instances remaining. "
                f"({skipped_count} skipped, {warned_count} warned)"
            )

    return executions, skipped_instances
