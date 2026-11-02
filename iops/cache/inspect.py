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

from .execution_cache import (
    COMMANDS_TABLE_NAME,
    get_schema_version,
    has_commands_table,
    has_fingerprint_column,
)


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


def _fingerprint_select(conn: sqlite3.Connection) -> str:
    """SELECT expression for the fingerprint, valid on caches older than schema v1."""
    if has_fingerprint_column(conn):
        return "command_fingerprint"
    return "NULL AS command_fingerprint"


def _load_commands(conn: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    """Map each fingerprint to its stored command text (empty for older caches)."""
    if not has_commands_table(conn):
        return {}
    rows = conn.execute(
        f"SELECT fingerprint, template, env_json, first_seen FROM {COMMANDS_TABLE_NAME}"
    ).fetchall()
    return {
        row["fingerprint"]: {
            "template": row["template"],
            "env": json.loads(row["env_json"]) if row["env_json"] else {},
            "first_seen": row["first_seen"],
        }
        for row in rows
    }


def _one_line(text: str, max_width: int) -> str:
    """Collapse whitespace so a multi-line template fits on one table line."""
    flat = " ".join(text.split())
    if len(flat) <= max_width:
        return flat
    return flat[:max_width - 3] + "..."


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
    """List cached entries, collapsed per parameter set and command.

    Each returned dict represents one unique parameter set recorded with one
    command, and aggregates across repetitions. Results for the same
    parameters measured with different commands are listed separately, so
    repetition counts and metric means never mix commands:

        {
            "hash": str,                # full param_hash
            "params": dict,             # parameter values
            "command_fingerprint": str or None,  # None: unknown command
            "command": str or None,     # command.template, if stored
            "rep_count": int,           # number of distinct cached repetitions
            "repetitions": list[int],   # sorted distinct repetition numbers
            "entries": int,             # stored rows (rebuilt caches may hold
                                        # several per repetition)
            "metrics": dict,            # metric name -> mean across entries
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
        List of per-(hash, command) summary dicts, sorted by last_cached
        descending.
    """
    conn = _connect(Path(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT param_hash, params_json, repetition, metrics_json, created_at,
                   {_fingerprint_select(conn)}
            FROM cached_executions
            ORDER BY created_at ASC
            """
        )
        rows = cursor.fetchall()
        known_commands = _load_commands(conn)
    finally:
        conn.close()

    grouped: Dict[tuple, Dict[str, Any]] = {}
    for row in rows:
        h = row["param_hash"]
        fp = row["command_fingerprint"]
        params = json.loads(row["params_json"]) if row["params_json"] else {}
        metrics = json.loads(row["metrics_json"]) if row["metrics_json"] else {}
        created_at = row["created_at"]

        key = (h, fp)
        if key not in grouped:
            grouped[key] = {
                "hash": h,
                "params": params,
                "command_fingerprint": fp,
                "repetitions": [],
                "_metric_lists": {},
                "first_cached": created_at,
                "last_cached": created_at,
            }
        entry = grouped[key]
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
        reps_sorted = sorted(set(entry["repetitions"]))
        fp = entry["command_fingerprint"]
        results.append({
            "hash": entry["hash"],
            "params": entry["params"],
            "command_fingerprint": fp,
            "command": known_commands.get(fp, {}).get("template") if fp else None,
            "rep_count": len(reps_sorted),
            "repetitions": reps_sorted,
            "entries": len(entry["repetitions"]),
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
                        "command_fingerprint": str or None,
                    },
                    ...
                ],
                "commands": {
                    fingerprint: {"template": str, "env": dict, "first_seen": str},
                    ...
                },
            }

        ``commands`` holds the stored command text for the fingerprints of
        this entry. A fingerprint can be missing from it when its results
        were stored before IOPS kept the command text.

    Raises:
        HashPrefixError: If the prefix is ambiguous or has no match.
    """
    full_hash = resolve_hash_prefix(db_path, hash_prefix)

    conn = _connect(Path(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT params_json, repetition, metrics_json, metadata_json, created_at,
                   {_fingerprint_select(conn)}
            FROM cached_executions
            WHERE param_hash = ?
            ORDER BY repetition ASC, created_at ASC
            """,
            (full_hash,),
        )
        rows = cursor.fetchall()
        known_commands = _load_commands(conn)
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
            "command_fingerprint": row["command_fingerprint"],
        })

    fingerprints = {rep["command_fingerprint"] for rep in repetitions} - {None}
    commands = {fp: known_commands[fp] for fp in sorted(fingerprints) if fp in known_commands}

    return {"hash": full_hash, "params": params, "repetitions": repetitions, "commands": commands}


def get_cache_stats(db_path: Path) -> Dict[str, Any]:
    """Compute summary statistics for a cache database.

    Args:
        db_path: Path to the cache database.

    Returns:
        Dict with total_entries, unique_parameter_sets, oldest_entry,
        newest_entry, distinct_repetitions, schema_version,
        distinct_commands, unverified_entries (entries with unknown
        command), commands, and db_path. ``commands`` lists one dict per
        fingerprint with fingerprint, entries, template, env, and
        first_seen (template and env are None when the command text was
        not stored).
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

        schema_version = get_schema_version(conn)
        if has_fingerprint_column(conn):
            cursor.execute(
                "SELECT COUNT(DISTINCT command_fingerprint) AS c FROM cached_executions"
            )
            distinct_commands = cursor.fetchone()["c"]
            cursor.execute(
                "SELECT COUNT(*) AS c FROM cached_executions "
                "WHERE command_fingerprint IS NULL"
            )
            unverified = cursor.fetchone()["c"]

            known_commands = _load_commands(conn)
            cursor.execute(
                "SELECT command_fingerprint AS fp, COUNT(*) AS c, MIN(created_at) AS first "
                "FROM cached_executions WHERE command_fingerprint IS NOT NULL "
                "GROUP BY command_fingerprint ORDER BY first ASC"
            )
            commands = []
            for row in cursor.fetchall():
                known = known_commands.get(row["fp"], {})
                commands.append({
                    "fingerprint": row["fp"],
                    "entries": row["c"],
                    "template": known.get("template"),
                    "env": known.get("env"),
                    "first_seen": known.get("first_seen", row["first"]),
                })
        else:
            distinct_commands = 0
            unverified = total_entries
            commands = []
    finally:
        conn.close()

    return {
        "db_path": str(Path(db_path)),
        "total_entries": total_entries,
        "unique_parameter_sets": unique_params,
        "distinct_repetitions": distinct_reps,
        "schema_version": schema_version,
        "distinct_commands": distinct_commands,
        "unverified_entries": unverified,
        "commands": commands,
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
    """Print a tabular view of cache entries (one row per parameter set and command)."""
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

    headers = ["Hash", "Cmd"] + var_names + ["Reps"] + metric_names + ["Last Cached"]

    rows: List[List[str]] = []
    for e in entries:
        fp = e.get("command_fingerprint")
        row = [e["hash"][:SHORT_HASH_LEN], fp[:SHORT_HASH_LEN] if fp else "unknown"]
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

    # Counted like 'iops cache stats': unknown commands are not a command
    param_sets = len({e["hash"] for e in entries})
    commands = len({e.get("command_fingerprint") for e in entries} - {None})
    unknown = sum(1 for e in entries if not e.get("command_fingerprint"))
    summary = f"\n{len(entries)} row(s): {param_sets} unique parameter set(s), {commands} command(s)"
    if unknown:
        summary += f", {unknown} row(s) with unknown command"
    print(summary)


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
        fingerprint = rep.get("command_fingerprint")
        command = fingerprint[:SHORT_HASH_LEN] if fingerprint else "unknown"
        print(f"\n  rep={rep['repetition']}  cached_at={rep['created_at']}  command={command}")
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

    fingerprints = sorted({rep.get("command_fingerprint") for rep in reps} - {None})
    if fingerprints:
        commands = entry.get("commands", {})
        print("\nCommands:")
        for fp in fingerprints:
            print(f"\n  {fp[:SHORT_HASH_LEN]}:")
            command = commands.get(fp)
            if command is None:
                print("    (command text not stored)")
                continue
            for line in command["template"].strip().splitlines():
                print(f"    {line}")
            for key in sorted(command["env"]):
                print(f"    env {key}={command['env'][key]}")


def display_cache_stats(stats: Dict[str, Any]) -> None:
    """Print cache summary statistics."""
    print(f"Cache: {stats['db_path']}")
    print("-" * 50)
    print(f"Total entries:          {stats['total_entries']}")
    print(f"Unique parameter sets:  {stats['unique_parameter_sets']}")
    print(f"Distinct repetitions:   {stats['distinct_repetitions']}")
    print(f"Distinct commands:      {stats['distinct_commands']}")
    print(f"Unknown command:        {stats['unverified_entries']}")
    print(f"Schema version:         {stats['schema_version']}")
    print(f"Oldest entry:           {stats['oldest_entry'] or '(empty)'}")
    print(f"Newest entry:           {stats['newest_entry'] or '(empty)'}")

    commands = stats.get("commands") or []
    if commands:
        print("\nCommands:")
        for command in commands:
            text = command["template"]
            text = _one_line(text, 70) if text is not None else "(command text not stored)"
            print(f"  {command['fingerprint'][:SHORT_HASH_LEN]}  {command['entries']:>5} entries  {text}")
