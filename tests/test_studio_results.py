"""Tests for the UI-free Studio results helpers."""

from iops.studio.results import (
    REPORT_FILENAME,
    light_tar_command,
    list_runs_command,
    localize_report_html,
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


def test_light_tar_command_excludes_scratch_and_stays_relative():
    cmd = light_tar_command("/wd/run_001", "/tmp/out.tar.gz")
    assert 'cd "/wd/run_001"' in cmd
    assert "find . -type f" in cmd              # relative paths in the tar
    assert "-name '*.csv'" in cmd and "-name '*.json'" in cmd
    assert "*.ior" not in cmd                   # scratch data never named -> excluded
    assert 'tar czf "/tmp/out.tar.gz" --null -T -' in cmd


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
