# iops/cache/inspect.py

"""Inspection utilities for IOPS execution cache databases.

Provides functions to list cached entries, resolve git-style hash prefixes,
fetch full entry details, and compute summary statistics. Read-only: these
helpers never mutate the cache.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import sqlite3
import json


# Width used when truncating long parameter/metric values in the default view.
DEFAULT_TRUNCATE_WIDTH = 30

# Length of the short hash shown in listings (matches git's default).
SHORT_HASH_LEN = 8


class HashPrefixError(ValueError):
    """Raised when a hash prefix is ambiguous or has no match."""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Cache database not found: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _truncate(value: str, max_width: int) -> str:
    if len(value) <= max_width:
        return value
    if max_width <= 3:
        return "..."[:max_width] if max_width > 0 else ""
    return "..." + value[-(max_width - 3):]


def _format_metric(value: Any) -> str:
    """Format a metric value for table display."""
    if isinstance(value, float):
        if value == 0 or (abs(value) >= 0.01 and abs(value) < 1e6):
            return f"{value:.2f}"
        return f"{value:.3g}"
    return str(value)


def resolve_hash_prefix(db_path: Path, prefix: str) -> str:
    """Resolve a git-style hash prefix to a full hash.

    Args:
        db_path: Path to the cache database.
        prefix: Hash prefix (at least 1 character).

    Returns:
        The full param_hash.

    Raises:
        HashPrefixError: If no hash matches or multiple hashes match.
    """
    if not prefix:
        raise HashPrefixError("Hash prefix cannot be empty")

    conn = _connect(Path(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT DISTINCT param_hash FROM cached_executions WHERE param_hash LIKE ?",
            (prefix + "%",),
        )
        matches = [row["param_hash"] for row in cursor.fetchall()]
    finally:
        conn.close()

    if not matches:
        raise HashPrefixError(f"No cache entry matches hash prefix '{prefix}'")
    if len(matches) > 1:
        shown = ", ".join(m[:SHORT_HASH_LEN] for m in matches[:5])
        extra = f" (and {len(matches) - 5} more)" if len(matches) > 5 else ""
        raise HashPrefixError(
            f"Hash prefix '{prefix}' is ambiguous: matches {len(matches)} "
            f"entries ({shown}{extra}). Provide a longer prefix."
        )
    return matches[0]


def list_cache_entries(
    db_path: Path,
    param_filters: Optional[Dict[str, str]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """List cached entries, collapsed per unique parameter hash.

    Each returned dict represents one unique parameter set and aggregates
    across repetitions:

        {
            "hash": str,                # full param_hash
            "params": dict,             # parameter values
            "rep_count": int,           # number of cached repetitions
            "repetitions": list[int],   # sorted list of repetition numbers
            "metrics": dict,            # metric name -> mean across reps
            "first_cached": str,        # earliest created_at (ISO string)
            "last_cached": str,         # latest created_at (ISO string)
        }

    Args:
        db_path: Path to the cache database.
        param_filters: Optional VAR=VALUE filters. Values are compared as
            strings against the stringified parameter values (same semantics
            as ``iops find``).
        limit: Maximum number of entries to return (applied after filtering).

    Returns:
        List of per-hash summary dicts, sorted by last_cached descending.
    """
    conn = _connect(Path(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT param_hash, params_json, repetition, metrics_json, created_at
            FROM cached_executions
            ORDER BY created_at ASC
            """
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        h = row["param_hash"]
        params = json.loads(row["params_json"]) if row["params_json"] else {}
        metrics = json.loads(row["metrics_json"]) if row["metrics_json"] else {}
        created_at = row["created_at"]

        if h not in grouped:
            grouped[h] = {
                "hash": h,
                "params": params,
                "repetitions": [],
                "_metric_lists": {},
                "first_cached": created_at,
                "last_cached": created_at,
            }
        entry = grouped[h]
        entry["repetitions"].append(row["repetition"])
        if created_at < entry["first_cached"]:
            entry["first_cached"] = created_at
        if created_at > entry["last_cached"]:
            entry["last_cached"] = created_at

        for metric_name, metric_value in metrics.items():
            if isinstance(metric_value, (int, float)):
                entry["_metric_lists"].setdefault(metric_name, []).append(
                    float(metric_value)
                )

    results = []
    for entry in grouped.values():
        metric_means = {
            name: sum(vals) / len(vals)
            for name, vals in entry["_metric_lists"].items()
            if vals
        }
        reps_sorted = sorted(entry["repetitions"])
        results.append({
            "hash": entry["hash"],
            "params": entry["params"],
            "rep_count": len(reps_sorted),
            "repetitions": reps_sorted,
            "metrics": metric_means,
            "first_cached": entry["first_cached"],
            "last_cached": entry["last_cached"],
        })

    if param_filters:
        def matches(entry: Dict[str, Any]) -> bool:
            for key, expected in param_filters.items():
                if key not in entry["params"]:
                    return False
                if str(entry["params"][key]) != str(expected):
                    return False
            return True
        results = [e for e in results if matches(e)]

    results.sort(key=lambda e: e["last_cached"], reverse=True)

    if limit is not None:
        results = results[:limit]

    return results


def get_cache_entry(db_path: Path, hash_prefix: str) -> Dict[str, Any]:
    """Fetch full details for a single cached parameter set.

    Args:
        db_path: Path to the cache database.
        hash_prefix: Full hash or git-style prefix.

    Returns:
        Dict with shape::

            {
                "hash": str,
                "params": dict,
                "repetitions": [
                    {
                        "repetition": int,
                        "metrics": dict,
                        "metadata": dict,
                        "created_at": str,
                    },
                    ...
                ],
            }

    Raises:
        HashPrefixError: If the prefix is ambiguous or has no match.
    """
    full_hash = resolve_hash_prefix(db_path, hash_prefix)

    conn = _connect(Path(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT params_json, repetition, metrics_json, metadata_json, created_at
            FROM cached_executions
            WHERE param_hash = ?
            ORDER BY repetition ASC, created_at ASC
            """,
            (full_hash,),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    params: Dict[str, Any] = {}
    repetitions = []
    for row in rows:
        if not params and row["params_json"]:
            params = json.loads(row["params_json"])
        repetitions.append({
            "repetition": row["repetition"],
            "metrics": json.loads(row["metrics_json"]) if row["metrics_json"] else {},
            "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            "created_at": row["created_at"],
        })

    return {"hash": full_hash, "params": params, "repetitions": repetitions}


def get_cache_stats(db_path: Path) -> Dict[str, Any]:
    """Compute summary statistics for a cache database.

    Args:
        db_path: Path to the cache database.

    Returns:
        Dict with total_entries, unique_parameter_sets, oldest_entry,
        newest_entry, total_repetitions, and db_path.
    """
    conn = _connect(Path(db_path))
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) AS c FROM cached_executions")
        total_entries = cursor.fetchone()["c"]

        cursor.execute(
            "SELECT COUNT(DISTINCT param_hash) AS c FROM cached_executions"
        )
        unique_params = cursor.fetchone()["c"]

        cursor.execute(
            "SELECT MIN(created_at) AS oldest, MAX(created_at) AS newest "
            "FROM cached_executions"
        )
        row = cursor.fetchone()
        oldest = row["oldest"]
        newest = row["newest"]

        cursor.execute(
            "SELECT COUNT(DISTINCT repetition) AS c FROM cached_executions"
        )
        distinct_reps = cursor.fetchone()["c"]
    finally:
        conn.close()

    return {
        "db_path": str(Path(db_path)),
        "total_entries": total_entries,
        "unique_parameter_sets": unique_params,
        "distinct_repetitions": distinct_reps,
        "oldest_entry": oldest,
        "newest_entry": newest,
    }


# ---------------------------------------------------------------------------
# Display helpers (CLI)
# ---------------------------------------------------------------------------


def display_cache_list(
    entries: List[Dict[str, Any]],
    show_full: bool = False,
    hide_metrics: bool = False,
) -> None:
    """Print a tabular view of cache entries (one row per unique hash)."""
    if not entries:
        print("No cache entries match.")
        return

    truncate_width = None if show_full else DEFAULT_TRUNCATE_WIDTH

    def dv(val: str) -> str:
        return val if truncate_width is None else _truncate(val, truncate_width)

    var_names: List[str] = sorted({k for e in entries for k in e["params"].keys()})

    metric_names: List[str] = []
    if not hide_metrics:
        metric_names = sorted({m for e in entries for m in e["metrics"].keys()})

    headers = ["Hash"] + var_names + ["Reps"] + metric_names + ["Last Cached"]

    rows: List[List[str]] = []
    for e in entries:
        row = [e["hash"][:SHORT_HASH_LEN]]
        for v in var_names:
            row.append(dv(str(e["params"].get(v, ""))))
        row.append(str(e["rep_count"]))
        for m in metric_names:
            if m in e["metrics"]:
                row.append(dv(_format_metric(e["metrics"][m])))
            else:
                row.append("-")
        row.append(e["last_cached"][:19])  # trim microseconds
        rows.append(row)

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if len(cell) > widths[i]:
                widths[i] = len(cell)

    header_line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("-" * len(header_line))
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))

    print(f"\n{len(entries)} unique parameter set(s)")


def display_cache_entry(entry: Dict[str, Any], show_full: bool = False) -> None:
    """Print full details of a single cache entry, including every repetition."""
    print(f"Hash: {entry['hash']}")
    print(f"Short: {entry['hash'][:SHORT_HASH_LEN]}")

    print("\nParameters:")
    for key in sorted(entry["params"].keys()):
        val = str(entry["params"][key])
        if not show_full:
            val = _truncate(val, 60)
        print(f"  {key}: {val}")

    reps = entry.get("repetitions", [])
    print(f"\nRepetitions: {len(reps)}")

    if not reps:
        return

    for rep in reps:
        print(f"\n  rep={rep['repetition']}  cached_at={rep['created_at']}")
        if rep["metrics"]:
            print("    metrics:")
            for name in sorted(rep["metrics"].keys()):
                val = rep["metrics"][name]
                val_str = _format_metric(val) if isinstance(val, (int, float)) else str(val)
                if not show_full:
                    val_str = _truncate(val_str, 60)
                print(f"      {name}: {val_str}")
        if rep["metadata"]:
            print("    metadata:")
            for name in sorted(rep["metadata"].keys()):
                val_str = str(rep["metadata"][name])
                if not show_full:
                    val_str = _truncate(val_str, 60)
                print(f"      {name}: {val_str}")


def display_cache_stats(stats: Dict[str, Any]) -> None:
    """Print cache summary statistics."""
    print(f"Cache: {stats['db_path']}")
    print("-" * 50)
    print(f"Total entries:          {stats['total_entries']}")
    print(f"Unique parameter sets:  {stats['unique_parameter_sets']}")
    print(f"Distinct repetitions:   {stats['distinct_repetitions']}")
    print(f"Oldest entry:           {stats['oldest_entry'] or '(empty)'}")
    print(f"Newest entry:           {stats['newest_entry'] or '(empty)'}")
