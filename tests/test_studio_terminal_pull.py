"""Round-trip test for TerminalSession.pull_file against a local PTY.

pull_file streams a remote file's bytes over the interactive channel. Here the
"remote" is a local bash PTY, so we can write a file, pull it back, and assert
the bytes survive intact (including binary content and the base64 wrap). The
tests drive the coroutines with ``asyncio.run`` so no async plugin is required.
"""

import asyncio
import base64

from iops.studio.terminal import TerminalSession


async def _pull(tmp_path, payload: bytes):
    session = TerminalSession()
    captured = bytearray()
    session.start(on_output=lambda d: captured.extend(d))
    try:
        await session.run("true", timeout=10)  # wait for the first prompt
        src = tmp_path / "artifact.bin"
        src.write_bytes(payload)
        captured.clear()  # measure only what the pull phase writes to the terminal
        got = await session.pull_file(str(src), timeout=30)
        return got, bytes(captured)
    finally:
        session.close()


def test_pull_file_roundtrips_bytes(tmp_path):
    # A few KB spanning all byte values, plus newlines/nulls -> exercises base64
    # and the wrap-column newlines the decoder must tolerate.
    payload = bytes(range(256)) * 40 + b"\nhello\x00world\n"
    got, during_pull = asyncio.run(_pull(tmp_path, payload))
    assert got == payload
    # A pull suppresses its own stream, so the base64 payload and the sentinel
    # markers never flood the xterm. A few incidental shell-prompt control bytes
    # (e.g. bracketed-paste "\x1b[?2004h") can arrive in the brief window before
    # the pull begins, so assert on the flood, not on exact emptiness.
    assert b"\x1e" not in during_pull                       # R/E sentinel markers suppressed
    assert base64.b64encode(payload) not in during_pull     # base64 payload not echoed
    assert len(during_pull) < 512                           # no flood (payload is ~14 KB encoded)


def test_pull_file_missing_returns_none(tmp_path):
    async def run():
        session = TerminalSession()
        session.start(on_output=lambda d: None)
        try:
            await session.run("true", timeout=10)
            return await session.pull_file(str(tmp_path / "nope.bin"), timeout=15)
        finally:
            session.close()
    assert asyncio.run(run()) is None


def test_pull_file_empty_file(tmp_path):
    got, _ = asyncio.run(_pull(tmp_path, b""))
    assert got == b""
