from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Iterable
import json
import sqlite3

import pandas as pd


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


def _apply_include_exclude(
    row: Dict[str, Any],
    include: List[str],
    exclude: List[str],
) -> Dict[str, Any]:
    keys = list(row.keys())

    if include:
        keep = {k for k in keys if any(_matches(k, s) for s in include)}
        return {k: row[k] for k in keys if k in keep}

    if exclude:
        drop = {k for k in keys if any(_matches(k, s) for s in exclude)}
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

def build_output_row(test) -> Dict[str, Any]:
    row: Dict[str, Any] = {}

    # benchmark
    _flatten("benchmark", {
        "name": getattr(test, "benchmark_name", None),
        "description": getattr(test, "benchmark_description", None),
    }, row)

    # execution identifiers
    meta = getattr(test, "metadata", {}) or {}
    _flatten("execution", {
        "execution_id": getattr(test, "execution_id", None),
        "repetition": meta.get("repetition", getattr(test, "repetition", None)),
    }, row)

    # round
    _flatten("round", {
        "name": getattr(test, "round_name", None),
        "index": getattr(test, "round_index", None),
    }, row)

    # vars
    _flatten("vars", dict(getattr(test, "vars", {}) or {}), row)

    # metadata (exclude metrics to avoid duplicating columns)
    metadata = dict(meta)
    metrics_obj = metadata.pop("metrics", None)  # keep separate
    _flatten("metadata", metadata, row)

    # metrics (safe even if missing)
    _flatten("metrics", metrics_obj or meta.get("metrics", {}) or {}, row)

    # normalize
    row = {k: _jsonify_if_needed(v) for k, v in row.items()}
    return row


# -------------------------
# Sink writers
# -------------------------

def _write_csv(path: Path, df: pd.DataFrame, mode: str) -> None:
    """
    CSV writer with schema stabilization.

    - overwrite OR file missing: write df with its columns
    - append AND file exists:
        * align incoming df to existing header columns
        * if new columns appear, rewrite entire file with extended header
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if mode == "overwrite" or not path.exists():
        df.to_csv(path, index=False)
        return

    # APPEND: align to existing schema
    existing_cols = list(pd.read_csv(path, nrows=0).columns)

    # If df introduces new columns, extend schema and rewrite file
    new_cols = [c for c in df.columns if c not in existing_cols]
    if new_cols:
        old = pd.read_csv(path)
        all_cols = existing_cols + new_cols
        old = old.reindex(columns=all_cols)
        df = df.reindex(columns=all_cols)
        out = pd.concat([old, df], ignore_index=True)
        out.to_csv(path, index=False)
        return

    # Normal append: just reindex to existing columns and append no header
    df = df.reindex(columns=existing_cols)
    df.to_csv(path, index=False, mode="a", header=False)


def _write_parquet(path: Path, df: pd.DataFrame, mode: str) -> None:
    """
    Parquet schema stabilization similar to CSV.

    - overwrite OR missing: write
    - append: read+concat+rewrite, unioning columns
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if mode == "overwrite" or not path.exists():
        df.to_parquet(path, index=False)
        return

    old = pd.read_parquet(path)

    # union schema
    all_cols = list(old.columns)
    for c in df.columns:
        if c not in all_cols:
            all_cols.append(c)

    old = old.reindex(columns=all_cols)
    df = df.reindex(columns=all_cols)

    new = pd.concat([old, df], ignore_index=True)
    new.to_parquet(path, index=False)


def _write_sqlite(db_path: Path, table: str, df: pd.DataFrame, mode: str) -> None:
    """
    SQLite: appends rows. Note: schema evolution (new columns) is not handled here.
    If you want schema evolution for sqlite, you need ALTER TABLE logic.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as con:
        if mode == "overwrite":
            con.execute(f'DROP TABLE IF EXISTS "{table}"')
        df.to_sql(table, con, if_exists="append", index=False)


# -------------------------
# Public API
# -------------------------

def save_test_execution(test) -> Path:
    out_path = getattr(test, "output_path", None)
    if out_path is None:
        raise ValueError("test.output_path is None (output_path_template not set?)")

    row = build_output_row(test)
    row = _apply_include_exclude(row, getattr(test, "output_include", []) or [], getattr(test, "output_exclude", []) or [])

    df = pd.DataFrame([row])

    typ = str(getattr(test, "output_type", "")).lower().strip()
    mode = str(getattr(test, "output_mode", "append")).lower().strip()

    if typ == "csv":
        _write_csv(Path(out_path), df, mode)
        return Path(out_path)

    if typ == "parquet":
        _write_parquet(Path(out_path), df, mode)
        return Path(out_path)

    if typ == "sqlite":
        table = getattr(test, "output_table", None) or "results"
        _write_sqlite(Path(out_path), table, df, mode)
        return Path(out_path)

    raise ValueError(f"Unsupported output type: {getattr(test, 'output_type', None)}")
