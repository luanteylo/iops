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

from iops.studio.terminal import (
    TerminalSession,
    _MAX_INLINE_CMD,
    _fits_inline,
    _inline_write_command,
)


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
    assert len(base64.b64encode(text.encode())) > _MAX_INLINE_CMD
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


def _largest_inline_text_len(dest) -> int:
    """Longest text that still rides inline when written to ``dest``."""
    n = 0
    while _fits_inline(_inline_write_command(
            str(dest), base64.b64encode(b"x" * (n + 1)).decode())):
        n += 1
    return n


def test_push_text_roundtrips_exactly_at_threshold(tmp_path):
    # Sizes either side of the inline/stream switch must produce identical
    # files. The switch is decided on the whole command line, so the boundary
    # depends on the destination path and has to be found for this tmp_path.
    boundary = _largest_inline_text_len(tmp_path / "c.yaml")
    assert boundary > 0, "no payload fits inline; budget is too small to test"
    for n in (boundary, boundary + 1):
        text = "x" * n
        rc, got, _ = asyncio.run(_push(tmp_path, text, name=f"c{n}.yaml"))
        assert rc == 0, f"failed at text length {n}"
        assert got == text


def test_push_text_empty(tmp_path):
    rc, got, _ = asyncio.run(_push(tmp_path, ""))
    assert rc == 0
    assert got == ""


def test_run_long_command_is_streamed_and_does_not_wedge(tmp_path):
    """A command too long for one line must still run, and leave the shell usable.

    Regression test for environment discovery hanging on PLAFRIM: its ~2.1 KB
    command line was silently truncated in transit, so the remote shell waited
    forever for a newline that could not arrive and every later command hung
    behind it.
    """
    marker = tmp_path / "out.txt"
    # Padding comment pushes the command well past the single-line budget.
    command = ("# " + "p" * (_MAX_INLINE_CMD * 2) + "\n"
               f'printf STREAMED > "{marker}"\n'
               "echo TAGGED_OUTPUT\n")
    assert not _fits_inline(command), "command must exceed the inline budget"

    async def _drive():
        session = TerminalSession()
        session.start(on_output=lambda d: None)
        try:
            await session.run("true", timeout=10)
            first = await session.run(command, timeout=60)
            # The channel must still be healthy for the next command.
            second = await session.run("echo STILL_ALIVE", timeout=10)
            return first, second
        finally:
            session.close()

    (code, out), (code2, out2) = asyncio.run(_drive())
    assert code == 0
    assert "TAGGED_OUTPUT" in out
    assert marker.read_text() == "STREAMED"
    assert code2 == 0 and "STILL_ALIVE" in out2


def test_run_long_in_shell_command_persists_env(tmp_path):
    """A long ``subshell=False`` command still applies its env to later commands.

    Streaming must source the script rather than run it in a child shell, or
    setup commands (module load, export PATH) would silently lose their effect.
    """
    command = ("# " + "p" * (_MAX_INLINE_CMD * 2) + "\n"
               "export IOPS_STREAM_PROBE=persisted\n")
    assert not _fits_inline(command, subshell=False)

    async def _drive():
        session = TerminalSession()
        session.start(on_output=lambda d: None)
        try:
            await session.run("true", timeout=10)
            code, _ = await session.run(command, timeout=60, subshell=False)
            return code, await session.run("echo $IOPS_STREAM_PROBE", timeout=10)
        finally:
            session.close()

    code, (code2, out) = asyncio.run(_drive())
    assert code == 0
    assert code2 == 0 and "persisted" in out
