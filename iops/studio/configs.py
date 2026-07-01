"""Store the user's IOPS benchmark configs (YAML) as a local library.

Each config is bound to a setup (the target it runs on) and carries the full
YAML text as the single source of truth. Configs are saved locally under
``~/.config/iops/studio-configs.json``; on run, Studio writes the YAML into the
target's workdir and executes ``iops run`` there through the terminal.

Identity is (setup_name, name): the same config name can exist for different
targets. The workdir lives inside the YAML (``benchmark.workdir``); Studio reads
it from there rather than duplicating it.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

_SCHEMA = 1


def _config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "iops"


def configs_path() -> Path:
    """Absolute path of the saved-configs file (may not exist yet)."""
    return _config_dir() / "studio-configs.json"


@dataclass
class StudioConfig:
    """One saved benchmark config: a named YAML bound to a setup/target."""

    name: str
    setup_name: str
    yaml_text: str


def _read_raw() -> Optional[dict]:
    try:
        data = json.loads(configs_path().read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _parse(d: object) -> Optional[StudioConfig]:
    if not isinstance(d, dict):
        return None
    try:
        return StudioConfig(name=d["name"], setup_name=d["setup_name"],
                            yaml_text=d.get("yaml_text", ""))
    except KeyError:
        return None


def load_configs(setup_name: Optional[str] = None) -> list:
    """All saved configs, or only those bound to ``setup_name`` if given."""
    data = _read_raw()
    if data is None or data.get("schema") != _SCHEMA:
        return []
    out = [cfg for cfg in (_parse(x) for x in (data.get("configs") or [])) if cfg is not None]
    if setup_name is not None:
        out = [c for c in out if c.setup_name == setup_name]
    return out


def get_config(setup_name: str, name: str) -> Optional[StudioConfig]:
    return next((c for c in load_configs(setup_name) if c.name == name), None)


def save_configs(configs: list) -> None:
    """Write the full collection to disk atomically (tmp file + rename)."""
    path = configs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": _SCHEMA, "configs": [asdict(c) for c in configs]}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def upsert_config(cfg: StudioConfig) -> None:
    """Add ``cfg`` or replace one with the same (setup_name, name) in place."""
    configs = load_configs()
    for i, existing in enumerate(configs):
        if existing.setup_name == cfg.setup_name and existing.name == cfg.name:
            configs[i] = cfg
            break
    else:
        configs.append(cfg)
    save_configs(configs)


def delete_config(setup_name: str, name: str) -> bool:
    """Remove one config. Returns True if it existed."""
    configs = load_configs()
    remaining = [c for c in configs
                 if not (c.setup_name == setup_name and c.name == name)]
    if len(remaining) == len(configs):
        return False
    save_configs(remaining)
    return True
