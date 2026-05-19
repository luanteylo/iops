"""Optional, env-gated memory profiler for diagnosing leaks in the runner.

Activate by exporting IOPS_MEMPROFILE=1 before running iops. Snapshots are
taken every IOPS_MEMPROFILE_INTERVAL completed executions (default 10) and a
final diff is logged at end-of-run. Zero overhead when the env var is unset.
"""

from __future__ import annotations

import os
import tracemalloc
from pathlib import Path
from typing import List, Optional, Tuple


def _read_rss_bytes() -> Optional[int]:
    """Return the current process RSS in bytes, or None if unavailable.

    Uses /proc/self/status on Linux to avoid adding a psutil dependency.
    """
    status = Path("/proc/self/status")
    if not status.exists():
        return None
    try:
        for line in status.read_text().splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                return int(parts[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


class MemProfiler:
    """Lightweight tracemalloc + RSS sampler driven by env vars.

    Snapshots are stored only at sampling boundaries (every `interval`
    completions), not per-test, to keep memory overhead bounded.
    """

    def __init__(self) -> None:
        self.enabled = os.environ.get("IOPS_MEMPROFILE", "").lower() in ("1", "true", "yes")
        if not self.enabled:
            return

        try:
            self.interval = max(1, int(os.environ.get("IOPS_MEMPROFILE_INTERVAL", "10")))
        except ValueError:
            self.interval = 10

        try:
            self.top_n = max(1, int(os.environ.get("IOPS_MEMPROFILE_TOP_N", "20")))
        except ValueError:
            self.top_n = 20

        self._samples: List[Tuple[int, tracemalloc.Snapshot, Optional[int]]] = []
        self._initial_rss: Optional[int] = None
        self._peak_rss: Optional[int] = None

        tracemalloc.start(25)
        self._initial_rss = _read_rss_bytes()
        self._peak_rss = self._initial_rss
        self._samples.append((0, tracemalloc.take_snapshot(), self._initial_rss))

    def announce(self, logger) -> None:
        if not self.enabled:
            return
        logger.info(
            f"MemProfiler: enabled (interval={self.interval}, top_n={self.top_n}, "
            f"initial RSS={_fmt(self._initial_rss)})"
        )

    def tick(self, completed_count: int, logger) -> None:
        """Take a snapshot every `interval` completions."""
        if not self.enabled or completed_count <= 0:
            return
        if completed_count % self.interval != 0:
            return

        rss = _read_rss_bytes()
        if rss is not None and (self._peak_rss is None or rss > self._peak_rss):
            self._peak_rss = rss

        snap = tracemalloc.take_snapshot()
        self._samples.append((completed_count, snap, rss))

        delta = rss - self._initial_rss if rss is not None and self._initial_rss is not None else None
        logger.info(
            f"MemProfiler[#{completed_count}]: RSS={_fmt(rss)} "
            f"(delta from start: {_fmt_delta(delta)})"
        )

    def report(self, logger) -> None:
        """Log a final summary: peak RSS plus top allocation diffs vs first snapshot."""
        if not self.enabled or not self._samples:
            return

        rss = _read_rss_bytes()
        if rss is not None and (self._peak_rss is None or rss > self._peak_rss):
            self._peak_rss = rss

        logger.info("=" * 70)
        logger.info("MemProfiler: final report")
        logger.info(f"  Initial RSS: {_fmt(self._initial_rss)}")
        logger.info(f"  Final RSS:   {_fmt(rss)}")
        logger.info(f"  Peak RSS:    {_fmt(self._peak_rss)}")

        first_snap = self._samples[0][1]
        last_snap = tracemalloc.take_snapshot()
        diffs = last_snap.compare_to(first_snap, "lineno")

        logger.info(f"  Top {self.top_n} allocation growth sites (since start):")
        for stat in diffs[: self.top_n]:
            frame = stat.traceback[0]
            logger.info(
                f"    +{_fmt(stat.size_diff)} (count +{stat.count_diff}) "
                f"{frame.filename}:{frame.lineno}"
            )

        tracemalloc.stop()
        logger.info("=" * 70)


def _fmt(n: Optional[int]) -> str:
    if n is None:
        return "n/a"
    sign = "-" if n < 0 else ""
    value = float(abs(n))
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024.0 or unit == "GiB":
            if unit == "B":
                return f"{sign}{int(value)} B"
            return f"{sign}{value:.1f} {unit}"
        value /= 1024.0
    return f"{n} B"


def _fmt_delta(n: Optional[int]) -> str:
    if n is None:
        return "n/a"
    sign = "+" if n >= 0 else ""
    return f"{sign}{_fmt(n)}"
