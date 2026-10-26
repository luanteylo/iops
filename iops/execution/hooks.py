# iops/execution/hooks.py

"""
Run-level hooks: user commands fired when run events happen.

The user defines the command, IOPS defines the events (see HOOK_EVENTS):
the run starting, progress thresholds, failure thresholds, consecutive
failures, and the run finishing. A hook never affects the benchmark: commands
run in a background worker on the host running IOPS, with a timeout, and a
failure is logged and otherwise ignored.

All counting happens on the runner's main thread through HookManager.record(),
so no locking is needed for the counters. Commands are rendered on the main
thread too (so the context reflects the moment the event happened) and only
their execution is deferred to the worker.
"""

from __future__ import annotations

import concurrent.futures
import os
import shlex
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, StrictUndefined

from iops.config.models import HookConfig, HookThreshold

HOOKS_LOG_FILENAME = "__iops_hooks.log"

# Output kept per stream in the hooks log; hook commands can be chatty.
_MAX_LOGGED_OUTPUT = 4000

# Floating point slack when comparing a percentage against a threshold.
_EPS = 1e-9

SUCCESS_STATUSES = ("SUCCEEDED",)
FAILURE_STATUSES = ("FAILED", "ERROR")
SKIPPED_STATUSES = ("SKIPPED",)

_jinja_env = Environment(
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
    undefined=StrictUndefined,
)
_jinja_env.filters["quote"] = lambda value: shlex.quote(str(value))


def describe_hook_trigger(hook: HookConfig) -> str:
    """One-line description of when a hook fires, e.g. "progress at 25%, 50%; every 100"."""
    parts = []
    if hook.at:
        parts.append("at " + ", ".join(str(t) for t in hook.at))
    if hook.every is not None:
        parts.append(f"every {hook.every}")
    if hook.event == "finish":
        parts.append("when " + ", ".join(hook.when) if hook.when else "on any outcome")
    if hook.event == "failures" and any(t.percent for t in hook.at):
        parts.append(f"min_tests {hook.min_tests}")
    return hook.event + (" " + "; ".join(parts) if parts else "")


def render_hook_command(command: str, context: Dict[str, Any]) -> str:
    """Render a hook command template. Raises Jinja2 errors on failure."""
    return _jinja_env.from_string(command).render(**context).strip()


@dataclass
class HookStats:
    """Counters the hook context is built from."""
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    other: int = 0  # concluded with a status that is neither success nor failure
    consecutive_failures: int = 0
    core_hours: float = 0.0

    @property
    def completed(self) -> int:
        return self.succeeded + self.failed + self.skipped + self.other

    @property
    def ran(self) -> int:
        """Tests that produced a success or failure (the failure-rate denominator)."""
        return self.succeeded + self.failed

    @property
    def percent(self) -> float:
        return (self.completed / self.total * 100.0) if self.total > 0 else 0.0

    @property
    def failed_percent(self) -> float:
        return (self.failed / self.ran * 100.0) if self.ran > 0 else 0.0


@dataclass
class HookResult:
    """Outcome of one hook command."""
    hook: str
    event: str
    command: str
    exit_code: Optional[int]
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    timed_out: bool = False
    error: Optional[str] = None  # set when the command could not be rendered or started

    @property
    def ok(self) -> bool:
        return self.error is None and not self.timed_out and self.exit_code == 0


class _PermissiveEnv(dict):
    """os_env stand-in for validation: unknown variables render as empty."""

    def __missing__(self, key):
        return ""


def _format_elapsed(seconds: float) -> str:
    return str(timedelta(seconds=int(max(0, seconds))))


def _build_message(event: str, ctx: Dict[str, Any]) -> str:
    """Ready-made, human readable text describing the event."""
    p = ctx["progress"]
    r = ctx["run"]
    name = ctx["benchmark"]["name"]
    threshold = ctx["event"]["threshold"]
    counts = f"succeeded {p['succeeded']}, failed {p['failed']}, skipped {p['skipped']}"

    if event == "start":
        head = f"IOPS run '{name}' started on {ctx['hostname']}: {p['total']} tests planned."
        lines = [head]
    elif event == "progress":
        lines = [
            f"IOPS run '{name}' reached {threshold} progress: "
            f"{p['completed']}/{p['total']} tests concluded ({p['percent']}%).",
            f"{counts.capitalize()}. Elapsed: {r['elapsed']}.",
        ]
    elif event == "failures":
        lines = [
            f"IOPS run '{name}' reached {threshold} failures: "
            f"{p['failed']} of {p['succeeded'] + p['failed']} tests failed ({p['failed_percent']}%).",
            f"{p['completed']}/{p['total']} tests concluded. Elapsed: {r['elapsed']}.",
        ]
    elif event == "consecutive_failures":
        lines = [
            f"IOPS run '{name}' has {p['consecutive_failures']} consecutive failures.",
            f"{p['completed']}/{p['total']} tests concluded ({counts}). Elapsed: {r['elapsed']}.",
        ]
    else:  # finish
        lines = [
            f"IOPS run '{name}' finished ({r['outcome']}) after {r['elapsed']}.",
            f"{p['completed']}/{p['total']} tests concluded: {counts}.",
        ]
        if ctx["report_path"]:
            lines.append(f"Report: {ctx['report_path']}")

    lines.append(f"Run directory: {ctx['workdir']}")
    return "\n".join(lines)


def build_hook_context(
    hook: HookConfig,
    *,
    benchmark_name: str,
    workdir: Path,
    stats: HookStats,
    start_time: datetime,
    threshold: Optional[HookThreshold] = None,
    outcome: Optional[str] = None,
    report_path: Optional[Path] = None,
    os_env: Optional[Dict[str, str]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build the Jinja2 context a hook command is rendered with."""
    now = now or datetime.now()
    elapsed = (now - start_time).total_seconds()
    ctx: Dict[str, Any] = {
        "event": {
            "name": hook.event,
            "hook": hook.name,
            "threshold": str(threshold) if threshold is not None else "",
        },
        "progress": {
            "completed": stats.completed,
            "total": stats.total,
            "percent": round(stats.percent, 1),
            "succeeded": stats.succeeded,
            "failed": stats.failed,
            "skipped": stats.skipped,
            "failed_percent": round(stats.failed_percent, 1),
            "consecutive_failures": stats.consecutive_failures,
        },
        "run": {
            "outcome": outcome or "",
            "elapsed": _format_elapsed(elapsed),
            "elapsed_seconds": int(elapsed),
            "start_time": start_time.isoformat(timespec="seconds"),
            "core_hours": round(stats.core_hours, 4),
        },
        "benchmark": {"name": benchmark_name},
        "workdir": str(workdir),
        "report_path": str(report_path) if report_path else "",
        "hostname": socket.gethostname(),
        "os_env": os_env if os_env is not None else dict(os.environ),
    }
    ctx["message"] = _build_message(hook.event, ctx)
    return ctx


def sample_hook_context(hook: HookConfig, benchmark_name: str, workdir: Path) -> Dict[str, Any]:
    """
    A plausible context for validating and testing a hook without a run.

    Values describe a run of 100 tests, halfway through, adjusted so the
    numbers agree with the hook's first threshold (a progress hook at "25%"
    sees 25 concluded tests). ``os_env`` renders unknown variables as empty
    strings, so a config that reads a variable only defined on the cluster
    still validates elsewhere.
    """
    threshold = None
    if hook.at:
        threshold = hook.at[0]
    elif hook.every is not None:
        threshold = hook.every

    stats = HookStats(total=100, succeeded=45, failed=5, consecutive_failures=3, core_hours=12.5)
    if threshold is not None:
        value = int(round(threshold.value))
        if hook.event == "progress":
            completed = min(value, 100) if threshold.percent else value
            stats.total = max(100, completed)
            stats.failed = min(5, completed)
            stats.succeeded = completed - stats.failed
            stats.consecutive_failures = min(stats.consecutive_failures, stats.failed)
        elif hook.event == "failures":
            if threshold.percent:
                # failure rate among 50 tests that ran
                stats.failed = max(1, int(round(threshold.value * 50 / 100)))
                stats.succeeded = 50 - stats.failed
            else:
                stats.failed = value
                stats.total = max(100, value + stats.succeeded)
            stats.consecutive_failures = min(stats.consecutive_failures, stats.failed)
        elif hook.event == "consecutive_failures":
            stats.consecutive_failures = value
            stats.failed = max(stats.failed, value)
            stats.total = max(100, stats.failed + stats.succeeded)
    outcome = None
    if hook.event == "finish":
        outcome = (hook.when or ["completed"])[0]
    start = datetime.now() - timedelta(minutes=30)
    return build_hook_context(
        hook,
        benchmark_name=benchmark_name,
        workdir=workdir,
        stats=stats,
        start_time=start,
        threshold=threshold,
        outcome=outcome,
        report_path=Path(workdir) / "analysis_report.html" if hook.event == "finish" else None,
        os_env=_PermissiveEnv(os.environ),
    )


def hook_environment(ctx: Dict[str, Any]) -> Dict[str, str]:
    """IOPS_* environment variables mirroring the context, for hook scripts."""
    p = ctx["progress"]
    r = ctx["run"]
    return {
        "IOPS_HOOK": ctx["event"]["hook"],
        "IOPS_EVENT": ctx["event"]["name"],
        "IOPS_THRESHOLD": ctx["event"]["threshold"],
        "IOPS_OUTCOME": r["outcome"],
        "IOPS_COMPLETED": str(p["completed"]),
        "IOPS_TOTAL": str(p["total"]),
        "IOPS_PERCENT": str(p["percent"]),
        "IOPS_SUCCEEDED": str(p["succeeded"]),
        "IOPS_FAILED": str(p["failed"]),
        "IOPS_SKIPPED": str(p["skipped"]),
        "IOPS_FAILED_PERCENT": str(p["failed_percent"]),
        "IOPS_CONSECUTIVE_FAILURES": str(p["consecutive_failures"]),
        "IOPS_ELAPSED_SECONDS": str(r["elapsed_seconds"]),
        "IOPS_CORE_HOURS": str(r["core_hours"]),
        "IOPS_BENCHMARK": ctx["benchmark"]["name"],
        "IOPS_WORKDIR": ctx["workdir"],
        "IOPS_REPORT_PATH": ctx["report_path"],
        "IOPS_MESSAGE": ctx["message"],
    }


def run_hook_command(
    hook: HookConfig,
    rendered: str,
    env: Dict[str, str],
    cwd: Optional[Path] = None,
) -> HookResult:
    """
    Run a rendered hook command through bash and wait for it.

    The command gets its own session, so a Ctrl+C aimed at IOPS does not kill
    a hook reporting the interruption, and on timeout the whole process group
    is killed (a plain kill of the shell could leave a child holding the
    output pipes open).
    """
    started = time.monotonic()
    full_env = dict(os.environ)
    full_env.update(env)
    executable = "/bin/bash" if os.path.exists("/bin/bash") else None
    run_cwd = str(cwd) if cwd is not None and Path(cwd).is_dir() else None

    try:
        proc = subprocess.Popen(
            rendered,
            shell=True,
            executable=executable,
            cwd=run_cwd,
            env=full_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as e:
        return HookResult(hook.name, hook.event, rendered, None, error=f"could not start command: {e}")

    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=hook.timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        stdout, stderr = proc.communicate()

    return HookResult(
        hook=hook.name,
        event=hook.event,
        command=rendered,
        exit_code=proc.returncode,
        stdout=stdout or "",
        stderr=stderr or "",
        duration=time.monotonic() - started,
        timed_out=timed_out,
    )


class HookManager:
    """
    Tracks run progress and fires the configured hooks.

    The runner calls start() once, record() after every concluded test, and
    finish() once in its finally block. finish() waits for every pending hook
    so the process does not exit before, for example, a notification is sent.
    """

    def __init__(
        self,
        hooks: List[HookConfig],
        benchmark_name: str,
        workdir: Path,
        logger,
    ):
        self.hooks = list(hooks)
        self.benchmark_name = benchmark_name
        self.workdir = Path(workdir)
        self.logger = logger
        self.stats = HookStats()
        self.start_time = datetime.now()
        self.results: List[HookResult] = []

        # Per-hook trigger state, keyed by hook name
        self._fired_at: Dict[str, set] = {h.name: set() for h in self.hooks}
        self._every_multiple: Dict[str, int] = {h.name: 0 for h in self.hooks}

        self._pool: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._futures: List[concurrent.futures.Future] = []
        self._log_lock = threading.Lock()
        self.started = False
        self._finished = False

    # ------------------------------------------------------------------ #
    # Runner interface
    # ------------------------------------------------------------------ #

    def start(self, total: int) -> None:
        """Fire start hooks. Only the first call has an effect."""
        if self.started:
            return
        self.started = True
        self.stats.total = int(total or 0)
        for hook in self._hooks_for("start"):
            self._fire(hook)

    def record(self, status: str, total: int, core_hours: float = 0.0) -> None:
        """Count one concluded test and fire every hook whose threshold it crosses."""
        if self._finished:
            return
        s = self.stats
        s.total = max(int(total or 0), 0)
        s.core_hours = core_hours

        streak_reset = False
        if status in SUCCESS_STATUSES:
            s.succeeded += 1
            if s.consecutive_failures:
                streak_reset = True
            s.consecutive_failures = 0
        elif status in FAILURE_STATUSES:
            s.failed += 1
            s.consecutive_failures += 1
        elif status in SKIPPED_STATUSES:
            s.skipped += 1
        else:
            s.other += 1

        # A fresh streak re-arms consecutive_failures hooks
        if streak_reset:
            for hook in self._hooks_for("consecutive_failures"):
                self._fired_at[hook.name].clear()
                self._every_multiple[hook.name] = 0

        for hook in self.hooks:
            if hook.event == "progress":
                threshold = self._crossed(hook, s.completed, s.percent if s.total > 0 else None)
            elif hook.event == "failures":
                # Evaluated on every test, not only failures: a success can
                # open the min_tests guard on a rate that is already too high.
                # The guard is lowered on runs with fewer runnable tests than
                # min_tests, so small runs still report.
                runnable = s.total - s.skipped - s.other
                guard = min(hook.min_tests, runnable) if s.total > 0 else hook.min_tests
                rate = s.failed_percent if s.ran >= max(guard, 1) else None
                threshold = self._crossed(hook, s.failed, rate)
            elif hook.event == "consecutive_failures":
                threshold = self._crossed(hook, s.consecutive_failures, None)
            else:
                continue
            if threshold is not None:
                self._fire(hook, threshold=threshold)

    def finish(self, outcome: str, total: Optional[int] = None,
               core_hours: Optional[float] = None, report_path: Optional[Path] = None) -> None:
        """Fire finish hooks matching the outcome, then wait for all pending hooks."""
        if self._finished:
            return
        # A run that never yielded a test still reports that it started
        if not self.started:
            self.start(total=total or 0)
        if total is not None:
            self.stats.total = int(total)
        if core_hours is not None:
            self.stats.core_hours = core_hours

        for hook in self._hooks_for("finish"):
            if hook.when and outcome not in hook.when:
                continue
            self._fire(hook, outcome=outcome, report_path=report_path)

        self._finished = True
        self.wait()

    def wait(self) -> None:
        """Block until every submitted hook has finished."""
        if self._pool is None:
            return
        pending = [f for f in self._futures if not f.done()]
        if pending:
            self.logger.info(f"Waiting for {len(pending)} hook(s) to finish...")
        self._pool.shutdown(wait=True)
        self._pool = None
        self._futures = []

    # ------------------------------------------------------------------ #
    # Threshold logic
    # ------------------------------------------------------------------ #

    def _crossed(self, hook: HookConfig, count: int, percent: Optional[float]) -> Optional[HookThreshold]:
        """
        Mark and return the threshold this update crossed, if any.

        ``at`` thresholds fire once each. ``every`` fires at each multiple of
        its value; when one update jumps several multiples (a percentage on a
        small run), it fires once for the highest one. When several thresholds
        are crossed at once the last one is reported.
        """
        crossed: Optional[HookThreshold] = None
        fired = self._fired_at[hook.name]

        for t in hook.at:
            key = str(t)
            if key in fired:
                continue
            value = percent if t.percent else count
            if value is not None and value + _EPS >= t.value:
                fired.add(key)
                crossed = t

        if hook.every is not None:
            t = hook.every
            value = percent if t.percent else count
            if value is not None and t.value > 0:
                multiple = int((value + _EPS) // t.value)
                if multiple > self._every_multiple[hook.name]:
                    self._every_multiple[hook.name] = multiple
                    crossed = HookThreshold(value=t.value * multiple, percent=t.percent)

        return crossed

    # ------------------------------------------------------------------ #
    # Execution
    # ------------------------------------------------------------------ #

    def _hooks_for(self, event: str) -> List[HookConfig]:
        return [h for h in self.hooks if h.event == event]

    def _fire(self, hook: HookConfig, threshold: Optional[HookThreshold] = None,
              outcome: Optional[str] = None, report_path: Optional[Path] = None) -> None:
        ctx = build_hook_context(
            hook,
            benchmark_name=self.benchmark_name,
            workdir=self.workdir,
            stats=self.stats,
            start_time=self.start_time,
            threshold=threshold,
            outcome=outcome,
            report_path=report_path,
        )
        try:
            rendered = render_hook_command(hook.command, ctx)
        except Exception as e:
            result = HookResult(hook.name, hook.event, hook.command, None,
                                error=f"could not render command: {e}")
            self._report(result, threshold)
            return

        label = f" ({threshold})" if threshold is not None else ""
        self.logger.info(f"[Hook] {hook.name}: {hook.event}{label}")

        env = hook_environment(ctx)
        if self._pool is None:
            self._pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="iops-hook"
            )
        future = self._pool.submit(self._run, hook, rendered, env, threshold)
        self._futures = [f for f in self._futures if not f.done()]
        self._futures.append(future)

    def _run(self, hook: HookConfig, rendered: str, env: Dict[str, str],
             threshold: Optional[HookThreshold]) -> None:
        try:
            result = run_hook_command(hook, rendered, env, cwd=self.workdir)
        except Exception as e:  # never let a hook take the worker down
            result = HookResult(hook.name, hook.event, rendered, None, error=str(e))
        self._report(result, threshold)

    def _report(self, result: HookResult, threshold: Optional[HookThreshold]) -> None:
        self.results.append(result)
        if result.error:
            self.logger.warning(f"[Hook] {result.hook} failed: {result.error}")
        elif result.timed_out:
            self.logger.warning(f"[Hook] {result.hook} timed out and was killed")
        elif result.exit_code != 0:
            detail = result.stderr.strip().splitlines()[-1:] or [""]
            self.logger.warning(
                f"[Hook] {result.hook} exited with code {result.exit_code}"
                + (f": {detail[0]}" if detail[0] else "")
            )
        else:
            self.logger.debug(f"[Hook] {result.hook} succeeded in {result.duration:.2f}s")
        self._append_log(result, threshold)

    def _append_log(self, result: HookResult, threshold: Optional[HookThreshold]) -> None:
        if not self.workdir.is_dir():
            return
        status = (
            f"error={result.error}" if result.error
            else "timeout" if result.timed_out
            else f"exit={result.exit_code}"
        )
        lines = [
            f"[{datetime.now().isoformat(timespec='seconds')}] hook={result.hook} "
            f"event={result.event} threshold={threshold if threshold is not None else '-'} "
            f"{status} duration={result.duration:.2f}s",
            f"  command: {result.command}",
        ]
        for name, text in (("stdout", result.stdout), ("stderr", result.stderr)):
            text = text.strip()
            if text:
                if len(text) > _MAX_LOGGED_OUTPUT:
                    text = text[:_MAX_LOGGED_OUTPUT] + " ...[truncated]"
                lines.append(f"  {name}: " + text.replace("\n", "\n    "))
        try:
            with self._log_lock, open(self.workdir / HOOKS_LOG_FILENAME, "a") as f:
                f.write("\n".join(lines) + "\n")
        except OSError as e:
            self.logger.debug(f"Could not write hooks log: {e}")
