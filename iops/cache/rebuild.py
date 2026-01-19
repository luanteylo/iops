# iops/cache/rebuild.py

"""Cache rebuild functionality for IOPS.

Allows rebuilding a cache database with different excluded variables,
useful when users discover that certain variables (like paths) should
have been excluded from the cache hash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import sqlite3
import json
import logging

from .execution_cache import normalize_params, hash_params


@dataclass
class RebuildStats:
    """Statistics from a cache rebuild operation."""

    source_entries: int = 0
    source_unique_hashes: int = 0
    output_entries: int = 0
    output_unique_hashes: int = 0
    excluded_vars: List[str] = field(default_factory=list)
    collisions: int = 0  # Entries that collapsed to same (hash, rep)

    def summary(self) -> str:
        """Return a human-readable summary of the rebuild."""
        lines = [
            "Cache Rebuild Summary",
            "=" * 50,
            f"Source entries:        {self.source_entries}",
            f"Source unique hashes:  {self.source_unique_hashes}",
            f"Excluded variables:    {', '.join(self.excluded_vars) or '(none)'}",
            "-" * 50,
            f"Output entries:        {self.output_entries}",
            f"Output unique hashes:  {self.output_unique_hashes}",
            f"Collapsed entries:     {self.collisions}",
            "=" * 50,
        ]
        return "\n".join(lines)


def rebuild_cache(
    source_db: Path,
    output_db: Path,
    exclude_vars: List[str],
    logger: Optional[logging.Logger] = None,
) -> RebuildStats:
    """
    Rebuild a cache database with additional excluded variables.

    This function reads all entries from the source cache, re-normalizes
    the parameters with the new exclude_vars, re-hashes them, and writes
    to a new database.

    When multiple entries collapse to the same (new_hash, repetition) due
    to the excluded variables, all entries are kept (the output database
    does NOT have a UNIQUE constraint on param_hash + repetition).

    Args:
        source_db: Path to the source cache database
        output_db: Path for the rebuilt cache database
        exclude_vars: List of variable names to exclude from the hash
        logger: Optional logger for progress messages

    Returns:
        RebuildStats with statistics about the rebuild operation

    Raises:
        FileNotFoundError: If source_db doesn't exist
        ValueError: If output_db already exists (won't overwrite)
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    source_db = Path(source_db)
    output_db = Path(output_db)

    if not source_db.exists():
        raise FileNotFoundError(f"Source cache not found: {source_db}")

    if output_db.exists():
        raise ValueError(f"Output file already exists: {output_db}. Remove it first or choose a different path.")

    exclude_vars_set = set(exclude_vars)
    stats = RebuildStats(excluded_vars=list(exclude_vars))

    logger.info(f"Rebuilding cache: {source_db} -> {output_db}")
    logger.info(f"Excluding variables: {exclude_vars}")

    # Read all entries from source
    with sqlite3.connect(str(source_db)) as src_conn:
        src_conn.row_factory = sqlite3.Row
        cursor = src_conn.cursor()

        # Get source stats
        cursor.execute("SELECT COUNT(*) FROM cached_executions")
        stats.source_entries = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT param_hash) FROM cached_executions")
        stats.source_unique_hashes = cursor.fetchone()[0]

        # Read all entries
        cursor.execute("""
            SELECT param_hash, params_json, repetition, metrics_json, metadata_json, created_at
            FROM cached_executions
            ORDER BY created_at ASC
        """)
        entries = cursor.fetchall()

    logger.info(f"Read {stats.source_entries} entries from source cache")

    # Create output database (without UNIQUE constraint to allow all entries)
    output_db.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(output_db)) as out_conn:
        out_conn.execute("""
            CREATE TABLE cached_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                param_hash TEXT NOT NULL,
                params_json TEXT NOT NULL,
                repetition INTEGER NOT NULL,
                metrics_json TEXT,
                metadata_json TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # Create index for fast lookups (same as original)
        out_conn.execute("""
            CREATE INDEX idx_param_hash
            ON cached_executions(param_hash, repetition)
        """)

        # Track seen (hash, rep) combinations for collision counting
        seen_hash_rep: Set[tuple] = set()
        new_hashes: Set[str] = set()

        # Process and insert entries
        for entry in entries:
            old_params = json.loads(entry["params_json"])

            # Re-normalize with new exclude_vars
            new_params = normalize_params(old_params, exclude_vars_set)
            new_hash = hash_params(new_params)
            new_params_json = json.dumps(new_params, sort_keys=True, default=str)

            repetition = entry["repetition"]
            hash_rep_key = (new_hash, repetition)

            if hash_rep_key in seen_hash_rep:
                stats.collisions += 1
            else:
                seen_hash_rep.add(hash_rep_key)

            new_hashes.add(new_hash)

            out_conn.execute("""
                INSERT INTO cached_executions
                (param_hash, params_json, repetition, metrics_json, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                new_hash,
                new_params_json,
                repetition,
                entry["metrics_json"],
                entry["metadata_json"],
                entry["created_at"],
            ))

        out_conn.commit()

        # Get output stats
        cursor = out_conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cached_executions")
        stats.output_entries = cursor.fetchone()[0]
        stats.output_unique_hashes = len(new_hashes)

    logger.info(f"Wrote {stats.output_entries} entries to rebuilt cache")
    logger.info(f"Unique hashes: {stats.source_unique_hashes} -> {stats.output_unique_hashes}")
    if stats.collisions > 0:
        logger.info(f"Entries that collapsed to same (hash, repetition): {stats.collisions}")

    return stats
