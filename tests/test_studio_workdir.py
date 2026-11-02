"""Tests for how Studio relates a setup's workdir to a config's benchmark.workdir,
and for listing runs in a folder the user chooses."""

import shutil
import subprocess

import pytest

import iops.studio.settings as settings
from iops.studio.builder import target_path, workdir_outside_setup
from iops.studio.results import (
    is_safe_remote_dir,
    list_runs_command,
    parse_run_list,
    parse_runs_folder,
)
from iops.studio.settings import SetupConfig


# --------------------------------------------------------------------------- #
# target_path
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path,base,home,expected", [
    ("/scratch/me/runs", None, None, "/scratch/me/runs"),
    ("/a/b/../c/", None, None, "/a/c"),
    ("~/runs", None, None, "~/runs"),
    ("~/runs", None, "/home/me", "/home/me/runs"),
    ("$HOME/runs", None, "/home/me", "/home/me/runs"),
    ("${HOME}/runs", None, None, "~/runs"),
    ("./runs", "~/iops_workdir", None, "~/iops_workdir/runs"),
    ("runs", "/work", None, "/work/runs"),
    ("../elsewhere", "/work/wd", None, "/work/elsewhere"),
])
def test_target_path_resolves(path, base, home, expected):
    assert target_path(path, base, home) == expected


@pytest.mark.parametrize("path,base", [
    ("", "/work"),
    ("{{ os_env.SCRATCH }}/runs", "/work"),
    ("$SCRATCH/runs", "/work"),
    ("~other/runs", "/work"),
    ("runs", None),
])
def test_target_path_unresolvable(path, base):
    assert target_path(path, base) is None


# --------------------------------------------------------------------------- #
# workdir_outside_setup
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("setup,yaml_wd,home", [
    ("~/iops_workdir", "~/iops_workdir", None),
    ("~/iops_workdir", "~/iops_workdir/runs", None),
    ("~/iops_workdir", "./runs", None),
    ("~/iops_workdir", "runs/a", None),
    ("~/iops_workdir", "/home/me/iops_workdir/runs", "/home/me"),
    ("/work/wd", "/work/wd/x", None),
])
def test_workdir_inside_setup(setup, yaml_wd, home):
    assert workdir_outside_setup(setup, yaml_wd, home) is None


@pytest.mark.parametrize("setup,yaml_wd,home,expected", [
    ("~/iops_workdir", "~/other", None, "~/other"),
    ("~/iops_workdir", "../other", None, "~/other"),
    ("~/iops_workdir", "~/iops_workdir_old", None, "~/iops_workdir_old"),  # not a prefix match
    ("~/iops_workdir", "/scratch/me/runs", "/home/me", "/scratch/me/runs"),
    ("/work/wd", "/scratch/runs", None, "/scratch/runs"),
])
def test_workdir_outside_setup(setup, yaml_wd, home, expected):
    assert workdir_outside_setup(setup, yaml_wd, home) == expected


@pytest.mark.parametrize("setup,yaml_wd", [
    ("~/iops_workdir", "/scratch/me/runs"),          # ~ vs absolute, home unknown
    ("~/iops_workdir", "$SCRATCH/runs"),             # unknown variable
    ("~/iops_workdir", "{{ os_env.WORK }}/runs"),    # template
    ("~/iops_workdir", ""),
])
def test_workdir_location_unknown_does_not_warn(setup, yaml_wd):
    assert workdir_outside_setup(setup, yaml_wd) is None


# --------------------------------------------------------------------------- #
# Listing runs in a chosen folder
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path,ok", [
    ("~/iops_workdir", True),
    ("$SCRATCH/runs", True),
    ("/path with spaces/runs", True),
    ('/bad"quote', False),
    ("/bad`cmd`", False),
    ("/bad\\slash", False),
    ("", False),
    ("   ", False),
])
def test_is_safe_remote_dir(path, ok):
    assert is_safe_remote_dir(path) is ok


def test_parse_runs_folder():
    assert parse_runs_folder("__IOPS_DIR=/home/me/wd\n1.0\t/home/me/wd/run_001\n") == \
        (True, "/home/me/wd")
    assert parse_runs_folder("__IOPS_NO_DIR__\n") == (False, None)
    assert parse_runs_folder("") == (True, None)


def test_list_runs_command_does_not_contain_its_markers():
    # The markers are assembled by printf, so an echoed command line can never
    # be mistaken for the result.
    cmd = list_runs_command("/x")
    assert "__IOPS_DIR=" not in cmd and "__IOPS_NO_DIR__" not in cmd


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_list_runs_command_reports_missing_folder(tmp_path):
    out = subprocess.run(["bash", "-c", list_runs_command(str(tmp_path / "nope"))],
                         capture_output=True, text=True).stdout
    assert parse_runs_folder(out) == (False, None)
    assert parse_run_list(out) == []


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_list_runs_command_reports_resolved_folder(tmp_path):
    (tmp_path / "wd").mkdir()
    out = subprocess.run(["bash", "-c", list_runs_command(f"{tmp_path}/wd/../wd")],
                         capture_output=True, text=True).stdout
    exists, folder = parse_runs_folder(out)
    assert exists and folder == str(tmp_path / "wd")


# --------------------------------------------------------------------------- #
# The searched folder is remembered per setup
# --------------------------------------------------------------------------- #
def test_setup_runs_dir_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings.upsert_setup(SetupConfig("s", "local", None, "/usr/bin/python3",
                                      runs_dir="/scratch/me/runs"))
    settings.upsert_setup(SetupConfig("t", "local", None, "/usr/bin/python3"))
    assert settings.get_setup("s").runs_dir == "/scratch/me/runs"
    assert settings.get_setup("t").runs_dir is None
