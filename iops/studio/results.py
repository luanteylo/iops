"""Helpers for bringing IOPS run output back into Studio (UI-free).

Studio runs benchmarks on a target and writes results under the run directory
(the folder holding ``__iops_run_metadata.json``). This module builds the shell
commands to enumerate those runs and to bundle their *small* artifacts (the
report HTML, result CSVs, and ``__iops_*`` metadata) into a tarball, plus pure
helpers to locate/patch the generated report so it renders inside Studio.

Deliberately excluded: raw scratch data (e.g. multi-GB ``testfile.ior``). A full
``iops archive`` would include those, so Studio pulls a name-filtered light
tarball instead, which stays streamable over the terminal channel (pull_file).

All path arguments are already-safe remote shell paths (Studio builds them from
its workdir setting); they are embedded inside double quotes here.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# The report filename `iops report <run_dir>` always writes (it ignores the
# config's output_filename on the CLI path).
REPORT_FILENAME = "analysis_report.html"

# File types worth pulling back: results, metadata, report, configs, logs. Raw
# benchmark data files (no matching suffix) are left on the target.
_LIGHT_NAME_GLOBS = ("*.csv", "*.json", "*.html", "*.yaml", "*.yml",
                     "*.log", "*.txt", "*.parquet")

# The report loads Plotly from this CDN; we rewrite it to a locally served copy
# so charts render without internet.
_CDN_PLOTLY_RE = re.compile(rb'https://cdn\.plot\.ly/plotly[^"\']*?\.min\.js')


def slug(text: str) -> str:
    """A filesystem-safe slug for local storage folders."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text or "").strip("_") or "item"


def list_runs_command(workdir: str) -> str:
    """Shell to list run roots under ``workdir``, newest first.

    Emits ``<mtime>\\t<run_dir>`` lines: each ``run_dir`` is a directory holding
    ``__iops_run_metadata.json``. ``-printf``/``%T@`` are GNU find features
    (present on Linux clusters).
    """
    return (
        f'find "{workdir}" -maxdepth 5 -name __iops_run_metadata.json '
        "-printf '%T@\\t%h\\n' 2>/dev/null | sort -rn"
    )


def parse_run_list(output: str) -> list:
    """Parse ``list_runs_command`` output into run-root paths (newest first)."""
    runs, seen = [], set()
    for line in (output or "").splitlines():
        line = line.strip()
        if "\t" not in line:
            continue
        _, _, path = line.partition("\t")
        path = path.strip()
        if path and path not in seen:
            seen.add(path)
            runs.append(path)
    return runs


def report_html_path(run_dir: str) -> str:
    """Remote path of the report HTML inside ``run_dir``."""
    return f'{run_dir.rstrip("/")}/{REPORT_FILENAME}'


def light_tar_command(run_dir: str, tmp_path: str) -> str:
    """Shell to bundle a run's small artifacts into ``tmp_path`` (a .tar.gz).

    Runs relative to ``run_dir`` so the tar stores clean relative paths, and
    filters by name so only results/metadata/report/logs are included, never raw
    scratch data. Exit code is the pipeline's (tar), so the caller can check it.
    """
    globs = " -o ".join(f"-name '{g}'" for g in _LIGHT_NAME_GLOBS)
    return (
        f'cd "{run_dir}" && find . -type f \\( {globs} \\) -print0 '
        f'| tar czf "{tmp_path}" --null -T -'
    )


def localize_report_html(html: bytes, plotly_url: str) -> bytes:
    """Point the report's Plotly ``<script src>`` at ``plotly_url``.

    Returns the HTML unchanged if the CDN reference is absent (e.g. a future
    report that already inlines Plotly).
    """
    return _CDN_PLOTLY_RE.sub(plotly_url.encode(), html, count=1)


def plotly_bundle_path() -> Optional[Path]:
    """Locate the offline ``plotly.min.js`` shipped with the plotly package."""
    try:
        import plotly
    except ImportError:
        return None
    candidate = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
    return candidate if candidate.is_file() else None
