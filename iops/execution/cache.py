# iops/execution/cache.py

"""Execution caching for IOPS benchmarks using SQLite."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import sqlite3
import json
import hashlib
from datetime import datetime

from iops.logger import HasLogger


class ExecutionCache(HasLogger):
    """
    SQLite-based cache for benchmark execution results.

    Caches execution results based on parameters and repetition numbers,
    allowing reuse of previous results when --use_cache is enabled.

    Schema:
        cached_executions:
            - id: INTEGER PRIMARY KEY
            - param_hash: TEXT (indexed, for fast lookup)
            - params_json: TEXT (full parameters as JSON)
            - repetition: INTEGER (which repetition: 1, 2, 3, etc.)
            - metrics_json: TEXT (cached metrics)
            - metadata_json: TEXT (execution metadata: status, timestamps, etc.)
            - round_name: TEXT (optional, for multi-round workflows)
            - round_index: INTEGER (optional)
            - created_at: TEXT (timestamp)
    """

    def __init__(self, db_path: Path, exclude_vars: Optional[List[str]] = None):
        """
        Initialize the execution cache.

        Args:
            db_path: Path to SQLite database file
            exclude_vars: List of variable names to exclude from cache hash
        """
        super().__init__()
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.exclude_vars = set(exclude_vars or [])

        self._init_db()

        if self.exclude_vars:
            self.logger.info(
                f"Execution cache initialized at: {self.db_path} "
                f"(excluding {len(self.exclude_vars)} vars from hash: {sorted(self.exclude_vars)})"
            )
        else:
            self.logger.info(f"Execution cache initialized at: {self.db_path}")

    def _init_db(self):
        """Create the cache table if it doesn't exist."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cached_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    param_hash TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    repetition INTEGER NOT NULL,
                    metrics_json TEXT,
                    metadata_json TEXT,
                    round_name TEXT,
                    round_index INTEGER,
                    created_at TEXT NOT NULL,
                    UNIQUE(param_hash, repetition, round_name)
                )
            """)

            # Create index for fast lookups
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_param_hash
                ON cached_executions(param_hash, repetition)
            """)

            conn.commit()

    def _normalize_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize parameters for hashing.

        Removes internal/metadata keys (starting with __), excluded vars, and sorts keys.
        Converts Path objects to strings for JSON serialization.

        Args:
            params: Raw parameters dict

        Returns:
            Normalized parameters dict suitable for hashing
        """
        normalized = {}

        for key, value in sorted(params.items()):
            # Skip internal keys (like __test_index, __phase_index, etc.)
            if key.startswith("__"):
                continue

            # Skip excluded variables (e.g., path-based derived vars)
            if key in self.exclude_vars:
                continue

            # Convert Path to string
            if isinstance(value, Path):
                value = str(value)

            # Normalize numeric types (treat "8" and 8 as same)
            if isinstance(value, str) and value.isdigit():
                value = int(value)
            elif isinstance(value, str):
                try:
                    value = float(value)
                except ValueError:
                    pass  # Keep as string

            normalized[key] = value

        return normalized

    def _hash_params(self, params: Dict[str, Any]) -> str:
        """
        Generate a hash for parameters.

        Args:
            params: Parameters dict (should be normalized first)

        Returns:
            MD5 hash of parameters as hex string
        """
        params_str = json.dumps(params, sort_keys=True, default=str)
        return hashlib.md5(params_str.encode()).hexdigest()

    def get_cached_result(
        self,
        params: Dict[str, Any],
        repetition: int,
        round_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached result for given parameters and repetition.

        Args:
            params: Execution parameters
            repetition: Repetition number (1-based)
            round_name: Optional round name for multi-round workflows

        Returns:
            Dict with 'metrics' and 'metadata' if found, None otherwise
        """
        normalized = self._normalize_params(params)
        param_hash = self._hash_params(normalized)

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Query for exact match
            if round_name is not None:
                cursor.execute("""
                    SELECT metrics_json, metadata_json, created_at
                    FROM cached_executions
                    WHERE param_hash = ? AND repetition = ? AND round_name = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (param_hash, repetition, round_name))
            else:
                cursor.execute("""
                    SELECT metrics_json, metadata_json, created_at
                    FROM cached_executions
                    WHERE param_hash = ? AND repetition = ? AND round_name IS NULL
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (param_hash, repetition))

            row = cursor.fetchone()

            if row:
                self.logger.debug(
                    f"  [Cache] HIT: hash={param_hash[:8]} rep={repetition} "
                    f"round={round_name or 'N/A'} (cached_at={row['created_at']})"
                )

                return {
                    'metrics': json.loads(row['metrics_json']) if row['metrics_json'] else {},
                    'metadata': json.loads(row['metadata_json']) if row['metadata_json'] else {},
                    'cached_at': row['created_at'],
                }

            self.logger.debug(
                f"  [Cache] MISS: hash={param_hash[:8]} rep={repetition} round={round_name or 'N/A'}"
            )
            return None

    def store_result(
        self,
        params: Dict[str, Any],
        repetition: int,
        metrics: Dict[str, Any],
        metadata: Dict[str, Any],
        round_name: Optional[str] = None,
        round_index: Optional[int] = None,
    ):
        """
        Store execution result in cache.

        Args:
            params: Execution parameters
            repetition: Repetition number (1-based)
            metrics: Execution metrics
            metadata: Execution metadata
            round_name: Optional round name
            round_index: Optional round index
        """
        normalized = self._normalize_params(params)
        param_hash = self._hash_params(normalized)

        params_json = json.dumps(normalized, sort_keys=True, default=str)
        metrics_json = json.dumps(metrics, default=str)
        metadata_json = json.dumps(metadata, default=str)
        created_at = datetime.now().isoformat()

        with sqlite3.connect(str(self.db_path)) as conn:
            try:
                conn.execute("""
                    INSERT INTO cached_executions
                    (param_hash, params_json, repetition, metrics_json, metadata_json,
                     round_name, round_index, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    param_hash, params_json, repetition, metrics_json, metadata_json,
                    round_name, round_index, created_at
                ))
                conn.commit()

                self.logger.debug(
                    f"  [Cache] STORE: hash={param_hash[:8]} rep={repetition} "
                    f"round={round_name or 'N/A'} metrics={len(metrics)} keys"
                )

            except sqlite3.IntegrityError:
                # Already exists (same param_hash, repetition, round_name)
                # Update with latest result
                conn.execute("""
                    UPDATE cached_executions
                    SET metrics_json = ?, metadata_json = ?, created_at = ?
                    WHERE param_hash = ? AND repetition = ?
                    AND (round_name = ? OR (round_name IS NULL AND ? IS NULL))
                """, (
                    metrics_json, metadata_json, created_at,
                    param_hash, repetition, round_name, round_name
                ))
                conn.commit()

                self.logger.debug(
                    f"  [Cache] UPDATE: hash={param_hash[:8]} rep={repetition} "
                    f"round={round_name or 'N/A'} metrics={len(metrics)} keys"
                )

    def get_cached_repetitions_count(
        self,
        params: Dict[str, Any],
        round_name: Optional[str] = None,
    ) -> int:
        """
        Count how many repetitions are cached for given parameters.

        Args:
            params: Execution parameters
            round_name: Optional round name

        Returns:
            Number of cached repetitions
        """
        normalized = self._normalize_params(params)
        param_hash = self._hash_params(normalized)

        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()

            if round_name is not None:
                cursor.execute("""
                    SELECT COUNT(*) FROM cached_executions
                    WHERE param_hash = ? AND round_name = ?
                """, (param_hash, round_name))
            else:
                cursor.execute("""
                    SELECT COUNT(*) FROM cached_executions
                    WHERE param_hash = ? AND round_name IS NULL
                """, (param_hash,))

            count = cursor.fetchone()[0]
            return count

    def clear_cache(self):
        """Clear all cached results."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM cached_executions")
            conn.commit()

        self.logger.info("Cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dict with cache statistics
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()

            # Total entries
            cursor.execute("SELECT COUNT(*) FROM cached_executions")
            total_entries = cursor.fetchone()[0]

            # Unique parameter sets
            cursor.execute("SELECT COUNT(DISTINCT param_hash) FROM cached_executions")
            unique_params = cursor.fetchone()[0]

            # Oldest entry
            cursor.execute("SELECT MIN(created_at) FROM cached_executions")
            oldest = cursor.fetchone()[0]

            # Newest entry
            cursor.execute("SELECT MAX(created_at) FROM cached_executions")
            newest = cursor.fetchone()[0]

            return {
                'total_entries': total_entries,
                'unique_parameter_sets': unique_params,
                'oldest_entry': oldest,
                'newest_entry': newest,
                'db_path': str(self.db_path),
            }
