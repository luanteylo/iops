"""Persist and restore the IOPS Studio setup so the wizard runs only once.

Once a user completes Connection -> Python environment -> Install IOPS, the
resulting choice is written to ``~/.config/iops/studio.json`` (XDG-aware). On the
next launch Studio loads it, re-validates it live (the interpreter still exists
and IOPS is importable), and skips straight to a ready state. "Re-run setup"
deletes the file and drops the user back into the wizard.

Only the durable identity of the setup is stored (target + interpreter path +
versions), never live handles or secrets. Validation always re-probes the target,
so a stale file can describe an environment that no longer works; that is caught
at load time and surfaced, not trusted.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from iops.studio import __version__ as STUDIO_VERSION

# Bump when the on-disk shape changes incompatibly; older/newer files are ignored.
_SCHEMA = 1


def _config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "iops"


def config_path() -> Path:
    """Absolute path of the saved-setup file (may not exist yet)."""
    return _config_dir() / "studio.json"


@dataclass
class SetupConfig:
    """The durable description of a completed Studio setup."""

    target_kind: str                    # "local" | "ssh"
    target_alias: Optional[str]         # ssh host alias, or None for local
    env_path: str                       # interpreter path on the target
    env_kind: str = "venv"              # "system" | "venv" | "custom"
    env_version: Optional[str] = None   # python version, informational
    iops_version: Optional[str] = None  # IOPS version present at save time
    studio_version: str = STUDIO_VERSION
    schema: int = _SCHEMA

    @property
    def where(self) -> str:
        return f"SSH · {self.target_alias}" if self.target_kind == "ssh" else "Local machine"


def load_setup() -> Optional[SetupConfig]:
    """Load the saved setup, or ``None`` if absent, unreadable, or a foreign schema."""
    try:
        data = json.loads(config_path().read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != _SCHEMA:
        return None
    try:
        return SetupConfig(
            target_kind=data["target_kind"],
            target_alias=data.get("target_alias"),
            env_path=data["env_path"],
            env_kind=data.get("env_kind", "venv"),
            env_version=data.get("env_version"),
            iops_version=data.get("iops_version"),
            studio_version=data.get("studio_version", ""),
            schema=data["schema"],
        )
    except KeyError:
        return None


def save_setup(cfg: SetupConfig) -> None:
    """Write ``cfg`` to disk atomically (tmp file + rename)."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(asdict(cfg), indent=2))
    tmp.replace(path)


def clear_setup() -> bool:
    """Delete the saved setup. Returns True if a file was removed."""
    try:
        config_path().unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
