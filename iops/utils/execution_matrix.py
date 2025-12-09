# iops/utils/execution_matrix.py

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Iterable, Tuple

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

    # Jinja-style expression
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


# ----------------- Cartesian sweep helpers ----------------- #

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
            range(vcfg.sweep.start, vcfg.sweep.end + (1 if vcfg.sweep.step > 0 else -1), vcfg.sweep.step)
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


# ----------------- Execution instance ----------------- #

@dataclass
class ExecutionInstance:
    """
    Fully materialized instance of a benchmark execution.
    Contains everything needed to submit/run one test.
    """
    execution_id: int

    # Benchmark-level
    benchmark_name: str
    benchmark_description: str | None
    workdir: Path
    repetitions: int | None = None
    sqlite_db: Path | None = None

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

        # Header
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

    # -------------------------------------------------
    # Optional: full verbose dump for DEBUG only
    # -------------------------------------------------

    def describe(self) -> str:
        """
        Verbose, multi-section representation for DEBUG logs.
        """
        sep_start = "#" * 80
        sep = "-" * 80
        sep_end = "#" * 80
        lines: list[str] = [
            sep_start,
            f"Execution #{self.execution_id}",
            f"Benchmark : {self.benchmark_name}",
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


# ----------------- Main builder ----------------- #

def build_execution_matrix(cfg: GenericBenchmarkConfig) -> List[ExecutionInstance]:
    """
    Build the Cartesian product of all swept variables, evaluate derived vars,
    render command/script/post/parser/output for each combination, and
    return a list of ExecutionInstance objects.
    """

    # 1) Split vars into swept and derived
    swept_vars: List[Tuple[str, VarConfig]] = []
    derived_vars: List[Tuple[str, VarConfig]] = []

    for name, v in cfg.vars.items():
        if v.sweep is not None:
            swept_vars.append((name, v))
        else:
            derived_vars.append((name, v))

    if not swept_vars:
        raise ConfigValidationError(
            "No swept variables defined – at least one 'vars.*.sweep' is required to build a matrix."
        )

    # 2) Build sweep value lists
    sweep_value_lists: List[Tuple[str, List[Any]]] = []
    for name, vcfg in swept_vars:
        values = _build_sweep_values(name, vcfg)
        if not values:
            raise ConfigValidationError(f"Variable '{name}' produced an empty sweep.")
        sweep_value_lists.append((name, values))

    # keep deterministic order
    sweep_names = [name for name, _ in sweep_value_lists]
    sweep_values_product = itertools.product(
        *[vals for _, vals in sweep_value_lists]
    )

    # 3) Build ExecutionInstance objects
    executions: List[ExecutionInstance] = []
    exec_id = 0

    for combo in sweep_values_product:
        exec_id += 1

        # Base context: benchmark + swept vars + execution_id
        var_assignment = dict(zip(sweep_names, combo))

        base_ctx: Dict[str, Any] = {
            "benchmark": {
                "name": cfg.benchmark.name,
                "description": cfg.benchmark.description,
                "workdir": str(cfg.benchmark.workdir),
            },
            "workdir": str(cfg.benchmark.workdir),
            "execution_id": exec_id,
            **var_assignment,
        }

        # 3.1) Compute derived vars (expr)
        derived_values: Dict[str, Any] = {}
        for name, vcfg in derived_vars:
            if not vcfg.expr:
                raise ConfigValidationError(
                    f"Derived variable '{name}' must define 'expr'."
                )
            value = _eval_expr(vcfg.expr, vcfg.type, {**base_ctx, **derived_values})
            derived_values[name] = value

        # Merge all vars into one mapping
        all_vars = {**var_assignment, **derived_values}

        # Updated context including derived vars
        full_ctx_for_expr = {**base_ctx, **derived_values}

        # 3.2) Render command template with current context
        command_str = _render_template(cfg.command.template, full_ctx_for_expr)

        # 3.3) Render command env with current context
        env_rendered: Dict[str, str] = {}
        for k, v in cfg.command.env.items():
            if isinstance(v, str):
                env_rendered[k] = _render_template(v, full_ctx_for_expr)
            else:
                env_rendered[k] = str(v)

        # 3.4) Render metadata
        metadata_rendered: Dict[str, Any] = {}
        for k, v in cfg.command.metadata.items():
            if isinstance(v, str):
                metadata_rendered[k] = _render_template(v, full_ctx_for_expr)
            else:
                metadata_rendered[k] = v

        # 3.5) Render output CSV path for this execution
        csv_path_str = _render_template(cfg.output.csv.path, full_ctx_for_expr)
        csv_path = Path(csv_path_str)

        # 3.6) For each script, build an ExecutionInstance
        #      (one execution per script per combination)
        for script_cfg in cfg.scripts:
            # context for script: add 'command' object so {{ command.template }} works
            command_obj = type("CmdObj", (), {})()
            setattr(command_obj, "template", command_str)

            script_ctx = {
                **full_ctx_for_expr,
                "vars": all_vars,
                "command": command_obj,          # <-- fixes 'command is undefined'
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
                # We might need to render the 'file' field
                parser_file_rendered = _render_template(
                    script_cfg.parser.file, script_ctx
                )

                # metrics are usually static; copy them as-is
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
                benchmark_name=cfg.benchmark.name,
                benchmark_description=cfg.benchmark.description,
                workdir=cfg.benchmark.workdir,
                repetitions=cfg.benchmark.repetitions,
                sqlite_db=cfg.benchmark.sqlite_db,
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
