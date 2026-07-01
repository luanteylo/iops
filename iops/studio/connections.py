"""Connection targets for IOPS Studio.

A *connection* is where IOPS will run: the local machine, or a remote host
reached over SSH. Both expose the same small interface (`run` a shell command,
`test` reachability), so the rest of Studio (environment discovery, and later
remote install / dispatch) is written once against `Connection`.

SSH uses the system `ssh` binary via subprocess so the user's full
``~/.ssh/config`` is honored natively (ProxyJump, agent, keys, known_hosts),
exactly like VSCode Remote-SSH. No third-party SSH library is required.
"""

from __future__ import annotations

import glob
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# Callback receiving one line of output at a time (used for install progress notes).
LineFn = Callable[[str], None]

DEFAULT_SSH_CONFIG = Path.home() / ".ssh" / "config"


# --------------------------------------------------------------------------- #
# SSH config parsing
# --------------------------------------------------------------------------- #
@dataclass
class SSHHost:
    """A single selectable host alias from ~/.ssh/config."""
    alias: str
    hostname: Optional[str] = None
    user: Optional[str] = None
    proxy_jump: Optional[str] = None

    @property
    def label(self) -> str:
        """Human-friendly label for a dropdown (alias plus resolved target)."""
        target = self.hostname or self.alias
        if self.user:
            target = f"{self.user}@{target}"
        return self.alias if target == self.alias else f"{self.alias}  ({target})"


def parse_ssh_hosts(config_path: Optional[Path] = None) -> list[SSHHost]:
    """Parse ~/.ssh/config and return concrete (non-wildcard) host aliases.

    Follows ``Include`` directives (globbed relative to the config's directory,
    as OpenSSH does). Wildcard patterns (``Host *``, ``?``, ``!``) are skipped
    since they are not directly connectable targets.
    """
    config_path = config_path or DEFAULT_SSH_CONFIG
    hosts: list[SSHHost] = []
    seen: set[str] = set()
    _parse_ssh_file(Path(config_path), hosts, seen)
    return hosts


def _parse_ssh_file(path: Path, hosts: list[SSHHost], seen: set[str]) -> None:
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return

    current: list[SSHHost] = []  # host stanzas the following keywords apply to
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Split "Keyword value" (also tolerate "Keyword=value").
        if "=" in line and len(line.split(None, 1)) == 1:
            key, _, value = line.partition("=")
        else:
            parts = line.split(None, 1)
            key, value = parts[0], (parts[1] if len(parts) > 1 else "")
        key = key.lower()
        value = value.strip()

        if key == "include":
            current = []
            for token in value.split():
                pattern = os.path.expanduser(token)
                if not os.path.isabs(pattern):
                    pattern = str(path.parent / pattern)
                for included in sorted(glob.glob(pattern)):
                    _parse_ssh_file(Path(included), hosts, seen)
        elif key == "host":
            current = []
            for pattern in value.split():
                if any(ch in pattern for ch in "*?!"):
                    continue
                if pattern in seen:
                    # Reuse the existing entry so later keywords still apply.
                    existing = next(h for h in hosts if h.alias == pattern)
                    current.append(existing)
                    continue
                host = SSHHost(alias=pattern)
                seen.add(pattern)
                hosts.append(host)
                current.append(host)
        elif key == "hostname":
            for h in current:
                h.hostname = h.hostname or value
        elif key == "user":
            for h in current:
                h.user = h.user or value
        elif key == "proxyjump":
            for h in current:
                h.proxy_jump = h.proxy_jump or value


# --------------------------------------------------------------------------- #
# Command execution
# --------------------------------------------------------------------------- #
@dataclass
class CommandResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


@dataclass
class ConnectionTestResult:
    ok: bool
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class StagedDir:
    """Result of staging a local directory onto a target."""
    ok: bool
    path: str          # path to use in remote shell commands
    log: str = ""


class Connection:
    """Base connection interface."""

    kind: str = "base"
    name: str = ""

    def run(self, command: str, timeout: Optional[float] = None) -> CommandResult:
        raise NotImplementedError

    def stage_dir(self, local_dir: str, remote_rel: str, timeout: Optional[float] = None) -> "StagedDir":
        """Make the contents of a local directory available on the target.

        Returns a StagedDir whose ``path`` is usable in remote shell commands
        (e.g. as pip ``--find-links``). For a local connection this is the
        directory itself (no copy); for SSH it is copied under the remote home.
        """
        raise NotImplementedError

    def test(self, timeout: float = 10.0) -> ConnectionTestResult:
        """Probe reachability and report the remote identity."""
        probe = (
            'printf "%s|%s|%s\\n" '
            '"$(whoami 2>/dev/null)" '
            '"$(hostname 2>/dev/null)" '
            '"$(uname -sm 2>/dev/null)"'
        )
        try:
            res = self.run(probe, timeout=timeout)
        except subprocess.TimeoutExpired:
            return ConnectionTestResult(False, f"Connection timed out after {int(timeout)}s")
        except FileNotFoundError as e:
            return ConnectionTestResult(False, f"Command not found: {e}")

        if res.ok and res.stdout.strip():
            user, host, uname = (res.stdout.strip().split("|") + ["", "", ""])[:3]
            details = {"user": user, "hostname": host, "uname": uname}
            return ConnectionTestResult(True, f"Connected as {user}@{host} ({uname})", details)

        message = res.stderr.strip() or res.stdout.strip() or f"Exited with code {res.exit_code}"
        return ConnectionTestResult(False, message)


class LocalConnection(Connection):
    """Runs commands on the local machine through a login shell."""

    kind = "local"

    def __init__(self):
        self.name = "local"

    def run(self, command: str, timeout: Optional[float] = None) -> CommandResult:
        proc = subprocess.run(
            ["bash", "-lc", command],
            capture_output=True, text=True, timeout=timeout,
        )
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)

    def stage_dir(self, local_dir: str, remote_rel: str, timeout: Optional[float] = None) -> StagedDir:
        # Already local: use the directory in place, no copy needed.
        return StagedDir(True, local_dir)


class SSHConnection(Connection):
    """Runs commands on a remote host via the system ssh binary."""

    kind = "ssh"

    def __init__(self, alias: str, connect_timeout: int = 10):
        self.name = alias
        self.alias = alias
        self.connect_timeout = connect_timeout

    def _argv(self, command: str) -> list[str]:
        return [
            "ssh",
            "-o", "BatchMode=yes",                       # never block on a password prompt
            "-o", f"ConnectTimeout={self.connect_timeout}",
            self.alias,
            command,
        ]

    def run(self, command: str, timeout: Optional[float] = None) -> CommandResult:
        proc = subprocess.run(
            self._argv(command),
            capture_output=True, text=True, timeout=timeout,
        )
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)

    def stage_dir(self, local_dir: str, remote_rel: str, timeout: Optional[float] = None) -> StagedDir:
        # remote_rel is relative to the remote home; scp and the returned path
        # both resolve there. Create the target dir, then copy the contents in.
        mk = self.run(f'mkdir -p "{remote_rel}"', timeout=30)
        if not mk.ok:
            return StagedDir(False, remote_rel, mk.stderr or "failed to create remote directory")
        argv = [
            "scp", "-r",
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={self.connect_timeout}",
            f"{local_dir}/.",
            f"{self.alias}:{remote_rel}",
        ]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return StagedDir(False, remote_rel, "scp timed out")
        if proc.returncode != 0:
            return StagedDir(False, remote_rel, proc.stderr or proc.stdout)
        return StagedDir(True, f'$HOME/{remote_rel}', proc.stdout)


def build_connection(kind: str, alias: Optional[str] = None) -> Connection:
    """Factory: 'local' -> LocalConnection, 'ssh' -> SSHConnection(alias)."""
    if kind == "local":
        return LocalConnection()
    if kind == "ssh":
        if not alias:
            raise ValueError("An SSH host alias is required for an ssh connection")
        return SSHConnection(alias)
    raise ValueError(f"Unknown connection kind: {kind!r}")
