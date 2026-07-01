"""Persist and restore IOPS Studio setups so the wizard runs only once each.

A *setup* is one completed Connection -> Python environment -> Install choice,
saved under a user-facing ``name``. Studio keeps a collection of them in
``~/.config/iops/studio.json`` (XDG-aware), because one workstation often reaches
several targets (a laptop plus a few clusters). On launch Studio lists the saved
setups; picking one re-validates it live and skips the wizard. "Add setup" runs
the wizard again and appends a new entry.

Only the durable identity of each setup is stored (name + target + interpreter
path + versions + setup commands), never live handles or secrets. Validation
always re-probes the target, so a stale entry can describe an environment that no
longer works; that is caught at use time and surfaced, not trusted.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from iops.studio import __version__ as STUDIO_VERSION

# Schema history:
#   1 - a single setup object at the file root.
#   2 - {"schema": 2, "setups": [<setup>, ...]} with a per-setup "name".
# A v1 file is migrated to a one-element v2 list on load.
_SCHEMA = 2


def _config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "iops"


def config_path() -> Path:
    """Absolute path of the saved-setups file (may not exist yet)."""
    return _config_dir() / "studio.json"


@dataclass
class SetupConfig:
    """The durable description of one completed Studio setup."""

    name: str                           # user-facing, unique key within the file
    target_kind: str                    # "local" | "ssh"
    target_alias: Optional[str]         # ssh host alias, or None for local
    env_path: str                       # interpreter path on the target
    env_kind: str = "venv"              # "system" | "venv" | "custom"
    env_version: Optional[str] = None   # python version, informational
    iops_version: Optional[str] = None  # IOPS version present at save time
    # Commands run in the interactive shell right after connecting, before
    # anything else (e.g. "module load python3/3.12", "export PATH=..."). They
    # set up the environment so discovery / install / validation see it.
    init_commands: list = field(default_factory=list)
    studio_version: str = STUDIO_VERSION

    @property
    def where(self) -> str:
        return f"SSH · {self.target_alias}" if self.target_kind == "ssh" else "Local machine"


def _read_raw() -> Optional[dict]:
    try:
        data = json.loads(config_path().read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _parse_setup(d: object) -> Optional[SetupConfig]:
    if not isinstance(d, dict):
        return None
    try:
        return SetupConfig(
            name=d["name"],
            target_kind=d["target_kind"],
            target_alias=d.get("target_alias"),
            env_path=d["env_path"],
            env_kind=d.get("env_kind", "venv"),
            env_version=d.get("env_version"),
            iops_version=d.get("iops_version"),
            init_commands=list(d.get("init_commands") or []),
            studio_version=d.get("studio_version", ""),
        )
    except KeyError:
        return None


def _migrated_name(d: dict) -> str:
    if d.get("target_kind") == "ssh" and d.get("target_alias"):
        return str(d["target_alias"])
    return "local"


def load_setups() -> list:
    """Return all saved setups (possibly empty). Migrates a v1 file in memory."""
    data = _read_raw()
    if data is None:
        return []
    schema = data.get("schema")
    if schema == _SCHEMA:
        raw_list = data.get("setups") or []
    elif schema == 1 and "target_kind" in data:
        migrated = dict(data)
        migrated.setdefault("name", _migrated_name(data))
        raw_list = [migrated]
    else:
        return []
    return [cfg for cfg in (_parse_setup(item) for item in raw_list) if cfg is not None]


def get_setup(name: str) -> Optional[SetupConfig]:
    """Return the setup with ``name``, or None."""
    return next((s for s in load_setups() if s.name == name), None)


def save_setups(setups: list) -> None:
    """Write the full collection to disk atomically (tmp file + rename)."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": _SCHEMA, "setups": [asdict(s) for s in setups]}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def upsert_setup(cfg: SetupConfig) -> None:
    """Add ``cfg``, or replace an existing setup with the same name in place."""
    setups = load_setups()
    for i, existing in enumerate(setups):
        if existing.name == cfg.name:
            setups[i] = cfg
            break
    else:
        setups.append(cfg)
    save_setups(setups)


def delete_setup(name: str) -> bool:
    """Remove the setup named ``name``. Returns True if one was removed."""
    setups = load_setups()
    remaining = [s for s in setups if s.name != name]
    if len(remaining) == len(setups):
        return False
    save_setups(remaining)
    return True
