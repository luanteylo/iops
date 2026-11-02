"""Tests for the Studio file browser's directory-listing logic.

Only ``_entries`` is covered here: it is the browser's sole non-UI helper, so it
can be exercised without a NiceGUI client context.
"""

from iops.studio.filebrowser import YAML_EXTS, _entries


def _make_tree(root):
    (root / "sub").mkdir()
    (root / "zsub").mkdir()
    (root / ".hidden_dir").mkdir()
    (root / "a.yaml").write_text("x")
    (root / "b.yml").write_text("x")
    (root / "c.txt").write_text("x")
    (root / ".secret.yaml").write_text("x")


def test_entries_filters_hidden_and_extensions(tmp_path):
    _make_tree(tmp_path)
    dirs, files = _entries(tmp_path, show_hidden=False, extensions=YAML_EXTS)
    assert [d.name for d in dirs] == ["sub", "zsub"]          # sorted, no dotdir
    assert [f.name for f in files] == ["a.yaml", "b.yml"]     # .txt and dotfile dropped


def test_entries_show_hidden_includes_dotfiles(tmp_path):
    _make_tree(tmp_path)
    dirs, files = _entries(tmp_path, show_hidden=True, extensions=YAML_EXTS)
    assert ".hidden_dir" in [d.name for d in dirs]
    assert ".secret.yaml" in [f.name for f in files]
    assert "c.txt" not in [f.name for f in files]             # ext filter still applies


def test_entries_no_extension_filter_returns_all_files(tmp_path):
    _make_tree(tmp_path)
    _, files = _entries(tmp_path, show_hidden=False, extensions=())
    assert [f.name for f in files] == ["a.yaml", "b.yml", "c.txt"]


def test_entries_missing_directory_is_empty(tmp_path):
    dirs, files = _entries(tmp_path / "does_not_exist", show_hidden=False, extensions=YAML_EXTS)
    assert dirs == [] and files == []


# --------------------------------------------------------------------------- #
# Search: live filter of one listing and the recursive subfolder search
# --------------------------------------------------------------------------- #
from iops.studio.filebrowser import _filter_entries, _name_matcher, _search  # noqa: E402


def _make_deep_tree(root):
    (root / "projects" / "ior_study" / "configs").mkdir(parents=True)
    (root / "projects" / "fio_study").mkdir(parents=True)
    (root / "projects" / "ior_study" / "configs" / "ior_run.yaml").write_text("x")
    (root / "projects" / "ior_study" / "notes.txt").write_text("x")
    (root / ".cache" / "ior_hidden").mkdir(parents=True)
    (root / "node_modules" / "ior_pkg").mkdir(parents=True)


def test_name_matcher_substring_is_case_insensitive():
    match = _name_matcher("IOR")
    assert match("ior_study") and match("My_Ior") and not match("fio")


def test_name_matcher_glob():
    match = _name_matcher("*_study")
    assert match("ior_study") and not match("ior_study_old")


def test_name_matcher_empty_matches_everything():
    assert _name_matcher("  ")("anything")


def test_filter_entries(tmp_path):
    _make_tree(tmp_path)
    dirs, files = _entries(tmp_path, show_hidden=False, extensions=YAML_EXTS)
    fdirs, ffiles = _filter_entries(dirs, files, "z")
    assert [d.name for d in fdirs] == ["zsub"] and ffiles == []


def test_search_finds_nested_folders_and_files(tmp_path):
    _make_deep_tree(tmp_path)
    matches, truncated = _search(tmp_path, "ior", show_hidden=False, extensions=YAML_EXTS)
    found = {(p.relative_to(tmp_path).as_posix(), is_dir) for p, is_dir in matches}
    assert found == {("projects/ior_study", True),
                     ("projects/ior_study/configs/ior_run.yaml", False)}
    assert not truncated


def test_search_is_breadth_first(tmp_path):
    _make_deep_tree(tmp_path)
    matches, _ = _search(tmp_path, "ior", show_hidden=False, extensions=YAML_EXTS)
    assert [is_dir for _, is_dir in matches] == [True, False]  # shallow folder first


def test_search_hidden_and_skipped_dirs(tmp_path):
    _make_deep_tree(tmp_path)
    names = [p.name for p, _ in _search(tmp_path, "ior", show_hidden=True,
                                        extensions=YAML_EXTS)[0]]
    assert "ior_hidden" in names        # hidden folders searched when asked
    assert "ior_pkg" not in names       # node_modules is never entered


def test_search_folders_only(tmp_path):
    _make_deep_tree(tmp_path)
    matches, _ = _search(tmp_path, "ior", show_hidden=False, extensions=(), include_files=False)
    assert all(is_dir for _, is_dir in matches)


def test_search_stops_at_max_results(tmp_path):
    for i in range(5):
        (tmp_path / f"run_{i}").mkdir()
    matches, truncated = _search(tmp_path, "run", show_hidden=False, extensions=(),
                                 max_results=3)
    assert len(matches) == 3 and truncated


def test_search_stops_at_max_dirs(tmp_path):
    _make_deep_tree(tmp_path)
    _, truncated = _search(tmp_path, "nothing_matches", show_hidden=False,
                           extensions=(), max_dirs=1)
    assert truncated


def test_search_does_not_follow_symlinked_folders(tmp_path):
    (tmp_path / "real" / "target_dir").mkdir(parents=True)
    (tmp_path / "real" / "loop").symlink_to(tmp_path)
    matches, truncated = _search(tmp_path, "target", show_hidden=False, extensions=())
    assert [p.name for p, _ in matches] == ["target_dir"] and not truncated
