"""Tests for run-level hooks (user commands fired on run events)."""

import copy
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml

from conftest import load_config
from iops.config.loader import load_generic_config, validate_yaml_config
from iops.config.models import ConfigValidationError, HookConfig, HookThreshold, ReportingConfig
from iops.execution.hooks import (
    HOOKS_LOG_FILENAME,
    HookManager,
    HookStats,
    build_hook_context,
    describe_hook_trigger,
    hook_environment,
    render_hook_command,
    run_hook_command,
    sample_hook_context,
)
from iops.execution.runner import IOPSRunner
from iops.main import main, parse_arguments


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_config(tmp_path, config_dict, name="hooks_config.yaml"):
    path = tmp_path / name
    with open(path, "w") as f:
        yaml.dump(config_dict, f)
    return path


def _with_hooks(config_dict, hooks):
    cfg = copy.deepcopy(config_dict)
    cfg["hooks"] = hooks
    return cfg


def _load_with_hooks(tmp_path, config_dict, hooks):
    return load_config(_write_config(tmp_path, _with_hooks(config_dict, hooks)))


def _assert_invalid(tmp_path, config_dict, hooks, match):
    path = _write_config(tmp_path, _with_hooks(config_dict, hooks))
    with pytest.raises(ConfigValidationError, match=match):
        load_config(path)


def _hook(event, name="h", command="true", at=None, every=None, when=None,
          min_tests=10, timeout=60.0):
    return HookConfig(name=name, event=event, command=command, at=at or [],
                      every=every, when=when, min_tests=min_tests, timeout=timeout)


def _pct(value):
    return HookThreshold(value=float(value), percent=True)


def _cnt(value):
    return HookThreshold(value=float(value), percent=False)


class RecordingManager(HookManager):
    """HookManager that records what would fire instead of running commands."""

    def __init__(self, hooks, workdir=Path("/tmp/run")):
        super().__init__(hooks, "bench", workdir, logging.getLogger("test_hooks"))
        self.fired = []

    def _fire(self, hook, threshold=None, outcome=None, report_path=None):
        self.fired.append((hook.name, str(threshold) if threshold is not None else None, outcome))


def _record(manager, statuses, total):
    for status in statuses:
        manager.record(status, total=total)


def _make_args(**overrides):
    args = Mock()
    args.use_cache = False
    args.cache_only = False
    args.log_level = "WARNING"
    args.max_core_hours = None
    args.time_estimate = None
    args.parallel = None
    args.fail_fast = False
    args.no_hooks = False
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------

class TestHookParsing:

    def test_no_hooks_section_gives_empty_list(self, sample_config_file):
        assert load_config(sample_config_file).hooks == []

    def test_null_hooks_section_gives_empty_list(self, tmp_path, sample_config_dict):
        assert _load_with_hooks(tmp_path, sample_config_dict, None).hooks == []

    def test_full_hook_is_parsed(self, tmp_path, sample_config_dict):
        cfg = _load_with_hooks(tmp_path, sample_config_dict, [
            {"name": "prog", "event": "progress", "at": ["25%", 10], "every": "10%",
             "timeout": 5, "command": "echo {{ progress.percent }}"},
        ])
        (hook,) = cfg.hooks
        assert hook.name == "prog"
        assert hook.event == "progress"
        assert hook.at == [_pct(25), _cnt(10)]
        assert hook.every == _pct(10)
        assert hook.timeout == 5.0
        assert hook.min_tests == 10
        assert hook.when is None

    def test_scalar_at_and_when_become_lists(self, tmp_path, sample_config_dict):
        cfg = _load_with_hooks(tmp_path, sample_config_dict, [
            {"name": "f", "event": "failures", "at": 3, "command": "true"},
            {"name": "e", "event": "finish", "when": "crashed", "command": "true"},
        ])
        assert cfg.hooks[0].at == [_cnt(3)]
        assert cfg.hooks[1].when == ["crashed"]

    def test_defaults(self, tmp_path, sample_config_dict):
        cfg = _load_with_hooks(tmp_path, sample_config_dict, [
            {"name": "s", "event": "start", "command": "true"},
        ])
        hook = cfg.hooks[0]
        assert hook.at == [] and hook.every is None
        assert hook.min_tests == 10
        assert hook.timeout == 60.0

    def test_unnamed_hook_gets_generated_name(self, tmp_path, sample_config_dict):
        cfg = _load_with_hooks(tmp_path, sample_config_dict, [
            {"event": "start", "command": "true"},
        ])
        assert cfg.hooks[0].name == "hook_0"

    def test_decimal_percentage(self, tmp_path, sample_config_dict):
        cfg = _load_with_hooks(tmp_path, sample_config_dict, [
            {"name": "p", "event": "progress", "at": "12.5%", "command": "true"},
        ])
        assert cfg.hooks[0].at == [_pct(12.5)]

    def test_hooks_must_be_a_list(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict, {"event": "start"}, "hooks must be a list")

    def test_entry_must_be_mapping(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict, ["echo hi"], r"hooks\[0\] must be a mapping")

    def test_unknown_key_suggests_correction(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "s", "event": "start", "comand": "true"}],
                        "did you mean 'command'")

    def test_bare_on_key_gets_dedicated_error(self, tmp_path, sample_config_dict):
        # Written by hand: yaml.dump would quote the key and hide the problem
        text = yaml.dump(sample_config_dict) + "hooks:\n  - name: s\n    on: start\n    command: 'true'\n"
        path = tmp_path / "on_key.yaml"
        path.write_text(text)
        with pytest.raises(ConfigValidationError, match="Use 'event:'"):
            load_config(path)

    @pytest.mark.parametrize("value, match", [
        (True, "integer count or a percentage"),
        (2.5, "write percentages as a string"),
        ("abc", "integer count or a percentage"),
        ("ten%", "integer count or a percentage"),
        ("5", "integer count or a percentage"),
    ])
    def test_bad_threshold_values(self, tmp_path, sample_config_dict, value, match):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "p", "event": "progress", "at": value, "command": "true"}], match)

    def test_bad_min_tests_type(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "f", "event": "failures", "at": "5%", "min_tests": "ten",
                          "command": "true"}], "min_tests must be an integer")

    def test_bad_timeout_type(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "s", "event": "start", "timeout": "1m", "command": "true"}],
                        "timeout must be a number")


# ---------------------------------------------------------------------------
# Semantic validation
# ---------------------------------------------------------------------------

class TestHookValidation:

    def test_missing_event(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict, [{"name": "x", "command": "true"}],
                        "missing 'event'")

    def test_unknown_event(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "x", "event": "end", "command": "true"}], "event must be one of")

    def test_missing_command(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict, [{"name": "x", "event": "start"}],
                        "command must not be empty")

    def test_blank_command(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "x", "event": "start", "command": "   "}], "command must not be empty")

    def test_jinja_syntax_error(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "x", "event": "start", "command": "echo {%if x%}"}], r"hooks\[0\]")

    def test_misspelled_context_name_is_caught(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "x", "event": "start", "command": "echo {{ progres.total }}"}],
                        "cannot be rendered")

    def test_benchmark_variables_are_not_in_context(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "x", "event": "start", "command": "echo {{ nodes }}"}],
                        "not the benchmark variables")

    def test_unknown_os_env_variable_is_accepted(self, tmp_path, sample_config_dict):
        cfg = _load_with_hooks(tmp_path, sample_config_dict, [
            {"name": "x", "event": "start", "command": "echo {{ os_env.IOPS_SURELY_UNSET_VAR }}"},
        ])
        assert len(cfg.hooks) == 1

    def test_duplicate_names(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict, [
            {"name": "x", "event": "start", "command": "true"},
            {"name": "x", "event": "finish", "command": "true"},
        ], "duplicate hook name")

    @pytest.mark.parametrize("event", ["progress", "failures", "consecutive_failures"])
    def test_threshold_events_need_at_or_every(self, tmp_path, sample_config_dict, event):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "x", "event": event, "command": "true"}], "need 'at' and/or 'every'")

    @pytest.mark.parametrize("event, key", [("start", "at"), ("finish", "every")])
    def test_thresholds_rejected_on_start_and_finish(self, tmp_path, sample_config_dict, event, key):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "x", "event": event, key: 5, "command": "true"}],
                        "do not apply")

    def test_when_only_on_finish(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "x", "event": "progress", "at": 1, "when": ["completed"],
                          "command": "true"}], "only applies to 'finish'")

    def test_unknown_outcome(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "x", "event": "finish", "when": ["done"], "command": "true"}],
                        "when must list outcomes")

    def test_empty_when(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "x", "event": "finish", "when": [], "command": "true"}],
                        "when must list outcomes")

    @pytest.mark.parametrize("value", ["0%", "101%", "-5%"])
    def test_percentage_out_of_range(self, tmp_path, sample_config_dict, value):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "x", "event": "progress", "at": value, "command": "true"}],
                        "percentage must be greater than 0%")

    @pytest.mark.parametrize("value", [0, -3])
    def test_count_below_one(self, tmp_path, sample_config_dict, value):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "x", "event": "progress", "every": value, "command": "true"}],
                        "count must be at least 1")

    def test_consecutive_failures_rejects_percentages(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "x", "event": "consecutive_failures", "at": "50%",
                          "command": "true"}], "counts only")

    def test_failures_every_rejects_percentage(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "x", "event": "failures", "every": "10%", "command": "true"}],
                        "repeating percentage is ambiguous")

    def test_failures_every_count_is_valid(self, tmp_path, sample_config_dict):
        cfg = _load_with_hooks(tmp_path, sample_config_dict, [
            {"name": "x", "event": "failures", "every": 10, "command": "true"},
        ])
        assert cfg.hooks[0].every == _cnt(10)

    def test_min_tests_below_one(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "x", "event": "failures", "at": "5%", "min_tests": 0,
                          "command": "true"}], "min_tests must be at least 1")

    def test_timeout_must_be_positive(self, tmp_path, sample_config_dict):
        _assert_invalid(tmp_path, sample_config_dict,
                        [{"name": "x", "event": "start", "timeout": 0, "command": "true"}],
                        "timeout must be positive")

    def test_check_reports_hook_errors(self, tmp_path, sample_config_dict):
        path = _write_config(tmp_path, _with_hooks(sample_config_dict, [
            {"name": "x", "event": "nope", "command": "true"},
        ]))
        errors = validate_yaml_config(path)
        assert len(errors) == 1
        assert "event must be one of" in errors[0]

    def test_check_accepts_valid_hooks(self, tmp_path, sample_config_dict):
        path = _write_config(tmp_path, _with_hooks(sample_config_dict, [
            {"name": "s", "event": "start", "command": "echo {{ message | quote }}"},
            {"name": "p", "event": "progress", "at": ["50%"], "every": 2, "command": "true"},
            {"name": "f", "event": "failures", "at": [1, "10%"], "min_tests": 3, "command": "true"},
            {"name": "c", "event": "consecutive_failures", "every": 3, "command": "true"},
            {"name": "e", "event": "finish", "when": ["completed", "crashed"],
             "command": "echo {{ run.outcome }} {{ report_path }}"},
        ]))
        assert validate_yaml_config(path) == []


# ---------------------------------------------------------------------------
# Machine overrides and loading without side effects
# ---------------------------------------------------------------------------

class TestHookMachinesAndLoading:

    def test_machine_override_merges_hooks_by_name(self, tmp_path, sample_config_dict):
        config = _with_hooks(sample_config_dict, [
            {"name": "notify", "event": "finish", "command": "echo base"},
        ])
        config["machines"] = {"cluster": {"hooks": [
            {"name": "notify", "command": "mail -s done me@lab.org < /dev/null"},
            {"name": "extra", "event": "start", "command": "echo started"},
        ]}}
        path = _write_config(tmp_path, config)
        cfg = load_generic_config(path, logging.getLogger("test"), machine="cluster")
        by_name = {h.name: h for h in cfg.hooks}
        assert by_name["notify"].event == "finish"
        assert by_name["notify"].command.startswith("mail")
        assert by_name["extra"].event == "start"

    def test_hooks_allowed_only_in_machine_profile(self, tmp_path, sample_config_dict):
        config = copy.deepcopy(sample_config_dict)
        config["machines"] = {"cluster": {"hooks": [
            {"name": "notify", "event": "finish", "command": "true"},
        ]}}
        path = _write_config(tmp_path, config)
        assert load_generic_config(path, logging.getLogger("test")).hooks == []
        assert len(load_generic_config(path, logging.getLogger("test"), machine="cluster").hooks) == 1

    def test_create_dirs_false_leaves_filesystem_untouched(self, tmp_path, sample_config_dict):
        path = _write_config(tmp_path, sample_config_dict)
        workdir = Path(sample_config_dict["benchmark"]["workdir"])
        cfg = load_generic_config(path, logging.getLogger("test"), create_dirs=False)
        assert Path(cfg.benchmark.workdir) == workdir
        assert list(workdir.iterdir()) == []


# ---------------------------------------------------------------------------
# Threshold logic
# ---------------------------------------------------------------------------

class TestThresholdDisplay:

    @pytest.mark.parametrize("threshold, text", [
        (_pct(25), "25%"), (_pct(12.5), "12.5%"), (_cnt(5), "5"),
    ])
    def test_str(self, threshold, text):
        assert str(threshold) == text


class TestProgressTriggers:

    def test_at_percentages_fire_once_each(self):
        m = RecordingManager([_hook("progress", at=[_pct(25), _pct(50)])])
        _record(m, ["SUCCEEDED"] * 8, total=8)
        assert m.fired == [("h", "25%", None), ("h", "50%", None)]

    def test_at_counts(self):
        m = RecordingManager([_hook("progress", at=[_cnt(3)])])
        _record(m, ["SUCCEEDED"] * 5, total=10)
        assert m.fired == [("h", "3", None)]

    def test_every_count(self):
        m = RecordingManager([_hook("progress", every=_cnt(2))])
        _record(m, ["SUCCEEDED"] * 7, total=10)
        assert [t for _, t, _ in m.fired] == ["2", "4", "6"]

    def test_every_percentage(self):
        m = RecordingManager([_hook("progress", every=_pct(25))])
        _record(m, ["SUCCEEDED"] * 8, total=8)
        assert [t for _, t, _ in m.fired] == ["25%", "50%", "75%", "100%"]

    def test_every_percentage_jump_fires_once_for_highest(self):
        # One test out of four is 25%, crossing 10% and 20% in a single update
        m = RecordingManager([_hook("progress", every=_pct(10))])
        _record(m, ["SUCCEEDED"], total=4)
        assert m.fired == [("h", "20%", None)]

    def test_all_statuses_count_as_progress(self):
        m = RecordingManager([_hook("progress", at=[_cnt(4)])])
        _record(m, ["SUCCEEDED", "FAILED", "ERROR", "SKIPPED"], total=4)
        assert m.fired == [("h", "4", None)]

    def test_unknown_total_skips_percentages_but_not_counts(self):
        m = RecordingManager([_hook("progress", at=[_pct(50), _cnt(2)])])
        _record(m, ["SUCCEEDED"] * 3, total=0)
        assert m.fired == [("h", "2", None)]

    def test_growing_total_is_followed(self):
        # Adaptive planners re-estimate the total as they go
        m = RecordingManager([_hook("progress", at=[_pct(50)])])
        m.record("SUCCEEDED", total=4)
        m.record("SUCCEEDED", total=8)  # 2/8 = 25%, not yet
        assert m.fired == []
        m.record("SUCCEEDED", total=8)
        m.record("SUCCEEDED", total=8)  # 4/8 = 50%
        assert m.fired == [("h", "50%", None)]

    def test_at_and_every_together(self):
        m = RecordingManager([_hook("progress", at=[_pct(50)], every=_cnt(2))])
        _record(m, ["SUCCEEDED"] * 6, total=6)
        assert [t for _, t, _ in m.fired] == ["2", "50%", "4", "6"]

    def test_simultaneous_crossings_fire_once_reporting_the_last(self):
        # Test 3 of 6 reaches both 50% and the first multiple of 3
        m = RecordingManager([_hook("progress", at=[_pct(50)], every=_cnt(3))])
        _record(m, ["SUCCEEDED"] * 6, total=6)
        assert [t for _, t, _ in m.fired] == ["3", "6"]

    def test_several_at_thresholds_in_one_update(self):
        m = RecordingManager([_hook("progress", at=[_pct(10), _pct(20)])])
        _record(m, ["SUCCEEDED"], total=4)
        assert m.fired == [("h", "20%", None)]
        _record(m, ["SUCCEEDED"] * 3, total=4)
        assert len(m.fired) == 1


class TestFailureTriggers:

    def test_count(self):
        m = RecordingManager([_hook("failures", at=[_cnt(2)])])
        _record(m, ["SUCCEEDED", "FAILED", "SUCCEEDED", "ERROR", "FAILED"], total=10)
        assert m.fired == [("h", "2", None)]

    def test_every_count(self):
        m = RecordingManager([_hook("failures", every=_cnt(2))])
        _record(m, ["FAILED"] * 5, total=10)
        assert [t for _, t, _ in m.fired] == ["2", "4"]

    def test_rate_waits_for_min_tests(self):
        m = RecordingManager([_hook("failures", at=[_pct(20)], min_tests=5)])
        _record(m, ["FAILED", "SUCCEEDED", "SUCCEEDED", "SUCCEEDED"], total=100)
        assert m.fired == []
        m.record("SUCCEEDED", total=100)  # 1/5 = 20%, guard now open
        assert m.fired == [("h", "20%", None)]

    def test_guard_opening_on_success_fires(self):
        m = RecordingManager([_hook("failures", at=[_pct(50)], min_tests=3)])
        _record(m, ["FAILED", "FAILED"], total=100)
        assert m.fired == []
        m.record("SUCCEEDED", total=100)  # 2/3 = 66%
        assert m.fired == [("h", "50%", None)]

    def test_guard_lowered_on_small_runs(self):
        m = RecordingManager([_hook("failures", at=[_pct(50)], min_tests=10)])
        _record(m, ["FAILED", "FAILED", "SUCCEEDED", "SUCCEEDED"], total=4)
        assert m.fired == [("h", "50%", None)]

    def test_skipped_tests_do_not_count_in_rate(self):
        m = RecordingManager([_hook("failures", at=[_pct(50)], min_tests=2)])
        _record(m, ["SKIPPED", "SKIPPED", "SKIPPED", "FAILED", "SUCCEEDED"], total=5)
        assert m.fired == [("h", "50%", None)]
        assert m.stats.failed_percent == 50.0

    def test_rate_below_threshold_does_not_fire(self):
        m = RecordingManager([_hook("failures", at=[_pct(50)], min_tests=1)])
        _record(m, ["SUCCEEDED", "SUCCEEDED", "FAILED"], total=3)
        assert m.fired == []

    def test_fires_once_even_if_rate_dips_and_recovers(self):
        m = RecordingManager([_hook("failures", at=[_pct(50)], min_tests=1)])
        _record(m, ["FAILED", "SUCCEEDED", "SUCCEEDED", "FAILED", "FAILED"], total=5)
        assert m.fired == [("h", "50%", None)]


class TestConsecutiveFailureTriggers:

    def test_fires_at_streak_length(self):
        m = RecordingManager([_hook("consecutive_failures", at=[_cnt(2)])])
        _record(m, ["FAILED", "FAILED", "FAILED"], total=10)
        assert m.fired == [("h", "2", None)]

    def test_success_breaks_the_streak(self):
        m = RecordingManager([_hook("consecutive_failures", at=[_cnt(3)])])
        _record(m, ["FAILED", "FAILED", "SUCCEEDED", "FAILED", "FAILED"], total=10)
        assert m.fired == []

    def test_rearms_after_a_new_streak(self):
        m = RecordingManager([_hook("consecutive_failures", at=[_cnt(2)])])
        _record(m, ["FAILED", "FAILED", "SUCCEEDED", "FAILED", "ERROR"], total=10)
        assert m.fired == [("h", "2", None), ("h", "2", None)]

    def test_every(self):
        m = RecordingManager([_hook("consecutive_failures", every=_cnt(2))])
        _record(m, ["FAILED"] * 5, total=10)
        assert [t for _, t, _ in m.fired] == ["2", "4"]

    def test_skipped_does_not_break_the_streak(self):
        m = RecordingManager([_hook("consecutive_failures", at=[_cnt(2)])])
        _record(m, ["FAILED", "SKIPPED", "FAILED"], total=10)
        assert m.fired == [("h", "2", None)]


class TestStartAndFinish:

    def test_start_fires_once(self):
        m = RecordingManager([_hook("start")])
        m.start(total=5)
        m.start(total=5)
        assert m.fired == [("h", None, None)]
        assert m.stats.total == 5

    def test_finish_fires_with_outcome(self):
        m = RecordingManager([_hook("finish")])
        m.start(total=1)
        m.finish("completed", total=1)
        assert m.fired == [("h", None, "completed")]

    @pytest.mark.parametrize("outcome, fires", [("crashed", True), ("completed", False)])
    def test_finish_when_filter(self, outcome, fires):
        m = RecordingManager([_hook("finish", when=["crashed", "interrupted"])])
        m.finish(outcome)
        assert bool([f for f in m.fired if f[0] == "h"]) is fires

    def test_finish_triggers_start_when_no_test_ran(self):
        m = RecordingManager([_hook("start", name="s"), _hook("finish", name="e")])
        m.finish("interrupted", total=0)
        assert m.fired == [("s", None, None), ("e", None, "interrupted")]

    def test_finish_is_idempotent_and_stops_recording(self):
        m = RecordingManager([_hook("finish"), _hook("progress", name="p", every=_cnt(1))])
        m.finish("completed")
        m.finish("completed")
        m.record("SUCCEEDED", total=1)
        assert m.fired == [("h", None, "completed")]

    def test_only_matching_event_hooks_fire(self):
        m = RecordingManager([
            _hook("start", name="s"),
            _hook("progress", name="p", at=[_cnt(1)]),
            _hook("failures", name="f", at=[_cnt(1)]),
            _hook("finish", name="e"),
        ])
        m.start(total=1)
        m.record("SUCCEEDED", total=1)
        assert [name for name, _, _ in m.fired] == ["s", "p"]


class TestHookStats:

    def test_counts_by_status(self):
        m = RecordingManager([])
        _record(m, ["SUCCEEDED", "FAILED", "ERROR", "SKIPPED", "UNKNOWN"], total=10)
        s = m.stats
        assert (s.succeeded, s.failed, s.skipped, s.other) == (1, 2, 1, 1)
        assert s.completed == 5
        assert s.ran == 3
        assert s.percent == 50.0
        assert s.failed_percent == pytest.approx(66.67, abs=0.01)

    def test_empty_stats(self):
        s = HookStats()
        assert s.percent == 0.0 and s.failed_percent == 0.0


# ---------------------------------------------------------------------------
# Context, environment and rendering
# ---------------------------------------------------------------------------

def _context(event, **kwargs):
    hook = _hook(event, at=[_pct(50)] if event in ("progress", "failures") else None)
    stats = HookStats(total=10, succeeded=4, failed=1, skipped=0, consecutive_failures=1,
                      core_hours=2.5)
    start = datetime(2026, 1, 1, 12, 0, 0)
    defaults = dict(benchmark_name="bench", workdir=Path("/runs/run_001"), stats=stats,
                    start_time=start, now=start + timedelta(seconds=3725), os_env={"USER": "me"})
    defaults.update(kwargs)
    return build_hook_context(hook, **defaults)


class TestHookContext:

    def test_structure(self):
        ctx = _context("progress", threshold=_pct(50))
        assert ctx["event"] == {"name": "progress", "hook": "h", "threshold": "50%"}
        assert ctx["progress"] == {
            "completed": 5, "total": 10, "percent": 50.0, "succeeded": 4, "failed": 1,
            "skipped": 0, "failed_percent": 20.0, "consecutive_failures": 1,
        }
        assert ctx["run"]["elapsed"] == "1:02:05"
        assert ctx["run"]["elapsed_seconds"] == 3725
        assert ctx["run"]["start_time"] == "2026-01-01T12:00:00"
        assert ctx["run"]["core_hours"] == 2.5
        assert ctx["run"]["outcome"] == ""
        assert ctx["benchmark"] == {"name": "bench"}
        assert ctx["workdir"] == "/runs/run_001"
        assert ctx["report_path"] == ""
        assert ctx["os_env"] == {"USER": "me"}
        assert ctx["hostname"]

    def test_finish_context(self):
        ctx = _context("finish", outcome="budget_exceeded",
                       report_path=Path("/runs/run_001/analysis_report.html"))
        assert ctx["run"]["outcome"] == "budget_exceeded"
        assert ctx["report_path"] == "/runs/run_001/analysis_report.html"
        assert "finished (budget_exceeded) after 1:02:05" in ctx["message"]
        assert "Report: /runs/run_001/analysis_report.html" in ctx["message"]

    @pytest.mark.parametrize("event, expected", [
        ("start", "started on"),
        ("progress", "reached 50% progress: 5/10 tests concluded (50.0%)"),
        ("failures", "reached 50% failures: 1 of 5 tests failed (20.0%)"),
        ("consecutive_failures", "has 1 consecutive failures"),
        ("finish", "finished"),
    ])
    def test_message_per_event(self, event, expected):
        ctx = _context(event, threshold=_pct(50), outcome="completed")
        assert expected in ctx["message"]
        assert "IOPS run 'bench'" in ctx["message"]
        assert ctx["message"].endswith("Run directory: /runs/run_001")

    def test_environment_mirrors_context(self):
        ctx = _context("finish", outcome="completed", report_path=Path("/r.html"))
        env = hook_environment(ctx)
        assert env["IOPS_EVENT"] == "finish"
        assert env["IOPS_HOOK"] == "h"
        assert env["IOPS_OUTCOME"] == "completed"
        assert env["IOPS_COMPLETED"] == "5"
        assert env["IOPS_TOTAL"] == "10"
        assert env["IOPS_FAILED"] == "1"
        assert env["IOPS_FAILED_PERCENT"] == "20.0"
        assert env["IOPS_REPORT_PATH"] == "/r.html"
        assert env["IOPS_WORKDIR"] == "/runs/run_001"
        assert env["IOPS_MESSAGE"] == ctx["message"]
        assert all(isinstance(v, str) for v in env.values())

    def test_quote_filter_makes_text_shell_safe(self):
        out = render_hook_command("echo {{ text | quote }}", {"text": "it's \"done\" $HOME"})
        assert out == "echo 'it'\"'\"'s \"done\" $HOME'"

    def test_render_strips_whitespace(self):
        assert render_hook_command("\n  echo {{ x }}  \n", {"x": 1}) == "echo 1"

    def test_render_is_strict(self):
        with pytest.raises(Exception):
            render_hook_command("echo {{ missing }}", {})

    def test_sample_context_renders_every_field(self):
        hook = _hook("finish", when=["crashed"])
        ctx = sample_hook_context(hook, "bench", Path("/w"))
        assert ctx["run"]["outcome"] == "crashed"
        assert ctx["report_path"].endswith("analysis_report.html")
        assert ctx["os_env"]["SURELY_NOT_SET_ANYWHERE"] == ""
        assert ctx["progress"]["total"] == 100

    def test_sample_context_uses_first_threshold(self):
        ctx = sample_hook_context(_hook("progress", at=[_pct(25)]), "bench", Path("/w"))
        assert ctx["event"]["threshold"] == "25%"

    @pytest.mark.parametrize("hook, field, expected", [
        (_hook("progress", at=[_pct(25)]), "completed", 25),
        (_hook("progress", every=_cnt(300)), "completed", 300),
        (_hook("failures", at=[_cnt(7)]), "failed", 7),
        (_hook("failures", at=[_pct(20)]), "failed_percent", 20.0),
        (_hook("consecutive_failures", at=[_cnt(4)]), "consecutive_failures", 4),
    ])
    def test_sample_context_agrees_with_threshold(self, hook, field, expected):
        progress = sample_hook_context(hook, "bench", Path("/w"))["progress"]
        assert progress[field] == expected
        assert progress["completed"] <= progress["total"]
        assert progress["consecutive_failures"] <= progress["failed"]

    def test_sample_context_without_threshold_is_halfway(self):
        progress = sample_hook_context(_hook("start"), "bench", Path("/w"))["progress"]
        assert (progress["completed"], progress["total"]) == (50, 100)

    @pytest.mark.parametrize("hook, text", [
        (_hook("start"), "start"),
        (_hook("progress", at=[_pct(25), _pct(50)], every=_cnt(100)), "progress at 25%, 50%; every 100"),
        (_hook("failures", at=[_pct(5)], min_tests=20), "failures at 5%; min_tests 20"),
        (_hook("failures", at=[_cnt(5)]), "failures at 5"),
        (_hook("finish"), "finish on any outcome"),
        (_hook("finish", when=["completed", "crashed"]), "finish when completed, crashed"),
    ])
    def test_describe_trigger(self, hook, text):
        assert describe_hook_trigger(hook) == text


# ---------------------------------------------------------------------------
# Running commands
# ---------------------------------------------------------------------------

class TestRunHookCommand:

    def test_success_captures_output(self, tmp_path):
        result = run_hook_command(_hook("start"), "echo out; echo err >&2", {}, cwd=tmp_path)
        assert result.ok
        assert result.exit_code == 0
        assert result.stdout.strip() == "out"
        assert result.stderr.strip() == "err"

    def test_nonzero_exit(self, tmp_path):
        result = run_hook_command(_hook("start"), "exit 3", {}, cwd=tmp_path)
        assert not result.ok
        assert result.exit_code == 3

    def test_environment_and_cwd(self, tmp_path):
        result = run_hook_command(_hook("start"), 'echo "$IOPS_EVENT $(pwd)"',
                                  {"IOPS_EVENT": "start"}, cwd=tmp_path)
        assert result.stdout.strip() == f"start {tmp_path.resolve()}"

    def test_missing_cwd_falls_back(self, tmp_path):
        result = run_hook_command(_hook("start"), "true", {}, cwd=tmp_path / "missing")
        assert result.ok

    def test_timeout_kills_the_whole_process_group(self, tmp_path):
        # The background child keeps stdout open; killing only the shell would hang
        hook = _hook("start", timeout=0.5)
        started = time.monotonic()
        result = run_hook_command(hook, "sleep 30 & sleep 30", {}, cwd=tmp_path)
        assert result.timed_out
        assert not result.ok
        assert time.monotonic() - started < 10


class TestHookManagerExecution:

    def test_hooks_run_and_are_logged(self, tmp_path):
        out = tmp_path / "events.txt"
        hooks = [
            _hook("start", name="s", command=f"echo start $IOPS_TOTAL >> {out}"),
            _hook("progress", name="p", at=[_pct(50)],
                  command=f"echo {{{{ event.threshold }}}} >> {out}"),
            _hook("finish", name="e", command=f"echo {{{{ run.outcome }}}} >> {out}"),
        ]
        m = HookManager(hooks, "bench", tmp_path, logging.getLogger("test_hooks"))
        m.start(total=2)
        m.record("SUCCEEDED", total=2)
        m.record("SUCCEEDED", total=2)
        m.finish("completed", total=2)
        assert out.read_text().splitlines() == ["start 2", "50%", "completed"]
        log = (tmp_path / HOOKS_LOG_FILENAME).read_text()
        assert "hook=s event=start threshold=- exit=0" in log
        assert "hook=p event=progress threshold=50% exit=0" in log
        assert "hook=e event=finish" in log
        assert [r.hook for r in m.results] == ["s", "p", "e"]

    def test_failing_hook_is_logged_not_raised(self, tmp_path, caplog):
        m = HookManager([_hook("start", command="echo boom >&2; exit 7")], "bench", tmp_path,
                        logging.getLogger("test_hooks"))
        with caplog.at_level(logging.WARNING, logger="test_hooks"):
            m.start(total=1)
            m.finish("completed")
        assert "exited with code 7: boom" in caplog.text
        log = (tmp_path / HOOKS_LOG_FILENAME).read_text()
        assert "exit=7" in log
        assert "stderr: boom" in log

    def test_render_failure_is_logged_not_raised(self, tmp_path, caplog):
        # Bypasses config validation on purpose
        m = HookManager([_hook("start", command="echo {{ nope }}")], "bench", tmp_path,
                        logging.getLogger("test_hooks"))
        with caplog.at_level(logging.WARNING, logger="test_hooks"):
            m.start(total=1)
            m.finish("completed")
        assert "could not render command" in caplog.text
        assert "error=could not render command" in (tmp_path / HOOKS_LOG_FILENAME).read_text()

    def test_timeout_is_logged(self, tmp_path, caplog):
        m = HookManager([_hook("start", command="sleep 30", timeout=0.3)], "bench", tmp_path,
                        logging.getLogger("test_hooks"))
        with caplog.at_level(logging.WARNING, logger="test_hooks"):
            m.start(total=1)
            m.finish("completed")
        assert "timed out" in caplog.text
        assert "timeout" in (tmp_path / HOOKS_LOG_FILENAME).read_text()

    def test_hooks_do_not_block_the_caller(self, tmp_path):
        m = HookManager([_hook("start", command="sleep 3")], "bench", tmp_path,
                        logging.getLogger("test_hooks"))
        started = time.monotonic()
        m.start(total=1)
        assert time.monotonic() - started < 2
        m.finish("completed")  # waits for the pending hook
        assert time.monotonic() - started >= 2.9
        assert m.results[0].ok

    def test_long_output_is_truncated_in_log(self, tmp_path):
        m = HookManager([_hook("start", command="head -c 10000 /dev/zero | tr '\\0' x")],
                        "bench", tmp_path, logging.getLogger("test_hooks"))
        m.start(total=1)
        m.finish("completed")
        assert "...[truncated]" in (tmp_path / HOOKS_LOG_FILENAME).read_text()

    def test_missing_workdir_skips_log(self, tmp_path):
        m = HookManager([_hook("start")], "bench", tmp_path / "missing",
                        logging.getLogger("test_hooks"))
        m.start(total=1)
        m.finish("completed")
        assert m.results[0].ok
        assert not (tmp_path / "missing").exists()


# ---------------------------------------------------------------------------
# Runner integration
# ---------------------------------------------------------------------------

@pytest.fixture
def hook_run_config(tmp_path, sample_config_dict):
    """
    A local run with 4 tests (nodes 1..4, one repetition) where every test but
    nodes=1 fails, and one hook per event appending to events.txt in the base
    workdir. The planner may shuffle the order, but with three failures out of
    four, two of them are always consecutive.
    """
    config = copy.deepcopy(sample_config_dict)
    config["benchmark"]["repetitions"] = 1
    config["vars"]["nodes"]["sweep"]["values"] = [1, 2, 3, 4]
    config["scripts"][0]["script_template"] = (
        "#!/bin/bash\n"
        "if [ {{ nodes }} -ge 2 ]; then exit 1; fi\n"
        "echo 'result: 100' > {{ execution_dir }}/output.txt\n"
    )
    events = Path(config["benchmark"]["workdir"]) / "events.txt"
    config["hooks"] = [
        {"name": "s", "event": "start", "command": f"echo start $IOPS_TOTAL >> {events}"},
        {"name": "p", "event": "progress", "at": ["50%"],
         "command": f"echo progress {{{{ event.threshold }}}} >> {events}"},
        {"name": "f", "event": "failures", "at": 1,
         "command": f"echo failures {{{{ progress.failed }}}} >> {events}"},
        {"name": "c", "event": "consecutive_failures", "at": 2,
         "command": f"echo streak >> {events}"},
        {"name": "e", "event": "finish",
         "command": f"echo finish {{{{ run.outcome }}}} {{{{ progress.completed }}}} >> {events}"},
    ]
    return _write_config(tmp_path, config), events


def _events(path):
    return path.read_text().splitlines() if path.exists() else []


class TestRunnerIntegration:

    def test_events_fire_in_order(self, hook_run_config):
        config_path, events = hook_run_config
        cfg = load_config(config_path)
        IOPSRunner(cfg, _make_args()).run()
        lines = _events(events)
        assert lines[0] == "start 4"
        assert lines[-1] == "finish completed 4"
        assert sorted(lines[1:-1]) == ["failures 1", "progress 50%", "streak"]
        assert (Path(cfg.benchmark.workdir) / HOOKS_LOG_FILENAME).exists()

    def test_no_hooks_flag_disables_them(self, hook_run_config):
        config_path, events = hook_run_config
        cfg = load_config(config_path)
        runner = IOPSRunner(cfg, _make_args(no_hooks=True))
        assert runner.hooks is None
        runner.run()
        assert _events(events) == []
        assert not (Path(cfg.benchmark.workdir) / HOOKS_LOG_FILENAME).exists()

    def test_mock_args_without_no_hooks_keep_hooks(self, hook_run_config):
        # A Mock attribute is truthy; only a real True disables hooks
        config_path, _ = hook_run_config
        args = _make_args()
        del args.no_hooks
        assert IOPSRunner(load_config(config_path), args).hooks is not None

    def test_runner_without_hooks(self, sample_config_file):
        runner = IOPSRunner(load_config(sample_config_file), _make_args())
        assert runner.hooks is None
        runner.run()

    def test_fail_fast_outcome(self, hook_run_config):
        config_path, events = hook_run_config
        IOPSRunner(load_config(config_path), _make_args(fail_fast=True)).run()
        lines = _events(events)
        assert "failures 1" in lines
        assert "streak" not in lines  # the run stopped at the first failure
        assert lines[-1].startswith("finish fail_fast")

    def test_interrupted_outcome(self, hook_run_config):
        config_path, events = hook_run_config
        runner = IOPSRunner(load_config(config_path), _make_args())
        runner.interrupted = True  # as the SIGINT handler does
        runner.run()
        lines = _events(events)
        assert lines[0].startswith("start")
        assert lines[-1] == "finish interrupted 0"

    def test_budget_exceeded_outcome(self, hook_run_config):
        config_path, events = hook_run_config
        runner = IOPSRunner(load_config(config_path), _make_args(max_core_hours=1.5))
        with patch.object(runner, "_compute_core_hours", return_value=1.0):
            runner.run()
        assert _events(events)[-1] == "finish budget_exceeded 2"

    def test_crashed_outcome_and_exception_propagates(self, hook_run_config):
        config_path, events = hook_run_config
        runner = IOPSRunner(load_config(config_path), _make_args())
        with patch.object(runner, "_run_sequential", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                runner.run()
        assert _events(events)[-1] == "finish crashed 0"

    def test_parallel_run_fires_hooks(self, hook_run_config):
        config_path, events = hook_run_config
        IOPSRunner(load_config(config_path), _make_args(parallel=2)).run()
        lines = _events(events)
        assert lines[0] == "start 4"
        assert "progress 50%" in lines
        assert lines[-1] == "finish completed 4"

    def test_report_path_passed_to_finish(self, tmp_path, sample_config_dict):
        config = _with_hooks(sample_config_dict, [
            {"name": "e", "event": "finish", "command": "echo {{ report_path }} > report_path.txt"},
        ])
        cfg = load_config(_write_config(tmp_path, config))
        runner = IOPSRunner(cfg, _make_args())
        report = Path(cfg.benchmark.workdir) / "analysis_report.html"
        runner.cfg.reporting = ReportingConfig(enabled=True)
        with patch.object(runner, "_generate_report", return_value=report):
            runner.run()
        assert (Path(cfg.benchmark.workdir) / "report_path.txt").read_text().strip() == str(report)

    def test_cache_only_skips_count_as_progress(self, tmp_path, sample_config_dict):
        config = copy.deepcopy(sample_config_dict)
        config["benchmark"]["cache_file"] = str(tmp_path / "empty_cache.db")
        events = tmp_path / "events.txt"
        config["hooks"] = [
            {"name": "p", "event": "progress", "at": ["100%"],
             "command": f"echo {{{{ progress.skipped }}}} >> {events}"},
        ]
        cfg = load_config(_write_config(tmp_path, config))
        IOPSRunner(cfg, _make_args(use_cache=True, cache_only=True)).run()
        assert _events(events) == ["4"]

    def test_dry_run_lists_but_does_not_fire(self, hook_run_config, caplog):
        config_path, events = hook_run_config
        cfg = load_generic_config(config_path, logging.getLogger("test"), dry_run=True)
        runner = IOPSRunner(cfg, _make_args(dry_run=True, log_level="INFO"))
        with caplog.at_level(logging.INFO):
            runner.run_dry()
        assert _events(events) == []
        assert "HOOKS CONFIGURED" in caplog.text
        assert "p: progress at 50%" in caplog.text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_cli(argv):
    with patch.object(sys, "argv", ["iops"] + argv):
        return main()


class TestCli:

    def test_parse_no_hooks(self):
        with patch.object(sys, "argv", ["iops", "run", "c.yaml", "--no-hooks"]):
            assert parse_arguments().no_hooks is True
        with patch.object(sys, "argv", ["iops", "run", "c.yaml"]):
            assert parse_arguments().no_hooks is False

    def test_parse_hooks_test(self):
        argv = ["iops", "hooks", "test", "c.yaml", "--hook", "a", "--hook", "b",
                "--event", "finish", "--render-only"]
        with patch.object(sys, "argv", argv):
            args = parse_arguments()
        assert args.command == "hooks"
        assert args.hooks_command == "test"
        assert args.hook == ["a", "b"]
        assert args.event == "finish"
        assert args.render_only is True

    @pytest.fixture
    def cli_config(self, tmp_path, sample_config_dict):
        out = tmp_path / "fired.txt"
        config = _with_hooks(sample_config_dict, [
            {"name": "ok", "event": "progress", "at": "25%",
             "command": f"echo {{{{ event.threshold }}}} $IOPS_EVENT >> {out}"},
            {"name": "done", "event": "finish", "when": ["crashed"],
             "command": f"echo {{{{ run.outcome }}}} >> {out}"},
            {"name": "bad", "event": "start", "command": "exit 2"},
        ])
        return _write_config(tmp_path, config), out

    def test_hooks_test_runs_selected_hooks(self, cli_config, capsys):
        path, out = cli_config
        rc = _run_cli(["hooks", "test", str(path), "--hook", "ok", "--hook", "done",
                       "--no-log-terminal", "--log-file", str(path.parent / "x.log")])
        assert rc is None
        assert out.read_text().splitlines() == ["25% progress", "crashed"]
        printed = capsys.readouterr().out
        assert "== ok: progress at 25%" in printed
        assert "exit code 0" in printed

    def test_hooks_test_does_not_create_run_folder(self, cli_config, sample_config_dict):
        path, _ = cli_config
        _run_cli(["hooks", "test", str(path), "--hook", "ok", "--no-log-terminal",
                  "--log-file", str(path.parent / "x.log")])
        workdir = Path(sample_config_dict["benchmark"]["workdir"])
        assert not any(p.name.startswith("run_") for p in workdir.iterdir())

    def test_hooks_test_failure_returns_1(self, cli_config, capsys):
        path, _ = cli_config
        rc = _run_cli(["hooks", "test", str(path), "--hook", "bad", "--no-log-terminal",
                       "--log-file", str(path.parent / "x.log")])
        assert rc == 1
        assert "exit code 2" in capsys.readouterr().out

    def test_hooks_test_event_filter(self, cli_config, capsys):
        path, out = cli_config
        _run_cli(["hooks", "test", str(path), "--event", "finish", "--no-log-terminal",
                  "--log-file", str(path.parent / "x.log")])
        assert out.read_text().splitlines() == ["crashed"]

    def test_hooks_test_render_only(self, cli_config, capsys):
        path, out = cli_config
        rc = _run_cli(["hooks", "test", str(path), "--render-only", "--no-log-terminal",
                       "--log-file", str(path.parent / "x.log")])
        assert rc is None
        assert not out.exists()
        printed = capsys.readouterr().out
        assert "command: exit 2" in printed
        assert f"echo 25% $IOPS_EVENT >> {out}" in printed

    def test_hooks_test_unknown_hook(self, cli_config):
        path, _ = cli_config
        rc = _run_cli(["hooks", "test", str(path), "--hook", "nope", "--no-log-terminal",
                       "--log-file", str(path.parent / "x.log")])
        assert rc == 1

    def test_hooks_test_invalid_config(self, tmp_path, sample_config_dict):
        path = _write_config(tmp_path, _with_hooks(sample_config_dict, [
            {"name": "x", "event": "bogus", "command": "true"},
        ]))
        rc = _run_cli(["hooks", "test", str(path), "--no-log-terminal",
                       "--log-file", str(tmp_path / "x.log")])
        assert rc == 1

    def test_hooks_without_subcommand(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # the default log file lands in the cwd
        assert _run_cli(["hooks"]) == 1
