from __future__ import annotations


from curses import raw
from typing import Any, Dict, Callable
import traceback
import ast
from iops.execution.matrix import ExecutionInstance


class ParserError(Exception): ...
class ParserScriptError(ParserError): ...
class ParserContractError(ParserError): ...



def _build_parse_fn(parser_script: str):
    """
    Build parse(file_path) from embedded script.
    """
    ns: Dict[str, Any] = {"__builtins__": __builtins__}

    try:
        code = compile(parser_script, "<parser_script>", "exec")
        exec(code, ns, ns)   # <-- THIS IS THE KEY FIX
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
    """
    parser = test.parser
    if parser is None:
        raise ParserContractError("ExecutionInstance has no parser configured.")

    if not parser.file:
        raise ParserContractError("parser.file is empty after rendering.")

    if not parser.parser_script:
        raise ParserContractError("parser.parser_script is empty.")

    metric_names = [m.name for m in (parser.metrics or [])]
    if not metric_names:
        raise ParserContractError("parser.metrics is empty.")

    parse_fn = _build_parse_fn(parser.parser_script)

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