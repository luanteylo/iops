"""Tests for execution caching."""

import pytest
from pathlib import Path

from iops.execution.cache import ExecutionCache


@pytest.fixture
def cache_db(tmp_path):
    """Create a temporary cache database."""
    db_path = tmp_path / "test_cache.db"
    return db_path


def test_cache_initialization(cache_db):
    """Test cache database initialization."""
    cache = ExecutionCache(cache_db)

    assert cache.db_path.exists()
    assert cache.db_path == cache_db


def test_cache_store_and_retrieve(cache_db):
    """Test storing and retrieving cached results."""
    cache = ExecutionCache(cache_db)

    params = {"nodes": 2, "ppn": 4}
    metrics = {"bandwidth": 100.5, "iops": 1000}
    metadata = {"status": "SUCCESS"}

    # Store result
    cache.store_result(
        params=params,
        repetition=1,
        metrics=metrics,
        metadata=metadata
    )

    # Retrieve result
    result = cache.get_cached_result(
        params=params,
        repetition=1
    )

    assert result is not None
    assert result["metrics"] == metrics
    assert result["metadata"] == metadata
    assert "cached_at" in result


def test_cache_miss(cache_db):
    """Test cache miss for non-existent parameters."""
    cache = ExecutionCache(cache_db)

    result = cache.get_cached_result(
        params={"nodes": 999},
        repetition=1
    )

    assert result is None


def test_cache_repetition_isolation(cache_db):
    """Test that different repetitions are cached separately."""
    cache = ExecutionCache(cache_db)

    params = {"nodes": 2}

    # Store two different repetitions
    cache.store_result(params=params, repetition=1, metrics={"value": 100}, metadata={})
    cache.store_result(params=params, repetition=2, metrics={"value": 200}, metadata={})

    # Retrieve both
    result1 = cache.get_cached_result(params=params, repetition=1)
    result2 = cache.get_cached_result(params=params, repetition=2)

    assert result1["metrics"]["value"] == 100
    assert result2["metrics"]["value"] == 200


def test_cache_round_isolation(cache_db):
    """Test that different rounds are cached separately."""
    cache = ExecutionCache(cache_db)

    params = {"nodes": 2}

    # Store same params in different rounds
    cache.store_result(
        params=params,
        repetition=1,
        metrics={"value": 100},
        metadata={},
        round_name="round1"
    )
    cache.store_result(
        params=params,
        repetition=1,
        metrics={"value": 200},
        metadata={},
        round_name="round2"
    )

    # Retrieve both
    result1 = cache.get_cached_result(params=params, repetition=1, round_name="round1")
    result2 = cache.get_cached_result(params=params, repetition=1, round_name="round2")

    assert result1["metrics"]["value"] == 100
    assert result2["metrics"]["value"] == 200


def test_cache_parameter_normalization(cache_db):
    """Test that parameter types are normalized."""
    cache = ExecutionCache(cache_db)

    metrics = {"value": 100}
    metadata = {}

    # Store with int
    cache.store_result(params={"nodes": 2}, repetition=1, metrics=metrics, metadata=metadata)

    # Should match with string "2"
    result = cache.get_cached_result(params={"nodes": "2"}, repetition=1)
    assert result is not None


def test_cache_exclude_vars(cache_db):
    """Test that excluded variables don't affect cache hash."""
    cache = ExecutionCache(cache_db, exclude_vars=["output_path"])

    metrics = {"value": 100}
    metadata = {}

    # Store with one output_path
    cache.store_result(
        params={"nodes": 2, "output_path": "/path/1"},
        repetition=1,
        metrics=metrics,
        metadata=metadata
    )

    # Should match with different output_path
    result = cache.get_cached_result(
        params={"nodes": 2, "output_path": "/path/2"},
        repetition=1
    )

    assert result is not None
    assert result["metrics"]["value"] == 100


def test_cache_update_existing(cache_db):
    """Test updating an existing cache entry."""
    cache = ExecutionCache(cache_db)

    params = {"nodes": 2}

    # Store initial result
    cache.store_result(
        params=params,
        repetition=1,
        metrics={"value": 100},
        metadata={"status": "OLD"}
    )

    # Update with new metrics
    cache.store_result(
        params=params,
        repetition=1,
        metrics={"value": 200},
        metadata={"status": "NEW"}
    )

    # Should have updated values
    result = cache.get_cached_result(params=params, repetition=1)
    assert result["metrics"]["value"] == 200
    assert result["metadata"]["status"] == "NEW"


def test_cache_stats(cache_db):
    """Test cache statistics."""
    cache = ExecutionCache(cache_db)

    # Store some results
    for i in range(3):
        cache.store_result(
            params={"nodes": i},
            repetition=1,
            metrics={"value": i},
            metadata={}
        )

    stats = cache.get_cache_stats()

    assert stats["total_entries"] == 3
    assert stats["unique_parameter_sets"] == 3


def test_cache_internal_keys_excluded(cache_db):
    """Test that internal keys (starting with __) are excluded from cache hash."""
    cache = ExecutionCache(cache_db)

    metrics = {"value": 100}
    metadata = {}

    # Store with internal key
    cache.store_result(
        params={"nodes": 2, "__internal_id": 123},
        repetition=1,
        metrics=metrics,
        metadata=metadata
    )

    # Should match without internal key
    result = cache.get_cached_result(
        params={"nodes": 2},
        repetition=1
    )

    assert result is not None
