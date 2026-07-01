"""Python environment discovery and creation on a Studio connection.

Works identically for local and SSH targets because everything runs through
``Connection.run``. Discovery finds candidate interpreters (system pythons and
virtualenvs under the usual dirs), reports each one's Python version, and flags
whether ``iops-benchmark`` is already installed there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from iops.studio.connections import Connection

# POSIX-sh discovery prelude. Emits one tab-separated "ENV" line per env:
#   ENV\t<interpreter_path>\t<kind>\t<python_version>\t<iops_version_or_empty>
# Dedups by sys.prefix (the environment identity), not by interpreter realpath:
# every venv symlinks its bin/python to the same base interpreter, so realpath
# would wrongly collapse distinct venvs into one. sys.prefix keeps each venv
# distinct while still merging system python3/python (shared /usr prefix).
_DISCOVER_PRELUDE = r'''
# Probe from a neutral directory: `python -c` puts the current directory on
# sys.path, so running from a project dir (with an *.egg-info / *.dist-info)
# would make importlib.metadata falsely report the package installed for every
# interpreter. cd away so IOPS detection reflects each interpreter's own env.
cd "$HOME" 2>/dev/null || cd / 2>/dev/null || true
SEEN=""
emit_check() {
  p="$1"; kind="$2"
  [ -x "$p" ] || return 0
  pref="$("$p" -c 'import sys;print(sys.prefix)' 2>/dev/null)" || pref="$p"
  [ -n "$pref" ] || pref="$p"
  case " $SEEN " in *" $pref "*) return 0 ;; esac
  SEEN="$SEEN $pref"
  ver="$("$p" -c 'import platform;print(platform.python_version())' 2>/dev/null)"
  iv="$("$p" -c 'import importlib.metadata as m; print(m.version("iops-benchmark"))' 2>/dev/null)"
  printf 'ENV\t%s\t%s\t%s\t%s\n' "$p" "$kind" "$ver" "$iv"
}
# scan_base handles any of: a direct interpreter file, a venv root (has
# bin/python), or a directory containing several venvs.
scan_base() {
  base="$1"; kind="$2"
  [ -n "$base" ] || return 0
  if [ -x "$base" ] && [ ! -d "$base" ]; then emit_check "$base" "$kind"; return 0; fi
  [ -e "$base/bin/python" ] && emit_check "$base/bin/python" "$kind"
  if [ -d "$base" ]; then
    for d in "$base"/*; do
      [ -e "$d/bin/python" ] && emit_check "$d/bin/python" "$kind"
    done
  fi
}
'''

# Default scans: system pythons plus the conventional venv base directories.
_DISCOVER_DEFAULTS = r'''
for name in python3 python; do
  p="$(command -v "$name" 2>/dev/null)" && emit_check "$p" system
done
for base in "$HOME/.venvs" "$HOME/.virtualenvs" "$HOME/venvs" "$HOME/venv"; do
  scan_base "$base" venv
done
'''


@dataclass
class PyEnv:
    """A discovered Python interpreter / virtualenv on a connection."""
    path: str
    kind: str                       # "system" | "venv"
    version: Optional[str] = None
    iops_version: Optional[str] = None

    @property
    def has_iops(self) -> bool:
        return bool(self.iops_version)

    @property
    def label(self) -> str:
        ver = f"Python {self.version}" if self.version else "Python"
        iops = f" · IOPS {self.iops_version}" if self.iops_version else ""
        return f"{self.path}  ({ver}{iops})"


def build_discovery_script(extra_paths: Optional[list[str]] = None) -> str:
    """Build the POSIX-sh discovery script, including any custom scan paths.

    ``extra_paths`` are additional locations to scan beyond the conventional
    ones (useful for clusters where envs live in scratch/project dirs). Each may
    be a direct interpreter, a venv root, or a directory containing venvs.
    """
    script = _DISCOVER_PRELUDE + _DISCOVER_DEFAULTS
    for raw in extra_paths or []:
        raw = raw.strip()
        if not raw:
            continue
        safe = _normalize_target_path(raw)  # ~/ -> $HOME/, rejects quote-breaking chars
        script += f'scan_base "{safe}" custom\n'
    return script


def parse_env_lines(text: str) -> list[PyEnv]:
    """Parse the ``ENV\\t...`` lines emitted by the discovery script.

    Tolerant of surrounding noise (shell echo, prompts), so it works whether the
    script ran via a one-shot connection or through the shared terminal session.
    Environments that already have IOPS sort first, then by path.
    """
    envs: list[PyEnv] = []
    for line in text.splitlines():
        if not line.startswith("ENV\t"):
            continue
        parts = line.split("\t")
        # ["ENV", path, kind, version, iops_version]
        _, path, kind, version, iops_version = (parts + [""] * 5)[:5]
        envs.append(PyEnv(
            path=path,
            kind=kind or "system",
            version=version or None,
            iops_version=iops_version or None,
        ))
    envs.sort(key=lambda e: (not e.has_iops, e.path))
    return envs


def discover_environments(
    conn: Connection,
    extra_paths: Optional[list[str]] = None,
    timeout: float = 60.0,
) -> list[PyEnv]:
    """Discover Python environments reachable on ``conn`` (one-shot connection)."""
    res = conn.run(build_discovery_script(extra_paths), timeout=timeout)
    return parse_env_lines(res.stdout)


def _normalize_target_path(path: str) -> str:
    """Make a user-entered venv path safe to embed in a shell command.

    Leading ``~/`` becomes ``$HOME/`` so it expands inside double quotes on the
    target. Raises ValueError on characters that would break out of the quoted
    string.
    """
    path = path.strip()
    if not path:
        raise ValueError("Environment path is empty")
    if any(ch in path for ch in ('"', "`", "$(", "\n")):
        raise ValueError("Environment path contains unsupported characters")
    if path.startswith("~/"):
        path = "$HOME/" + path[2:]
    elif path == "~":
        path = "$HOME"
    return path


def build_venv_command(path: str) -> str:
    """Shell command to create a venv at ``path`` (sanitized). Raises ValueError."""
    safe = _normalize_target_path(path)
    return f'python3 -m venv "{safe}"'


@dataclass
class CreateEnvResult:
    ok: bool
    path: str
    message: str


def create_environment(conn: Connection, path: str, timeout: float = 300.0) -> CreateEnvResult:
    """Create a new venv at ``path`` on the target via ``python3 -m venv``.

    Does not install IOPS: that is the later remote-install step. Returns a
    result describing success or the captured error.
    """
    safe = _normalize_target_path(path)
    res = conn.run(f'python3 -m venv "{safe}" && echo IOPS_VENV_CREATED', timeout=timeout)
    if res.ok and "IOPS_VENV_CREATED" in res.stdout:
        return CreateEnvResult(True, path, f"Created virtual environment at {path}")
    message = res.stderr.strip() or res.stdout.strip() or f"Exited with code {res.exit_code}"
    return CreateEnvResult(False, path, message)
