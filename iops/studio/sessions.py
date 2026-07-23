"""Per-runtime terminal sessions for IOPS Studio.

Studio can hold several runtimes open at once (a laptop plus a few clusters),
each with its own live shell shown in its own terminal tab. A ``StudioSession``
bundles everything that belongs to one such runtime: the PTY-backed
``TerminalSession``, its per-runtime ``state`` dict, which saved setup it is
bound to, and the NiceGUI element handles for its tab and terminal.

This module stays UI-free (it never imports ``nicegui``): the element handles
are opaque ``Any`` fields and the ``emit``/``note`` writers are callables, both
assigned by ``iops.studio.app`` once the elements exist. That keeps the session
model testable and mirrors the layering of ``terminal.py`` / ``settings.py``.

The ``SessionRegistry`` keys sessions by a stable session id (a uuid), never by
setup name: a wizard session is created before it has a name, and naming it must
not disturb its live shell or its tab identity. The bound setup is tracked
separately as ``setup_name`` and looked up with ``by_setup``. The registry lives
in the page scope (one per browser tab) so that distinct clients never share PTYs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from iops.studio.terminal import TerminalSession

# Lifecycle of a session's shell, reflected by the tab's status dot:
#   new        - created, not yet verified/connected (grey)
#   connecting - (re)connecting, e.g. after restart (amber)
#   connected  - shell verified / setup validated (green)
#   dropped    - the shell died / ssh dropped (red)
NEW = "new"
CONNECTING = "connecting"
CONNECTED = "connected"
DROPPED = "dropped"


@dataclass
class StudioSession:
    """One runtime: its shell, state, bound setup, and UI handles."""

    key: str                       # stable session id (uuid); never the setup name
    term: TerminalSession
    state: dict
    setup_name: Optional[str] = None  # bound SetupConfig name, once the wizard names it
    status: str = NEW

    # NiceGUI element handles, assigned by app.py after the elements are built.
    xterm: Any = None
    tab: Any = None
    column: Any = None
    status_dot: Any = None
    drop_banner: Any = None

    # Writers wired by app.py (they route through the page's client context so
    # background PTY callbacks can update the UI). ``emit`` takes raw bytes;
    # ``note`` takes a human message and renders it as a yellow shell comment.
    emit: Optional[Callable[[bytes], None]] = None
    note: Optional[Callable[[str], None]] = None


class SessionRegistry:
    """An ordered collection of ``StudioSession`` keyed by ``key``.

    Insertion order is preserved so the tab bar can render sessions in the order
    they were opened. All access is by key; there is no implicit "current"
    session (the app tracks the active key separately).
    """

    def __init__(self) -> None:
        self._by_key: dict[str, StudioSession] = {}

    def add(self, session: StudioSession) -> StudioSession:
        """Register ``session`` under its current ``key`` (replaces same key)."""
        self._by_key[session.key] = session
        return session

    def get(self, key: Optional[str]) -> Optional[StudioSession]:
        """Return the session for ``key``, or None."""
        if key is None:
            return None
        return self._by_key.get(key)

    def by_setup(self, setup_name: Optional[str]) -> Optional[StudioSession]:
        """Return the (first) session bound to ``setup_name``, or None.

        There is at most one live session per setup: opening a setup that already
        has one focuses it rather than creating a second.
        """
        if setup_name is None:
            return None
        return next((s for s in self._by_key.values() if s.setup_name == setup_name), None)

    def all(self) -> list:
        """All sessions, in insertion order (snapshot: safe to mutate during)."""
        return list(self._by_key.values())

    def keys(self) -> list:
        return list(self._by_key.keys())

    def remove(self, key: str) -> Optional[StudioSession]:
        """Drop the session for ``key`` and return it (None if absent).

        This only forgets the session; the caller is responsible for closing its
        ``TerminalSession`` and deleting its elements first.
        """
        return self._by_key.pop(key, None)
