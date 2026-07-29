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
