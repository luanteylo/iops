# iops/cache/execution_cache.py

"""Execution caching for IOPS benchmarks using SQLite."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import sqlite3
import json
import hashlib
from datetime import datetime

from iops.logger import HasLogger

# Default timeout for SQLite connections (seconds)
# Higher value helps with slow filesystems like NFS
DEFAULT_SQLITE_TIMEOUT = 60

# Retry settings for database lock errors
MAX_RETRIES = 5
RETRY_BASE_DELAY = 0.5  # seconds


def _is_on_nfs(path: Path) -> bool:
    """
    Check if a path is on an NFS filesystem (best effort).

    Args:
        path: Path to check

    Returns:
        True if path appears to be on NFS, False otherwise
    """
    import os
    import subprocess

    try:
        # Use df -T to get filesystem type (Linux)
        # Resolve to parent if file doesn't exist yet
        check_path = path if path.exists() else path.parent
        result = subprocess.run(
            ["df", "-T", str(check_path)],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            # Output format: "Filesystem Type ..."
            # Second line contains the actual data
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 2:
                    fs_type = parts[1].lower()
                    return fs_type in ('nfs', 'nfs4', 'nfs3')
    except Exception:
        pass

    # Fallback: check /proc/mounts on Linux
    try:
        check_path = str(path if path.exists() else path.parent)
        with open('/proc/mounts', 'r') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3:
                    mount_point = parts[1]
                    fs_type = parts[2].lower()
                    if check_path.startswith(mount_point) and fs_type in ('nfs', 'nfs4', 'nfs3'):
                        return True
    except Exception:
        pass

    return False


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
            - created_at: TEXT (timestamp)
    """

    def __init__(
        self,
        db_path: Path,
        exclude_vars: Optional[List[str]] = None,
        timeout: int = DEFAULT_SQLITE_TIMEOUT,
        objective_metric: Optional[str] = None,
        objective: str = "maximize",
    ):
        """
        Initialize the execution cache.

        Args:
            db_path: Path to SQLite database file
            exclude_vars: List of variable names to exclude from cache hash
            timeout: SQLite connection timeout in seconds (default: 60, helps with NFS)
            objective_metric: If set, cache lookup returns the entry with best metric value
                             instead of most recent. Used for Bayesian optimization.
            objective: "maximize" or "minimize" - determines what "best" means
        """
        super().__init__()
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.exclude_vars = set(exclude_vars or [])
        self.timeout = timeout
        self.objective_metric = objective_metric
        self.objective = objective

        # Detect NFS and use NFS-friendly mode
        # NFS has unreliable file locking, so we disable it since IOPS
        # only uses single-process access to the cache
        self._nfs_mode = _is_on_nfs(self.db_path)
        if self._nfs_mode:
            self.logger.info(
                f"NFS filesystem detected for cache file. Using NFS-compatible mode "
                f"(no file locking). Ensure only one IOPS process uses this cache."
            )

        self._init_db()

        if self.exclude_vars:
            self.logger.info(
                f"Execution cache initialized at: {self.db_path} "
                f"(excluding {len(self.exclude_vars)} vars from hash: {sorted(self.exclude_vars)})"
            )
        else:
            self.logger.info(f"Execution cache initialized at: {self.db_path}")

    def _connect_with_retry(self):
        """
        Create a SQLite connection with retry logic for handling lock errors.

        NFS and other network filesystems can have delayed file locking,
        causing "database is locked" errors. This method retries with
        exponential backoff to handle such cases.

        On NFS filesystems, uses NFS-compatible mode:
        - isolation_level=None (autocommit, no transaction locking)
        - PRAGMA journal_mode=DELETE (more compatible than WAL)
        - PRAGMA locking_mode=NORMAL (default, but explicit)

        This is safe because IOPS only uses single-process access to the cache.

        Returns:
            sqlite3.Connection: An open database connection

        Raises:
            sqlite3.OperationalError: If connection fails after all retries
        """
        import time

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                if self._nfs_mode:
                    # NFS-compatible mode: disable Python's transaction handling
                    # This uses autocommit and avoids most locking issues
                    conn = sqlite3.connect(
                        str(self.db_path),
                        timeout=self.timeout,
                        isolation_level=None  # Autocommit mode
                    )
                    # Use DELETE journal mode (more NFS-compatible than WAL)
                    conn.execute("PRAGMA journal_mode=DELETE")
                else:
                    conn = sqlite3.connect(str(self.db_path), timeout=self.timeout)
                    # Set busy timeout as additional protection
                    conn.execute(f"PRAGMA busy_timeout = {self.timeout * 1000}")
                return conn
            except sqlite3.OperationalError as e:
                last_error = e
                error_msg = str(e).lower()
                # Retry on lock-related errors
                if "locked" in error_msg or "busy" in error_msg:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    self.logger.warning(
                        f"Database locked, retrying in {delay:.1f}s "
                        f"(attempt {attempt + 1}/{MAX_RETRIES}): {e}"
                    )
                    time.sleep(delay)
                else:
                    # Non-lock error, raise immediately
                    raise

        # All retries exhausted
        raise sqlite3.OperationalError(
            f"Failed to connect to cache database after {MAX_RETRIES} attempts. "
            f"Last error: {last_error}. "
            f"This may be caused by a slow filesystem (e.g., NFS). "
            f"Consider using a local filesystem for the cache file."
        )

    def _init_db(self):
        """Create the cache table if it doesn't exist."""
        conn = self._connect_with_retry()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cached_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    param_hash TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    repetition INTEGER NOT NULL,
                    metrics_json TEXT,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(param_hash, repetition)
                )
            """)

            # Create index for fast lookups
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_param_hash
                ON cached_executions(param_hash, repetition)
            """)

            conn.commit()
        finally:
            conn.close()

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
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached result for given parameters and repetition.

        If objective_metric is set, returns the entry with the best metric value
        (max for maximize, min for minimize). Otherwise returns most recent entry.

        Args:
            params: Execution parameters
            repetition: Repetition number (1-based)

        Returns:
            Dict with 'metrics' and 'metadata' if found, None otherwise
        """
        normalized = self._normalize_params(params)
        param_hash = self._hash_params(normalized)

        conn = self._connect_with_retry()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # If objective_metric is set, find the best entry for this (hash, repetition)
            # This handles cases where multiple entries exist for the same key
            if self.objective_metric:
                cursor.execute("""
                    SELECT metrics_json, metadata_json, created_at
                    FROM cached_executions
                    WHERE param_hash = ? AND repetition = ?
                """, (param_hash, repetition))

                rows = cursor.fetchall()

                if not rows:
                    self.logger.debug(
                        f"  [Cache] MISS: hash={param_hash[:8]} rep={repetition}"
                    )
                    return None

                # Find the entry with the best metric value
                best_row = None
                best_value = None

                for row in rows:
                    metrics = json.loads(row['metrics_json']) if row['metrics_json'] else {}
                    metric_value = metrics.get(self.objective_metric)

                    if metric_value is None:
                        continue

                    if best_value is None:
                        best_value = metric_value
                        best_row = row
                    elif self.objective == "maximize" and metric_value > best_value:
                        best_value = metric_value
                        best_row = row
                    elif self.objective == "minimize" and metric_value < best_value:
                        best_value = metric_value
                        best_row = row

                if best_row:
                    self.logger.debug(
                        f"  [Cache] HIT: hash={param_hash[:8]} rep={repetition} "
                        f"(best {self.objective_metric}={best_value:.2f} from {len(rows)} entries)"
                    )

                    return {
                        'metrics': json.loads(best_row['metrics_json']) if best_row['metrics_json'] else {},
                        'metadata': json.loads(best_row['metadata_json']) if best_row['metadata_json'] else {},
                        'cached_at': best_row['created_at'],
                    }

                # No entry with the metric found, fall back to most recent
                row = rows[-1]
            else:
                # Default behavior: return most recent entry
                cursor.execute("""
                    SELECT metrics_json, metadata_json, created_at
                    FROM cached_executions
                    WHERE param_hash = ? AND repetition = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (param_hash, repetition))

                row = cursor.fetchone()

            if row:
                self.logger.debug(
                    f"  [Cache] HIT: hash={param_hash[:8]} rep={repetition} "
                    f"(cached_at={row['created_at']})"
                )

                return {
                    'metrics': json.loads(row['metrics_json']) if row['metrics_json'] else {},
                    'metadata': json.loads(row['metadata_json']) if row['metadata_json'] else {},
                    'cached_at': row['created_at'],
                }

            self.logger.debug(
                f"  [Cache] MISS: hash={param_hash[:8]} rep={repetition}"
            )
            return None
        finally:
            conn.close()

    def store_result(
        self,
        params: Dict[str, Any],
        repetition: int,
        metrics: Dict[str, Any],
        metadata: Dict[str, Any],
    ):
        """
        Store execution result in cache.

        Args:
            params: Execution parameters
            repetition: Repetition number (1-based)
            metrics: Execution metrics
            metadata: Execution metadata
        """
        normalized = self._normalize_params(params)
        param_hash = self._hash_params(normalized)

        params_json = json.dumps(normalized, sort_keys=True, default=str)
        metrics_json = json.dumps(metrics, default=str)
        metadata_json = json.dumps(metadata, default=str)
        created_at = datetime.now().isoformat()

        conn = self._connect_with_retry()
        try:
            try:
                conn.execute("""
                    INSERT INTO cached_executions
                    (param_hash, params_json, repetition, metrics_json, metadata_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    param_hash, params_json, repetition, metrics_json, metadata_json, created_at
                ))
                conn.commit()

                self.logger.debug(
                    f"  [Cache] STORE: hash={param_hash[:8]} rep={repetition} "
                    f"metrics={len(metrics)} keys"
                )

            except sqlite3.IntegrityError:
                # Already exists (same param_hash, repetition)
                # Update with latest result
                conn.execute("""
                    UPDATE cached_executions
                    SET metrics_json = ?, metadata_json = ?, created_at = ?
                    WHERE param_hash = ? AND repetition = ?
                """, (
                    metrics_json, metadata_json, created_at,
                    param_hash, repetition
                ))
                conn.commit()

                self.logger.debug(
                    f"  [Cache] UPDATE: hash={param_hash[:8]} rep={repetition} "
                    f"metrics={len(metrics)} keys"
                )
        finally:
            conn.close()

    def get_cached_repetitions_count(
        self,
        params: Dict[str, Any],
    ) -> int:
        """
        Count how many repetitions are cached for given parameters.

        Args:
            params: Execution parameters

        Returns:
            Number of cached repetitions
        """
        normalized = self._normalize_params(params)
        param_hash = self._hash_params(normalized)

        conn = self._connect_with_retry()
        try:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COUNT(*) FROM cached_executions
                WHERE param_hash = ?
            """, (param_hash,))

            count = cursor.fetchone()[0]
            return count
        finally:
            conn.close()

    def clear_cache(self):
        """Clear all cached results."""
        conn = self._connect_with_retry()
        try:
            conn.execute("DELETE FROM cached_executions")
            conn.commit()
        finally:
            conn.close()

        self.logger.info("Cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dict with cache statistics
        """
        conn = self._connect_with_retry()
        try:
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
        finally:
            conn.close()


# Standalone functions for use in rebuild operations

def normalize_params(params: Dict[str, Any], exclude_vars: Optional[set] = None) -> Dict[str, Any]:
    """
    Normalize parameters for hashing (standalone function).

    Args:
        params: Raw parameters dict
        exclude_vars: Set of variable names to exclude

    Returns:
        Normalized parameters dict suitable for hashing
    """
    exclude_vars = exclude_vars or set()
    normalized = {}

    for key, value in sorted(params.items()):
        if key.startswith("__"):
            continue
        if key in exclude_vars:
            continue

        if isinstance(value, Path):
            value = str(value)

        if isinstance(value, str) and value.isdigit():
            value = int(value)
        elif isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                pass

        normalized[key] = value

    return normalized


def hash_params(params: Dict[str, Any]) -> str:
    """
    Generate a hash for parameters (standalone function).

    Args:
        params: Parameters dict (should be normalized first)

    Returns:
        MD5 hash of parameters as hex string
    """
    params_str = json.dumps(params, sort_keys=True, default=str)
    return hashlib.md5(params_str.encode()).hexdigest()
