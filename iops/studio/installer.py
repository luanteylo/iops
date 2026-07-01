"""Install IOPS onto a Studio target (connection + environment).

Flow (see the ``install_iops`` orchestrator):
1. Check whether the selected interpreter already has ``iops-benchmark``.
2. Try a normal ``pip install`` (the target reaches PyPI).
3. If that fails, fall back to a *wheelhouse*: on the client (which has
   internet) download IOPS and its dependencies as wheels, ship them to the
   target with scp, and install offline with ``--no-index --find-links``.

By default the version installed matches this client's version so the local
client and the remote runner behave identically.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from iops.main import load_version
from iops.studio.connections import Connection, LineFn, LocalConnection

PACKAGE = "iops-benchmark"
CLIENT_VERSION = load_version()

# Where the wheelhouse is cached locally (client side) and staged remotely.
_LOCAL_WHEELHOUSE_ROOT = Path.home() / ".cache" / "iops-studio" / "wheelhouse"
_REMOTE_WHEELHOUSE_REL = ".cache/iops-studio/wheelhouse"

ProgressFn = Callable[[str], None]


@dataclass
class InstallResult:
    ok: bool
    method: str = ""            # "" | "pip" | "wheelhouse"
    version: Optional[str] = None
    log: str = ""
    steps: list = field(default_factory=list)


def _spec(version: Optional[str]) -> str:
    return f"{PACKAGE}=={version}" if version else PACKAGE


def _iops_version_cmd(python_path: str) -> str:
    # cd away first: `python -c` puts cwd on sys.path, which would let a project
    # dir's metadata masquerade as an installed package (see environments.py).
    return (
        'cd "$HOME" 2>/dev/null || cd / 2>/dev/null; '
        f'"{python_path}" -c '
        "'import importlib.metadata as m; print(m.version(\"iops-benchmark\"))' "
        "2>/dev/null"
    )


def installed_iops_version(conn: Connection, python_path: str, timeout: float = 30.0) -> Optional[str]:
    """Return the IOPS version installed for ``python_path``, or None."""
    res = conn.run(_iops_version_cmd(python_path), timeout=timeout)
    version = res.stdout.strip()
    return version if res.ok and version else None


def pip_install(conn: Connection, python_path: str, version: Optional[str] = None,
                timeout: float = 1800.0) -> tuple[bool, str]:
    """Install IOPS with a normal pip (target reaches PyPI). Returns (ok, log)."""
    cmd = f'"{python_path}" -m pip install "{_spec(version)}"'
    res = conn.run(cmd, timeout=timeout)
    log = (res.stdout + res.stderr).strip()
    return res.ok, log


def build_wheelhouse(version: Optional[str] = None, dest: Optional[Path] = None,
                     timeout: float = 1800.0) -> tuple[bool, Path, str]:
    """Download IOPS + deps as wheels on the client. Returns (ok, dir, log).

    Wheels are built for the client's platform; targets that share the client
    arch (typical linux x86_64 HPC) can install them directly.
    """
    dest = dest or (_LOCAL_WHEELHOUSE_ROOT / (version or "latest"))
    dest.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "download", _spec(version), "-d", str(dest)],
        capture_output=True, text=True, timeout=timeout,
    )
    log = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, dest, log


def wheelhouse_install(conn: Connection, python_path: str, find_links: str,
                       version: Optional[str] = None, timeout: float = 1800.0) -> tuple[bool, str]:
    """Install IOPS offline from a staged wheelhouse. Returns (ok, log)."""
    cmd = (
        f'"{python_path}" -m pip install --no-index '
        f'--find-links "{find_links}" "{_spec(version)}"'
    )
    res = conn.run(cmd, timeout=timeout)
    log = (res.stdout + res.stderr).strip()
    return res.ok, log


def install_iops(conn: Connection, python_path: str, version: Optional[str] = CLIENT_VERSION,
                 prebuilt_wheelhouse: Optional[str] = None,
                 progress: Optional[ProgressFn] = None) -> InstallResult:
    """Ensure IOPS is installed for ``python_path``: pip first, wheelhouse fallback.

    ``prebuilt_wheelhouse`` (a local dir of wheels) skips the client-side
    download step. ``progress`` receives short status strings for the UI.
    """
    def note(msg: str):
        if progress:
            progress(msg)

    result = InstallResult(ok=False)

    # Already installed?
    existing = installed_iops_version(conn, python_path)
    if existing and (version is None or existing == version):
        note(f"IOPS {existing} already installed")
        return InstallResult(True, "existing", existing, f"IOPS {existing} already installed",
                             steps=["already installed"])

    # 1) pip
    note("Installing with pip...")
    ok, log = pip_install(conn, python_path, version)
    result.steps.append("pip")
    result.log += f"$ pip install {_spec(version)}\n{log}\n"
    if ok:
        note("pip install succeeded")
        result.ok = True
        result.method = "pip"
        result.version = installed_iops_version(conn, python_path) or version
        return result
    note("pip failed, falling back to wheelhouse...")

    # 2) wheelhouse fallback
    if prebuilt_wheelhouse:
        local_dir = Path(prebuilt_wheelhouse)
        if not local_dir.is_dir():
            result.log += f"\nWheelhouse not found: {prebuilt_wheelhouse}\n"
            return result
    else:
        note("Building wheelhouse on the client...")
        built_ok, local_dir, build_log = build_wheelhouse(version)
        result.steps.append("build-wheelhouse")
        result.log += f"\n$ pip download {_spec(version)}\n{build_log}\n"
        if not built_ok:
            note("wheelhouse build failed")
            return result

    note("Transferring wheelhouse to target...")
    staged = conn.stage_dir(str(local_dir), _REMOTE_WHEELHOUSE_REL, timeout=600)
    result.steps.append("transfer")
    if not staged.ok:
        result.log += f"\nTransfer failed: {staged.log}\n"
        note("transfer failed")
        return result

    note("Installing from wheelhouse (offline)...")
    ok, log = wheelhouse_install(conn, python_path, staged.path, version)
    result.steps.append("wheelhouse")
    result.log += f"\n$ pip install --no-index --find-links {staged.path} {_spec(version)}\n{log}\n"
    if ok:
        note("wheelhouse install succeeded")
        result.ok = True
        result.method = "wheelhouse"
        result.version = installed_iops_version(conn, python_path) or version
    else:
        note("wheelhouse install failed")
    return result


async def install_iops_stream(conn: Connection, python_path: str,
                              version: Optional[str] = CLIENT_VERSION,
                              emit: Optional[LineFn] = None) -> InstallResult:
    """Streaming variant of ``install_iops``: emits each command and its output
    line by line via ``emit`` (for a live terminal in the UI). Same pip-first,
    wheelhouse-fallback flow. Runs on the asyncio event loop.
    """
    def out(line: str = ""):
        if emit:
            emit(line)

    result = InstallResult(ok=False)

    existing = installed_iops_version(conn, python_path)
    if existing and (version is None or existing == version):
        out(f"IOPS {existing} already installed in {python_path}")
        return InstallResult(True, "existing", existing, steps=["already installed"])

    # 1) pip
    pip_cmd = f'"{python_path}" -m pip install "{_spec(version)}"'
    out(f"$ {pip_cmd}")
    rc = await conn.run_stream(pip_cmd, out)
    result.steps.append("pip")
    if rc == 0:
        ver = installed_iops_version(conn, python_path) or version
        out(f"\n✓ pip install succeeded (IOPS {ver})")
        return InstallResult(True, "pip", ver, steps=result.steps)
    out("\n✗ pip failed, falling back to wheelhouse...\n")

    # 2a) build the wheelhouse on the client (has internet)
    local = LocalConnection()
    dest = _LOCAL_WHEELHOUSE_ROOT / (version or "latest")
    dest.mkdir(parents=True, exist_ok=True)
    build_cmd = f'"{sys.executable}" -m pip download "{_spec(version)}" -d "{dest}"'
    out(f"$ {build_cmd}")
    rc = await local.run_stream(build_cmd, out)
    result.steps.append("build-wheelhouse")
    if rc != 0:
        out("\n✗ wheelhouse build failed")
        return result

    # 2b) transfer to the target
    out("")
    staged = await conn.stage_dir_stream(str(dest), _REMOTE_WHEELHOUSE_REL, out, timeout=600)
    result.steps.append("transfer")
    if not staged.ok:
        out(f"\n✗ transfer failed: {staged.log}")
        return result

    # 2c) offline install from the staged wheelhouse
    wh_cmd = (
        f'"{python_path}" -m pip install --no-index '
        f'--find-links "{staged.path}" "{_spec(version)}"'
    )
    out(f"\n$ {wh_cmd}")
    rc = await conn.run_stream(wh_cmd, out)
    result.steps.append("wheelhouse")
    if rc == 0:
        ver = installed_iops_version(conn, python_path) or version
        out(f"\n✓ wheelhouse install succeeded (IOPS {ver})")
        return InstallResult(True, "wheelhouse", ver, steps=result.steps)
    out("\n✗ wheelhouse install failed")
    return result
