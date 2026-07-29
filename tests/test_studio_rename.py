"""Tests for migrating a setup's configs and runs when it is renamed."""

import iops.studio.configs as configs
import iops.studio.runs as runs
from iops.studio.configs import StudioConfig
from iops.studio.runs import RunRecord


def test_configs_rename_setup_moves_only_matching(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    configs.upsert_config(StudioConfig("a", "old", "yaml: a"))
    configs.upsert_config(StudioConfig("b", "old", "yaml: b"))
    configs.upsert_config(StudioConfig("c", "other", "yaml: c"))

    moved = configs.rename_setup("old", "new")
    assert moved == 2
    assert {c.name for c in configs.load_configs("new")} == {"a", "b"}
    assert configs.load_configs("old") == []
    assert [c.name for c in configs.load_configs("other")] == ["c"]  # untouched
    # yaml_text preserved through the migration
    assert configs.get_config("new", "a").yaml_text == "yaml: a"


def test_runs_rename_setup_moves_only_matching(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    runs.add_run(RunRecord("old", "cfg1", "iops_1", "node1"))
    runs.add_run(RunRecord("old", "cfg2", "iops_2", "node2"))
    runs.add_run(RunRecord("keep", "cfg3", "iops_3", "node3"))

    moved = runs.rename_setup("old", "new")
    assert moved == 2
    assert {r.screen_name for r in runs.load_runs("new")} == {"iops_1", "iops_2"}
    assert runs.load_runs("old") == []
    assert [r.screen_name for r in runs.load_runs("keep")] == ["iops_3"]


def test_rename_setup_noop_when_names_equal(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    configs.upsert_config(StudioConfig("a", "same", "y"))
    assert configs.rename_setup("same", "same") == 0
    assert runs.rename_setup("same", "same") == 0


def test_rename_setup_absent_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert configs.rename_setup("nope", "new") == 0
    assert runs.rename_setup("nope", "new") == 0
