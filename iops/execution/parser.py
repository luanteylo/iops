from __future__ import annotations

import os
from typing import Any, Dict, Callable
import traceback
import ast
from iops.execution.matrix import ExecutionInstance


class ParserError(Exception): ...
class ParserScriptError(ParserError): ...
class ParserContractError(ParserError): ...



def _build_parse_fn(parser_script: str, context: Dict[str, Any] | None = None):
    """
    Build parse(file_path) from embedded script.

    Args:
        parser_script: The parser script code defining a parse() function
        context: Optional dict of variables to inject into the script's namespace.
                 These will be available as global variables in the parser script.
                 Typically includes: vars, env, execution_id, execution_dir, workdir, repetition, repetitions
    """
    ns: Dict[str, Any] = {"__builtins__": __builtins__}

    # Inject context variables into the namespace
    if context:
        ns.update(context)

    try:
        code = compile(parser_script, "<parser_script>", "exec")
        exec(code, ns, ns)
    except Exception as e:
        raise ParserScriptError(
            f"Failed to load parser_script: {e}\n{traceback.format_exc()}"
        ) from e

    fn = ns.get("parse")
    if not callable(fn):
        raise ParserContractError(
            "parser_script must define a callable function:\n"
            "  def parse(file_path: str): ..."
        )

    return fn


def parse_metrics_from_execution(test: ExecutionInstance) -> Dict[str, Any]:
    """
    Uses test.parser (rendered) and maps returned list values by metric order.
    Returns: {"write_bandwidth": ..., "iops": ..., "_raw": [...]}

    The parser script has access to the following global variables:
        - vars: Dict of all execution variables (e.g., vars["nodes"], vars["block_size"])
        - env: Dict of rendered command.env variables
        - os_env: Dict of system environment variables (e.g., os_env["PATH"])
        - execution_id: The execution ID string
        - execution_dir: The execution directory path (as string)
        - workdir: The root working directory path (as string)
        - repetition: The current repetition number
        - repetitions: Total number of repetitions
    """
    parser = test.parser
    if parser is None:
        raise ParserContractError("ExecutionInstance has no parser configured.")

    if not parser.file:
        raise ParserContractError("parser.file is empty after rendering.")

    # Note: parser_script and metrics validation is handled by loader.py
    metric_names = [m.name for m in parser.metrics]

    # Build context with execution variables for the parser script
    context = {
        "vars": dict(test.vars),
        "env": dict(test.env),
        "os_env": dict(os.environ),
        "execution_id": test.execution_id,
        "execution_dir": str(test.execution_dir) if test.execution_dir else None,
        "workdir": str(test.workdir) if test.workdir else None,
        "repetition": test.repetition,
        "repetitions": test.repetitions,
    }

    parse_fn = _build_parse_fn(parser.parser_script, context)

    try:
        metrics = parse_fn(parser.file)
    except Exception as e:
        raise ParserScriptError(
            f"parse() failed for file '{parser.file}': {e}\n{traceback.format_exc()}"
        ) from e

    if not isinstance(metrics, dict):
        raise ParserContractError(
            f"parse() must return dict, got {type(metrics).__name__}."
        )

    # Validate returned metrics
    for name in metric_names:
        if name not in metrics:
            raise ParserContractError(
                f"parse() result missing metric '{name}'."
            )

    
    return {"metrics": metrics}