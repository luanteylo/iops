# iops/cache/__init__.py

"""
Cache module for IOPS benchmark execution results.

This module provides:
- ExecutionCache: SQLite-based cache for benchmark results
- rebuild_cache: Function to rebuild cache with different exclude_vars
- create_cache_from_csv: Function to build a cache from a CSV file
"""

from .execution_cache import ExecutionCache, normalize_params, hash_params
from .rebuild import rebuild_cache, RebuildStats
from .from_csv import create_cache_from_csv, CreateFromCsvStats
from .inspect import (
    HashPrefixError,
    list_cache_entries,
    get_cache_entry,
    get_cache_stats,
    resolve_hash_prefix,
)

__all__ = [
    "ExecutionCache",
    "normalize_params",
    "hash_params",
    "rebuild_cache",
    "RebuildStats",
    "create_cache_from_csv",
    "CreateFromCsvStats",
    "HashPrefixError",
    "list_cache_entries",
    "get_cache_entry",
    "get_cache_stats",
    "resolve_hash_prefix",
]
