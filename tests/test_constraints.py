"""Unit tests for constraint validation functionality."""

import pytest
from unittest.mock import Mock, MagicMock
from pathlib import Path

from iops.config.models import ConstraintConfig, ConfigValidationError
from iops.execution.constraints import evaluate_constraint, filter_execution_matrix, ConstraintViolation


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
        instance.metadata = {}  # Required for skipped instances
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

        kept, skipped, violations = filter_execution_matrix(instances, [constraint])

        assert len(kept) == 2
        assert kept[0].execution_id == 1
        assert kept[1].execution_id == 3
        assert len(skipped) == 2
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

        kept, skipped, violations = filter_execution_matrix(instances, [constraint])

        # All instances should be kept with warn policy
        assert len(kept) == 3
        assert len(skipped) == 0  # warn policy doesn't skip
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

        kept, skipped, violations = filter_execution_matrix(instances, [constraint1, constraint2])

        assert len(kept) == 2
        assert kept[0].execution_id == 1
        assert kept[1].execution_id == 4
        assert len(skipped) == 2
        assert len(violations) == 2

    def test_filter_with_no_constraints(self):
        """Test that filtering with no constraints returns all instances."""
        instances = [
            self.create_mock_instance(1, {"x": 1}),
            self.create_mock_instance(2, {"x": 2}),
        ]

        kept, skipped, violations = filter_execution_matrix(instances, [])

        assert len(kept) == 2
        assert len(skipped) == 0
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

        kept, skipped, violations = filter_execution_matrix(instances, [constraint_skip, constraint_warn])

        # Instance 2 should be filtered (skip), instance 3 should be kept (warn)
        assert len(kept) == 2
        assert kept[0].execution_id == 1
        assert kept[1].execution_id == 3
        assert len(skipped) == 1  # Only instance 2 is skipped
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


class TestExtractConstraintVariables:
    """Test variable extraction from constraint rules."""

    def test_simple_comparison(self):
        """Test extracting variables from simple comparison."""
        from iops.execution.constraints import extract_constraint_variables

        result = extract_constraint_variables("x > 10")
        assert result == {"x"}

    def test_multiple_variables(self):
        """Test extracting multiple variables."""
        from iops.execution.constraints import extract_constraint_variables

        result = extract_constraint_variables("total_procs >= nodes")
        assert result == {"total_procs", "nodes"}

    def test_with_operators(self):
        """Test extracting variables with modulo and division."""
        from iops.execution.constraints import extract_constraint_variables

        result = extract_constraint_variables("block_size % transfer_size == 0")
        assert result == {"block_size", "transfer_size"}

    def test_with_functions(self):
        """Test that functions are not included in extracted variables."""
        from iops.execution.constraints import extract_constraint_variables

        result = extract_constraint_variables("max(a, b) <= 100 and min(c, d) > 0")
        assert result == {"a", "b", "c", "d"}

    def test_complex_expression(self):
        """Test extracting from complex boolean expression."""
        from iops.execution.constraints import extract_constraint_variables

        result = extract_constraint_variables("(nodes * ppn) >= total_procs and block_size > 0")
        assert result == {"nodes", "ppn", "total_procs", "block_size"}


class TestClassifyConstraints:
    """Test constraint classification into early/late."""

    def test_classify_swept_only_constraint(self):
        """Test that constraint using only swept vars is classified as early."""
        from iops.execution.constraints import classify_constraints

        constraint = ConstraintConfig(
            name="valid_procs",
            rule="total_procs >= nodes",
            violation_policy="skip"
        )

        swept_vars = {"nodes", "total_procs", "ppn"}
        derived_vars = {"procs_per_node", "block_size"}

        early, late = classify_constraints([constraint], swept_vars, derived_vars)

        assert len(early) == 1
        assert len(late) == 0
        assert early[0].name == "valid_procs"

    def test_classify_derived_constraint(self):
        """Test that constraint using derived var is classified as late."""
        from iops.execution.constraints import classify_constraints

        constraint = ConstraintConfig(
            name="block_alignment",
            rule="block_size % transfer_size == 0",
            violation_policy="skip"
        )

        swept_vars = {"nodes", "transfer_size"}
        derived_vars = {"block_size"}

        early, late = classify_constraints([constraint], swept_vars, derived_vars)

        assert len(early) == 0
        assert len(late) == 1
        assert late[0].name == "block_alignment"

    def test_classify_mixed_constraints(self):
        """Test classifying a mix of early and late constraints."""
        from iops.execution.constraints import classify_constraints

        constraint_early = ConstraintConfig(
            name="valid_procs",
            rule="total_procs >= nodes",
            violation_policy="skip"
        )
        constraint_late = ConstraintConfig(
            name="block_alignment",
            rule="block_size % transfer_size == 0",
            violation_policy="skip"
        )

        swept_vars = {"nodes", "total_procs", "transfer_size"}
        derived_vars = {"procs_per_node", "block_size"}

        early, late = classify_constraints(
            [constraint_early, constraint_late],
            swept_vars,
            derived_vars
        )

        assert len(early) == 1
        assert len(late) == 1
        assert early[0].name == "valid_procs"
        assert late[0].name == "block_alignment"


class TestEarlyConstraintFiltering:
    """Test that early constraints prevent derived expression errors."""

    def test_early_constraint_prevents_division_by_zero(self, tmp_path):
        """Test that early constraint filters before derived expr evaluation."""
        import logging
        from iops.config.loader import load_generic_config
        from iops.execution.matrix import build_execution_matrix

        # Create config with derived var that would divide by zero
        # when total_procs < nodes (procs_per_node = 0)
        config_content = """
benchmark:
  name: test
  workdir: {workdir}
  executor: local

vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 4, 8, 16]
  total_procs:
    type: int
    sweep:
      mode: list
      values: [8, 16]
  procs_per_node:
    type: int
    expr: "total_procs // nodes"
  block_size:
    type: int
    expr: "(1024) // (nodes * procs_per_node)"

constraints:
  - name: "valid_procs_distribution"
    rule: "total_procs >= nodes"
    violation_policy: "skip"

command:
  template: "echo test"

scripts:
  - name: test
    script_template: |
      #!/bin/bash
      echo test

output:
  sink:
    type: csv
    path: "{{{{ workdir }}}}/results.csv"
""".format(workdir=tmp_path)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_content)

        logger = logging.getLogger("test")
        cfg = load_generic_config(Path(config_file), logger)

        # This should NOT raise a division by zero error
        # because the early constraint filters out invalid combinations
        # BEFORE derived expressions are evaluated
        kept, skipped = build_execution_matrix(cfg)

        # Verify we got valid combinations
        # nodes=1 with total_procs=8,16 -> valid
        # nodes=4 with total_procs=8,16 -> valid
        # nodes=8 with total_procs=8,16 -> valid
        # nodes=16 with total_procs=8,16 -> invalid (would be filtered)
        assert len(kept) > 0

        # Verify all kept instances have valid derived vars
        for instance in kept:
            vars_data = instance.vars
            # procs_per_node should be >= 1
            assert vars_data["procs_per_node"] >= 1
            # block_size should be computable without error
            assert "block_size" in vars_data
