"""Tests for the Studio session registry.

``SessionRegistry`` is UI-free, so it can be exercised without a NiceGUI client.
The ``TerminalSession`` inside each ``StudioSession`` is never started here, so
no PTY is spawned.
"""

from iops.studio.sessions import (
    NEW,
    SessionRegistry,
    StudioSession,
)
from iops.studio.terminal import TerminalSession


def _mk(key, setup_name=None):
    return StudioSession(key=key, term=TerminalSession(), state={}, setup_name=setup_name)


def test_add_get_and_order():
    reg = SessionRegistry()
    a, b = _mk("local"), _mk("irene")
    reg.add(a)
    reg.add(b)
    assert reg.get("local") is a
    assert reg.get("irene") is b
    assert reg.keys() == ["local", "irene"]        # insertion order preserved
    assert reg.get("missing") is None
    assert reg.get(None) is None


def test_remove():
    reg = SessionRegistry()
    reg.add(_mk("local"))
    assert reg.remove("local") is not None
    assert reg.get("local") is None
    assert reg.remove("local") is None             # idempotent


def test_by_setup_finds_bound_session():
    reg = SessionRegistry()
    unbound = _mk("sid-1")                          # wizard session, no name yet
    bound = _mk("sid-2", setup_name="irene")
    reg.add(unbound)
    reg.add(bound)
    assert reg.by_setup("irene") is bound
    assert reg.by_setup("missing") is None
    assert reg.by_setup(None) is None               # unbound never matches a lookup


def test_by_setup_reflects_late_binding():
    reg = SessionRegistry()
    s = _mk("sid-1")                                # created before it has a name
    reg.add(s)
    assert reg.by_setup("irene") is None
    s.setup_name = "irene"                          # wizard finishes and names it
    assert reg.by_setup("irene") is s
    assert s.key == "sid-1"                         # stable id unchanged


def test_default_status_is_new():
    assert _mk("local").status == NEW
