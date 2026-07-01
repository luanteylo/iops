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

import asyncio
import io
import subprocess
import sys
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from iops.main import load_version
from iops.studio.connections import Connection, LineFn

PACKAGE = "iops-benchmark"
CLIENT_VERSION = load_version()

# Fail fast when the target has no route to PyPI (common on HPC login nodes):
# one attempt, short connect timeout. pip otherwise retries 5x at a 15s timeout,
# stalling ~75s before giving up. We have an offline wheelhouse fallback, so a
# quick failure just gets us there sooner; a genuinely working link connects in
# well under this timeout.
_PIP_RETRIES = 0
_PIP_CONNECT_TIMEOUT = 10
_PIP_NET_OPTS = f"--retries {_PIP_RETRIES} --timeout {_PIP_CONNECT_TIMEOUT}"

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


# --- Command builders + tagged-line parsing for the shared terminal session --- #
# In the interactive terminal, a command's output is captured amid shell noise,
# so structured values are emitted on a tagged "IOPSVER=" line and grepped out.

def iops_version_command(python_path: str) -> str:
    """Shell command that prints ``IOPSVER=<version>`` (nothing if not installed)."""
    return (
        'cd "$HOME" 2>/dev/null; '
        f'"{python_path}" -c '
        "'import importlib.metadata as m; print(\"IOPSVER=\"+m.version(\"iops-benchmark\"))' "
        "2>/dev/null || true"
    )


def parse_iops_version(text: str) -> Optional[str]:
    """Extract the version from an ``IOPSVER=`` line in captured output."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("IOPSVER="):
            version = line[len("IOPSVER="):].strip()
            return version or None
    return None


def pip_install_command(python_path: str, version: Optional[str]) -> str:
    return f'"{python_path}" -m pip install {_PIP_NET_OPTS} "{_spec(version)}"'


def wheelhouse_install_command(python_path: str, find_links: str, version: Optional[str]) -> str:
    return (
        f'"{python_path}" -m pip install --no-index '
        f'--find-links "{find_links}" "{_spec(version)}"'
    )


def tar_gz_dir(src: Path) -> bytes:
    """Pack the *contents* of ``src`` (wheel files) into a gzip tarball in memory.

    Entries are stored by basename at the archive root, so extracting into the
    remote wheelhouse directory drops the wheels straight in.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for path in sorted(src.iterdir()):
            if path.is_file():
                tf.add(str(path), arcname=path.name)
    return buf.getvalue()


async def install_iops_session(session, python_path: str, *,
                               version: Optional[str] = CLIENT_VERSION,
                               scp_conn: Optional[Connection] = None,
                               emit: Optional[LineFn] = None) -> InstallResult:
    """Ensure IOPS is installed, driving commands through the shared terminal.

    pip first; on failure builds a wheelhouse on the client, transfers it (scp,
    for ssh targets) and installs offline. ``emit`` writes short notes for the
    client-side steps (build/transfer) that don't run in the terminal itself.
    """
    def note(msg: str):
        if emit:
            emit(msg)

    result = InstallResult(ok=False)

    _, out = await session.run(iops_version_command(python_path), display="check for IOPS")
    existing = parse_iops_version(out)
    if existing and (version is None or existing == version):
        return InstallResult(True, "existing", existing, steps=["already installed"])

    # 1) pip (runs in the terminal, output streams live)
    code, _ = await session.run(pip_install_command(python_path, version),
                                display=f"pip install {_spec(version)}", timeout=1800)
    result.steps.append("pip")
    if code == 0:
        _, out = await session.run(iops_version_command(python_path))
        return InstallResult(True, "pip", parse_iops_version(out) or version, steps=result.steps)
    note("pip failed; falling back to an offline wheelhouse")

    # 2a) build the wheelhouse on the client (off the event loop)
    note("building wheelhouse on the client (pip download)...")
    built_ok, dest, _log = await asyncio.to_thread(build_wheelhouse, version)
    result.steps.append("build-wheelhouse")
    if not built_ok:
        note("wheelhouse build failed")
        return result

    # 2b) transfer to the target when remote. Stream the wheelhouse through the
    # authenticated terminal channel rather than a background scp, so it works on
    # hardened hosts that reject a second connection (password/2FA only, no
    # multiplexing). Falls back to nothing: this is the one channel that works.
    find_links = str(dest)
    if scp_conn is not None and getattr(scp_conn, "kind", "local") == "ssh":
        tar_gz = await asyncio.to_thread(tar_gz_dir, dest)
        note(f"transferring wheelhouse through the terminal ({len(tar_gz) // 1024} KiB)...")
        rc = await session.push_tar(_REMOTE_WHEELHOUSE_REL, tar_gz, timeout=1200)
        result.steps.append("transfer")
        if rc != 0:
            note(f"transfer failed (exit {rc})")
            return result
        find_links = f"$HOME/{_REMOTE_WHEELHOUSE_REL}"

    # 2c) offline install (runs in the terminal)
    code, _ = await session.run(wheelhouse_install_command(python_path, find_links, version),
                                display="pip install (offline, from wheelhouse)", timeout=1800)
    result.steps.append("wheelhouse")
    if code == 0:
        _, out = await session.run(iops_version_command(python_path))
        return InstallResult(True, "wheelhouse", parse_iops_version(out) or version, steps=result.steps)
    note("wheelhouse install failed")
    return result


def pip_install(conn: Connection, python_path: str, version: Optional[str] = None,
                timeout: float = 1800.0) -> tuple[bool, str]:
    """Install IOPS with a normal pip (target reaches PyPI). Returns (ok, log)."""
    cmd = f'"{python_path}" -m pip install {_PIP_NET_OPTS} "{_spec(version)}"'
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
