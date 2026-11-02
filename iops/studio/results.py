"""Helpers for bringing IOPS run output back into Studio (UI-free).

Studio runs benchmarks on a target and writes results under the run directory
(the folder holding ``__iops_run_metadata.json``). This module builds the shell
commands to enumerate those runs and to package one with ``iops archive
create``, plus pure helpers to locate/patch the generated report so it renders
inside Studio.

Pulling a run produces the same archive as the CLI (manifest and checksums
included), so the host can inspect it with ``iops find run.tar.gz`` or unpack it
with ``iops archive extract``. The archive holds everything under the run
directory: a study that writes raw data there (rather than to a scratch
filesystem) makes it correspondingly large, which is why Studio copies it with
scp instead of the in-memory terminal channel.

All path arguments are already-safe remote shell paths (Studio builds them from
its workdir setting); they are embedded inside double quotes here.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# The report filename Studio writes and fetches. Studio forces this name via
# `iops report --output` so the fetch stays deterministic regardless of any
# output_filename set in the run's report_config.yaml.
REPORT_FILENAME = "analysis_report.html"

# `iops report <run_dir>` auto-detects this file in the run dir and uses it to
# drive the report (sections, plots, ...). Editing it and re-running regenerates.
REPORT_CONFIG_FILENAME = "report_config.yaml"

# The report loads Plotly from this CDN; we rewrite it to a locally served copy
# so charts render without internet.
_CDN_PLOTLY_RE = re.compile(rb'https://cdn\.plot\.ly/plotly[^"\']*?\.min\.js')


def slug(text: str) -> str:
    """A filesystem-safe slug for local storage folders."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text or "").strip("_") or "item"


RUNS_SEARCH_DEPTH = 5

# Characters that would break out of the double quotes a remote folder is
# embedded in (variables such as $SCRATCH are allowed and expanded on purpose).
_UNSAFE_REMOTE_CHARS = ('"', "`", "\\", "\n", "\r")


def is_safe_remote_dir(path: str) -> bool:
    """True if ``path`` can be embedded in a double-quoted remote shell word."""
    return bool((path or "").strip()) and not any(c in path for c in _UNSAFE_REMOTE_CHARS)


def list_runs_command(workdir: str) -> str:
    """Shell to list run roots under ``workdir``, newest first.

    First emits ``__IOPS_DIR=<absolute folder>`` (the folder as the target
    resolved it) or ``__IOPS_NO_DIR__`` when the folder does not exist, then
    ``<mtime>\\t<run_dir>`` lines: each ``run_dir`` is a directory holding
    ``__iops_run_metadata.json``. ``-printf``/``%T@`` are GNU find features
    (present on Linux clusters). The markers are assembled by ``printf`` so the
    command text itself never contains them.
    """
    return (
        f'if [ -d "{workdir}" ]; then '
        f'printf \'__IOPS_%s=%s\\n\' DIR "$(cd "{workdir}" && pwd)"; '
        f'find "{workdir}" -maxdepth {RUNS_SEARCH_DEPTH} -name __iops_run_metadata.json '
        "-printf '%T@\\t%h\\n' 2>/dev/null | sort -rn; "
        "else printf '__IOPS_%s__\\n' NO_DIR; fi"
    )


def parse_runs_folder(output: str) -> tuple[bool, Optional[str]]:
    """From ``list_runs_command`` output: ``(folder_exists, absolute_folder)``."""
    exists, folder = True, None
    for line in (output or "").splitlines():
        line = line.strip()
        if line == "__IOPS_NO_DIR__":
            exists = False
        elif line.startswith("__IOPS_DIR=") and folder is None:
            folder = line[len("__IOPS_DIR="):] or None
    return exists, folder


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


def report_config_path(run_dir: str) -> str:
    """Remote path of the report config inside ``run_dir`` (auto-detected by report)."""
    return f'{run_dir.rstrip("/")}/{REPORT_CONFIG_FILENAME}'


# Seed used when a run has no report_config.yaml yet; the user expands it.
DEFAULT_REPORT_CONFIG = """\
# Report configuration. Edit and regenerate to customize the HTML report.
# Docs: sections, default_plots, per-metric plots, gallery, theme.
reporting:
  enabled: true
  sections:
    test_summary: true
    best_results: true
    variable_impact: true
    parallel_coordinates: true
  best_results:
    top_n: 5
  # default_plots apply to every metric; add per-metric overrides under `metrics:`.
  default_plots:
    - type: line
      # x_var: nodes
      # log_y: true
"""


def archive_command(env_path: str, run_dir: str, staging_dir: str, name: str) -> str:
    """Shell to package ``run_dir`` with ``iops archive create``.

    The archive is written to ``staging_dir/name``. On success the command
    prints ``__IOPS_ARCHIVE=<absolute path>`` (scp needs an absolute path, and
    ``staging_dir`` usually starts with ``$HOME``) and ``__IOPS_SIZE=<bytes>``,
    for ``parse_archive_output``. As in ``list_runs_command``, the markers are
    assembled by ``printf`` so the echoed command line never contains them. The
    exit status is the archive command's.

    ``iops archive create`` writes a log file to the current directory by
    default; it is pointed into ``staging_dir`` and removed afterwards, so
    pulling a run leaves nothing behind in the terminal's working directory.
    """
    out = f"{staging_dir}/{name}"
    log = f"{out}.log"
    return (
        f'mkdir -p "{staging_dir}" && '
        f'"{env_path}" -m iops archive create "{run_dir}" -o "{out}" '
        f'--no-progress --log-file "{log}"; '
        f'__iops_rc=$?; rm -f "{log}"; '
        f'if [ $__iops_rc -eq 0 ] && [ -f "{out}" ]; then '
        f'printf \'__IOPS_%s=%s\\n\' ARCHIVE "$(cd "{staging_dir}" && pwd)/{name}"; '
        f'printf \'__IOPS_%s=%s\\n\' SIZE "$(( $(wc -c < "{out}") ))"; '
        f'fi; [ $__iops_rc -eq 0 ]'
    )


def parse_archive_output(output: str) -> tuple[Optional[str], Optional[int]]:
    """From ``archive_command`` output: ``(absolute_archive_path, size_bytes)``.

    Either is None when its marker is missing (the archive was not created).
    """
    path, size = None, None
    for line in (output or "").splitlines():
        line = line.strip()
        if line.startswith("__IOPS_ARCHIVE="):
            path = line[len("__IOPS_ARCHIVE="):] or None
        elif line.startswith("__IOPS_SIZE="):
            value = line[len("__IOPS_SIZE="):]
            size = int(value) if value.isdigit() else None
    return path, size


def local_archive_path(dest_dir: Path, base: str) -> Path:
    """Where to save a pulled archive in ``dest_dir`` without overwriting one.

    ``base.tar.gz`` when free, otherwise ``base_2.tar.gz``, ``base_3.tar.gz``...
    Pulling the same run twice keeps both copies, since the run may have changed
    in between (a resumed study, a regenerated report).
    """
    candidate = dest_dir / f"{base}.tar.gz"
    n = 2
    while candidate.exists():
        candidate = dest_dir / f"{base}_{n}.tar.gz"
        n += 1
    return candidate


def human_size(num_bytes: Optional[int]) -> str:
    """``1536`` -> ``"1.5 KiB"``; unknown sizes read as ``"unknown size"``."""
    if num_bytes is None:
        return "unknown size"
    size = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"


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
