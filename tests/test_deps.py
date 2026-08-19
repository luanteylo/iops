"""Unit tests for the optional dependency catalog (iops/deps.py) and `iops deps`.

Covers:
1. The catalog agrees with [project.optional-dependencies] in pyproject.toml
2. Availability detection, including packages whose import name differs
3. Table rendering, the --missing filter, and the install hint
4. The CLI command's output and its --check exit code
"""

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from iops import deps


PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


# ============================================================================ #
# Catalog integrity
# ============================================================================ #

def test_catalog_matches_pyproject_extras():
    """Every extra IOPS ships must be described exactly once in the catalog."""
    declared = tomllib.loads(PYPROJECT.read_text())["project"]["optional-dependencies"]
    assert {d.extra for d in deps.OPTIONAL_DEPENDENCIES} == set(declared)


def test_catalog_package_names_match_pyproject():
    declared = tomllib.loads(PYPROJECT.read_text())["project"]["optional-dependencies"]
    for dep in deps.OPTIONAL_DEPENDENCIES:
        assert declared[dep.extra] == [dep.package]


def test_catalog_entries_are_unique_and_described():
    extras = [d.extra for d in deps.OPTIONAL_DEPENDENCIES]
    assert len(extras) == len(set(extras))
    for dep in deps.OPTIONAL_DEPENDENCIES:
        assert dep.enables.strip()


def test_get_rejects_unknown_extra():
    with pytest.raises(KeyError, match="Unknown optional dependency"):
        deps.get("nope")


# ============================================================================ #
# Availability detection
# ============================================================================ #

def test_import_name_differs_from_package_name():
    """pillow imports as PIL; detection must use the module, not the package."""
    gallery = deps.get("gallery")
    assert gallery.package == "pillow" and gallery.module == "PIL"


def test_is_available_agrees_with_a_real_import():
    """The cheap check and the authoritative one must not disagree in practice."""
    for dep in deps.OPTIONAL_DEPENDENCIES:
        assert deps.is_available(dep.extra) == _importable(dep.module)


def test_is_importable_reflects_a_real_import():
    for dep in deps.OPTIONAL_DEPENDENCIES:
        assert deps.is_importable(dep.extra) == _importable(dep.module)


def test_is_available_does_not_load_the_package(monkeypatch):
    """The gates run on every startup, so they must not pay a package's import cost."""
    import sys

    for name in [m for m in sys.modules if m == "skopt" or m.startswith("skopt.")]:
        del sys.modules[name]
    deps.is_available.cache_clear()

    assert deps.is_available("bayesian") is True
    assert "skopt" not in sys.modules


def _importable(module):
    import importlib

    try:
        importlib.import_module(module)
        return True
    except ImportError:
        return False


def test_missing_extras_are_a_subset_of_the_catalog():
    known = {d.extra for d in deps.OPTIONAL_DEPENDENCIES}
    assert set(deps.missing_extras()) <= known


def test_installed_version_is_none_only_when_unavailable():
    for dep in deps.OPTIONAL_DEPENDENCIES:
        version = deps.installed_version(dep.extra)
        assert (version is None) == (not deps.is_importable(dep.extra))


# ============================================================================ #
# Rendering
# ============================================================================ #

def test_install_hint_joins_extras():
    assert deps.install_hint(["watch", "plots"]) == 'pip install "iops-benchmark[watch,plots]"'


def test_install_hint_quotes_the_spec_for_zsh():
    """zsh globs square brackets, so an unquoted spec fails with 'no matches found'."""
    hint = deps.install_hint(["bayesian"])
    assert hint == 'pip install "iops-benchmark[bayesian]"'
    assert hint.count('"') == 2


def test_no_source_file_prints_an_unquoted_install_hint():
    """Every install hint IOPS emits must survive being pasted into zsh."""
    root = Path(__file__).resolve().parent.parent / "iops"
    offenders = [
        f"{path.relative_to(root)}:{n}"
        for path in root.rglob("*.py")
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if "pip install iops-benchmark[" in line
    ]
    assert offenders == []


def test_format_status_lists_every_extra(monkeypatch):
    monkeypatch.setattr(deps, "is_importable", lambda extra: True)
    out = deps.format_status()
    for dep in deps.OPTIONAL_DEPENDENCIES:
        assert dep.extra in out
        assert dep.package in out


def test_format_status_marks_absent_packages(monkeypatch):
    monkeypatch.setattr(deps, "is_importable", lambda extra: False)
    assert deps.format_status().count("not installed") == len(deps.OPTIONAL_DEPENDENCIES)


def test_format_status_missing_only_filters_installed(monkeypatch):
    monkeypatch.setattr(deps, "is_importable", lambda extra: extra != "watch")
    out = deps.format_status(missing_only=True)
    assert "watch" in out
    assert "studio" not in out


def test_format_status_missing_only_says_so_when_all_present(monkeypatch):
    monkeypatch.setattr(deps, "is_importable", lambda extra: True)
    assert deps.format_status(missing_only=True) == "All optional dependencies are installed."


# ============================================================================ #
# CLI
# ============================================================================ #

def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "iops.main", *args],
        capture_output=True, text=True,
    )


def test_cli_lists_dependencies():
    result = _run("deps")
    assert result.returncode == 0
    for dep in deps.OPTIONAL_DEPENDENCIES:
        assert dep.extra in result.stdout
    assert "EXTRA" in result.stdout and "ENABLES" in result.stdout


def test_cli_check_exit_code_tracks_missing_packages():
    result = _run("deps", "--check")
    assert result.returncode == (1 if deps.missing_extras() else 0)


def test_cli_missing_flag_hides_installed_packages():
    result = _run("deps", "--missing")
    assert result.returncode == 0
    installed = [d.extra for d in deps.OPTIONAL_DEPENDENCIES if deps.is_available(d.extra)]
    for extra in installed:
        assert f"\n{extra} " not in result.stdout
