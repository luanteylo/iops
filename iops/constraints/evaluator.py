"""Constraint evaluation for IOPS parameter combinations."""

from typing import Dict, Any, List, Tuple, Optional, TYPE_CHECKING
from dataclasses import dataclass
import logging
import math

from iops.config.models import ConstraintConfig, ConfigValidationError

if TYPE_CHECKING:
    from iops.execution.matrix import ExecutionInstance


@dataclass
class ConstraintViolation:
    """Record of a constraint violation."""
    constraint_name: str
    execution_id: int
    rule: str
    vars: Dict[str, Any]
    violation_policy: str
    message: str


def evaluate_constraint(
    constraint: ConstraintConfig,
    instance_vars: Dict[str, Any]
) -> Tuple[bool, Optional[str]]:
    """
    Evaluate a constraint rule against parameter values.

    Args:
        constraint: The constraint configuration with rule expression
        instance_vars: Dictionary of all variable values for this instance

    Returns:
        (is_valid, error_message):
            - is_valid: True if constraint passes, False if violated
            - error_message: None if valid, description of violation otherwise
    """
    rule = constraint.rule.strip()

    # Evaluate as Python expression with restricted builtins
    # Same pattern as _eval_expr from matrix.py
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
        # Evaluate the rule expression with variables in context
        result = eval(rule, {"__builtins__": {}}, {**allowed_funcs, **instance_vars})

        # Rule should evaluate to a boolean
        if not isinstance(result, bool):
            # Try to convert to bool
            result = bool(result)

        if result:
            # Constraint satisfied
            return True, None
        else:
            # Constraint violated
            msg = f"Constraint '{constraint.name}' violated: {rule}"
            if constraint.description:
                msg += f" ({constraint.description})"
            return False, msg

    except NameError as e:
        # Variable not found in context
        raise ConfigValidationError(
            f"Constraint '{constraint.name}' references undefined variable: {e}"
        ) from e
    except Exception as e:
        # Other evaluation errors
        raise ConfigValidationError(
            f"Error evaluating constraint '{constraint.name}' with rule '{rule}': {e}"
        ) from e


def filter_execution_matrix(
    instances: List["ExecutionInstance"],
    constraints: List[ConstraintConfig],
    logger: Optional[logging.Logger] = None
) -> Tuple[List["ExecutionInstance"], List[ConstraintViolation]]:
    """
    Filter execution instances based on constraints.

    For each instance:
    - Evaluate all constraints against instance.vars
    - Handle violations based on violation_policy:
        - "skip": Remove instance from list
        - "error": Raise ConfigValidationError immediately
        - "warn": Log warning but keep instance

    Args:
        instances: List of ExecutionInstance objects to filter
        constraints: List of constraints to apply
        logger: Optional logger for warnings and info messages

    Returns:
        (filtered_instances, violations):
            - filtered_instances: List of instances that pass all constraints
            - violations: List of ConstraintViolation records

    Raises:
        ConfigValidationError: If any constraint has violation_policy="error" and is violated
    """
    if not constraints:
        return instances, []

    if logger is None:
        logger = logging.getLogger(__name__)

    filtered_instances = []
    all_violations = []

    for instance in instances:
        # Get all variables (base + derived) for this instance
        instance_vars = instance.vars

        # Track if this instance should be kept
        keep_instance = True

        # Evaluate all constraints for this instance
        for constraint in constraints:
            is_valid, error_msg = evaluate_constraint(constraint, instance_vars)

            if not is_valid:
                # Constraint violated
                violation = ConstraintViolation(
                    constraint_name=constraint.name,
                    execution_id=instance.execution_id,
                    rule=constraint.rule,
                    vars=instance_vars.copy(),
                    violation_policy=constraint.violation_policy,
                    message=error_msg or f"Constraint {constraint.name} failed"
                )
                all_violations.append(violation)

                # Handle based on violation policy
                if constraint.violation_policy == "error":
                    # Fail immediately
                    raise ConfigValidationError(
                        f"{error_msg}\n"
                        f"Execution ID {instance.execution_id}: {instance_vars}"
                    )
                elif constraint.violation_policy == "skip":
                    # Mark this instance to be filtered out
                    keep_instance = False
                    logger.debug(
                        f"Skipping execution {instance.execution_id}: {error_msg}"
                    )
                elif constraint.violation_policy == "warn":
                    # Log warning but keep instance
                    logger.warning(
                        f"Execution {instance.execution_id}: {error_msg}. "
                        f"Proceeding anyway (violation_policy=warn)."
                    )
                else:
                    # Unknown policy (shouldn't happen if validation is correct)
                    logger.error(
                        f"Unknown violation_policy '{constraint.violation_policy}' "
                        f"for constraint '{constraint.name}'"
                    )

        # Keep instance if no "skip" violations occurred
        if keep_instance:
            filtered_instances.append(instance)

    # Log summary
    if all_violations:
        skipped_count = sum(1 for v in all_violations if v.violation_policy == "skip")
        warned_count = sum(1 for v in all_violations if v.violation_policy == "warn")

        logger.info(
            f"Constraint filtering complete: "
            f"{len(filtered_instances)}/{len(instances)} instances passed. "
            f"Filtered: {skipped_count} skipped, {warned_count} warned."
        )

    return filtered_instances, all_violations
