"""Tests for execution caching."""

import pytest
from pathlib import Path

from iops.cache import ExecutionCache


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


# ============================================================================
# Tests for cache rebuild functionality
# ============================================================================

from iops.cache import rebuild_cache, RebuildStats


def test_rebuild_basic(tmp_path):
    """Test basic cache rebuild with excluded variables."""
    source_db = tmp_path / "source.db"
    output_db = tmp_path / "output.db"

    # Create source cache with entries that include a path variable
    cache = ExecutionCache(source_db)

    # Store entries with different paths but same core params
    cache.store_result(
        params={"nodes": 2, "ppn": 4, "output_path": "/run1/out.txt"},
        repetition=1,
        metrics={"bandwidth": 100},
        metadata={"status": "SUCCESS"}
    )
    cache.store_result(
        params={"nodes": 2, "ppn": 4, "output_path": "/run2/out.txt"},
        repetition=1,
        metrics={"bandwidth": 110},
        metadata={"status": "SUCCESS"}
    )
    cache.store_result(
        params={"nodes": 4, "ppn": 4, "output_path": "/run3/out.txt"},
        repetition=1,
        metrics={"bandwidth": 200},
        metadata={"status": "SUCCESS"}
    )

    # Source should have 3 unique hashes (different paths)
    stats_before = cache.get_cache_stats()
    assert stats_before["total_entries"] == 3
    assert stats_before["unique_parameter_sets"] == 3

    # Rebuild excluding output_path
    stats = rebuild_cache(
        source_db=source_db,
        output_db=output_db,
        exclude_vars=["output_path"]
    )

    assert stats.source_entries == 3
    assert stats.source_unique_hashes == 3
    assert stats.output_entries == 3  # All entries preserved
    assert stats.output_unique_hashes == 2  # nodes=2 and nodes=4
    assert stats.collisions == 1  # Two entries collapsed to same (hash, rep=1)


def test_rebuild_keeps_all_entries(tmp_path):
    """Test that rebuild keeps all entries even when they collapse to same hash."""
    source_db = tmp_path / "source.db"
    output_db = tmp_path / "output.db"

    cache = ExecutionCache(source_db)

    # Store 5 entries that will all collapse to the same hash when excluding 'run_id'
    for i in range(5):
        cache.store_result(
            params={"nodes": 2, "run_id": f"run_{i}"},
            repetition=1,
            metrics={"value": i * 10},
            metadata={}
        )

    stats = rebuild_cache(
        source_db=source_db,
        output_db=output_db,
        exclude_vars=["run_id"]
    )

    assert stats.source_entries == 5
    assert stats.output_entries == 5  # All kept
    assert stats.output_unique_hashes == 1  # All collapse to same hash
    assert stats.collisions == 4  # 4 collisions (first is not a collision)


def test_rebuild_different_repetitions(tmp_path):
    """Test rebuild with multiple repetitions."""
    source_db = tmp_path / "source.db"
    output_db = tmp_path / "output.db"

    cache = ExecutionCache(source_db)

    # Store entries with different repetitions
    for rep in range(1, 4):
        cache.store_result(
            params={"nodes": 2, "path": f"/path/{rep}"},
            repetition=rep,
            metrics={"value": rep * 100},
            metadata={}
        )

    stats = rebuild_cache(
        source_db=source_db,
        output_db=output_db,
        exclude_vars=["path"]
    )

    # 3 entries, 3 unique hashes before (due to different paths)
    # After rebuild: 1 unique hash, but 3 different repetitions = no collision
    assert stats.source_entries == 3
    assert stats.output_entries == 3
    assert stats.output_unique_hashes == 1
    assert stats.collisions == 0  # Different repetitions don't collide


def test_rebuild_source_not_found(tmp_path):
    """Test rebuild raises error when source doesn't exist."""
    source_db = tmp_path / "nonexistent.db"
    output_db = tmp_path / "output.db"

    with pytest.raises(FileNotFoundError):
        rebuild_cache(source_db, output_db, exclude_vars=["var"])


def test_rebuild_output_exists(tmp_path):
    """Test rebuild raises error when output already exists."""
    source_db = tmp_path / "source.db"
    output_db = tmp_path / "output.db"

    # Create both files
    ExecutionCache(source_db)
    output_db.touch()

    with pytest.raises(ValueError, match="already exists"):
        rebuild_cache(source_db, output_db, exclude_vars=["var"])


def test_rebuild_empty_cache(tmp_path):
    """Test rebuilding an empty cache."""
    source_db = tmp_path / "source.db"
    output_db = tmp_path / "output.db"

    # Create empty cache
    ExecutionCache(source_db)

    stats = rebuild_cache(
        source_db=source_db,
        output_db=output_db,
        exclude_vars=["anything"]
    )

    assert stats.source_entries == 0
    assert stats.output_entries == 0
    assert stats.output_unique_hashes == 0
    assert stats.collisions == 0


def test_rebuild_stats_summary():
    """Test RebuildStats summary formatting."""
    stats = RebuildStats(
        source_entries=100,
        source_unique_hashes=50,
        output_entries=100,
        output_unique_hashes=25,
        excluded_vars=["path", "run_id"],
        collisions=25
    )

    summary = stats.summary()

    assert "100" in summary  # source entries
    assert "50" in summary   # source unique hashes
    assert "25" in summary   # output unique hashes and collisions
    assert "path, run_id" in summary  # excluded vars


def test_rebuild_conflict_all_data_preserved(tmp_path):
    """Test that conflicting entries are all preserved and queryable in rebuilt cache."""
    import sqlite3

    source_db = tmp_path / "source.db"
    output_db = tmp_path / "output.db"

    cache = ExecutionCache(source_db)

    # Store 3 entries that will collapse to same (hash, rep=1) when excluding 'path'
    # Each has different metrics to verify all are preserved
    cache.store_result(
        params={"nodes": 2, "path": "/run1"},
        repetition=1,
        metrics={"bandwidth": 100},
        metadata={"run": "first"}
    )
    cache.store_result(
        params={"nodes": 2, "path": "/run2"},
        repetition=1,
        metrics={"bandwidth": 200},
        metadata={"run": "second"}
    )
    cache.store_result(
        params={"nodes": 2, "path": "/run3"},
        repetition=1,
        metrics={"bandwidth": 300},
        metadata={"run": "third"}
    )

    stats = rebuild_cache(
        source_db=source_db,
        output_db=output_db,
        exclude_vars=["path"]
    )

    assert stats.collisions == 2  # 2 collisions (entries 2 and 3 collide with entry 1)

    # Query the rebuilt database directly to verify all entries exist
    with sqlite3.connect(str(output_db)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # All entries should have the same param_hash now
        cursor.execute("SELECT DISTINCT param_hash FROM cached_executions")
        hashes = cursor.fetchall()
        assert len(hashes) == 1  # All collapsed to one hash

        # But all 3 entries should be present
        cursor.execute("SELECT * FROM cached_executions ORDER BY created_at")
        rows = cursor.fetchall()
        assert len(rows) == 3

        # Verify each entry's metrics are preserved
        import json
        bandwidths = [json.loads(row["metrics_json"])["bandwidth"] for row in rows]
        assert sorted(bandwidths) == [100, 200, 300]

        # Verify the params_json no longer contains 'path'
        for row in rows:
            params = json.loads(row["params_json"])
            assert "path" not in params
            assert params["nodes"] == 2


def test_rebuild_add_vars(tmp_path):
    """Test adding variables to all cache entries."""
    import sqlite3
    import json

    source_db = tmp_path / "source.db"
    output_db = tmp_path / "output.db"

    cache = ExecutionCache(source_db)

    # Store some entries
    cache.store_result(
        params={"nodes": 2, "ppn": 4},
        repetition=1,
        metrics={"bandwidth": 100},
        metadata={"status": "SUCCESS"}
    )
    cache.store_result(
        params={"nodes": 4, "ppn": 8},
        repetition=1,
        metrics={"bandwidth": 200},
        metadata={"status": "SUCCESS"}
    )

    # Rebuild with add_vars
    stats = rebuild_cache(
        source_db=source_db,
        output_db=output_db,
        add_vars={"cluster": "skylake", "version": "1.0"}
    )

    assert stats.source_entries == 2
    assert stats.output_entries == 2
    assert stats.added_vars == {"cluster": "skylake", "version": "1.0"}

    # Verify the new variables are in params_json
    with sqlite3.connect(str(output_db)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT params_json FROM cached_executions")
        rows = cursor.fetchall()

        for row in rows:
            params = json.loads(row["params_json"])
            assert params["cluster"] == "skylake"
            # Note: "1.0" gets normalized to float 1.0 by normalize_params
            assert params["version"] == 1.0


def test_rebuild_add_vars_changes_hash(tmp_path):
    """Test that adding variables changes the param_hash."""
    import sqlite3

    source_db = tmp_path / "source.db"
    output_db = tmp_path / "output.db"

    cache = ExecutionCache(source_db)

    cache.store_result(
        params={"nodes": 2},
        repetition=1,
        metrics={"value": 100},
        metadata={}
    )

    # Get the original hash
    with sqlite3.connect(str(source_db)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT param_hash FROM cached_executions")
        original_hash = cursor.fetchone()[0]

    # Rebuild with add_vars
    rebuild_cache(
        source_db=source_db,
        output_db=output_db,
        add_vars={"new_var": "value"}
    )

    # Get the new hash
    with sqlite3.connect(str(output_db)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT param_hash FROM cached_executions")
        new_hash = cursor.fetchone()[0]

    # Hash should be different because we added a variable
    assert original_hash != new_hash


def test_rebuild_add_and_exclude_combined(tmp_path):
    """Test combining add_vars and exclude_vars in same rebuild."""
    import sqlite3
    import json

    source_db = tmp_path / "source.db"
    output_db = tmp_path / "output.db"

    cache = ExecutionCache(source_db)

    cache.store_result(
        params={"nodes": 2, "path": "/run1"},
        repetition=1,
        metrics={"value": 100},
        metadata={}
    )
    cache.store_result(
        params={"nodes": 2, "path": "/run2"},
        repetition=1,
        metrics={"value": 200},
        metadata={}
    )

    # Rebuild: exclude path, add cluster
    stats = rebuild_cache(
        source_db=source_db,
        output_db=output_db,
        exclude_vars=["path"],
        add_vars={"cluster": "test"}
    )

    assert stats.source_entries == 2
    assert stats.output_entries == 2
    assert stats.excluded_vars == ["path"]
    assert stats.added_vars == {"cluster": "test"}
    # Both entries should collapse to same hash (path excluded, same cluster added)
    assert stats.output_unique_hashes == 1
    assert stats.collisions == 1

    # Verify params
    with sqlite3.connect(str(output_db)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT params_json FROM cached_executions")
        rows = cursor.fetchall()

        for row in rows:
            params = json.loads(row["params_json"])
            assert "path" not in params  # excluded
            assert params["cluster"] == "test"  # added
            assert params["nodes"] == 2  # preserved


def test_rebuild_stats_summary_with_added_vars():
    """Test RebuildStats summary formatting with added variables."""
    stats = RebuildStats(
        source_entries=100,
        source_unique_hashes=50,
        output_entries=100,
        output_unique_hashes=50,
        excluded_vars=[],
        added_vars={"cluster": "skylake", "version": "2.0"},
        collisions=0
    )

    summary = stats.summary()

    assert "cluster=skylake" in summary
    assert "version=2.0" in summary


def test_rebuild_add_vars_typed_values(tmp_path):
    """Test adding typed variables (bool, int, float) to cache entries."""
    import sqlite3
    import json

    source_db = tmp_path / "source.db"
    output_db = tmp_path / "output.db"

    cache = ExecutionCache(source_db)

    cache.store_result(
        params={"nodes": 2},
        repetition=1,
        metrics={"value": 100},
        metadata={}
    )

    # Add typed values (as they would come from CLI after parsing)
    stats = rebuild_cache(
        source_db=source_db,
        output_db=output_db,
        add_vars={
            "use_new_flag": False,  # bool
            "threshold": 1.5,       # float
            "count": 10,            # int
            "label": "test",        # str
        }
    )

    assert stats.output_entries == 1

    # Verify the typed values are preserved correctly
    with sqlite3.connect(str(output_db)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT params_json FROM cached_executions")
        row = cursor.fetchone()
        params = json.loads(row["params_json"])

        # Check types are preserved after JSON round-trip
        assert params["use_new_flag"] is False
        assert isinstance(params["use_new_flag"], bool)
        assert params["threshold"] == 1.5
        assert isinstance(params["threshold"], float)
        assert params["count"] == 10
        assert isinstance(params["count"], int)
        assert params["label"] == "test"
        assert isinstance(params["label"], str)


def test_rebuild_add_vars_bool_matches_yaml_config(tmp_path):
    """Test that added bool values match what YAML config would produce."""
    import sqlite3
    import json

    source_db = tmp_path / "source.db"
    output_db = tmp_path / "output.db"

    # Simulate what would be in cache from a YAML config with bool var
    cache = ExecutionCache(source_db)
    cache.store_result(
        params={"nodes": 2, "use_feature": True},  # bool from YAML
        repetition=1,
        metrics={"value": 100},
        metadata={}
    )

    # Get the hash for the entry with use_feature=True
    with sqlite3.connect(str(source_db)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT param_hash FROM cached_executions")
        original_hash = cursor.fetchone()[0]

    # Now rebuild a different cache, adding use_feature=True as bool
    source_db2 = tmp_path / "source2.db"
    output_db2 = tmp_path / "output2.db"

    cache2 = ExecutionCache(source_db2)
    cache2.store_result(
        params={"nodes": 2},  # no use_feature
        repetition=1,
        metrics={"value": 200},
        metadata={}
    )

    rebuild_cache(
        source_db=source_db2,
        output_db=output_db2,
        add_vars={"use_feature": True}  # Add as bool
    )

    # Get the hash after adding use_feature=True
    with sqlite3.connect(str(output_db2)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT param_hash FROM cached_executions")
        rebuilt_hash = cursor.fetchone()[0]

    # The hashes should match - both have nodes=2, use_feature=True (bool)
    assert original_hash == rebuilt_hash
