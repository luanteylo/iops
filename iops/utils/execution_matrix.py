# iops/utils/execution_matrix.py

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

import itertools
import math

from jinja2 import Environment, StrictUndefined

from iops.utils.generic_config import (
    GenericBenchmarkConfig,
    VarConfig,
    ParserConfig,
    MetricConfig,
    ConfigValidationError,
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
    Contains everything needed to submit/run one test.
    """
    execution_id: int

    # Round-level metadata
    round_name: Optional[str] = None
    round_index: Optional[int] = None
    repetitions: int = 1
    search_metric: Optional[str] = None
    search_objective: Optional[str] = None

    # Benchmark-level
    benchmark_name: str = ""
    benchmark_description: str | None = None
    workdir: Path = Path(".")

    # Variables (swept + derived)
    vars: Dict[str, Any] = field(default_factory=dict)

    # Command (already rendered)
    command: str = ""

    # Environment for this command (already rendered)
    env: Dict[str, str] = field(default_factory=dict)

    # Script metadata
    script_name: str = ""
    script_mode: str = ""
    submit_cmd: str = ""
    script_text: str = ""

    # Optional post-processing
    post_script: str | None = None

    # Parser information (per execution)
    parser: ParserConfig | None = None

    # Command metadata (already rendered)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Output configuration (per execution)
    output_csv_path: Path | None = None
    output_csv_fields: List[str] = field(default_factory=list)

    # Optional: DB path (if you want it here)
    sqlite_db: Path | None = None

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

        # Header
        if self.round_name is not None:
            lines.append(
                f"Execution #{self.execution_id} — {self.benchmark_name} "
                f"(round={self.round_name})"
            )
        else:
            lines.append(f"Execution #{self.execution_id} — {self.benchmark_name}")

        # Vars (sorted for stability)
        if self.vars:
            vars_str = ", ".join(
                f"{k}={self.vars[k]!r}"
                for k in sorted(self.vars)
            )
            lines.append(f"  Vars     : {vars_str}")

        # Command (compact)
        if self.command:
            cmd = self.command.replace("\n", " ").strip()
            if len(cmd) > 120:
                cmd = cmd[:117] + "..."
            lines.append(f"  Command  : {cmd}")

        # Script info
        lines.append(
            f"  Script   : {self.script_name} "
            f"(mode={self.script_mode}, submit={self.submit_cmd})"
        )

        # Repetitions / search
        lines.append(f"  Repeats  : {self.repetitions}")
        if self.search_metric and self.search_objective:
            lines.append(
                f"  Search   : {self.search_objective} {self.search_metric}"
            )

        # Output
        if self.output_csv_path:
            lines.append(f"  Output   : {self.output_csv_path}")

        # Parser
        if self.parser:
            metric_names = [m.name for m in self.parser.metrics]
            metrics_str = ", ".join(metric_names) if metric_names else "custom"
            lines.append(
                f"  Parser   : type={self.parser.type}, metrics={metrics_str}"
            )

        return "\n".join(lines)

    def describe(self) -> str:
        """
        Verbose, multi-section representation for DEBUG logs.
        """
        sep_start = "#" * 80
        sep = "-" * 80
        lines: list[str] = [
            sep_start,
            f"Execution #{self.execution_id}",
            f"Benchmark : {self.benchmark_name}",
            f"Round     : {self.round_name} (idx={self.round_index})",
            f"Workdir   : {self.workdir}",
            f"Repetitions: {self.repetitions}",
            f"SQLite DB : {self.sqlite_db}",
            sep,
            "Variables:",
        ]

        for k in sorted(self.vars):
            lines.append(f"  {k} = {self.vars[k]!r}")

        lines.extend([
            sep,
            "Command:",
            self.command,
            sep,
            f"Script ({self.script_name}, mode={self.script_mode}):",
            self.script_text,
        ])

        if self.post_script:
            lines.extend([sep, "Post-script:", self.post_script])

        if self.env:
            lines.extend([sep, "Environment:"])
            for k, v in self.env.items():
                lines.append(f"  {k}={v}")

        if self.metadata:
            lines.extend([sep, "Metadata:"])
            for k, v in self.metadata.items():
                lines.append(f"  {k}: {v}")

        if self.output_csv_path:
            lines.extend([
                sep,
                f"Output CSV : {self.output_csv_path}",
                f"Fields     : {', '.join(self.output_csv_fields)}",
            ])

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
    Build the Cartesian product of swept variables for a given round,
    evaluate derived vars, render command/script/post/parser/output
    for each combination, and return a list of ExecutionInstance objects.

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

    # Round-specific parameters
    if round_cfg is not None:
        sweep_names_round = set(round_cfg.sweep_vars or [])
        fixed_overrides = getattr(round_cfg, "fixed_overrides", {}) or {}
        repetitions = max(1, getattr(round_cfg, "repetitions", 1))
    else:
        sweep_names_round = None
        fixed_overrides = {}
        # legacy: try benchmark.repetitions if it exists
        repetitions = max(
            1,
            int(getattr(cfg.benchmark, "repetitions", 1) or 1),
        )

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

    # ----------------- build sweep product ----------------- #

    sweep_value_lists: List[Tuple[str, List[Any]]] = []
    for name, vcfg in swept_vars:
        values = _build_sweep_values(name, vcfg)
        if not values:
            raise ConfigValidationError(f"Variable '{name}' produced an empty sweep.")
        sweep_value_lists.append((name, values))

    sweep_names = [name for name, _ in sweep_value_lists]
    sweep_values_product = itertools.product(
        *[vals for _, vals in sweep_value_lists]
    )

    # ----------------- build ExecutionInstance objects ----------------- #

    executions: List[ExecutionInstance] = []
    exec_id = start_execution_id

    # Search metadata (per round)
    search_metric: Optional[str] = None
    search_objective: Optional[str] = None
    if round_cfg is not None and getattr(round_cfg, "search", None) is not None:
        search_metric = round_cfg.search.metric
        search_objective = round_cfg.search.objective

    for combo in sweep_values_product:
        exec_id += 1

        # Swept vars assignment
        swept_assignment = dict(zip(sweep_names, combo))

        # Combine with fixed scalar vars
        all_scalar_base = {**fixed_scalars, **swept_assignment}

        # Base context: benchmark + execution_id + scalar vars
        base_ctx: Dict[str, Any] = {
            "benchmark": {
                "name": cfg.benchmark.name,
                "description": cfg.benchmark.description,
                "workdir": str(cfg.benchmark.workdir),
            },
            "workdir": str(cfg.benchmark.workdir),
            "execution_id": exec_id,
            **all_scalar_base,
        }

        # 1) Compute derived vars
        derived_values: Dict[str, Any] = {}
        for name, vcfg in derived_vars:
            if not vcfg.expr:
                raise ConfigValidationError(
                    f"Derived variable '{name}' must define 'expr'."
                )
            value = _eval_expr(vcfg.expr, vcfg.type, {**base_ctx, **derived_values})
            derived_values[name] = value

        # Merge all vars into one mapping
        all_vars = {**all_scalar_base, **derived_values}

        # Updated context including derived vars
        full_ctx = {**base_ctx, **derived_values}

        # 2) Render command template
        command_str = _render_template(cfg.command.template, full_ctx)

        # 3) Render command env
        env_rendered: Dict[str, str] = {}
        for k, v in cfg.command.env.items():
            if isinstance(v, str):
                env_rendered[k] = _render_template(v, full_ctx)
            else:
                env_rendered[k] = str(v)

        # 4) Render metadata
        metadata_rendered: Dict[str, Any] = {}
        for k, v in cfg.command.metadata.items():
            if isinstance(v, str):
                metadata_rendered[k] = _render_template(v, full_ctx)
            else:
                metadata_rendered[k] = v

        # 5) Render output CSV path
        csv_path_str = _render_template(cfg.output.csv.path, full_ctx)
        csv_path = Path(csv_path_str)

        # 6) For each script, build an ExecutionInstance
        for script_cfg in cfg.scripts:
            # provide 'command.template' to the script
            command_obj = type("CmdObj", (), {})()
            setattr(command_obj, "template", command_str)

            script_ctx = {
                **full_ctx,
                "vars": all_vars,
                "command": command_obj,
                "command_env": env_rendered,
                "command_metadata": metadata_rendered,
            }

            # Script text
            script_text = _render_template(script_cfg.script_template, script_ctx)

            # Optional post script
            post_script_rendered = None
            if script_cfg.post and script_cfg.post.script:
                post_script_rendered = _render_template(
                    script_cfg.post.script, script_ctx
                )

            # Optional parser
            parser_instance: ParserConfig | None = None
            if script_cfg.parser is not None:
                parser_file_rendered = _render_template(
                    script_cfg.parser.file, script_ctx
                )

                metrics: List[MetricConfig] = []
                for m in script_cfg.parser.metrics:
                    metrics.append(MetricConfig(name=m.name, path=m.path))

                parser_instance = ParserConfig(
                    type=script_cfg.parser.type,
                    file=parser_file_rendered,
                    metrics=metrics,
                    parser_script=script_cfg.parser.parser_script,
                )

            exec_instance = ExecutionInstance(
                execution_id=exec_id,
                round_name=getattr(round_cfg, "name", None) if round_cfg else None,
                round_index=round_idx,
                repetitions=repetitions,
                search_metric=search_metric,
                search_objective=search_objective,
                benchmark_name=cfg.benchmark.name,
                benchmark_description=cfg.benchmark.description,
                workdir=cfg.benchmark.workdir,
                sqlite_db=getattr(cfg.benchmark, "sqlite_db", None),
                vars=all_vars,
                command=command_str,
                env=env_rendered,
                script_name=script_cfg.name,
                script_mode=script_cfg.mode,
                submit_cmd=script_cfg.submit,
                script_text=script_text,
                post_script=post_script_rendered,
                parser=parser_instance,
                metadata=metadata_rendered,
                output_csv_path=csv_path,
                output_csv_fields=list(cfg.output.csv.include),
            )

            executions.append(exec_instance)

    return executions
