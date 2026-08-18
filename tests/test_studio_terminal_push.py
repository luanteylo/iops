"""Round-trip tests for TerminalSession.push_text against a local PTY.

push_text writes a config to the target over the interactive channel. Small
payloads ride inline on a command line; anything larger must be streamed,
because an inlined payload has to fit the tty's input buffer and a big config
would otherwise never be delivered (the shell waits for the rest of a line that
cannot arrive). These tests cover both sides of that threshold, driving the
coroutines with ``asyncio.run`` so no async plugin is required.
"""

import asyncio
import base64

from iops.studio.terminal import TerminalSession, _MAX_INLINE_B64


async def _push(tmp_path, text: str, name: str = "config.yaml"):
    session = TerminalSession()
    captured = bytearray()
    session.start(on_output=lambda d: captured.extend(d))
    try:
        await session.run("true", timeout=10)  # wait for the first prompt
        dest = tmp_path / name
        captured.clear()  # measure only what the push phase writes to the terminal
        rc = await session.push_text(str(dest), text, timeout=60)
        return rc, (dest.read_text() if dest.exists() else None), bytes(captured)
    finally:
        session.close()


def test_push_text_small_payload_inline(tmp_path):
    text = "benchmark:\n  name: small\n"
    rc, got, _ = asyncio.run(_push(tmp_path, text))
    assert rc == 0
    assert got == text


def test_push_text_large_payload_is_streamed(tmp_path):
    # Comfortably past the inline ceiling: this is the size class that used to
    # hang until the caller's timeout with nothing written.
    text = "".join(f"  key_{i}: value_{i}\n" for i in range(2000))
    assert len(base64.b64encode(text.encode())) > _MAX_INLINE_B64
    rc, got, during_push = asyncio.run(_push(tmp_path, text))
    assert rc == 0
    assert got == text
    # Streaming reads in raw/no-echo, so the payload never floods the xterm.
    assert base64.b64encode(text.encode()) not in during_push


def test_push_text_creates_parent_directory(tmp_path):
    # Both the inline and the streaming path have to create the configs/ dir.
    small = "benchmark:\n  name: nested\n"
    big = "".join(f"  key_{i}: value_{i}\n" for i in range(2000))
    for text, name in ((small, "inline/nested.yaml"), (big, "streamed/nested.yaml")):
        rc, _, _ = asyncio.run(_push(tmp_path, text, name=name))
        assert rc == 0, f"failed for {name}"
        assert (tmp_path / name).read_text() == text


def test_push_text_roundtrips_exactly_at_threshold(tmp_path):
    # Sizes either side of the inline/stream switch must produce identical files.
    for b64_len in (_MAX_INLINE_B64 - 4, _MAX_INLINE_B64 + 4):
        text = "x" * ((b64_len // 4) * 3)
        rc, got, _ = asyncio.run(_push(tmp_path, text, name=f"c{b64_len}.yaml"))
        assert rc == 0, f"failed at b64 length {b64_len}"
        assert got == text


def test_push_text_empty(tmp_path):
    rc, got, _ = asyncio.run(_push(tmp_path, ""))
    assert rc == 0
    assert got == ""
