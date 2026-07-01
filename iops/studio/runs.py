"""Track IOPS runs launched inside ``screen`` so they survive ssh disconnects.

When Studio starts a benchmark on a target it wraps it in a detached ``screen``
session and records here which session it is and, crucially, which login node it
runs on. Login-node aliases often load-balance, so on reconnect Studio may land
on a different node; the recorded hostname lets it hop back with ``ssh <node>``
and reattach. Records are kept until the user dismisses them (a finished screen
simply fails to reattach, which the user then dismisses).

Stored in ``~/.config/iops/studio-runs.json``. No secrets, just identifiers.
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


def runs_path() -> Path:
    return _config_dir() / "studio-runs.json"


@dataclass
class RunRecord:
    """One benchmark launched in a screen session on a specific login node."""

    setup_name: str
    config_name: str
    screen_name: str      # `screen -S` session name (unique)
    node: str             # hostname where the screen (and iops) run
    started_at: str = ""  # human timestamp, informational


def _parse(d: object) -> Optional[RunRecord]:
    if not isinstance(d, dict):
        return None
    try:
        return RunRecord(setup_name=d["setup_name"], config_name=d["config_name"],
                        screen_name=d["screen_name"], node=d.get("node", ""),
                        started_at=d.get("started_at", ""))
    except KeyError:
        return None


def load_runs(setup_name: Optional[str] = None) -> list:
    """All tracked runs, or only those for ``setup_name`` if given."""
    try:
        data = json.loads(runs_path().read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or data.get("schema") != _SCHEMA:
        return []
    out = [r for r in (_parse(x) for x in (data.get("runs") or [])) if r is not None]
    if setup_name is not None:
        out = [r for r in out if r.setup_name == setup_name]
    return out


def save_runs(runs: list) -> None:
    path = runs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": _SCHEMA, "runs": [asdict(r) for r in runs]}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def add_run(rec: RunRecord) -> None:
    """Record a run, replacing any with the same (setup_name, screen_name)."""
    runs = [r for r in load_runs()
            if not (r.setup_name == rec.setup_name and r.screen_name == rec.screen_name)]
    runs.append(rec)
    save_runs(runs)


def remove_run(setup_name: str, screen_name: str) -> bool:
    runs = load_runs()
    remaining = [r for r in runs
                 if not (r.setup_name == setup_name and r.screen_name == screen_name)]
    if len(remaining) == len(runs):
        return False
    save_runs(remaining)
    return True
