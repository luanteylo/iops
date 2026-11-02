"""Tests for command fingerprinting and cache schema migration."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from iops.cache import (
    CacheSchemaError,
    ExecutionCache,
    command_fingerprint,
    get_cache_entry,
    get_cache_stats,
    rebuild_cache,
)
from iops.cache.execution_cache import SCHEMA_VERSION


# Caches written by IOPS 3.5.10 (schema v0): a regular cache and the output
# of 'iops cache rebuild' (no unique constraint, duplicate keys)
FIXTURES = Path(__file__).parent / "fixtures" / "cache"
V0_PARAMS = [({"nodes": n, "ppn": 4, "path": f"/w/{n}"}, rep) for n in (1, 2) for rep in (1, 2)]

FP_A = command_fingerprint("ior -w -b {{ block }}")
FP_B = command_fingerprint("ior -w -r -b {{ block }}")


@pytest.fixture
def v0_cache(tmp_path):
    path = tmp_path / "cache.db"
    shutil.copy(FIXTURES / "cache_v0.db", path)
    return path


@pytest.fixture
def v0_rebuilt_cache(tmp_path):
    path = tmp_path / "rebuilt.db"
    shutil.copy(FIXTURES / "cache_v0_rebuilt.db", path)
    return path


def _user_version(path):
    with sqlite3.connect(str(path)) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def _store(cache, params, rep, bw):
    cache.store_result(params=params, repetition=rep, metrics={"bw": bw}, metadata={})


# ---------------------------------------------------------------------------
# command_fingerprint
# ---------------------------------------------------------------------------


def test_fingerprint_ignores_whitespace_reflow():
    assert command_fingerprint("ior  -w\n  -b {{ block }}") == command_fingerprint("ior -w -b {{ block }}")


def test_fingerprint_changes_with_template():
    assert FP_A != FP_B


def test_fingerprint_includes_env():
    base = command_fingerprint("ior", {"OMP_NUM_THREADS": "4"})
    assert base != command_fingerprint("ior", {"OMP_NUM_THREADS": "8"})
    assert base != command_fingerprint("ior")


def test_fingerprint_env_order_independent():
    assert command_fingerprint("ior", {"A": "1", "B": "2"}) == command_fingerprint("ior", {"B": "2", "A": "1"})


def test_fingerprint_no_env_equals_empty_env():
    assert command_fingerprint("ior", None) == command_fingerprint("ior", {})


# ---------------------------------------------------------------------------
# Lookup by fingerprint
# ---------------------------------------------------------------------------


def test_new_cache_has_current_schema(tmp_path):
    db = tmp_path / "cache.db"
    ExecutionCache(db)
    assert _user_version(db) == SCHEMA_VERSION


def test_hit_with_same_fingerprint(tmp_path):
    cache = ExecutionCache(tmp_path / "c.db", command_fingerprint=FP_A)
    _store(cache, {"nodes": 1}, 1, 10)

    result = cache.get_cached_result({"nodes": 1}, 1)
    assert result["metrics"] == {"bw": 10}
    assert result["verified"] is True
    assert cache.unverified_hits == 0


def test_miss_after_command_change(tmp_path):
    db = tmp_path / "c.db"
    _store(ExecutionCache(db, command_fingerprint=FP_A), {"nodes": 1}, 1, 10)

    assert ExecutionCache(db, command_fingerprint=FP_B).get_cached_result({"nodes": 1}, 1) is None


def test_results_for_two_commands_coexist(tmp_path):
    db = tmp_path / "c.db"
    _store(ExecutionCache(db, command_fingerprint=FP_A), {"nodes": 1}, 1, 10)
    _store(ExecutionCache(db, command_fingerprint=FP_B), {"nodes": 1}, 1, 20)

    assert ExecutionCache(db, command_fingerprint=FP_A).get_cached_result({"nodes": 1}, 1)["metrics"] == {"bw": 10}
    assert ExecutionCache(db, command_fingerprint=FP_B).get_cached_result({"nodes": 1}, 1)["metrics"] == {"bw": 20}


def test_store_replaces_entry_with_same_fingerprint(tmp_path):
    db = tmp_path / "c.db"
    cache = ExecutionCache(db, command_fingerprint=FP_A)
    _store(cache, {"nodes": 1}, 1, 10)
    _store(cache, {"nodes": 1}, 1, 11)

    assert cache.get_cached_result({"nodes": 1}, 1)["metrics"] == {"bw": 11}
    assert cache.get_cache_stats()["total_entries"] == 1


def test_store_without_fingerprint_replaces_entry(tmp_path):
    """Entries with unknown command keep one row per key (as before schema v1)."""
    cache = ExecutionCache(tmp_path / "c.db")
    _store(cache, {"nodes": 1}, 1, 10)
    _store(cache, {"nodes": 1}, 1, 11)

    assert cache.get_cached_result({"nodes": 1}, 1)["metrics"] == {"bw": 11}
    assert cache.get_cache_stats()["total_entries"] == 1


def test_cache_without_fingerprint_matches_any_command(tmp_path):
    db = tmp_path / "c.db"
    _store(ExecutionCache(db, command_fingerprint=FP_A), {"nodes": 1}, 1, 10)

    result = ExecutionCache(db).get_cached_result({"nodes": 1}, 1)
    assert result["metrics"] == {"bw": 10}
    assert result["verified"] is True


def test_unknown_command_entry_is_fallback(tmp_path):
    db = tmp_path / "c.db"
    _store(ExecutionCache(db), {"nodes": 1}, 1, 10)

    cache = ExecutionCache(db, command_fingerprint=FP_A)
    result = cache.get_cached_result({"nodes": 1}, 1)
    assert result["metrics"] == {"bw": 10}
    assert result["verified"] is False
    assert cache.unverified_hits == 1


def test_unverified_hits_counted_once_per_key(tmp_path):
    db = tmp_path / "c.db"
    _store(ExecutionCache(db), {"nodes": 1}, 1, 10)

    cache = ExecutionCache(db, command_fingerprint=FP_A)
    cache.get_cached_result({"nodes": 1}, 1)
    cache.get_cached_result({"nodes": 1}, 1)
    assert cache.unverified_hits == 1


def test_matching_fingerprint_preferred_over_unknown(tmp_path):
    db = tmp_path / "c.db"
    cache = ExecutionCache(db, command_fingerprint=FP_A)
    _store(cache, {"nodes": 1}, 1, 10)
    # Unknown-command entry written later must not shadow the verified one
    _store(ExecutionCache(db), {"nodes": 1}, 1, 99)

    result = cache.get_cached_result({"nodes": 1}, 1)
    assert result["metrics"] == {"bw": 10}
    assert result["verified"] is True


def test_strict_ignores_unknown_command_entries(tmp_path):
    db = tmp_path / "c.db"
    _store(ExecutionCache(db), {"nodes": 1}, 1, 10)

    assert ExecutionCache(db, command_fingerprint=FP_A, strict=True).get_cached_result({"nodes": 1}, 1) is None


def test_objective_metric_restricted_to_matching_fingerprint(tmp_path):
    db = tmp_path / "c.db"
    _store(ExecutionCache(db, command_fingerprint=FP_A), {"nodes": 1}, 1, 10)
    _store(ExecutionCache(db, command_fingerprint=FP_B), {"nodes": 1}, 1, 500)

    cache = ExecutionCache(db, command_fingerprint=FP_A, objective_metric="bw", objective="maximize")
    assert cache.get_cached_result({"nodes": 1}, 1)["metrics"] == {"bw": 10}


def test_repetitions_count_respects_fingerprint(tmp_path):
    db = tmp_path / "c.db"
    cache_a = ExecutionCache(db, command_fingerprint=FP_A)
    _store(cache_a, {"nodes": 1}, 1, 10)
    _store(cache_a, {"nodes": 1}, 2, 10)
    _store(ExecutionCache(db), {"nodes": 1}, 3, 10)

    assert cache_a.get_cached_repetitions_count({"nodes": 1}) == 3
    assert ExecutionCache(db, command_fingerprint=FP_A, strict=True).get_cached_repetitions_count({"nodes": 1}) == 2
    assert ExecutionCache(db, command_fingerprint=FP_B, strict=True).get_cached_repetitions_count({"nodes": 1}) == 0


# ---------------------------------------------------------------------------
# Migration of caches written by older IOPS versions (schema v0)
# ---------------------------------------------------------------------------


def test_v0_entries_still_hit_after_upgrade(v0_cache):
    cache = ExecutionCache(v0_cache, command_fingerprint=FP_A)

    for params, rep in V0_PARAMS:
        result = cache.get_cached_result(params, rep)
        assert result is not None
        assert result["metrics"] == {"bw": params["nodes"] * 100 + rep}
        assert result["verified"] is False
    assert cache.unverified_hits == len(V0_PARAMS)


def test_v0_migration_sets_version_and_keeps_backup(v0_cache):
    original = v0_cache.read_bytes()
    ExecutionCache(v0_cache)

    assert _user_version(v0_cache) == SCHEMA_VERSION
    backup = v0_cache.with_name(v0_cache.name + ".v0.bak")
    assert backup.read_bytes() == original


def test_v0_migration_keeps_all_rows(v0_cache):
    with sqlite3.connect(str(v0_cache)) as conn:
        before = conn.execute(
            "SELECT id, param_hash, params_json, repetition, metrics_json, metadata_json, created_at "
            "FROM cached_executions ORDER BY id"
        ).fetchall()

    ExecutionCache(v0_cache)

    with sqlite3.connect(str(v0_cache)) as conn:
        after = conn.execute(
            "SELECT id, param_hash, params_json, repetition, metrics_json, metadata_json, created_at "
            "FROM cached_executions ORDER BY id"
        ).fetchall()
        fingerprints = {row[0] for row in conn.execute("SELECT command_fingerprint FROM cached_executions")}
    assert after == before
    assert fingerprints == {None}


def test_v0_migration_is_idempotent(v0_cache):
    ExecutionCache(v0_cache)
    backup = v0_cache.with_name(v0_cache.name + ".v0.bak")
    backup_bytes = backup.read_bytes()

    ExecutionCache(v0_cache)

    assert _user_version(v0_cache) == SCHEMA_VERSION
    assert backup.read_bytes() == backup_bytes
    assert ExecutionCache(v0_cache).get_cache_stats()["total_entries"] == len(V0_PARAMS)


def test_v0_migration_failure_leaves_cache_untouched(v0_cache, monkeypatch):
    import iops.cache.execution_cache as ec

    original = v0_cache.read_bytes()

    def failing_indexes(conn, unique=True):
        raise sqlite3.OperationalError("simulated failure")

    monkeypatch.setattr(ec, "create_cache_indexes", failing_indexes)
    with pytest.raises(sqlite3.OperationalError, match="simulated failure"):
        ExecutionCache(v0_cache)

    assert v0_cache.read_bytes() == original
    assert _user_version(v0_cache) == 0


def test_v0_entry_replaced_by_new_result_keeps_old_row(v0_cache):
    """Re-running a test after upgrade adds a verified row; the legacy row stays."""
    cache = ExecutionCache(v0_cache, command_fingerprint=FP_A)
    params, rep = V0_PARAMS[0]
    _store(cache, params, rep, 1234)

    result = cache.get_cached_result(params, rep)
    assert result["metrics"] == {"bw": 1234}
    assert result["verified"] is True
    assert cache.get_cache_stats()["total_entries"] == len(V0_PARAMS) + 1


def test_v0_rebuilt_cache_keeps_duplicate_entries(v0_rebuilt_cache):
    """Rebuilt caches have no unique constraint; the migration must not add one."""
    cache = ExecutionCache(v0_rebuilt_cache, exclude_vars=["nodes", "path"], command_fingerprint=FP_A)
    assert cache.get_cache_stats()["total_entries"] == 4

    # Storing again appends, as rebuilt caches always did
    _store(cache, {"ppn": 4}, 1, 7)
    _store(cache, {"ppn": 4}, 1, 8)
    assert cache.get_cache_stats()["total_entries"] == 6


def test_newer_schema_is_refused(tmp_path):
    db = tmp_path / "future.db"
    ExecutionCache(db)
    with sqlite3.connect(str(db)) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")

    with pytest.raises(CacheSchemaError, match="Upgrade IOPS"):
        ExecutionCache(db)


# ---------------------------------------------------------------------------
# Rebuild and inspection
# ---------------------------------------------------------------------------


def test_rebuild_carries_fingerprints(tmp_path):
    src = tmp_path / "src.db"
    out = tmp_path / "out.db"
    _store(ExecutionCache(src, command_fingerprint=FP_A), {"nodes": 1, "path": "/a"}, 1, 10)
    _store(ExecutionCache(src, command_fingerprint=FP_B), {"nodes": 1, "path": "/b"}, 1, 20)

    stats = rebuild_cache(src, out, exclude_vars=["path"])
    assert stats.collisions == 0  # different commands do not collide

    assert _user_version(out) == SCHEMA_VERSION
    assert ExecutionCache(out, exclude_vars=["path"], command_fingerprint=FP_A).get_cached_result(
        {"nodes": 1}, 1)["metrics"] == {"bw": 10}
    assert ExecutionCache(out, exclude_vars=["path"], command_fingerprint=FP_B).get_cached_result(
        {"nodes": 1}, 1)["metrics"] == {"bw": 20}


def test_rebuild_from_v0_source_does_not_modify_source(v0_cache, tmp_path):
    original = v0_cache.read_bytes()
    out = tmp_path / "out.db"

    stats = rebuild_cache(v0_cache, out, exclude_vars=["path"])

    assert v0_cache.read_bytes() == original
    assert stats.output_entries == len(V0_PARAMS)
    with sqlite3.connect(str(out)) as conn:
        fingerprints = {row[0] for row in conn.execute("SELECT command_fingerprint FROM cached_executions")}
    assert fingerprints == {None}


def test_inspect_reads_v0_cache_without_migrating(v0_cache):
    original = v0_cache.read_bytes()

    stats = get_cache_stats(v0_cache)
    entry_hash = next(iter(
        sqlite3.connect(str(v0_cache)).execute("SELECT param_hash FROM cached_executions")
    ))[0]
    entry = get_cache_entry(v0_cache, entry_hash)

    assert v0_cache.read_bytes() == original
    assert stats["schema_version"] == 0
    assert stats["unverified_entries"] == len(V0_PARAMS)
    assert all(rep["command_fingerprint"] is None for rep in entry["repetitions"])


def test_inspect_reports_fingerprints(tmp_path):
    db = tmp_path / "c.db"
    _store(ExecutionCache(db, command_fingerprint=FP_A), {"nodes": 1}, 1, 10)
    _store(ExecutionCache(db, command_fingerprint=FP_B), {"nodes": 1}, 1, 20)
    _store(ExecutionCache(db), {"nodes": 2}, 1, 30)

    stats = get_cache_stats(db)
    assert stats["schema_version"] == SCHEMA_VERSION
    assert stats["distinct_commands"] == 2
    assert stats["unverified_entries"] == 1


# ---------------------------------------------------------------------------
# Stored command text
# ---------------------------------------------------------------------------

TEMPLATE_A = "ior -w\n  -b {{ block }}"
ENV_A = {"OMP_NUM_THREADS": "4"}


def _commands(path):
    with sqlite3.connect(str(path)) as conn:
        return conn.execute(
            "SELECT fingerprint, template, env_json FROM cached_commands ORDER BY first_seen"
        ).fetchall()


def test_template_sets_fingerprint(tmp_path):
    cache = ExecutionCache(tmp_path / "c.db", command_template=TEMPLATE_A, command_env=ENV_A)
    assert cache.command_fingerprint == command_fingerprint(TEMPLATE_A, ENV_A)


def test_store_records_command_text(tmp_path):
    db = tmp_path / "c.db"
    cache = ExecutionCache(db, command_template=TEMPLATE_A, command_env=ENV_A)
    _store(cache, {"nodes": 1}, 1, 10)
    _store(cache, {"nodes": 2}, 1, 20)

    assert _commands(db) == [(cache.command_fingerprint, TEMPLATE_A, '{"OMP_NUM_THREADS": "4"}')]


def test_command_not_recorded_without_results(tmp_path):
    db = tmp_path / "c.db"
    ExecutionCache(db, command_template=TEMPLATE_A)
    assert _commands(db) == []


def test_command_not_recorded_without_template(tmp_path):
    db = tmp_path / "c.db"
    _store(ExecutionCache(db, command_fingerprint=FP_A), {"nodes": 1}, 1, 10)
    _store(ExecutionCache(db), {"nodes": 2}, 1, 20)
    assert _commands(db) == []


def test_first_command_text_kept_for_same_fingerprint(tmp_path):
    """A reflowed template has the same fingerprint; the first text stays."""
    db = tmp_path / "c.db"
    _store(ExecutionCache(db, command_template=TEMPLATE_A), {"nodes": 1}, 1, 10)
    _store(ExecutionCache(db, command_template="ior -w -b {{ block }}"), {"nodes": 2}, 1, 20)

    rows = _commands(db)
    assert len(rows) == 1
    assert rows[0][1] == TEMPLATE_A


def test_one_command_row_per_fingerprint(tmp_path):
    db = tmp_path / "c.db"
    _store(ExecutionCache(db, command_template="ior -w"), {"nodes": 1}, 1, 10)
    _store(ExecutionCache(db, command_template="ior -r"), {"nodes": 1}, 1, 20)

    assert [row[1] for row in _commands(db)] == ["ior -w", "ior -r"]


def test_commands_table_added_to_existing_v1_cache(tmp_path):
    """Caches created before the commands table get it on open, with no version bump."""
    db = tmp_path / "c.db"
    _store(ExecutionCache(db, command_fingerprint=FP_A), {"nodes": 1}, 1, 10)
    with sqlite3.connect(str(db)) as conn:
        conn.execute("DROP TABLE cached_commands")

    cache = ExecutionCache(db, command_template="ior -w")
    assert _user_version(db) == SCHEMA_VERSION
    assert _commands(db) == []
    assert ExecutionCache(db, command_fingerprint=FP_A).get_cached_result({"nodes": 1}, 1) is not None

    _store(cache, {"nodes": 2}, 1, 20)
    assert [row[1] for row in _commands(db)] == ["ior -w"]


def test_v0_migration_adds_commands_table(v0_cache):
    ExecutionCache(v0_cache)
    assert _commands(v0_cache) == []


def test_clear_cache_clears_commands(tmp_path):
    db = tmp_path / "c.db"
    cache = ExecutionCache(db, command_template="ior -w")
    _store(cache, {"nodes": 1}, 1, 10)
    cache.clear_cache()
    assert _commands(db) == []

    # The command is recorded again with the next result
    _store(cache, {"nodes": 1}, 1, 10)
    assert [row[1] for row in _commands(db)] == ["ior -w"]


def test_rebuild_copies_commands(tmp_path):
    src = tmp_path / "src.db"
    out = tmp_path / "out.db"
    _store(ExecutionCache(src, command_template="ior -w", command_env=ENV_A), {"nodes": 1, "path": "/a"}, 1, 10)

    rebuild_cache(src, out, exclude_vars=["path"])

    assert _commands(out) == _commands(src)


def test_inspect_entry_includes_command_text(tmp_path):
    db = tmp_path / "c.db"
    cache_a = ExecutionCache(db, command_template="ior -w", command_env=ENV_A)
    _store(cache_a, {"nodes": 1}, 1, 10)
    # Fingerprint without stored text, as for results stored before this table existed
    _store(ExecutionCache(db, command_fingerprint=FP_B), {"nodes": 1}, 2, 20)

    entry_hash = next(iter(sqlite3.connect(str(db)).execute("SELECT param_hash FROM cached_executions")))[0]
    entry = get_cache_entry(db, entry_hash)

    assert entry["commands"] == {
        cache_a.command_fingerprint: {
            "template": "ior -w",
            "env": ENV_A,
            "first_seen": entry["commands"][cache_a.command_fingerprint]["first_seen"],
        }
    }


def test_inspect_stats_lists_commands(tmp_path):
    db = tmp_path / "c.db"
    cache_a = ExecutionCache(db, command_template="ior -w")
    _store(cache_a, {"nodes": 1}, 1, 10)
    _store(cache_a, {"nodes": 2}, 1, 10)
    _store(ExecutionCache(db, command_fingerprint=FP_B), {"nodes": 1}, 1, 20)
    _store(ExecutionCache(db), {"nodes": 3}, 1, 30)

    commands = get_cache_stats(db)["commands"]

    assert [(c["fingerprint"], c["entries"], c["template"]) for c in commands] == [
        (cache_a.command_fingerprint, 2, "ior -w"),
        (FP_B, 1, None),
    ]


def test_display_shows_command_text(tmp_path, capsys):
    from iops.cache.inspect import display_cache_entry, display_cache_stats

    db = tmp_path / "c.db"
    cache = ExecutionCache(db, command_template="mpirun -np 4\n  ior -w", command_env=ENV_A)
    _store(cache, {"nodes": 1}, 1, 10)
    entry_hash = next(iter(sqlite3.connect(str(db)).execute("SELECT param_hash FROM cached_executions")))[0]

    display_cache_entry(get_cache_entry(db, entry_hash))
    shown = capsys.readouterr().out
    assert f"command={cache.command_fingerprint[:8]}" in shown
    assert "    mpirun -np 4\n      ior -w\n" in shown
    assert "env OMP_NUM_THREADS=4" in shown

    display_cache_stats(get_cache_stats(db))
    assert "mpirun -np 4 ior -w" in capsys.readouterr().out


def test_command_text_backfilled_on_open(tmp_path):
    """Results stored without text get it when the matching command opens the cache."""
    db = tmp_path / "c.db"
    fp = command_fingerprint("ior -w", ENV_A)
    _store(ExecutionCache(db, command_fingerprint=fp), {"nodes": 1}, 1, 10)
    assert _commands(db) == []

    # A different command must not be attached to those results
    ExecutionCache(db, command_template="ior -r")
    assert _commands(db) == []

    ExecutionCache(db, command_template="ior -w", command_env=ENV_A)
    assert [(row[0], row[1]) for row in _commands(db)] == [(fp, "ior -w")]


# ---------------------------------------------------------------------------
# Listing per parameter set and command
# ---------------------------------------------------------------------------


def test_list_separates_commands(tmp_path):
    from iops.cache import list_cache_entries

    db = tmp_path / "c.db"
    cache_a = ExecutionCache(db, command_template="ior -w")
    cache_b = ExecutionCache(db, command_template="ior -r")
    for rep in (1, 2):
        _store(cache_a, {"nodes": 1}, rep, 10)
    _store(cache_b, {"nodes": 1}, 1, 30)

    entries = list_cache_entries(db)
    by_cmd = {e["command"]: e for e in entries}

    assert len(entries) == 2
    assert entries[0]["hash"] == entries[1]["hash"]
    assert by_cmd["ior -w"]["repetitions"] == [1, 2]
    assert by_cmd["ior -w"]["metrics"] == {"bw": 10}
    assert by_cmd["ior -r"]["repetitions"] == [1]
    assert by_cmd["ior -r"]["metrics"] == {"bw": 30}
    assert by_cmd["ior -w"]["command_fingerprint"] == cache_a.command_fingerprint


def test_list_unknown_command_and_missing_text(tmp_path):
    from iops.cache import list_cache_entries

    db = tmp_path / "c.db"
    _store(ExecutionCache(db), {"nodes": 1}, 1, 10)
    _store(ExecutionCache(db, command_fingerprint=FP_B), {"nodes": 2}, 1, 20)

    by_nodes = {e["params"]["nodes"]: e for e in list_cache_entries(db)}
    assert by_nodes[1]["command_fingerprint"] is None
    assert by_nodes[1]["command"] is None
    assert by_nodes[2]["command_fingerprint"] == FP_B
    assert by_nodes[2]["command"] is None


def test_list_counts_distinct_repetitions_in_rebuilt_cache(v0_rebuilt_cache):
    """Rebuilt caches can hold several rows per repetition; count each once."""
    from iops.cache import list_cache_entries

    entries = list_cache_entries(v0_rebuilt_cache)
    assert len(entries) == 1
    assert entries[0]["repetitions"] == [1, 2]
    assert entries[0]["rep_count"] == 2
    assert entries[0]["entries"] == 4


def test_list_reads_v0_cache_without_migrating(v0_cache):
    from iops.cache import list_cache_entries

    original = v0_cache.read_bytes()
    entries = list_cache_entries(v0_cache)

    assert v0_cache.read_bytes() == original
    assert len(entries) == 2
    assert all(e["command_fingerprint"] is None for e in entries)


def test_display_list_shows_command_column(tmp_path, capsys):
    from iops.cache import list_cache_entries
    from iops.cache.inspect import display_cache_list

    db = tmp_path / "c.db"
    cache_a = ExecutionCache(db, command_template="ior -w")
    _store(cache_a, {"nodes": 1}, 1, 10)
    _store(ExecutionCache(db, command_template="ior -r"), {"nodes": 1}, 1, 30)
    _store(ExecutionCache(db), {"nodes": 2}, 1, 20)

    display_cache_list(list_cache_entries(db))
    out = capsys.readouterr().out

    header = out.splitlines()[0].split()
    assert header[:2] == ["Hash", "Cmd"]
    assert cache_a.command_fingerprint[:8] in out
    assert "unknown" in out
    assert "3 row(s): 2 unique parameter set(s), 2 command(s), 1 row(s) with unknown command" in out
