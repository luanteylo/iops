from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

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
from iops.constraints.evaluator import filter_execution_matrix


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
    """
    if vcfg.sweep is None:
        raise ConfigValidationError(
            f"Variable '{name}' has no sweep defined but is treated as swept."
        )

    mode = vcfg.sweep.mode
    if mode == "range":
        if vcfg.sweep.start is None or vcfg.sweep.end is None or vcfg.sweep.step is None:
            raise ConfigValidationError(
                f"Variable '{name}' with mode 'range' must have start, end, step."
            )

        if vcfg.sweep.step == 0:
            raise ConfigValidationError(
                f"Variable '{name}' with mode 'range' cannot have step=0"
            )

        values = list(
            range(
                vcfg.sweep.start,
                vcfg.sweep.end + (1 if vcfg.sweep.step > 0 else -1),
                vcfg.sweep.step,
            )
        )
        return [_cast_value(vcfg.type, v) for v in values]

    elif mode == "list":
        if not vcfg.sweep.values:
            raise ConfigValidationError(
                f"Variable '{name}' with mode 'list' must have non-empty 'values'."
            )
        return [_cast_value(vcfg.type, v) for v in vcfg.sweep.values]

    else:
        raise ConfigValidationError(
            f"Variable '{name}' has invalid sweep mode: {mode}"
        )


def _choose_default_value(name: str, vcfg: VarConfig) -> Any:
    """
    Choose a 'default' scalar value for a swept variable when it is not swept
    in the current round. Heuristic:

    - if sweep.mode == 'list': use first element
    - if sweep.mode == 'range': use 'start'
    """
    if vcfg.sweep is None:
        raise ConfigValidationError(
            f"Variable '{name}' has no sweep; cannot choose default."
        )

    mode = vcfg.sweep.mode
    if mode == "list":
        if not vcfg.sweep.values:
            raise ConfigValidationError(
                f"Variable '{name}' with mode 'list' has empty 'values'; cannot choose default."
            )
        return _cast_value(vcfg.type, vcfg.sweep.values[0])

    if mode == "range":
        if vcfg.sweep.start is None:
            raise ConfigValidationError(
                f"Variable '{name}' with mode 'range' has no 'start'; cannot choose default."
            )
        return _cast_value(vcfg.type, vcfg.sweep.start)

    raise ConfigValidationError(
        f"Variable '{name}' has invalid sweep mode '{mode}' when choosing default."
    )


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
      and all properties (command, env, script_text, derived vars, etc.)
      will re-render using the current state.
    """

    execution_id: int

    # Optional: per-instance default repetition index (0- or 1-based, as you prefer)
    # The planner can still override via metadata["repetition"].
    repetition: int = 0

    # Round-level metadata
    round_name: Optional[str] = None
    round_index: Optional[int] = None
    repetitions: int = 1
    execution_dir : Optional[Path] = None
    
    

    search_metric: Optional[str] = None
    search_objective: Optional[str] = None

    # Benchmark-level
    benchmark_name: str = ""
    benchmark_description: Optional[str] = None
    workdir: Optional[Path] = None

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

    # Optional: DB path (if you want it here)
    sqlite_db: Path | None = None

    # ---------- Template fields (stored from cfg, rendered lazily) ---------- #

    # Command template and env/metadata templates
    command_template: str = ""
    env_templates: Dict[str, Any] = field(default_factory=dict)
    metadata_templates: Dict[str, Any] = field(default_factory=dict)

    # Script metadata
    script_name: str = ""
    script_template: str = ""
    submit_cmd_template: str = ""
    script_file : Optional[Path] = None

    # Optional post-processing script template
    post_script_template: str | None = None
    post_script_file : Optional[Path] = None

    # Parser template (with possibly templated .file)
    parser_template: ParserConfig | None = None

    # Output configuration (template + selection)
    output_path_template: str | None = None
    output_type: str = "parquet"   # csv | parquet | sqlite
    output_mode: str = "append"    # append | overwrite
    output_table: str = "results"  # sqlite only

    output_include: List[str] = field(default_factory=list)
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
            "execution_dir": str(self.execution_dir),
            "execution_id": self.execution_id,
            "repetitions": self.repetitions,
            "round_name": self.round_name,
            "round_index": self.round_index,
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
        for name, (expr, vartype) in self.derived_var_cfgs.items():
            if not expr:
                raise ConfigValidationError(
                    f"Derived variable '{name}' must define 'expr'."
                )
            val = _eval_expr(expr, vartype, {**ctx0, **all_vars})
            all_vars[name] = val

        return all_vars

    def _render_context(self) -> Dict[str, Any]:
        """
        Build the full context used for all Jinja rendering.

        This context includes:
        - benchmark.* information
        - workdir
        - execution_id
        - repetitions
        - round_name / round_index
        - flattened vars ({{ my_var }})
        - vars mapping ({{ vars.my_var }})
        - metadata
        - repetition (from metadata or instance field)
        """
        ctx0 = self._base_context_for_vars()
        all_vars = self._compute_all_vars()

        ctx: Dict[str, Any] = {
            **ctx0,
            **all_vars,
        }
        ctx["vars"] = all_vars

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
    def command_metadata(self) -> Dict[str, Any]:
        """
        Render metadata from metadata_templates and merge with runtime metadata.
        Runtime metadata overwrites template-based keys.
        """
        ctx = self._render_context()
        rendered: Dict[str, Any] = {}
        for k, v in self.metadata_templates.items():
            if isinstance(v, str):
                rendered[k] = _render_template(v, ctx)
            else:
                rendered[k] = v
        # runtime metadata has priority
        rendered.update(self.metadata)
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
    def submit_cmd(self) -> str:
        """
        Render the submit command (e.g., sbatch ...) if templated.
        """
        if not self.submit_cmd_template:
            return ""
        ctx = self._render_context()
        return _render_template(self.submit_cmd_template, ctx)

    @property
    def script_text(self) -> str:
        """
        Render the main script text from script_template, using:
        - {{ vars.* }}
        - {{ command }}
        - {{ command_env }}
        - {{ command_metadata }}
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
            "command_metadata": self.command_metadata,
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
            "command_metadata": self.command_metadata,
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
        if self.round_name:
            return f"{self.benchmark_name}[{self.round_name}]#{self.execution_id}"
        return f"{self.benchmark_name}#{self.execution_id}"

    def __str__(self) -> str:
        """
        Human-friendly summary of this execution.
        Suitable for INFO-level logs.
        """
        lines: list[str] = []

        lines.append(70 * "-")

        # Header
        if self.round_name is not None:
            lines.append(
                f"Execution #{self.execution_id} — {self.benchmark_name} "
                f"(round={self.round_name})"
                f"(repetition={self.repetition})"
            )
        else:
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
            f"(submit={self.submit_cmd})"
            f"(file={self.script_file})"
        )
        # post script
        if self.post_script_template:
            lines.append(f"Post-script: {self.post_script_file}")
            

        # Repetitions / search
        lines.append(f"Repeats: {self.repetitions}")
        if self.search_metric and self.search_objective:
            lines.append(f"Search: {self.search_objective} {self.search_metric}")

        # Metadata (rendered)
        effective_metadata = self.command_metadata
        if effective_metadata:
            meta_items = ", ".join(f"{k}={v!r}" for k, v in effective_metadata.items())
            lines.append(f"Metadata: {meta_items}")

        # Output
        if self.output_path:
            extra = f", table={self.output_table}" if self.output_type == "sqlite" else ""
            lines.append(
                f"Output: type={self.output_type}, mode={self.output_mode}, path={self.output_path}{extra}"
            )
            if self.output_include:
                lines.append(f"Output fields (include): {', '.join(self.output_include)}")
            elif self.output_exclude:
                lines.append(f"Output fields (exclude): {', '.join(self.output_exclude)}")
            else:
                lines.append("Output fields: default (everything)")


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
        Verbose, multi-section representation for DEBUG logs.
        Everything rendered lazily with current state.
        """
        sep_start = sep_end = "#" * 80
        sep = "-" * 80
        lines: list[str] = [
            sep_start,
            f"Execution #{self.execution_id}",
            f"Benchmark : {self.benchmark_name}",
            f"Round     : {self.round_name} (idx={self.round_index})",
            f"Workdir   : {self.workdir}",
            f"Exeucution Dir: {self.execution_dir}",
            f"Repetitions: {self.repetition}/{self.repetitions}",            
            f"SQLite DB : {self.sqlite_db}",
            sep,
            "Variables:",
        ]

        vars_map = self.vars
        for k in sorted(vars_map):
            lines.append(f"  {k} = {vars_map[k]!r}")

        lines.extend([
            sep,
            "Command:",
            self.command,
            sep,
            f"Script ({self.script_name}):",
            self.script_text,
        ])

        if self.post_script:
            lines.extend([sep, "Post-script:", self.post_script])

        env_rendered = self.env
        if env_rendered:
            lines.extend([sep, "Environment:"])
            for k, v in env_rendered.items():
                lines.append(f"  {k}={v}")

        effective_metadata = self.command_metadata
        if effective_metadata:
            lines.extend([sep, "Metadata:"])
            for k, v in effective_metadata.items():
                lines.append(f"  {k}: {v}")

        if self.output_path:
            lines.extend([
                sep,
                f"Output type : {self.output_type}",
                f"Output mode : {self.output_mode}",
                f"Output path : {self.output_path}",
            ])
            if self.output_type == "sqlite":
                lines.append(f"Output table: {self.output_table}")

            if self.output_include:
                lines.append(f"Fields (include): {', '.join(self.output_include)}")
            elif self.output_exclude:
                lines.append(f"Fields (exclude): {', '.join(self.output_exclude)}")
            else:
                lines.append("Fields: default (everything)")


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
                lines.append(f"  parser_script: {parser_obj.parser_script}")

        lines.append(sep_end)

        return "\n".join(lines)


# ----------------- Round selection ----------------- #

def _select_round(
    cfg: GenericBenchmarkConfig,
    round_name: Optional[str],
) -> Tuple[Optional[Any], Optional[int]]:
    """
    Helper to pick a round from cfg.rounds.

    Returns:
        (round_cfg, round_index) or (None, None) if no rounds are defined.
    """
    rounds = getattr(cfg, "rounds", None)
    if not rounds:
        return None, None

    if round_name is None:
        if len(rounds) == 1:
            return rounds[0], 0
        raise ConfigValidationError(
            f"{len(rounds)} rounds defined in YAML; please specify round_name"
        )

    for idx, r in enumerate(rounds):
        if r.name == round_name:
            return r, idx

    raise ConfigValidationError(f"Round '{round_name}' not found in configuration")


# ----------------- Main builder ----------------- #

def build_execution_matrix(
    cfg: GenericBenchmarkConfig,
    round_name: Optional[str] = None,
    defaults: Optional[Dict[str, Any]] = None,
    start_execution_id: int = 0,
) -> List[ExecutionInstance]:
    """
    Build the Cartesian product of swept variables for a given round
    and return a list of ExecutionInstance objects.

    IMPORTANT:
    - No Jinja rendering is done here.
      All templates (command, env, metadata, scripts, parser, CSV path,
      and derived variable expressions) are stored in the ExecutionInstance
      and rendered lazily via @property.

    Behaviour:

    - If cfg.rounds is defined:
        * You MUST specify round_name if there is more than one round.
        * Only variables listed in that round's `sweep_vars` are swept.
        * Non-swept vars:
            - if in round.fixed_overrides -> use that value;
            - elif in `defaults` (from previous rounds) -> use that;
            - else -> use a default taken from the var sweep
                    (first list element or start of range).
        * repetitions for each ExecutionInstance is taken from round.repetitions.

    - If cfg.rounds is NOT defined:
        * Legacy behaviour: sweep over all vars that have a `sweep` defined.
        * All sweeps are done in a single implicit "round".
        * repetitions is 1 by default (or benchmark.repetitions if present).
    """

    # ----------------- choose round (if any) ----------------- #
    round_cfg, round_idx = _select_round(cfg, round_name)

    if defaults is None:
        defaults = {}

    # ----------------- split vars ----------------- #
    swept_vars: List[Tuple[str, VarConfig]] = []
    derived_vars: List[Tuple[str, VarConfig]] = []
    fixed_scalars: Dict[str, Any] = {}

    # Always use global repetitions (not per-round)
    repetitions = max(1, int(getattr(cfg.benchmark, "repetitions", 1) or 1))

    # Round-specific parameters
    if round_cfg is not None:
        sweep_names_round = set(round_cfg.sweep_vars or [])
        fixed_overrides = getattr(round_cfg, "fixed_overrides", {}) or {}
    else:
        sweep_names_round = None
        fixed_overrides = {}

    # Get exhaustive vars from benchmark config
    exhaustive_var_names = set(cfg.benchmark.exhaustive_vars or [])

    # Classify variables:
    for name, v in cfg.vars.items():
        # Derived variable: has expr and no sweep
        if v.sweep is None and v.expr is not None:
            derived_vars.append((name, v))
            continue

        # Swept in this round:
        if sweep_names_round is None or name in sweep_names_round:
            if v.sweep is None:
                raise ConfigValidationError(
                    f"Variable '{name}' is in sweep_vars but has no 'sweep' defined."
                )
            swept_vars.append((name, v))
        else:
            # Not swept this round: choose a scalar value
            if name in fixed_overrides:
                val = _cast_value(v.type, fixed_overrides[name])
            elif name in defaults:
                val = _cast_value(v.type, defaults[name])
            else:
                # Use a default from the sweep definition
                if v.sweep is None:
                    raise ConfigValidationError(
                        f"Variable '{name}' is neither swept nor derived; "
                        "must have either 'sweep' or 'expr' in YAML."
                    )
                val = _choose_default_value(name, v)
            fixed_scalars[name] = val

    if not swept_vars:
        raise ConfigValidationError(
            "No swept variables defined for this round – at least one "
            "'vars.*.sweep' and membership in sweep_vars is required."
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
                f"Variable '{name}' is listed in exhaustive_vars but is not swept in this round."
            )

    # If no search vars (all swept vars are exhaustive), treat as normal exhaustive search
    if not search_vars:
        search_vars = exhaustive_swept_vars
        exhaustive_swept_vars = []

    # ----------------- build sweep products ----------------- #

    # Build search space (variables that the planner optimizes over)
    search_value_lists: List[Tuple[str, List[Any]]] = []
    for name, vcfg in search_vars:
        values = _build_sweep_values(name, vcfg)
        if not values:
            raise ConfigValidationError(f"Variable '{name}' produced an empty sweep.")
        search_value_lists.append((name, values))

    search_names = [name for name, _ in search_value_lists]
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

    exhaustive_names = [name for name, _ in exhaustive_value_lists]

    # If there are exhaustive vars, build their product; otherwise single empty combination
    if exhaustive_value_lists:
        exhaustive_values_product = list(itertools.product(
            *[vals for _, vals in exhaustive_value_lists]
        ))
    else:
        exhaustive_values_product = [()]  # Single empty combination

    # ----------------- build ExecutionInstance objects ----------------- #

    executions: List[ExecutionInstance] = []
    exec_id = start_execution_id

    # Search metadata (per round)
    search_metric: Optional[str] = None
    search_objective: Optional[str] = None
    if round_cfg is not None and getattr(round_cfg, "search", None) is not None:
        search_metric = round_cfg.search.metric
        search_objective = round_cfg.search.objective

    # Pre-pack derived var cfgs as name -> (expr, type)
    derived_var_cfgs: Dict[str, Tuple[str, str]] = {}
    for name, vcfg in derived_vars:
        if not vcfg.expr:
            raise ConfigValidationError(
                f"Derived variable '{name}' must define 'expr'."
            )
        derived_var_cfgs[name] = (vcfg.expr, vcfg.type)

    # Command/env/metadata templates from cfg
    command_template = cfg.command.template
    env_templates = dict(cfg.command.env) if cfg.command.env else {}
    metadata_templates = dict(cfg.command.metadata) if cfg.command.metadata else {}


    # Output sink templates
    output_path_template = cfg.output.sink.path
    output_type = cfg.output.sink.type
    output_mode = cfg.output.sink.mode
    output_table = cfg.output.sink.table
    output_include = list(cfg.output.sink.include)
    output_exclude = list(cfg.output.sink.exclude)

    # Build execution instances as cross-product of search and exhaustive spaces
    for search_combo in search_values_product:
        # Search vars assignment
        search_assignment = dict(zip(search_names, search_combo))

        # For each search point, expand with all exhaustive var combinations
        for exhaustive_combo in exhaustive_values_product:
            # Exhaustive vars assignment (empty dict if no exhaustive vars)
            exhaustive_assignment = dict(zip(exhaustive_names, exhaustive_combo)) if exhaustive_names else {}

            # Combine: fixed scalars + search vars + exhaustive vars
            base_vars = {**fixed_scalars, **search_assignment, **exhaustive_assignment}

            # For each script, build an ExecutionInstance with templates and var configs
            for script_cfg in cfg.scripts:
                exec_id += 1

                # Script templates
                script_template = script_cfg.script_template
                submit_cmd_template = script_cfg.submit

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

                exec_instance = ExecutionInstance(
                    execution_id=exec_id,
                    repetition=0,  # planner will set metadata["repetition"] per run
                    round_name=getattr(round_cfg, "name", None) if round_cfg else None,
                    round_index=round_idx,
                    repetitions=repetitions,
                    search_metric=search_metric,
                    search_objective=search_objective,
                    benchmark_name=cfg.benchmark.name,
                    benchmark_description=cfg.benchmark.description,
                    workdir=cfg.benchmark.workdir,
                    sqlite_db=getattr(cfg.benchmark, "sqlite_db", None),
                    base_vars=base_vars,
                    derived_var_cfgs=derived_var_cfgs,
                    exhaustive_var_names=exhaustive_names,
                    search_var_names=search_names,
                    # runtime metadata starts empty; planner may fill it (e.g., repetition, metrics)
                    metadata={},
                    command_template=command_template,
                    env_templates=env_templates,
                    metadata_templates=metadata_templates,
                    script_name=script_cfg.name,
                    script_template=script_template,
                    submit_cmd_template=submit_cmd_template,
                    post_script_template=post_script_template,
                    parser_template=parser_template,
                    output_path_template=output_path_template,
                    output_type=output_type,
                    output_mode=output_mode,
                    output_table=output_table,
                    output_include=output_include,
                    output_exclude=output_exclude,
                )

                executions.append(exec_instance)

    # Apply constraints if defined
    if cfg.constraints:
        import logging
        logger = logging.getLogger(__name__)

        executions, violations = filter_execution_matrix(
            executions,
            cfg.constraints,
            logger
        )

        # Log summary of constraint filtering
        if violations:
            skipped = sum(1 for v in violations if v.violation_policy == "skip")
            warned = sum(1 for v in violations if v.violation_policy == "warn")
            logger.info(
                f"Constraint filtering complete: {len(executions)} instances remaining after filtering. "
                f"({skipped} skipped, {warned} warned)"
            )

    return executions
