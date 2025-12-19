"""Input validation utilities for the setup wizard."""

import re
from pathlib import Path
from typing import Optional, Tuple, List


def validate_name(name: str) -> Tuple[bool, Optional[str]]:
    """Validate benchmark name."""
    if not name or not name.strip():
        return False, "Name cannot be empty"
    if len(name) > 100:
        return False, "Name too long (max 100 characters)"
    return True, None


def validate_directory(path: str, create_if_missing: bool = False) -> Tuple[bool, Optional[str]]:
    """Validate directory path."""
    if not path or not path.strip():
        return False, "Path cannot be empty"

    try:
        p = Path(path).expanduser().resolve()
        if p.exists():
            if not p.is_dir():
                return False, f"{path} exists but is not a directory"
            return True, None

        if create_if_missing:
            return True, f"Will create directory: {p}"
        else:
            return False, f"Directory does not exist: {path}"
    except Exception as e:
        return False, f"Invalid path: {e}"


def validate_variable_name(name: str, existing_vars: List[str] = None) -> Tuple[bool, Optional[str]]:
    """Validate variable name."""
    if not name or not name.strip():
        return False, "Variable name cannot be empty"

    # Must be valid Python identifier
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
        return False, "Variable name must start with letter/underscore and contain only letters, numbers, underscores"

    # Check for conflicts with existing variables
    if existing_vars and name in existing_vars:
        return False, f"Variable '{name}' already exists"

    # Reserved names
    reserved = ['execution_id', 'repetition', 'repetitions', 'execution_dir', 'round', 'round_name']
    if name in reserved:
        return False, f"'{name}' is a reserved name"

    return True, None


def validate_number_list(values_str: str, var_type: str) -> Tuple[bool, Optional[str], List]:
    """Validate comma-separated list of numbers."""
    if not values_str or not values_str.strip():
        return False, "Values cannot be empty", []

    try:
        values = [x.strip() for x in values_str.split(',')]

        if var_type == "int":
            parsed = [int(v) for v in values]
        elif var_type == "float":
            parsed = [float(v) for v in values]
        else:
            return False, f"Cannot parse {var_type} values", []

        if len(parsed) == 0:
            return False, "Must provide at least one value", []

        return True, None, parsed

    except ValueError as e:
        return False, f"Invalid {var_type} value: {e}", []


def validate_range(start: str, end: str, step: str, var_type: str) -> Tuple[bool, Optional[str]]:
    """Validate range parameters."""
    try:
        if var_type == "int":
            s, e, st = int(start), int(end), int(step)
        elif var_type == "float":
            s, e, st = float(start), float(end), float(step)
        else:
            return False, f"Range not supported for type {var_type}"

        if st == 0:
            return False, "Step cannot be zero"

        if st > 0 and s >= e:
            return False, "Start must be less than end for positive step"

        if st < 0 and s <= e:
            return False, "Start must be greater than end for negative step"

        return True, None

    except ValueError as e:
        return False, f"Invalid {var_type} value: {e}"


def validate_choice(choice: str, min_val: int, max_val: int) -> Tuple[bool, Optional[str], int]:
    """Validate a numeric choice input."""
    try:
        value = int(choice)
        if value < min_val or value > max_val:
            return False, f"Choice must be between {min_val} and {max_val}", 0
        return True, None, value
    except ValueError:
        return False, "Please enter a number", 0


def validate_metric_name(name: str, existing_metrics: List[str] = None) -> Tuple[bool, Optional[str]]:
    """Validate metric name."""
    if not name or not name.strip():
        return False, "Metric name cannot be empty"

    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
        return False, "Metric name must be a valid identifier"

    if existing_metrics and name in existing_metrics:
        return False, f"Metric '{name}' already exists"

    return True, None


def validate_file_path(path: str, must_exist: bool = True) -> Tuple[bool, Optional[str]]:
    """Validate file path."""
    if not path or not path.strip():
        return False, "File path cannot be empty"

    try:
        p = Path(path).expanduser()

        if must_exist and not p.exists():
            return False, f"File does not exist: {path}"

        if must_exist and not p.is_file():
            return False, f"{path} is not a file"

        return True, None

    except Exception as e:
        return False, f"Invalid path: {e}"
