"""Round-trip test for TerminalSession.pull_file against a local PTY.

pull_file streams a remote file's bytes over the interactive channel. Here the
"remote" is a local bash PTY, so we can write a file, pull it back, and assert
the bytes survive intact (including binary content and the base64 wrap). The
tests drive the coroutines with ``asyncio.run`` so no async plugin is required.
"""

import asyncio

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
    # A pull suppresses terminal output entirely, so the base64 never floods the
    # xterm: nothing (payload nor sentinel markers) reaches on_output during it.
    assert during_pull == b""


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
