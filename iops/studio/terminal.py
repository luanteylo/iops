"""A persistent, interactive PTY-backed shell session for IOPS Studio.

One TerminalSession owns a single pseudo-terminal running a shell (local ``bash``
to begin with). It is wired to a NiceGUI ``ui.xterm`` so the user sees a live,
interactive terminal and can type into it. Studio drives its workflow by sending
commands into this same shell via ``run()`` and reading their exit code / output.

Connecting to a cluster is just running ``ssh -tt <host>`` inside this shell (the
terminal becomes the remote session), so any later ``run()`` executes on the
cluster and, if something fails, the user is already in the exact same shell to
fix it.

Design notes:
- Uses only the stdlib ``pty`` (no extra dependency).
- ``run()`` brackets each command with sentinel markers built from a raw control
  byte (0x1e) via ``printf '\\036...'``. Because the octal escape is only decoded
  when printf *executes*, the shell's echo of the command line contains the
  literal backslash form and never the raw byte, so marker detection is not fooled
  by the echoed command.
- Structured values are emitted on tagged lines (e.g. ``ENV\\t...``, ``IOPSVER=``)
  and grepped out of the captured block, tolerating echo / prompt noise.
"""

from __future__ import annotations

import asyncio
import base64
import fcntl
import os
import pty
import shlex
import signal
import struct
import subprocess
import termios
import uuid
from typing import Callable, Optional

_RS = 0x1e  # ASCII record separator, used to delimit sentinels invisibly

OutputFn = Callable[[bytes], None]


class TerminalSession:
    """A single interactive shell running in a PTY."""

    def __init__(self):
        self._fd: Optional[int] = None
        self._proc: Optional[subprocess.Popen] = None
        self._on_output: Optional[OutputFn] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._active: Optional[dict] = None
        self.input_locked: bool = False

    # -- lifecycle --------------------------------------------------------- #
    def start(self, on_output: OutputFn) -> None:
        """Spawn the local shell and begin streaming its output to ``on_output``."""
        self._on_output = on_output
        master, slave = pty.openpty()
        self._fd = master
        env = {**os.environ, "TERM": "xterm-256color"}
        self._proc = subprocess.Popen(
            ["bash"],
            stdin=slave, stdout=slave, stderr=slave,
            start_new_session=True, env=env, close_fds=True,
        )
        os.close(slave)
        flags = fcntl.fcntl(master, fcntl.F_GETFL)
        fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self._loop = asyncio.get_event_loop()
        self._loop.add_reader(master, self._on_readable)

    def close(self) -> None:
        """Terminate the child shell and release the PTY."""
        if self._fd is not None and self._loop is not None:
            try:
                self._loop.remove_reader(self._fd)
            except (ValueError, OSError):
                pass
        if self._proc is not None and self._proc.poll() is None:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGHUP)
            except (ProcessLookupError, OSError):
                pass
            try:
                self._proc.terminate()
            except OSError:
                pass
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
        self._fd = None

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None and self._fd is not None

    # -- raw I/O ----------------------------------------------------------- #
    def _on_readable(self) -> None:
        try:
            data = os.read(self._fd, 65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b""
        if not data:
            if self._fd is not None and self._loop is not None:
                try:
                    self._loop.remove_reader(self._fd)
                except (ValueError, OSError):
                    pass
            return
        if self._on_output:
            self._on_output(data)
        if self._active is not None:
            self._scan(data)

    def write(self, data) -> None:
        """Forward raw input (e.g. user keystrokes) to the shell."""
        if self._fd is None:
            return
        if isinstance(data, str):
            data = data.encode()
        try:
            os.write(self._fd, data)
        except OSError:
            pass

    def resize(self, cols: int, rows: int) -> None:
        """Resize the PTY to match the front-end terminal."""
        if self._fd is None:
            return
        try:
            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    # -- Studio command execution ------------------------------------------ #
    def _scan(self, data: bytes) -> None:
        """Watch the output stream for the active run's sentinel markers."""
        act = self._active
        act["buf"].extend(data)
        buf = bytes(act["buf"])
        s = buf.find(act["start"])
        if s < 0:
            return
        e = buf.find(act["end"], s + len(act["start"]))
        if e < 0:
            return
        output = buf[s + len(act["start"]):e].decode(errors="replace")
        rest = buf[e + len(act["end"]):]
        i = 0
        while i < len(rest) and 48 <= rest[i] <= 57:  # digits of the exit code
            i += 1
        code = int(rest[:i]) if i else -1
        fut = act["future"]
        self._active = None
        if not fut.done():
            fut.set_result((code, output))

    async def run(self, command: str, display: Optional[str] = None,
                  timeout: float = 120.0) -> tuple[int, str]:
        """Run ``command`` in the shell; return ``(exit_code, captured_output)``.

        A readable ``$ display`` line is shown first. Input is locked for the
        duration so the user's keystrokes cannot corrupt the running command;
        it unlocks as soon as the command finishes, times out, or fails.
        Multi-line commands are base64-wrapped to stay a single shell line.

        The PTY's line-discipline mode is snapshotted before the command runs
        and restored afterward. We never force ``ECHO`` on: an interactive
        ``bash`` uses readline, which keeps tty echo off and echoes typed
        characters itself, so enabling tty echo would double every keystroke.
        """
        if not self.alive or self._loop is None:
            return (-1, "")

        rid = uuid.uuid4().hex[:8]
        start = bytes([_RS]) + b"S" + rid.encode() + bytes([_RS])
        end = bytes([_RS]) + b"E" + rid.encode() + b":"
        future = self._loop.create_future()
        self._active = {"start": start, "end": end, "buf": bytearray(), "future": future}

        if display and self._on_output:
            self._on_output(("\r\n\x1b[36m$ " + display + "\x1b[0m\r\n").encode())

        if "\n" in command:
            b64 = base64.b64encode(command.encode()).decode()
            payload = f"echo {b64} | base64 -d | bash"
        else:
            payload = command
        # Run in a ( ) subshell so a stray exit/cd in a Studio command cannot
        # kill or perturb the user's interactive shell. The command still runs on
        # the current host (local, or the remote after ssh -tt).
        line = (f"printf '\\036S{rid}\\036'; ( {payload} ); "
                f"printf '\\036E{rid}:%s\\036' \"$?\"\n")

        self.input_locked = True
        saved_attrs = None
        try:
            saved_attrs = termios.tcgetattr(self._fd)
            quiet = list(saved_attrs)
            quiet[3] &= ~termios.ECHO
            termios.tcsetattr(self._fd, termios.TCSANOW, quiet)
        except (termios.error, OSError):
            saved_attrs = None
        try:
            os.write(self._fd, line.encode())
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return (124, "")
        except OSError:
            return (-1, "")
        finally:
            self._active = None
            if saved_attrs is not None:
                try:
                    termios.tcsetattr(self._fd, termios.TCSANOW, saved_attrs)
                except (termios.error, OSError):
                    pass
            self.input_locked = False

    # -- convenience ------------------------------------------------------- #
    def start_ssh(self, alias: str) -> None:
        """Begin an interactive ``ssh -tt`` into ``alias`` in this shell.

        Any auth prompt is answered by the user in the terminal. Confirm
        readiness afterwards with ``run('true')``.
        """
        self.write(f"ssh -tt {shlex.quote(alias)}\n")
