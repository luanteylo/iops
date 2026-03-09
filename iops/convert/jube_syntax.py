"""Syntax conversion utilities for JUBE to IOPS translation.

Handles variable reference syntax ($var -> {{ var }}), type mapping,
expression conversion, and pattern macro expansion.
"""

import re


# JUBE built-in pattern macros and their Python regex equivalents
JUBE_PATTERN_MACROS = {
    "$jube_pat_int": r"([+-]?\d+)",
    "$jube_pat_nint": r"(?:[+-]?\d+)",
    "$jube_pat_fp": r"([+-]?(?:\d*\.?\d+(?:[eE][-+]?\d+)?|\d+\.))",
    "$jube_pat_nfp": r"(?:[+-]?(?:\d*\.?\d+(?:[eE][-+]?\d+)?|\d+\.))",
    "$jube_pat_wrd": r"(\S+)",
    "$jube_pat_nwrd": r"(?:\S+)",
    "$jube_pat_bl": r"(?:\s+)",
}


def jube_var_to_jinja2(text):
    """Convert JUBE variable references to Jinja2 template syntax.

    Converts $var and ${var} to {{ var }}, preserving $$ as literal $.
    Skips variables that start with jube_ (internal JUBE variables).

    Args:
        text: String containing JUBE variable references.

    Returns:
        String with Jinja2 template syntax.
    """
    if not text:
        return text

    # Preserve escaped dollar signs by replacing with placeholder
    placeholder = "\x00DOLLAR\x00"
    result = text.replace("$$", placeholder)

    # Replace ${var} syntax first (more specific)
    result = re.sub(
        r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}",
        lambda m: (
            "${" + m.group(1) + "}"
            if m.group(1).startswith("jube_")
            else "{{ " + m.group(1) + " }}"
        ),
        result,
    )

    # Replace $var syntax (not followed by { which was already handled)
    result = re.sub(
        r"\$([a-zA-Z_][a-zA-Z0-9_]*)",
        lambda m: (
            "$" + m.group(1)
            if m.group(1).startswith("jube_")
            else "{{ " + m.group(1) + " }}"
        ),
        result,
    )

    # Restore escaped dollar signs
    result = result.replace(placeholder, "$")

    return result


def jube_python_expr_to_jinja2(expr):
    """Convert a JUBE python-mode expression to a Jinja2 expr string.

    JUBE python-mode parameters use Python syntax with $var references.
    This converts them to Jinja2 expression syntax: {{ expr }}.

    Args:
        expr: JUBE python expression string (e.g., "$nodes * $ppn").

    Returns:
        Jinja2 expression string (e.g., "{{ nodes * ppn }}").
    """
    if not expr:
        return expr

    # First convert variable references within the expression
    inner = expr.strip()

    # Preserve escaped dollar signs
    placeholder = "\x00DOLLAR\x00"
    inner = inner.replace("$$", placeholder)

    # Replace ${var} references
    inner = re.sub(r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}", r"\1", inner)

    # Replace $var references
    inner = re.sub(r"\$([a-zA-Z_][a-zA-Z0-9_]*)", r"\1", inner)

    # Restore escaped dollar signs
    inner = inner.replace(placeholder, "$")

    return "{{ " + inner + " }}"


def jube_type_to_iops_type(jube_type):
    """Map a JUBE parameter type to an IOPS variable type.

    Args:
        jube_type: JUBE type string ("string", "int", "float", "bool").

    Returns:
        IOPS type string ("str", "int", "float", "bool").
    """
    mapping = {
        "string": "str",
        "str": "str",
        "int": "int",
        "float": "float",
        "bool": "bool",
    }
    return mapping.get(jube_type, "str")


def jube_pattern_to_python_regex(pattern_value):
    """Expand JUBE built-in pattern macros in a regex pattern string.

    Replaces $jube_pat_* references with their regex equivalents.

    Args:
        pattern_value: Pattern string potentially containing JUBE macros.

    Returns:
        Pattern string with macros expanded to Python regex syntax.
    """
    if not pattern_value:
        return pattern_value

    result = pattern_value
    # Sort by length (longest first) to avoid partial matches
    for macro, regex in sorted(JUBE_PATTERN_MACROS.items(), key=lambda x: -len(x[0])):
        result = result.replace(macro, regex)
    return result
