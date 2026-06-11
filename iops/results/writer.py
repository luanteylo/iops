from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Iterable
import json
import sqlite3

import pandas as pd

# Optional pyarrow for parquet support
try:
    import pyarrow
    PYARROW_AVAILABLE = True
except ImportError:
    PYARROW_AVAILABLE = False


def _check_pyarrow():
    """Raise helpful error if pyarrow is not installed."""
    if not PYARROW_AVAILABLE:
        raise ImportError(
            "pyarrow is required for parquet output. "
            "Install it with: pip install pyarrow\n"
            "Or install iops with parquet support: pip install iops-benchmark[parquet]"
        )


# -------------------------
# flattening + filtering
# -------------------------

def _flatten(prefix: str, obj: Any, out: Dict[str, Any]) -> None:
    """
    Flatten nested dictionaries into dotted keys.
    """
    if obj is None:
        return

    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            _flatten(key, v, out)
    else:
        out[prefix] = obj


def _matches(field: str, selector: str) -> bool:
    """
    Selector matching rules:
      - exact key: "vars.processes_per_node"
      - prefix: "vars" matches "vars.*"
      - wildcard: "vars.*" matches "vars.*"
    """
    sel = selector.strip()
    if not sel:
        return False

    if sel.endswith(".*"):
        base = sel[:-2]
        return field == base or field.startswith(base + ".")

    # treat "vars" like "vars.*"
    if "." not in sel:
        return field == sel or field.startswith(sel + ".")

    return field == sel


# Fields that cannot be excluded - essential for identifying results
PROTECTED_FIELDS = {"execution.execution_id", "execution.repetition"}


def _apply_exclude(
    row: Dict[str, Any],
    exclude: List[str],
) -> Dict[str, Any]:
    keys = list(row.keys())

    if exclude:
        drop = {k for k in keys if any(_matches(k, s) for s in exclude)}
        # Never drop protected fields
        drop -= PROTECTED_FIELDS
        return {k: row[k] for k in keys if k not in drop}

    return row


def _jsonify_if_needed(v: Any) -> Any:
    """
    Ensure values are serializable to CSV/SQLite.
    """
    if v is None:
        return None
    if isinstance(v, (int, float, str, bool)):
        return v
    if isinstance(v, Path):
        return str(v)
    try:
        return json.dumps(v, default=str)
    except Exception:
        return str(v)


# -------------------------
# Build one output row
# -------------------------

# Per-execution versions captured by the version probe (benchmark.probes.versions).
# Written at-exit into the execution directory; surfaced here as version.* columns so
# old benchmarks can be reanalyzed programmatically (e.g. filter results by app version).
VERSIONS_FILENAME = "__iops_versions.json"


def _read_versions(execution_dir: Path) -> Dict[str, Any]:
    """Read captured software versions for an execution, or {} if absent/unreadable."""
    versions_path = execution_dir / VERSIONS_FILENAME
    if not versions_path.is_file():
        return {}
    try:
        with open(versions_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def build_output_row(test) -> Dict[str, Any]:
    row: Dict[str, Any] = {}

    # benchmark
    _flatten("benchmark", {
        "name": getattr(test, "benchmark_name", None),
        "description": getattr(test, "benchmark_description", None),
    }, row)

    # execution identifiers and paths
    meta = getattr(test, "metadata", {}) or {}
    workdir = getattr(test, "workdir", None)
    execution_dir = getattr(test, "execution_dir", None)
    _flatten("execution", {
        "execution_id": getattr(test, "execution_id", None),
        "repetition": meta.get("repetition", getattr(test, "repetition", None)),
        "repetitions": getattr(test, "repetitions", None),
        "workdir": str(workdir) if workdir else None,
        "execution_dir": str(execution_dir) if execution_dir else None,
    }, row)

    # round
    _flatten("round", {
        "name": getattr(test, "round_name", None),
        "index": getattr(test, "round_index", None),
    }, row)

    # vars
    _flatten("vars", dict(getattr(test, "vars", {}) or {}), row)

    # labels: user-defined fields from command.labels (Jinja-rendered)
    if hasattr(test, "command_labels"):
        _flatten("labels", dict(test.command_labels), row)

    # metadata: IOPS internal fields (executor status, timing, errors, etc.)
    # These are fields with __ prefix stored in test.metadata dict
    iops_metadata = {}
    metrics_obj = None
    for k, v in meta.items():
        if k == "metrics":
            metrics_obj = v
        elif k == "repetition":
            pass  # already in execution.repetition
        elif k.startswith("__"):
            # Strip __ prefix for cleaner output (e.g., __executor_status -> executor_status)
            clean_key = k[2:]
            iops_metadata[clean_key] = v
        # Ignore other keys that aren't internal metadata
    _flatten("metadata", iops_metadata, row)

    # metrics (safe even if missing)
    _flatten("metrics", metrics_obj or {}, row)

    # versions: captured by the version probe, surfaced as version.* columns
    if execution_dir:
        versions = _read_versions(Path(execution_dir))
        if versions:
            _flatten("version", versions, row)

    # normalize
    row = {k: _jsonify_if_needed(v) for k, v in row.items()}
    return row


# -------------------------
# Sink writers
# -------------------------

def _write_csv(path: Path, df: pd.DataFrame) -> None:
    """
    CSV writer with schema stabilization (always appends).

    - file missing: write df with its columns
    - file exists:
        * align incoming df to existing header columns
        * if new columns appear, rewrite entire file with extended header
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        df.to_csv(path, index=False)
        return

    # APPEND: align to existing schema
    try:
        existing_cols = list(pd.read_csv(path, nrows=0).columns)
    except pd.errors.EmptyDataError:
        # File exists but is empty (e.g. crash before first flush): fresh write
        df.to_csv(path, index=False)
        return

    # If df introduces new columns, extend schema and rewrite file
    new_cols = [c for c in df.columns if c not in existing_cols]
    if new_cols:
        # Read existing rows as verbatim strings so the rewrite cannot
        # re-infer dtypes and mutate stored values (e.g. "0010" -> 10).
        old = pd.read_csv(path, dtype=str, keep_default_na=False)
        all_cols = existing_cols + new_cols
        old = old.reindex(columns=all_cols, fill_value="")
        df = df.reindex(columns=all_cols)
        out = pd.concat([old, df], ignore_index=True)
        out.to_csv(path, index=False)
        return

    # Normal append: just reindex to existing columns and append no header
    df = df.reindex(columns=existing_cols)
    df.to_csv(path, index=False, mode="a", header=False)


def _write_parquet(path: Path, df: pd.DataFrame) -> None:
    """
    Parquet writer with schema stabilization (always appends).

    - missing: write
    - exists: read+concat+rewrite, unioning columns
    """
    _check_pyarrow()
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        df.to_parquet(path, index=False)
        return

    old = pd.read_parquet(path)

    # union schema
    all_cols = list(old.columns)
    for c in df.columns:
        if c not in all_cols:
            all_cols.append(c)

    int_cols = {
        c for frame in (old, df)
        for c in frame.columns
        if pd.api.types.is_integer_dtype(frame[c])
    }

    old = old.reindex(columns=all_cols)
    df = df.reindex(columns=all_cols)

    new = pd.concat([old, df], ignore_index=True)

    # Reindex/concat introduce NaN for missing values, silently upcasting
    # integer columns to float64 forever. Restore them as nullable Int64.
    for c in int_cols:
        if pd.api.types.is_float_dtype(new[c]):
            non_null = new[c].dropna()
            if (non_null % 1 == 0).all():
                new[c] = new[c].astype("Int64")

    new.to_parquet(path, index=False)


def _write_sqlite(db_path: Path, table: str, df: pd.DataFrame) -> None:
    """
    SQLite writer (always appends), extending the table schema with
    ALTER TABLE ADD COLUMN when new columns appear.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    try:
        exists = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if exists is not None:
            existing_cols = {
                row[1] for row in con.execute(f'PRAGMA table_info("{table}")')
            }
            for col in df.columns:
                if col not in existing_cols:
                    quoted = col.replace('"', '""')
                    con.execute(f'ALTER TABLE "{table}" ADD COLUMN "{quoted}"')
        df.to_sql(table, con, if_exists="append", index=False)
        con.commit()
    finally:
        con.close()


# -------------------------
# Public API
# -------------------------

def save_test_execution(test) -> Path:
    out_path = getattr(test, "output_path", None)
    if out_path is None:
        raise ValueError("test.output_path is None (output_path_template not set?)")

    row = build_output_row(test)
    row = _apply_exclude(row, getattr(test, "output_exclude", []) or [])

    df = pd.DataFrame([row])

    typ = str(getattr(test, "output_type", "")).lower().strip()

    if typ == "csv":
        _write_csv(Path(out_path), df)
        return Path(out_path)

    if typ == "parquet":
        _write_parquet(Path(out_path), df)
        return Path(out_path)

    if typ == "sqlite":
        table = getattr(test, "output_table", None) or "results"
        _write_sqlite(Path(out_path), table, df)
        return Path(out_path)

    raise ValueError(f"Unsupported output type: {getattr(test, 'output_type', None)}")
