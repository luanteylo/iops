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
        self._on_exit: Optional[Callable[[], None]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._active: Optional[dict] = None
        self._transfer: Optional[dict] = None
        self._closing: bool = False
        self.input_locked: bool = False

    # -- lifecycle --------------------------------------------------------- #
    def start(self, on_output: OutputFn, on_exit: Optional[Callable[[], None]] = None) -> None:
        """Spawn the local shell and begin streaming its output to ``on_output``.

        ``on_exit`` (if given) is called once when the shell dies on its own (the
        user typed ``exit``, an ``ssh`` session dropped back to a shell that then
        ended, the process was killed, etc.). It does not fire on an intentional
        ``close()``/``restart()``.
        """
        self._on_output = on_output
        self._on_exit = on_exit
        self._closing = False
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
        self._closing = True  # suppress the on_exit callback for intentional teardown
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

    def restart(self) -> None:
        """Kill the current child and spawn a fresh local shell in its place.

        Reuses the same ``on_output`` sink so the wired-up ``ui.xterm`` keeps
        working. Used when resetting setup: any lingering ``ssh`` session is torn
        down so subsequent commands run on the local machine again.
        """
        on_output = self._on_output
        on_exit = self._on_exit
        self.close()
        if on_output is not None:
            self.start(on_output, on_exit)

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
            # EOF: the child shell has died. Stop reading and, unless this is an
            # intentional close/restart, notify so the UI can offer to recover.
            if self._fd is not None and self._loop is not None:
                try:
                    self._loop.remove_reader(self._fd)
                except (ValueError, OSError):
                    pass
            # Fail any in-flight run()/push_tar so its awaiter returns now instead
            # of blocking for the full timeout on a shell that is gone.
            if self._active is not None:
                fut = self._active["future"]
                self._active = None
                if not fut.done():
                    fut.set_result((-1, ""))
            if self._transfer is not None:
                for key in ("ready_future", "end_future"):
                    f = self._transfer[key]
                    if not f.done():
                        f.set_result(-1 if key == "end_future" else False)
                self._transfer = None
            if not self._closing and self._on_exit is not None:
                self._on_exit()
            return
        if self._on_output:
            self._on_output(data)
        if self._active is not None:
            self._scan(data)
        if self._transfer is not None:
            self._scan_transfer(data)

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

    def _scan_transfer(self, data: bytes) -> None:
        """Track a push_tar's two markers: ``R`` (remote ready to read) and ``E``.

        ``R`` fires once the remote has switched its tty to raw/no-echo and is
        about to read the payload, gating when Studio starts streaming. ``E``
        carries the extraction exit code. If ``E`` appears before ``R`` the
        remote setup failed, so we never stream and report the failure.
        """
        t = self._transfer
        t["buf"].extend(data)
        buf = bytes(t["buf"])
        rf, ef = t["ready_future"], t["end_future"]
        r = buf.find(t["ready"])
        e = buf.find(t["end"])
        if not rf.done():
            if e >= 0 and (r < 0 or e < r):
                rf.set_result(False)  # setup failed before reaching the read
            elif r >= 0:
                rf.set_result(True)
        if e >= 0 and not ef.done():
            rest = buf[e + len(t["end"]):]
            i = 0
            while i < len(rest) and 48 <= rest[i] <= 57:
                i += 1
            ef.set_result(int(rest[:i]) if i else -1)

    async def _wait_writable(self) -> None:
        """Suspend until the PTY master accepts more bytes (write backpressure)."""
        fut = self._loop.create_future()

        def _ready():
            if not fut.done():
                fut.set_result(None)

        self._loop.add_writer(self._fd, _ready)
        try:
            await fut
        finally:
            try:
                self._loop.remove_writer(self._fd)
            except (ValueError, OSError):
                pass

    async def _drain_write(self, data: bytes) -> bool:
        """Write all of ``data`` to the PTY, awaiting writability on EAGAIN."""
        view = memoryview(data)
        off = 0
        while off < len(view):
            try:
                off += os.write(self._fd, view[off:off + 32768])
            except BlockingIOError:
                await self._wait_writable()
            except (OSError, ValueError):
                return False
        return True

    async def push_tar(self, dest_rel: str, tar_gz: bytes, timeout: float = 1200.0) -> int:
        """Stream a gzip tarball into ``$HOME/dest_rel`` on the remote and extract it.

        Uses only this one already-authenticated interactive channel, so it works
        on hosts that reject background scp/ssh (no key, no multiplexing, password
        or 2FA only). The remote drops its tty to raw/no-echo, reads exactly N
        payload bytes into a staging file (so nothing echoes back and the browser
        is not flooded), then base64-decodes and untars. Returns the remote exit
        code, or -1 on a local/transport failure.

        ``dest_rel`` must be a trusted, metacharacter-free path (it is embedded in
        the remote command); Studio only ever passes a fixed constant.
        """
        if not self.alive or self._loop is None:
            return -1
        payload = base64.b64encode(tar_gz)  # ASCII, unwrapped
        n = len(payload)
        rid = uuid.uuid4().hex[:8]
        ready = bytes([_RS]) + b"R" + rid.encode() + bytes([_RS])
        end = bytes([_RS]) + b"E" + rid.encode() + b":"
        ready_future = self._loop.create_future()
        end_future = self._loop.create_future()
        self._transfer = {
            "ready": ready, "end": end, "buf": bytearray(),
            "ready_future": ready_future, "end_future": end_future,
        }
        # The remote reads N bytes into a staging file *inside* the destination
        # (avoids /tmp size limits and a broken-pipe short read), restores the
        # tty, then decodes + extracts. R is emitted only after raw/-echo is set.
        line = (
            'D="$HOME/%s"; mkdir -p "$D" && __t="$D/.iops_incoming" && '
            "stty raw -echo 2>/dev/null && printf '\\036R%s\\036' && "
            'head -c %d > "$__t"; stty sane 2>/dev/null; '
            'base64 -d "$__t" 2>/dev/null | tar xzf - -C "$D"; __rc=$?; rm -f "$__t"; '
            "printf '\\036E%s:%%s\\036' \"$__rc\"\n"
        ) % (dest_rel, rid, n, rid)

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
            if not await self._drain_write(line.encode()):
                return -1
            try:
                remote_ready = await asyncio.wait_for(ready_future, timeout=60)
            except asyncio.TimeoutError:
                return -1
            if not remote_ready:
                # Setup failed before the read; the E marker carries the code.
                try:
                    return await asyncio.wait_for(end_future, timeout=15)
                except asyncio.TimeoutError:
                    return -1
            if not await self._drain_write(bytes(payload)):
                return -1
            return await asyncio.wait_for(end_future, timeout=timeout)
        except OSError:
            return -1
        finally:
            self._transfer = None
            if saved_attrs is not None:
                try:
                    termios.tcsetattr(self._fd, termios.TCSANOW, saved_attrs)
                except (termios.error, OSError):
                    pass
            self.input_locked = False

    async def run(self, command: str, display: Optional[str] = None,
                  timeout: float = 120.0, subshell: bool = True) -> tuple[int, str]:
        """Run ``command`` in the shell; return ``(exit_code, captured_output)``.

        A readable ``$ display`` line is shown first. Input is locked for the
        duration so the user's keystrokes cannot corrupt the running command;
        it unlocks as soon as the command finishes, times out, or fails.
        Multi-line commands are base64-wrapped to stay a single shell line.

        ``subshell`` (default) runs the command in a ``( )`` subshell so a stray
        ``exit``/``cd`` cannot perturb the user's interactive shell. Pass
        ``subshell=False`` for setup commands that must persist their effect
        (``module load``, ``export PATH=...``): those run in a ``{ }`` group in
        the current shell so PATH/env changes carry into later commands. Such a
        command must be a single shell statement (no base64 wrapping applies).

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

        if "\n" in command and subshell:
            b64 = base64.b64encode(command.encode()).decode()
            payload = f"echo {b64} | base64 -d | bash"
        else:
            payload = command
        # A ( ) subshell isolates the interactive shell from exit/cd. A { } group
        # runs in the current shell so setup commands persist their env changes.
        wrapped = f"( {payload} )" if subshell else f"{{ {payload} ; }}"
        line = (f"printf '\\036S{rid}\\036'; {wrapped}; "
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
    def start_ssh(self, alias: str, options: Optional[list] = None) -> None:
        """Begin an interactive ``ssh -tt`` into ``alias`` in this shell.

        ``options`` are extra ``ssh`` arguments (e.g. ControlMaster settings so
        later standalone ssh/scp reuse this authenticated connection). Any auth
        prompt is answered by the user in the terminal. Confirm readiness
        afterwards with ``run('true')``.
        """
        opts = " ".join(shlex.quote(o) for o in (options or []))
        opts = f"{opts} " if opts else ""
        self.write(f"ssh -tt {opts}{shlex.quote(alias)}\n")
