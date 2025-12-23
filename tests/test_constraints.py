"""Unit tests for constraint validation functionality."""

import pytest
from unittest.mock import Mock, MagicMock
from pathlib import Path

from iops.config.models import ConstraintConfig, ConfigValidationError
from iops.constraints.evaluator import evaluate_constraint, filter_execution_matrix, ConstraintViolation


class TestEvaluateConstraint:
    """Test constraint evaluation logic."""

    def test_simple_modulo_constraint_valid(self):
        """Test basic modulo constraint that passes."""
        constraint = ConstraintConfig(
            name="test_modulo",
            rule="x % y == 0",
            violation_policy="skip"
        )
        vars_data = {"x": 8, "y": 2}

        is_valid, msg = evaluate_constraint(constraint, vars_data)

        assert is_valid is True
        assert msg is None

    def test_simple_modulo_constraint_invalid(self):
        """Test basic modulo constraint that fails."""
        constraint = ConstraintConfig(
            name="test_modulo",
            rule="x % y == 0",
            violation_policy="skip"
        )
        vars_data = {"x": 7, "y": 2}

        is_valid, msg = evaluate_constraint(constraint, vars_data)

        assert is_valid is False
        assert "test_modulo" in msg
        assert "violated" in msg.lower()

    def test_constraint_with_max_function(self):
        """Test constraint using max() function."""
        constraint = ConstraintConfig(
            name="test_max",
            rule="max(a, b) <= 100",
            violation_policy="skip"
        )

        # Valid case
        vars_valid = {"a": 50, "b": 80}
        is_valid, msg = evaluate_constraint(constraint, vars_valid)
        assert is_valid is True

        # Invalid case
        vars_invalid = {"a": 50, "b": 120}
        is_valid, msg = evaluate_constraint(constraint, vars_invalid)
        assert is_valid is False

    def test_constraint_with_min_function(self):
        """Test constraint using min() function."""
        constraint = ConstraintConfig(
            name="test_min",
            rule="min(a, b) >= 10",
            violation_policy="skip"
        )

        # Valid case
        vars_valid = {"a": 20, "b": 15}
        is_valid, msg = evaluate_constraint(constraint, vars_valid)
        assert is_valid is True

        # Invalid case
        vars_invalid = {"a": 20, "b": 5}
        is_valid, msg = evaluate_constraint(constraint, vars_invalid)
        assert is_valid is False

    def test_constraint_with_abs_function(self):
        """Test constraint using abs() function."""
        constraint = ConstraintConfig(
            name="test_abs",
            rule="abs(x - y) <= 10",
            violation_policy="skip"
        )

        vars_valid = {"x": 100, "y": 95}
        is_valid, msg = evaluate_constraint(constraint, vars_valid)
        assert is_valid is True

        vars_invalid = {"x": 100, "y": 85}
        is_valid, msg = evaluate_constraint(constraint, vars_invalid)
        assert is_valid is False

    def test_constraint_with_comparison(self):
        """Test constraint with comparison operators."""
        constraint = ConstraintConfig(
            name="test_comparison",
            rule="transfer_size <= block_size",
            violation_policy="skip"
        )

        vars_valid = {"transfer_size": 4, "block_size": 16}
        is_valid, msg = evaluate_constraint(constraint, vars_valid)
        assert is_valid is True

        vars_invalid = {"transfer_size": 16, "block_size": 4}
        is_valid, msg = evaluate_constraint(constraint, vars_invalid)
        assert is_valid is False

    def test_constraint_with_boolean_operators(self):
        """Test constraint with AND/OR operators."""
        constraint = ConstraintConfig(
            name="test_boolean",
            rule="x > 0 and y > 0",
            violation_policy="skip"
        )

        vars_valid = {"x": 5, "y": 10}
        is_valid, msg = evaluate_constraint(constraint, vars_valid)
        assert is_valid is True

        vars_invalid = {"x": 5, "y": -1}
        is_valid, msg = evaluate_constraint(constraint, vars_invalid)
        assert is_valid is False

    def test_constraint_undefined_variable(self):
        """Test that undefined variables raise an error."""
        constraint = ConstraintConfig(
            name="test_undefined",
            rule="undefined_var > 0",
            violation_policy="skip"
        )

        vars_data = {"x": 5}

        with pytest.raises(ConfigValidationError) as exc_info:
            evaluate_constraint(constraint, vars_data)

        assert "undefined variable" in str(exc_info.value).lower()

    def test_constraint_with_description(self):
        """Test that constraint description is included in violation message."""
        constraint = ConstraintConfig(
            name="test_desc",
            rule="x > 10",
            violation_policy="skip",
            description="X must be greater than 10"
        )

        vars_data = {"x": 5}
        is_valid, msg = evaluate_constraint(constraint, vars_data)

        assert is_valid is False
        assert "X must be greater than 10" in msg


class TestFilterExecutionMatrix:
    """Test execution matrix filtering based on constraints."""

    def create_mock_instance(self, execution_id, vars_dict):
        """Helper to create a mock ExecutionInstance."""
        instance = Mock()
        instance.execution_id = execution_id
        instance.vars = vars_dict
        return instance

    def test_filter_with_skip_policy(self):
        """Test that skip policy removes invalid instances."""
        constraint = ConstraintConfig(
            name="modulo_check",
            rule="block_size % transfer_size == 0",
            violation_policy="skip"
        )

        instances = [
            self.create_mock_instance(1, {"block_size": 16, "transfer_size": 4}),  # Valid
            self.create_mock_instance(2, {"block_size": 15, "transfer_size": 4}),  # Invalid
            self.create_mock_instance(3, {"block_size": 32, "transfer_size": 8}),  # Valid
            self.create_mock_instance(4, {"block_size": 20, "transfer_size": 7}),  # Invalid
        ]

        filtered, violations = filter_execution_matrix(instances, [constraint])

        assert len(filtered) == 2
        assert filtered[0].execution_id == 1
        assert filtered[1].execution_id == 3
        assert len(violations) == 2
        assert all(v.violation_policy == "skip" for v in violations)

    def test_filter_with_error_policy(self):
        """Test that error policy raises exception on violation."""
        constraint = ConstraintConfig(
            name="strict_check",
            rule="x > 10",
            violation_policy="error"
        )

        instances = [
            self.create_mock_instance(1, {"x": 15}),  # Valid
            self.create_mock_instance(2, {"x": 5}),   # Invalid - should raise
        ]

        with pytest.raises(ConfigValidationError) as exc_info:
            filter_execution_matrix(instances, [constraint])

        assert "strict_check" in str(exc_info.value)

    def test_filter_with_warn_policy(self):
        """Test that warn policy keeps instances but logs warning."""
        constraint = ConstraintConfig(
            name="warning_check",
            rule="y >= 8",
            violation_policy="warn"
        )

        instances = [
            self.create_mock_instance(1, {"y": 10}),  # Valid
            self.create_mock_instance(2, {"y": 4}),   # Invalid but kept
            self.create_mock_instance(3, {"y": 12}),  # Valid
        ]

        filtered, violations = filter_execution_matrix(instances, [constraint])

        # All instances should be kept with warn policy
        assert len(filtered) == 3
        assert len(violations) == 1
        assert violations[0].violation_policy == "warn"
        assert violations[0].execution_id == 2

    def test_filter_with_multiple_constraints(self):
        """Test filtering with multiple constraints."""
        constraint1 = ConstraintConfig(
            name="check1",
            rule="a % b == 0",
            violation_policy="skip"
        )
        constraint2 = ConstraintConfig(
            name="check2",
            rule="a <= 100",
            violation_policy="skip"
        )

        instances = [
            self.create_mock_instance(1, {"a": 20, "b": 5}),   # Valid for both
            self.create_mock_instance(2, {"a": 21, "b": 5}),   # Invalid for check1
            self.create_mock_instance(3, {"a": 120, "b": 10}), # Invalid for check2
            self.create_mock_instance(4, {"a": 60, "b": 10}),  # Valid for both
        ]

        filtered, violations = filter_execution_matrix(instances, [constraint1, constraint2])

        assert len(filtered) == 2
        assert filtered[0].execution_id == 1
        assert filtered[1].execution_id == 4
        assert len(violations) == 2

    def test_filter_with_no_constraints(self):
        """Test that filtering with no constraints returns all instances."""
        instances = [
            self.create_mock_instance(1, {"x": 1}),
            self.create_mock_instance(2, {"x": 2}),
        ]

        filtered, violations = filter_execution_matrix(instances, [])

        assert len(filtered) == 2
        assert len(violations) == 0

    def test_filter_with_mixed_policies(self):
        """Test filtering with mixed violation policies."""
        constraint_skip = ConstraintConfig(
            name="skip_check",
            rule="x > 5",
            violation_policy="skip"
        )
        constraint_warn = ConstraintConfig(
            name="warn_check",
            rule="y < 100",
            violation_policy="warn"
        )

        instances = [
            self.create_mock_instance(1, {"x": 10, "y": 50}),   # Valid for both
            self.create_mock_instance(2, {"x": 3, "y": 50}),    # Invalid for skip_check
            self.create_mock_instance(3, {"x": 10, "y": 150}),  # Invalid for warn_check
        ]

        filtered, violations = filter_execution_matrix(instances, [constraint_skip, constraint_warn])

        # Instance 2 should be filtered (skip), instance 3 should be kept (warn)
        assert len(filtered) == 2
        assert filtered[0].execution_id == 1
        assert filtered[1].execution_id == 3
        assert len(violations) == 2


class TestConstraintViolation:
    """Test ConstraintViolation dataclass."""

    def test_violation_creation(self):
        """Test creating a constraint violation record."""
        violation = ConstraintViolation(
            constraint_name="test_constraint",
            execution_id=42,
            rule="x > 10",
            vars={"x": 5},
            violation_policy="skip",
            message="Constraint violated"
        )

        assert violation.constraint_name == "test_constraint"
        assert violation.execution_id == 42
        assert violation.rule == "x > 10"
        assert violation.vars == {"x": 5}
        assert violation.violation_policy == "skip"
        assert violation.message == "Constraint violated"
