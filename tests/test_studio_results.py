"""Tests for the UI-free Studio results helpers."""

import json
import subprocess
import sys
import tarfile
from pathlib import Path

from iops.studio.results import (
    REPORT_FILENAME,
    archive_command,
    human_size,
    list_runs_command,
    local_archive_path,
    localize_report_html,
    parse_archive_output,
    parse_run_list,
    plotly_bundle_path,
    report_html_path,
    slug,
)


def test_parse_run_list_newest_first_and_deduped():
    out = (
        "1720000002.5\t/home/u/wd/run_003\n"
        "1720000001.0\t/home/u/wd/run_002\n"
        "1720000001.0\t/home/u/wd/run_002\n"   # duplicate line
        "\n"
        "sort: warning noise without a tab\n"   # ignored
        "1720000000.0\t/home/u/wd/run_001\n"
    )
    assert parse_run_list(out) == [
        "/home/u/wd/run_003", "/home/u/wd/run_002", "/home/u/wd/run_001",
    ]


def test_parse_run_list_empty():
    assert parse_run_list("") == []
    assert parse_run_list(None) == []


def test_list_runs_command_targets_metadata_marker():
    cmd = list_runs_command("$HOME/iops_workdir")
    assert '"$HOME/iops_workdir"' in cmd
    assert "__iops_run_metadata.json" in cmd
    assert "sort -rn" in cmd


def test_report_html_path():
    assert report_html_path("/wd/run_001") == f"/wd/run_001/{REPORT_FILENAME}"
    assert report_html_path("/wd/run_001/") == f"/wd/run_001/{REPORT_FILENAME}"


def _make_run(root):
    """A minimal run directory that `iops archive create` accepts."""
    run = root / "run_001"
    exec_dir = run / "exec_0001" / "repetition_001"
    exec_dir.mkdir(parents=True)
    (run / "__iops_run_metadata.json").write_text(json.dumps(
        {"benchmark": {"name": "Pull test"}, "iops_version": "3.0.0"}))
    (run / "__iops_index.json").write_text(json.dumps({
        "benchmark": "Pull test", "total_expected": 1, "repetitions": 1,
        "executions": {"exec_0001": {"path": "exec_0001", "params": {"n": 1},
                                     "command": "echo"}},
    }))
    (run / "exec_0001" / "__iops_params.json").write_text(json.dumps({"n": 1}))
    (exec_dir / "__iops_status.json").write_text(json.dumps({"status": "SUCCEEDED"}))
    # Not one of the old "light" suffixes: the archive must still contain it
    (exec_dir / "raw.dat").write_bytes(b"\0" * 4096)
    (run / "results.csv").write_text("n,bw\n1,10\n")
    return run


def _run_archive(tmp_path, run_dir, staging):
    """Execute archive_command in bash from a scratch cwd, as the terminal would."""
    cwd = tmp_path / "cwd"
    cwd.mkdir(exist_ok=True)
    cmd = archive_command(sys.executable, str(run_dir), str(staging), "out.tar.gz")
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True,
                          text=True, timeout=120), cwd


def test_archive_command_produces_a_cli_archive(tmp_path):
    run = _make_run(tmp_path)
    staging = tmp_path / "staging"
    proc, cwd = _run_archive(tmp_path, run, staging)
    assert proc.returncode == 0, proc.stderr + proc.stdout

    path, size = parse_archive_output(proc.stdout)
    assert path == str((staging / "out.tar.gz").resolve())
    assert size == Path(path).stat().st_size

    # The whole run is in it, raw data included, along with the archive manifest
    from iops.archive.core import ArchiveReader
    reader = ArchiveReader(Path(path))
    assert reader.get_manifest() is not None
    with tarfile.open(path) as tf:
        names = tf.getnames()
    assert any(n.endswith("raw.dat") for n in names)
    assert any(n.endswith("results.csv") for n in names)

    # The log `iops archive create` writes is removed, and none lands in the cwd
    assert list(staging.iterdir()) == [staging / "out.tar.gz"]
    assert not (cwd / "iops.log").exists()


def test_archive_command_fails_without_markers_for_a_non_run(tmp_path):
    not_a_run = tmp_path / "empty"
    not_a_run.mkdir()
    proc, _ = _run_archive(tmp_path, not_a_run, tmp_path / "staging")
    assert proc.returncode != 0
    assert parse_archive_output(proc.stdout) == (None, None)


def test_archive_command_markers_not_in_command_text():
    """The terminal echoes the command; the parser must not match that echo."""
    cmd = archive_command("/env/python", "/wd/run_001", "$HOME/wd/.iops-studio", "a.tar.gz")
    assert "__IOPS_ARCHIVE=" not in cmd and "__IOPS_SIZE=" not in cmd
    assert parse_archive_output(cmd) == (None, None)
    assert '"/env/python" -m iops archive create "/wd/run_001"' in cmd


def test_parse_archive_output_handles_terminal_noise():
    out = ("$ some echoed command\r\n"
           "Archive created: /home/u/x.tar.gz\r\n"
           "__IOPS_ARCHIVE=/home/u/wd/.iops-studio/a.tar.gz\r\n"
           "__IOPS_SIZE=123456\r\n")
    assert parse_archive_output(out) == ("/home/u/wd/.iops-studio/a.tar.gz", 123456)
    assert parse_archive_output(None) == (None, None)


def test_local_archive_path_never_overwrites(tmp_path):
    first = local_archive_path(tmp_path, "setup_run_001")
    assert first == tmp_path / "setup_run_001.tar.gz"
    first.write_bytes(b"x")
    second = local_archive_path(tmp_path, "setup_run_001")
    assert second == tmp_path / "setup_run_001_2.tar.gz"
    second.write_bytes(b"x")
    assert local_archive_path(tmp_path, "setup_run_001") == tmp_path / "setup_run_001_3.tar.gz"


def test_human_size():
    assert human_size(None) == "unknown size"
    assert human_size(512) == "512 B"
    assert human_size(1536) == "1.5 KiB"
    assert human_size(3 * 1024 ** 3) == "3.0 GiB"


def test_local_connection_fetch_file(tmp_path):
    from iops.studio.connections import LocalConnection

    src = tmp_path / "a.tar.gz"
    src.write_bytes(b"archive bytes")
    dest = tmp_path / "copy.tar.gz"
    assert LocalConnection().fetch_file(str(src), str(dest)).ok
    assert dest.read_bytes() == b"archive bytes"
    missing = LocalConnection().fetch_file(str(tmp_path / "nope"), str(dest))
    assert not missing.ok and missing.stderr


def test_ssh_connection_fetch_file_uses_shared_socket(monkeypatch, tmp_path):
    """scp joins the terminal's master socket and never prompts for a password."""
    from iops.studio import connections

    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(connections.subprocess, "run", fake_run)
    monkeypatch.setattr(connections, "_ensure_control_dir", lambda: None)
    res = connections.SSHConnection("cluster").fetch_file("/abs/a.tar.gz", str(tmp_path / "a"))
    assert res.ok
    argv = seen["argv"]
    assert argv[0] == "scp"
    assert "BatchMode=yes" in argv
    assert any(a.startswith("ControlPath=") for a in argv)
    assert argv[-2:] == ["cluster:/abs/a.tar.gz", str(tmp_path / "a")]


def test_localize_report_html_rewrites_cdn():
    html = (b'<head><script src="https://cdn.plot.ly/plotly-2.26.0.min.js">'
            b'</script></head>')
    out = localize_report_html(html, "/studio-results/_assets/plotly.min.js")
    assert b"cdn.plot.ly" not in out
    assert b'src="/studio-results/_assets/plotly.min.js"' in out


def test_localize_report_html_noop_without_cdn():
    html = b"<head><script>/* inline plotly */</script></head>"
    assert localize_report_html(html, "/x/plotly.min.js") == html


def test_plotly_bundle_present():
    p = plotly_bundle_path()
    assert p is not None and p.is_file()
    assert p.name == "plotly.min.js"


def test_slug():
    assert slug("irene:iops_env") == "irene_iops_env"
    assert slug("run_001") == "run_001"
    assert slug("") == "item"
