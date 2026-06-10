"""
Run-root status roll-up: a single aggregate of per-repetition execution status.

Watch mode and ``iops find`` reconstruct live status by scanning every
``exec_XXXX/repetition_N/__iops_status.json`` file on each refresh. For a large
parameter space that is O(folders) filesystem operations per refresh, which
dominates wall-clock on parallel/network filesystems.

This module lets the runner maintain a single ``__iops_status_rollup.json`` in
the run root that mirrors what each per-folder status file contains, keyed by
``exec_key`` and repetition. Consumers can read this one file instead of walking
the tree. The per-folder files remain the source of truth (and the node->runner
IPC channel in single-allocation/kickoff mode); the roll-up is an accelerator
with a folder-scan fallback whenever it is missing, unreadable, or incomplete.

Roll-up file structure::

    {
      "benchmark": "Study Name",
      "repetitions": 3,
      "complete": false,            # true once the runner finishes its loop
      "executions": {
        "exec_0001": {
          "reps": {
            "1": { ...exact per-repetition status_data... },
            "2": { ... }
          }
        }
      }
    }
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from iops.fileutils import atomic_write_json

STATUS_ROLLUP_FILENAME = "__iops_status_rollup.json"


def exec_key_for(execution_id: int) -> str:
    """Build the index/roll-up key for an execution id (e.g. 1 -> 'exec_0001')."""
    return f"exec_{execution_id:04d}"


class StatusRollup:
    """
    Thread-safe writer that aggregates per-repetition status into one file.

    The runner records every status it (or its executor) writes for a
    repetition. A background daemon thread flushes the aggregate atomically,
    coalescing bursts so we never write more often than ``flush_interval``
    seconds regardless of how many transitions occur in between.
    """

    def __init__(
        self,
        run_root: Path | str,
        benchmark_name: str = "",
        repetitions: int = 1,
        flush_interval: float = 2.0,
    ) -> None:
        self._path = Path(run_root) / STATUS_ROLLUP_FILENAME
        self._benchmark = benchmark_name
        self._repetitions = max(1, int(repetitions or 1))
        self._flush_interval = max(0.0, float(flush_interval))

        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._executions: Dict[str, Dict[str, Any]] = {}
        self._dirty = False
        self._complete = False
        self._closed = False

        self._thread = threading.Thread(
            target=self._run, name="iops-status-rollup", daemon=True
        )
        self._thread.start()

    # -------------------------------------------------------------------- #
    # Recording
    # -------------------------------------------------------------------- #
    def record(self, exec_key: str, repetition: int, status_data: Dict[str, Any]) -> None:
        """Record the latest status dict for one repetition of one execution."""
        with self._cv:
            if self._closed:
                return
            entry = self._executions.setdefault(exec_key, {"reps": {}})
            entry["reps"][str(int(repetition))] = dict(status_data)
            self._dirty = True
            self._cv.notify()

    def record_for(self, execution_id: int, repetition: int, status_data: Dict[str, Any]) -> None:
        """Convenience wrapper keyed by numeric execution id."""
        self.record(exec_key_for(execution_id), repetition, status_data)

    # -------------------------------------------------------------------- #
    # Lifecycle
    # -------------------------------------------------------------------- #
    def close(self, complete: bool = True) -> None:
        """
        Mark the roll-up complete (or not) and flush a final time.

        ``complete=True`` tells offline consumers like ``iops find`` that the
        roll-up reflects the finished run and can be trusted without a folder
        scan. On an abrupt kill ``close`` never runs, ``complete`` stays false,
        and consumers fall back to scanning, so correctness is preserved.
        """
        with self._cv:
            if self._closed:
                return
            self._closed = True
            self._complete = complete
            self._dirty = True
            self._cv.notify_all()
        self._thread.join(timeout=10.0)
        # Guarantee the terminal state reached disk even if the worker raced.
        self._flush_once()

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._dirty and not self._closed:
                    self._cv.wait()
                if self._closed:
                    return
                self._dirty = False
            self._flush_once()
            # Coalesce: anything recorded during the sleep flushes on the next
            # pass, so we touch disk at most once per flush_interval.
            if self._flush_interval:
                time.sleep(self._flush_interval)

    def _flush_once(self) -> None:
        with self._lock:
            snapshot = {
                "benchmark": self._benchmark,
                "repetitions": self._repetitions,
                "complete": self._complete,
                "executions": {
                    key: {"reps": dict(entry["reps"])}
                    for key, entry in self._executions.items()
                },
            }
        try:
            atomic_write_json(self._path, snapshot, indent=2, default=str)
        except Exception:
            # Best-effort accelerator: never let a write failure break the run.
            pass


def load_status_rollup(run_root: Path | str) -> Optional[Dict[str, Any]]:
    """
    Load the roll-up for a run root, or None if absent/unreadable.

    Returns the parsed dict (with ``executions``, ``complete``, ...). Callers
    should fall back to a folder scan when this is None.
    """
    path = Path(run_root) / STATUS_ROLLUP_FILENAME
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def rollup_rep_statuses(
    rollup: Optional[Dict[str, Any]], exec_key: str
) -> Optional[list]:
    """
    Return the ordered list of per-repetition status dicts for an execution
    from a loaded roll-up, or None if the roll-up does not cover it.

    Repetitions are ordered by their numeric index so callers see them in the
    same order as sorted ``repetition_*`` folders.
    """
    if not rollup:
        return None
    entry = rollup.get("executions", {}).get(exec_key)
    if entry is None:
        return None
    reps = entry.get("reps", {})

    def _key(rep: str) -> int:
        try:
            return int(rep)
        except (TypeError, ValueError):
            return 0

    return [reps[r] for r in sorted(reps, key=_key)]
