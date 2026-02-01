from __future__ import annotations

import os
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Any, Dict, Callable, Optional, Tuple
import traceback
import ast
from iops.execution.matrix import ExecutionInstance


class ParserError(Exception): ...
class ParserScriptError(ParserError): ...
class ParserContractError(ParserError): ...



def _build_parse_fn(
    parser_script: str,
    context: Dict[str, Any] | None = None,
    stdout_buffer: Optional[StringIO] = None,
    stderr_buffer: Optional[StringIO] = None,
):
    """
    Build parse(file_path) from embedded script.

    Args:
        parser_script: The parser script code defining a parse() function
        context: Optional dict of variables to inject into the script's namespace.
                 These will be available as global variables in the parser script.
                 Typically includes: vars, env, execution_id, execution_dir, workdir, repetition, repetitions
        stdout_buffer: Optional StringIO to capture stdout during compilation
        stderr_buffer: Optional StringIO to capture stderr during compilation
    """
    ns: Dict[str, Any] = {"__builtins__": __builtins__}

    # Inject context variables into the namespace
    if context:
        ns.update(context)

    try:
        code = compile(parser_script, "<parser_script>", "exec")
        # Execute with optional output capture
        if stdout_buffer is not None and stderr_buffer is not None:
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                exec(code, ns, ns)
        else:
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


def _write_parser_output(
    execution_dir: Optional[Path],
    stdout_content: str,
    stderr_content: str,
) -> Tuple[Optional[Path], Optional[Path]]:
    """Write parser stdout/stderr to files if there's content."""
    if execution_dir is None:
        return None, None

    stdout_path = None
    stderr_path = None

    if stdout_content:
        stdout_path = execution_dir / "parser_stdout"
        stdout_path.write_text(stdout_content, encoding="utf-8", errors="replace")

    if stderr_content:
        stderr_path = execution_dir / "parser_stderr"
        stderr_path.write_text(stderr_content, encoding="utf-8", errors="replace")

    return stdout_path, stderr_path


def parse_metrics_from_execution(test: ExecutionInstance) -> Dict[str, Any]:
    """
    Uses test.parser (rendered) and maps returned list values by metric order.
    Returns: {"write_bandwidth": ..., "iops": ..., "_raw": [...]}

    Parser stdout/stderr are captured and written to parser_stdout and parser_stderr
    files in the execution directory.

    The parser script has access to the following global variables:
        - vars: Dict of all execution variables (e.g., vars["nodes"], vars["block_size"])
        - env: Dict of rendered command.env variables
        - os_env: Dict of system environment variables (e.g., os_env["PATH"])
        - execution_id: The execution ID string
        - execution_dir: The execution directory path (as string)
        - workdir: The root working directory path (as string)
        - log_dir: The logs directory path (as string)
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
        "log_dir": str(test.log_dir) if test.log_dir else None,
        "repetition": test.repetition,
        "repetitions": test.repetitions,
    }

    # Capture stdout/stderr during parser execution
    stdout_buffer = StringIO()
    stderr_buffer = StringIO()

    try:
        parse_fn = _build_parse_fn(
            parser.parser_script,
            context,
            stdout_buffer=stdout_buffer,
            stderr_buffer=stderr_buffer,
        )

        # Also capture output during parse() call
        with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
            metrics = parse_fn(parser.file)

    except Exception as e:
        # Write captured output and error traceback to file (helps debugging)
        error_details = f"parse() failed for file '{parser.file}': {e}\n{traceback.format_exc()}"
        stderr_content = stderr_buffer.getvalue()
        if stderr_content:
            stderr_content += "\n\n--- Error Traceback ---\n" + error_details
        else:
            stderr_content = error_details

        _, stderr_path = _write_parser_output(
            test.execution_dir,
            stdout_buffer.getvalue(),
            stderr_content,
        )

        # Store path in metadata so executor can reference it
        if stderr_path:
            test.metadata["__parser_stderr_path"] = str(stderr_path)

        if isinstance(e, ParserError):
            raise
        # Short message - full details are in parser_stderr file
        raise ParserScriptError(
            f"parse() failed for file '{parser.file}': {type(e).__name__}: {e}"
        ) from e

    # Write captured output to files
    stdout_path, stderr_path = _write_parser_output(
        test.execution_dir,
        stdout_buffer.getvalue(),
        stderr_buffer.getvalue(),
    )

    # Store paths in metadata for reference
    if stdout_path:
        test.metadata["__parser_stdout_path"] = str(stdout_path)
    if stderr_path:
        test.metadata["__parser_stderr_path"] = str(stderr_path)

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