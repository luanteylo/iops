"""
Regression tests for CLI and watch mode fixes.

Covers:
- Bare 'iops archive' / 'iops cache' reaching the friendly no-subcommand
  message instead of crashing in initialize_logger
- --interval validation for 'iops find'
- Parameter filter value matching (floats, bools, scientific notation)
- Safe parsing of the cores expression (no eval)
- Escape sequence handling in _KeyboardContext.read_key (PageUp/PageDown)
- /dev/tty fallback when stdin is unusable
- Display item construction used by the watch search ('/') handler
- Logger formatter handling of messages that contain ' | '
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import pytest

from iops.logger import setup_logger
from iops.main import initialize_logger, main, parse_arguments
from iops.results.find import param_value_matches
from iops.results import watch


# ---------------------------------------------------------------------------
# param_value_matches (shared filter helper)
# ---------------------------------------------------------------------------

class TestParamValueMatches:
    def test_exact_string_match(self):
        assert param_value_matches("abc", "abc")

    def test_string_mismatch(self):
        assert not param_value_matches("abc", "abd")

    def test_int_matches_string(self):
        assert param_value_matches(4, "4")

    def test_float_matches_int_string(self):
        # "block=4" should match a stored 4.0
        assert param_value_matches(4.0, "4")

    def test_int_matches_float_string(self):
        assert param_value_matches(4, "4.0")

    def test_scientific_notation(self):
        assert param_value_matches(1000.0, "1e3")
        assert param_value_matches(0.001, "1e-3")

    def test_numeric_mismatch(self):
        assert not param_value_matches(4.0, "5")

    def test_bool_true_case_insensitive(self):
        assert param_value_matches(True, "true")
        assert param_value_matches(True, "True")
        assert param_value_matches(True, "TRUE")

    def test_bool_false_case_insensitive(self):
        assert param_value_matches(False, "false")
        assert param_value_matches(False, "False")

    def test_bool_mismatch(self):
        assert not param_value_matches(True, "false")
        assert not param_value_matches(False, "true")

    def test_string_bool_value(self):
        # Params stored as strings should still match boolean filters
        assert param_value_matches("True", "true")
        assert param_value_matches("false", "FALSE")

    def test_non_numeric_strings_do_not_match(self):
        assert not param_value_matches("foo", "bar")

    def test_list_value_does_not_crash(self):
        assert not param_value_matches([1, 2], "3")
        assert param_value_matches([1, 2], "[1, 2]")


class TestCollectExecutionDataFilters:
    """Integration of param_value_matches into watch's data collection."""

    def test_float_param_matches_int_filter(self, tmp_path):
        executions = {
            "exec_0001": {"path": "runs/exec_0001", "params": {"block": 4.0}, "command": ""},
            "exec_0002": {"path": "runs/exec_0002", "params": {"block": 8.0}, "command": ""},
        }
        tests, _ = watch._collect_execution_data(
            tmp_path, executions, {"block": "4"}, None, set(),
            expected_repetitions=1,
        )
        assert len(tests) == 1
        assert tests[0]["exec_key"] == "exec_0001"

    def test_bool_param_matches_filter(self, tmp_path):
        executions = {
            "exec_0001": {"path": "runs/exec_0001", "params": {"flag": True}, "command": ""},
            "exec_0002": {"path": "runs/exec_0002", "params": {"flag": False}, "command": ""},
        }
        tests, _ = watch._collect_execution_data(
            tmp_path, executions, {"flag": "true"}, None, set(),
            expected_repetitions=1,
        )
        assert len(tests) == 1
        assert tests[0]["exec_key"] == "exec_0001"


# ---------------------------------------------------------------------------
# --interval validation
# ---------------------------------------------------------------------------

class TestIntervalValidation:
    def _parse(self, monkeypatch, argv):
        monkeypatch.setattr(sys, "argv", ["iops"] + argv)
        return parse_arguments()

    def test_interval_zero_rejected(self, monkeypatch, capsys):
        with pytest.raises(SystemExit):
            self._parse(monkeypatch, ["find", ".", "--watch", "--interval", "0"])
        assert "--interval" in capsys.readouterr().err

    def test_interval_negative_rejected(self, monkeypatch, capsys):
        with pytest.raises(SystemExit):
            self._parse(monkeypatch, ["find", ".", "--watch", "--interval", "-3"])
        assert "--interval" in capsys.readouterr().err

    def test_interval_valid(self, monkeypatch):
        args = self._parse(monkeypatch, ["find", ".", "--watch", "--interval", "2"])
        assert args.interval == 2

    def test_interval_default(self, monkeypatch):
        args = self._parse(monkeypatch, ["find", "."])
        assert args.interval == 5


# ---------------------------------------------------------------------------
# Bare 'iops archive' / 'iops cache'
# ---------------------------------------------------------------------------

class TestBareSubcommands:
    def test_initialize_logger_without_common_args(self, tmp_path, monkeypatch):
        # Namespace lacking log_file/log_level/no_log_terminal must not crash
        monkeypatch.chdir(tmp_path)
        args = argparse.Namespace(command="archive", archive_command=None)
        logger = initialize_logger(args)
        assert logger is not None
        for handler in logger.handlers:
            handler.close()
        logger.handlers.clear()

    @pytest.mark.parametrize("command,expected", [
        ("archive", "No archive subcommand specified"),
        ("cache", "No cache subcommand specified"),
    ])
    def test_bare_command_shows_friendly_message(self, command, expected,
                                                 tmp_path, monkeypatch, caplog):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["iops", command])
        with caplog.at_level(logging.INFO, logger="iops"):
            main()  # must not raise AttributeError
        assert expected in caplog.text
        # Cleanup handlers created by setup_logger
        logger = logging.getLogger("iops")
        for handler in logger.handlers:
            handler.close()
        logger.handlers.clear()


# ---------------------------------------------------------------------------
# Safe cores parsing (no eval)
# ---------------------------------------------------------------------------

class TestParseCoresValue:
    def test_plain_int(self):
        assert watch._parse_cores_value("8") == 8

    def test_whitespace(self):
        assert watch._parse_cores_value("  12  ") == 12

    def test_float_is_rounded(self):
        assert watch._parse_cores_value("7.6") == 8
        assert watch._parse_cores_value("7.4") == 7

    def test_non_numeric_returns_none(self):
        assert watch._parse_cores_value("abc") is None
        assert watch._parse_cores_value("") is None
        assert watch._parse_cores_value("2*4") is None

    def test_infinity_returns_none(self):
        assert watch._parse_cores_value("inf") is None


class TestComputeCoresFromExpr:
    def test_simple_expression(self):
        assert watch._compute_cores_from_expr("{{ nodes * ppn }}", {"nodes": 2, "ppn": 4}) == 8

    def test_minimum_one(self):
        assert watch._compute_cores_from_expr("{{ nodes }}", {"nodes": 0}) == 1

    def test_empty_expression(self):
        assert watch._compute_cores_from_expr("", {}) == 1

    def test_python_code_is_not_evaluated(self, tmp_path):
        # A metadata file could contain arbitrary text; it must never be
        # executed as Python. Without Jinja braces the template renders to
        # itself, which must fail numeric parsing and fall back to 1.
        marker = tmp_path / "pwned"
        expr = f"__import__('pathlib').Path('{marker}').write_text('x')"
        assert watch._compute_cores_from_expr(expr, {}) == 1
        assert not marker.exists()

    def test_arithmetic_text_not_evaluated(self):
        # Jinja already evaluates expressions; literal arithmetic text in the
        # rendered output must not be eval'd.
        assert watch._compute_cores_from_expr("2*4", {}) == 1


# ---------------------------------------------------------------------------
# read_key escape sequence handling
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not watch.UNIX_TERMINAL, reason="Requires Unix terminal support")
class TestReadKeyEscapeSequences:
    @pytest.fixture
    def kb_pipe(self):
        kb = watch._KeyboardContext()
        r, w = os.pipe()
        kb.fd = r
        yield kb, w
        kb.fd = None
        os.close(r)
        os.close(w)

    def test_regular_key(self, kb_pipe):
        kb, w = kb_pipe
        os.write(w, b"q")
        assert kb.read_key(0.1) == "q"

    def test_arrow_keys_still_work(self, kb_pipe):
        kb, w = kb_pipe
        os.write(w, b"\x1b[A")
        assert kb.read_key(0.1) == "\x1b[A"
        os.write(w, b"\x1b[B")
        assert kb.read_key(0.1) == "\x1b[B"

    def test_page_down_full_sequence(self, kb_pipe):
        kb, w = kb_pipe
        os.write(w, b"\x1b[6~")
        assert kb.read_key(0.1) == "\x1b[6~"
        # No leftover "~" consumed as a spurious key
        assert kb.read_key(0.05) is None

    def test_page_up_full_sequence(self, kb_pipe):
        kb, w = kb_pipe
        os.write(w, b"\x1b[5~")
        assert kb.read_key(0.1) == "\x1b[5~"
        assert kb.read_key(0.05) is None

    def test_key_following_page_down_not_swallowed(self, kb_pipe):
        kb, w = kb_pipe
        os.write(w, b"\x1b[6~q")
        assert kb.read_key(0.1) == "\x1b[6~"
        assert kb.read_key(0.1) == "q"

    def test_bare_escape(self, kb_pipe):
        kb, w = kb_pipe
        os.write(w, b"\x1b")
        assert kb.read_key(0.1) == "\x1b"


# ---------------------------------------------------------------------------
# /dev/tty fallback when stdin is unusable
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not watch.UNIX_TERMINAL, reason="Requires Unix terminal support")
class TestKeyboardContextFallback:
    def test_fallback_attempted_when_stdin_fileno_raises(self, monkeypatch):
        opened = []

        class BadStdin:
            def fileno(self):
                raise ValueError("I/O operation on closed file")

        def fake_open(path, flags):
            opened.append(path)
            raise OSError("no controlling terminal")

        monkeypatch.setattr(watch.sys, "stdin", BadStdin())
        monkeypatch.setattr(watch.os, "open", fake_open)

        kb = watch._KeyboardContext()
        kb.__enter__()
        try:
            assert "/dev/tty" in opened
            assert kb.fd is None
            assert not kb.available
        finally:
            kb.__exit__()

    def test_fallback_attempted_when_stdin_not_a_tty(self, monkeypatch):
        opened = []

        def fake_open(path, flags):
            opened.append(path)
            raise OSError("no controlling terminal")

        monkeypatch.setattr(watch.os, "isatty", lambda fd: False)
        monkeypatch.setattr(watch.os, "open", fake_open)

        kb = watch._KeyboardContext()
        kb.__enter__()
        try:
            assert "/dev/tty" in opened
        finally:
            kb.__exit__()


# ---------------------------------------------------------------------------
# Display items / search index correctness
# ---------------------------------------------------------------------------

def _make_test(exec_id, statuses):
    return {
        "exec_key": f"exec_{exec_id:04d}",
        "rel_path": f"runs/exec_{exec_id:04d}",
        "params": {},
        "command": "",
        "rep_statuses": statuses,
    }


class TestBuildDisplayItems:
    def test_all_items_when_not_filtering(self):
        tests = [_make_test(i, ["SUCCEEDED"]) for i in range(1, 4)]
        items = watch._build_display_items(tests, show_only_active=False,
                                           total_expected_configs=5)
        assert [item[0] for item in items] == [1, 2, 3, 4, 5]
        # 4 and 5 are queued placeholders
        assert items[3][2] is True
        assert items[4][2] is True

    def test_show_only_active_drops_succeeded_and_queued(self):
        tests = [
            _make_test(1, ["SUCCEEDED"]),
            _make_test(2, ["RUNNING"]),
            _make_test(3, ["SUCCEEDED"]),
            _make_test(4, ["PENDING"]),
        ]
        items = watch._build_display_items(tests, show_only_active=True,
                                           total_expected_configs=6)
        assert [item[0] for item in items] == [2, 4]

    def test_search_index_matches_exec_id_with_hidden_rows(self):
        # Regression: the '/' search must find exec 4 at display index 1,
        # not assume display index = exec id - 1 (which would be 3).
        tests = [
            _make_test(1, ["SUCCEEDED"]),
            _make_test(2, ["RUNNING"]),
            _make_test(3, ["SUCCEEDED"]),
            _make_test(4, ["PENDING"]),
        ]
        items = watch._build_display_items(tests, show_only_active=True,
                                           total_expected_configs=4)
        target_id = 4
        found_idx = None
        for idx, (exec_id, _, _, _) in enumerate(items):
            if exec_id == target_id:
                found_idx = idx
                break
        assert found_idx == 1

    def test_search_id_not_in_display_returns_none(self):
        tests = [
            _make_test(1, ["SUCCEEDED"]),
            _make_test(2, ["RUNNING"]),
        ]
        items = watch._build_display_items(tests, show_only_active=True,
                                           total_expected_configs=2)
        # exec 1 is hidden (SUCCEEDED), so a search for it finds nothing
        assert all(exec_id != 1 for exec_id, _, _, _ in items)

    def test_ids_beyond_estimate_are_kept(self):
        tests = [_make_test(i, ["RUNNING"]) for i in (1, 7)]
        items = watch._build_display_items(tests, show_only_active=False,
                                           total_expected_configs=3)
        assert [item[0] for item in items] == [1, 2, 3, 4, 5, 6, 7]


# ---------------------------------------------------------------------------
# Logger formatter: messages containing " | "
# ---------------------------------------------------------------------------

class TestLoggerFormatter:
    def _capture(self, tmp_path, message, name):
        log_file = tmp_path / "test.log"
        logger = setup_logger(name=name, log_file=log_file,
                              to_stdout=False, to_file=True)
        logger.info(message)
        for handler in logger.handlers:
            handler.close()
        logger.handlers.clear()
        return log_file.read_text().splitlines()

    def test_message_with_pipes_not_duplicated(self, tmp_path):
        lines = self._capture(tmp_path, "exec_0001 | bw=100.0 | lat=0.5",
                              name="iops_test_pipes")
        assert len(lines) == 1
        # The full message must appear after the prefix, intact
        prefix, _, body = lines[0].partition(" | INFO  | ")
        assert body == "exec_0001 | bw=100.0 | lat=0.5"

    def test_multiline_message_with_pipes(self, tmp_path):
        lines = self._capture(tmp_path,
                              "metrics | bw=100 | lat=5\nsecond line",
                              name="iops_test_multiline")
        assert len(lines) == 2
        body0 = lines[0].partition(" | INFO  | ")[2]
        body1 = lines[1].partition(" | INFO  | ")[2]
        assert body0 == "metrics | bw=100 | lat=5"
        # Continuation line must contain only its own text, with no part of
        # the first line absorbed into its prefix
        assert body1 == "second line"

    def test_plain_message_unchanged(self, tmp_path):
        lines = self._capture(tmp_path, "hello world", name="iops_test_plain")
        assert len(lines) == 1
        assert lines[0].endswith(" | INFO  | hello world")

    def test_long_message_is_wrapped_with_prefix(self, tmp_path):
        message = "word " * 50  # > 100 chars, forces wrapping
        lines = self._capture(tmp_path, message.strip(), name="iops_test_wrap")
        assert len(lines) > 1
        for line in lines:
            assert " | INFO  | " in line
