"""Closing a TerminalSession while a command is waiting on it.

Studio closes a page's shells when the browser tab disconnects. A command still
awaiting output (say, `iops report` behind a "View report" click) used to block
until its timeout, then raise TypeError from restoring the tty mode on the closed
PTY (``self._fd`` is None), which surfaced as a traceback in the Studio log. It
must instead return the failure result promptly.
"""

import asyncio
import time

from iops.studio.terminal import TerminalSession


def test_close_fails_a_pending_run_promptly():
    async def scenario():
        session = TerminalSession()
        session.start(on_output=lambda d: None)
        await session.run("true", timeout=10)  # wait for the first prompt
        task = asyncio.ensure_future(session.run("sleep 20", timeout=60))
        await asyncio.sleep(0.5)
        started = time.monotonic()
        session.close()
        result = await asyncio.wait_for(task, timeout=5)
        return result, time.monotonic() - started, session

    result, elapsed, session = asyncio.run(scenario())
    assert result == (-1, "")
    assert elapsed < 5
    assert not session.alive
    assert not session.input_locked


def test_run_after_close_returns_failure_without_raising():
    async def scenario():
        session = TerminalSession()
        session.start(on_output=lambda d: None)
        await session.run("true", timeout=10)
        session.close()
        return await session.run("echo hi", timeout=5)

    assert asyncio.run(scenario()) == (-1, "")


def test_restore_tty_is_a_noop_once_closed():
    async def scenario():
        session = TerminalSession()
        session.start(on_output=lambda d: None)
        session.close()
        # Must not raise TypeError on the closed PTY (fd None)
        session._restore_tty([0, 0, 0, 0, 0, 0, []])

    asyncio.run(scenario())
