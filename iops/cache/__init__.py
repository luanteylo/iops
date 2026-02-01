# iops/cache/__init__.py

"""
Cache module for IOPS benchmark execution results.

This module provides:
- ExecutionCache: SQLite-based cache for benchmark results
- rebuild_cache: Function to rebuild cache with different exclude_vars
"""

from .execution_cache import ExecutionCache, normalize_params, hash_params
from .rebuild import rebuild_cache, RebuildStats

__all__ = [
    "ExecutionCache",
    "normalize_params",
    "hash_params",
    "rebuild_cache",
    "RebuildStats",
]
