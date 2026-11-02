"""Tests for the hook threshold helpers of the Studio config builder."""

import pytest

from iops.studio.builder import (
    _parse_threshold,
    _parse_thresholds,
    _thresholds_text,
    dump_yaml,
    parse_yaml,
    starter_yaml,
    validate_yaml_text,
)


@pytest.mark.parametrize("text,expected", [
    ("5", 5),
    ("25%", "25%"),
    (" 50 % ", "50%"),
    ("2.5", 2.5),
    ("", None),
    ("   ", None),
])
def test_parse_threshold(text, expected):
    assert _parse_threshold(text) == expected


def test_parse_thresholds_scalar_list_and_empty():
    assert _parse_thresholds("50%") == "50%"
    assert _parse_thresholds("25%, 50%, 100") == ["25%", "50%", 100]
    assert _parse_thresholds(" , ") is None


@pytest.mark.parametrize("value", ["50%", 5, ["25%", "50%"], [5, "10%"]])
def test_thresholds_text_round_trip(value):
    assert _parse_thresholds(_thresholds_text(value)) == value


def test_thresholds_text_empty():
    assert _thresholds_text(None) == ""


def test_form_hooks_dump_to_a_valid_config():
    model, _ = parse_yaml(starter_yaml())
    model["hooks"] = [
        {"name": "half", "event": "progress", "at": _parse_thresholds("50%"),
         "command": "echo {{ message | quote }}"},
        {"name": "rate", "event": "failures", "at": _parse_thresholds("10%, 25%"),
         "every": _parse_threshold("3"), "min_tests": 20, "command": "echo {{ progress.failed }}"},
        {"name": "done", "event": "finish", "when": ["completed"], "timeout": 30,
         "command": "echo {{ run.outcome }}"},
    ]
    ok, msgs = validate_yaml_text(dump_yaml(model))
    assert ok, msgs


def test_invalid_hook_threshold_is_reported_by_validator():
    model, _ = parse_yaml(starter_yaml())
    model["hooks"] = [{"name": "streak", "event": "consecutive_failures",
                       "at": _parse_thresholds("10%"), "command": "echo x"}]
    ok, msgs = validate_yaml_text(dump_yaml(model))
    assert not ok
    assert "counts only" in msgs[0]
