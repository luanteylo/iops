from __future__ import annotations
import ast
from typing import Tuple, Optional


def validate_parser_script(
    script: str,
    *,
    require_parse_fn: bool = True,
    parse_fn_name: str = "parse",
) -> Tuple[bool, Optional[str]]:
    """
    Validate a parser_script.

    Returns:
        (True, None) if valid
        (False, error_message) if invalid

    Safe:
      - does NOT exec
      - AST only
    """
    if not isinstance(script, str) or not script.strip():
        return False, "parser_script is empty or not a string"

    try:
        tree = ast.parse(script, filename="<parser_script>", mode="exec")
    except SyntaxError as e:
        # Build a precise, user-friendly error
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
