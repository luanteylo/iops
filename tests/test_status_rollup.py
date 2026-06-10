"""
Tests for the run-root status roll-up (__iops_status_rollup.json).

The roll-up lets watch and `iops find` read one aggregate file instead of
scanning every execution's repetition folders. These tests cover the writer
helper in isolation and verify that the watch/find consumers produce identical
results whether they read the roll-up or fall back to the folder scan.
"""

import json
import logging
import time
from pathlib import Path

import pytest

from iops.results.status_rollup import (
    STATUS_ROLLUP_FILENAME,
    StatusRollup,
    exec_key_for,
    load_status_rollup,
    rollup_rep_statuses,
)
from iops.results import find as find_mod
from iops.results import watch as watch_mod

# Reuse the end-to-end mock-benchmark harness from the integration tests.
from test_integration_workflow import (  # noqa: E402
    MockArgs,
    create_mock_config,
    get_run_dir,
    mock_workdir,
    mock_config_file,
)
from iops.config.loader import load_generic_config
from iops.execution.runner import IOPSRunner

logging.getLogger("iops").setLevel(logging.WARNING)


# ============================================================================ #
# Writer / helper unit tests
# ============================================================================ #

class TestStatusRollupWriter:
    def test_records_and_flushes_on_close(self, tmp_path):
        rollup = StatusRollup(tmp_path, benchmark_name="B", repetitions=2)
        rollup.record("exec_0001", 1, {"status": "SUCCEEDED", "metrics": {"x": 1.0}})
        rollup.record("exec_0001", 2, {"status": "FAILED", "error": "boom"})
        rollup.record("exec_0002", 1, {"status": "RUNNING"})
        rollup.close(complete=True)

        data = load_status_rollup(tmp_path)
        assert data is not None
        assert data["benchmark"] == "B"
        assert data["repetitions"] == 2
        assert data["complete"] is True
        assert set(data["executions"]) == {"exec_0001", "exec_0002"}
        assert data["executions"]["exec_0001"]["reps"]["1"]["status"] == "SUCCEEDED"
        assert data["executions"]["exec_0001"]["reps"]["2"]["error"] == "boom"

    def test_background_flush_before_close(self, tmp_path):
        rollup = StatusRollup(tmp_path, flush_interval=0.05)
        try:
            rollup.record("exec_0001", 1, {"status": "RUNNING"})
            # The daemon flusher should write without waiting for close().
            deadline = time.monotonic() + 5.0
            path = tmp_path / STATUS_ROLLUP_FILENAME
            while not path.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert path.exists(), "background flush never wrote the roll-up"
            data = load_status_rollup(tmp_path)
            assert data["complete"] is False
            assert data["executions"]["exec_0001"]["reps"]["1"]["status"] == "RUNNING"
        finally:
            rollup.close()

    def test_latest_record_wins(self, tmp_path):
        rollup = StatusRollup(tmp_path)
        rollup.record("exec_0001", 1, {"status": "RUNNING"})
        rollup.record("exec_0001", 1, {"status": "SUCCEEDED", "duration_seconds": 3.0})
        rollup.close()
        data = load_status_rollup(tmp_path)
        reps = data["executions"]["exec_0001"]["reps"]
        assert reps["1"]["status"] == "SUCCEEDED"
        assert reps["1"]["duration_seconds"] == 3.0

    def test_record_after_close_is_ignored(self, tmp_path):
        rollup = StatusRollup(tmp_path)
        rollup.close()
        rollup.record("exec_0009", 1, {"status": "SUCCEEDED"})
        data = load_status_rollup(tmp_path)
        assert "exec_0009" not in data["executions"]


class TestRollupHelpers:
    def test_exec_key_for(self):
        assert exec_key_for(1) == "exec_0001"
        assert exec_key_for(42) == "exec_0042"

    def test_rollup_rep_statuses_orders_by_rep_number(self):
        rollup = {
            "executions": {
                "exec_0001": {"reps": {"2": {"status": "B"}, "10": {"status": "C"}, "1": {"status": "A"}}}
            }
        }
        reps = rollup_rep_statuses(rollup, "exec_0001")
        assert [r["status"] for r in reps] == ["A", "B", "C"]

    def test_rollup_rep_statuses_missing(self):
        assert rollup_rep_statuses(None, "exec_0001") is None
        assert rollup_rep_statuses({"executions": {}}, "exec_0001") is None

    def test_load_missing_returns_none(self, tmp_path):
        assert load_status_rollup(tmp_path) is None

    def test_load_corrupt_returns_none(self, tmp_path):
        (tmp_path / STATUS_ROLLUP_FILENAME).write_text("{not json")
        assert load_status_rollup(tmp_path) is None


# ============================================================================ #
# End-to-end: roll-up is produced and consumers reach parity with folder scan
# ============================================================================ #

def _run_mock(mock_workdir, mock_config_file, repetitions=2):
    config_content = create_mock_config(
        workdir=str(mock_workdir),
        search_method="exhaustive",
        repetitions=repetitions,
        collect_system_info=False,
    )
    config_file = mock_config_file(config_content)
    cfg = load_generic_config(config_file, logging.getLogger("test"))
    IOPSRunner(cfg, MockArgs()).run()
    return get_run_dir(mock_workdir)


class TestRollupEndToEnd:
    def test_rollup_written_and_complete(self, mock_workdir, mock_config_file):
        run_dir = _run_mock(mock_workdir, mock_config_file, repetitions=2)

        data = load_status_rollup(run_dir)
        assert data is not None, "roll-up file was not written"
        assert data["complete"] is True
        # 3 * 2 = 6 configs, each with 2 repetitions, all succeeded.
        assert len(data["executions"]) == 6
        for entry in data["executions"].values():
            reps = entry["reps"]
            assert len(reps) == 2
            assert all(r["status"] == "SUCCEEDED" for r in reps.values())

    def test_watch_parity_rollup_vs_scan(self, mock_workdir, mock_config_file):
        run_dir = _run_mock(mock_workdir, mock_config_file, repetitions=2)
        index = json.loads((run_dir / "__iops_index.json").read_text())
        executions = index["executions"]

        def collect():
            return watch_mod._collect_execution_data(
                run_dir, executions, {}, None, set(), expected_repetitions=2
            )

        # With the roll-up present (fast path).
        tests_rollup, counts_rollup = collect()

        # Force the folder-scan fallback by hiding the roll-up.
        (run_dir / STATUS_ROLLUP_FILENAME).rename(run_dir / "_hidden_rollup.json")
        tests_scan, counts_scan = collect()

        assert counts_rollup == counts_scan
        assert tests_rollup == tests_scan
        assert counts_rollup["SUCCEEDED"] == 12  # 6 configs * 2 reps

    def test_find_parity_rollup_vs_scan(self, mock_workdir, mock_config_file):
        run_dir = _run_mock(mock_workdir, mock_config_file, repetitions=2)
        index = json.loads((run_dir / "__iops_index.json").read_text())
        exec_key, exec_data = sorted(index["executions"].items())[0]
        exec_path = run_dir / exec_data["path"]

        rollup = load_status_rollup(run_dir)
        assert rollup and rollup.get("complete")

        from_rollup = find_mod._read_status(exec_path, rollup=rollup, exec_key=exec_key)
        from_scan = find_mod._read_status(exec_path)
        assert from_rollup == from_scan
        assert from_rollup["status"] == "SUCCEEDED"
