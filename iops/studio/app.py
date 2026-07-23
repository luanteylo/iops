"""NiceGUI page definitions for IOPS Studio.

This module is imported lazily (only after the NiceGUI availability check in
``iops.studio.server``), so importing ``nicegui`` at module top is safe here.

Layout: a two-pane page. The left pane is the setup wizard (Connection, Python
environment, Install IOPS); the right pane is a persistent, interactive terminal
(``ui.xterm``) backed by one shell session. The wizard drives its steps by
sending commands into that same shell, so everything shows up live and, on
failure, the user can take over in the exact same context.
"""

import asyncio
import base64
import io
import logging
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from nicegui import app, ui

from iops.main import load_version
from iops.studio import __version__ as STUDIO_VERSION
from iops.studio.connections import build_connection, parse_ssh_hosts, ssh_interactive_opts
from iops.studio.environments import (
    PyEnv,
    build_discovery_script,
    build_venv_command,
    parse_env_lines,
)
from iops.studio.installer import (
    CLIENT_VERSION,
    install_iops_session,
    iops_version_command,
    parse_iops_version,
)
from iops.studio.builder import build_editor, config_workdir, starter_yaml
from iops.studio.configs import (
    StudioConfig,
    delete_config,
    get_config,
    load_configs,
    rename_setup as rename_setup_configs,
    upsert_config,
)
from iops.studio.filebrowser import choose_dir, open_yaml, save_yaml
from iops.studio.results import (
    DEFAULT_REPORT_CONFIG,
    REPORT_FILENAME,
    light_tar_command,
    list_runs_command,
    localize_report_html,
    parse_run_list,
    plotly_bundle_path,
    report_config_path,
    report_html_path,
    slug as _result_slug,
)
from iops.studio.runs import (
    RunRecord,
    add_run,
    load_runs,
    remove_run,
    rename_setup as rename_setup_runs,
)
from iops.studio.sessions import (
    CONNECTED,
    CONNECTING,
    DROPPED,
    NEW,
    SessionRegistry,
    StudioSession,
)
from iops.studio.settings import (
    SetupConfig,
    delete_setup,
    get_setup,
    load_setups,
    upsert_setup,
)
from iops.studio.terminal import TerminalSession

# Tagged "studio.app" in the DEBUG log format; traces which handler is running so
# the low-level terminal trace (studio.terminal) can be read in context.
logger = logging.getLogger(__name__)

# Palette borrowed from the HTML report (iops/reporting/report_generator.py).
_STUDIO_HEAD = """
<style>
    body {
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        background-color: #f5f5f5;
    }
    .studio-card {
        background-color: white;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.12);
    }
</style>
"""

_XTERM_OPTIONS = {
    "cursorBlink": True,
    "fontSize": 13,
    "scrollback": 5000,
    "fontFamily": "'SFMono-Regular', Consolas, 'Liberation Mono', monospace",
    "theme": {"background": "#1e1e1e", "foreground": "#d4d4d4"},
}

# Terminal-tab text color per session status (colors the tab's label + status dot).
_STATUS_CLASS = {
    NEW: "text-grey",
    CONNECTING: "text-warning",
    CONNECTED: "text-positive",
    DROPPED: "text-negative",
}

_LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"


def _logo_data_uri() -> str:
    """Return the bundled IOPS logo as a base64 data URI ('' if unavailable).

    Embedding the image inline keeps Studio self-contained: no static route to
    register and no dependence on the process working directory.
    """
    try:
        data = _LOGO_PATH.read_bytes()
    except OSError:
        return ""
    return "data:image/png;base64," + base64.b64encode(data).decode()


_STUDIO_LOGO = _logo_data_uri()


def _alive(element) -> bool:
    """True while ``element`` is still mounted (not torn down by a view switch).

    Async handlers can await for a while (an ssh login, an install); if the user
    navigates meanwhile, the left pane is cleared and their elements deleted.
    Touching a deleted element warns in NiceGUI, so guard UI writes after awaits.
    """
    try:
        return element.id in element.client.elements
    except Exception:
        return False


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name or "").strip("_") or "config"


def _shell_workdir(workdir: str) -> str:
    """Make a setup workdir safe to embed in double quotes, expanding a leading ~.

    Inside ``"..."`` the shell won't expand ``~`` but will expand ``$HOME``, so
    ``~/iops_workdir`` becomes ``$HOME/iops_workdir``.
    """
    wd = (workdir or "~/iops_workdir").strip()
    if wd == "~":
        return "$HOME"
    if wd.startswith("~/"):
        return "$HOME/" + wd[2:]
    return wd


async def _ensure_workdir(session: TerminalSession, workdir: str) -> None:
    """Create ``<workdir>/configs`` on the target (idempotent)."""
    d = _shell_workdir(workdir)
    await session.run(f'mkdir -p "{d}/configs"', display=f"prepare workdir {workdir}", timeout=30)


async def _remote_value(session: TerminalSession, expr: str, tag: str) -> str:
    """Run ``printf 'TAG=%s' expr`` and return the captured value ("" on miss)."""
    _, out = await session.run(f"printf '{tag}=%s\\n' \"{expr}\"", timeout=30)
    for line in out.splitlines():
        line = line.strip()
        if line.startswith(tag + "="):
            return line[len(tag) + 1:].strip()
    return ""


async def _detach_if_attached(session: TerminalSession, state: dict) -> None:
    """If Studio is attached to a screen, detach so the next command runs in the
    login shell instead of being typed into the screen.

    ``Ctrl-A D`` is screen's detach chord; screen intercepts it regardless of what
    is running inside, and the detached IOPS keeps executing in the background.
    Only sent when we know we are attached (kept accurate by watching output for
    screen's ``[detached from ...]`` / ``[screen is terminating]`` messages).
    """
    if state.get("attached"):
        session.write("\x01d")  # Ctrl-A, D -> screen detaches
        state["attached"] = False
        await asyncio.sleep(0.5)  # let the login shell prompt come back
        # Ctrl-U clears any stray input: harmless at a clean prompt, and it saves
        # us if the flag was stale (e.g. an ssh drop that never printed "detached").
        session.write("\x15")


async def _screen_sessions(session: TerminalSession) -> set:
    """Names of live ``screen`` sessions on the current node (empty if none)."""
    _, out = await session.run("screen -ls || true", timeout=30)
    names = set()
    for line in out.splitlines():
        m = re.search(r"\d+\.(\S+)", line)  # lines look like: 12345.name  (Detached)
        if m:
            names.add(m.group(1))
    return names


async def _write_config_to_target(session: TerminalSession, note, workdir: str,
                                  name: str, yaml_text: str) -> Optional[str]:
    """Write ``yaml_text`` into ``<workdir>/configs/<name>.yaml`` on the target.

    Returns the remote path (with ``$HOME`` unexpanded, safe inside double
    quotes), or None on failure.
    """
    cfg_dir = f"{_shell_workdir(workdir)}/configs"
    remote = f"{cfg_dir}/{_slug(name)}.yaml"
    b64 = base64.b64encode(yaml_text.encode()).decode()
    cmd = (f'mkdir -p "{cfg_dir}" && printf %s \'{b64}\' | base64 -d > "{remote}" '
           f'&& echo __WROTE__')
    code, out = await session.run(cmd, display=f"write {_slug(name)}.yaml", timeout=60)
    if code != 0 or "__WROTE__" not in out:
        note(f"could not write config to target (exit {code})")
        return None
    return remote


def _node_command(setup: SetupConfig, node: str, action: str, tty: bool = False) -> str:
    """Shell to run ``action`` on ``node``, working from local *or* the cluster.

    The run's node is only reachable from inside the cluster; the ssh alias is
    only resolvable from the local machine. So we branch in the shell itself:
    on the node -> run directly; reachable directly (we're on the cluster) ->
    ssh to it; otherwise (local) -> ssh the alias and hop to the node from there.
    """
    if setup.target_kind == "local":
        return action
    alias = setup.target_alias
    opts = " ".join(ssh_interactive_opts(alias))
    t = "-tt " if tty else ""
    inner = (f'if [ "$(hostname)" = "{node}" ]; then {action}; '
             f'else ssh {t}"{node}" "{action}"; fi')
    return (
        f'if [ "$(hostname)" = "{node}" ]; then {action}; '
        f'elif ssh {t}"{node}" {shlex.quote(action)} 2>/dev/null; then :; '
        f'else ssh -tt {opts} {alias} {shlex.quote(inner)}; fi'
    )


def _runner_script(setup: SetupConfig, remote_config: str, session_name: str,
                   flags: str = "") -> str:
    """Bash the screen runs: apply setup commands, cd to workdir, run IOPS.

    Writes an exit-code marker to the shared workdir when IOPS finishes, so the
    status can be read from any login node even though the screen stays alive
    (``exec bash``) for the user to review the output. ``flags`` is a leading
    string of ``iops run`` options (e.g. " --use-cache --dry-run").
    """
    wd = _shell_workdir(setup.workdir)
    marker = f"{wd}/.iops-studio/{session_name}.exit"
    lines = ["#!/bin/bash"]
    lines += list(setup.init_commands or [])
    lines += [
        f'cd "{wd}" || exit 1',
        f'"{setup.env_path}" -m iops run "{remote_config}"{flags}',
        "__ec=$?",
        f'echo "$__ec" > "{marker}"',
        "echo",
        "echo \"=== iops finished (exit $__ec). Type 'exit' to close this screen. ===\"",
        "exec bash",
    ]
    return "\n".join(lines) + "\n"


def _suggest_name(target: dict, env) -> str:
    """A default setup name from the target and environment, e.g. ``irene:iops_env``."""
    where = target.get("alias") if target.get("kind") == "ssh" else "local"
    if getattr(env, "kind", None) == "system":
        leaf = "system"
    else:
        # .../<venv>/bin/python -> "<venv>"
        leaf = Path(env.path).parent.parent.name or "env"
    return f"{where}:{leaf}"


def _build_setup_list(setups: list, on_select, on_add, on_delete, on_edit):
    """Left-pane hub: the saved setups with select/edit/delete, plus 'Add setup'."""
    ui.label("Your setups").classes("text-lg font-semibold")
    ui.label("Pick a target to validate and use, or add a new one.") \
        .classes("text-gray-600 text-sm")
    with ui.column().classes("gap-2 w-full mt-2"):
        for cfg in setups:
            with ui.card().classes("studio-card w-full p-3"):
                with ui.row().classes("items-center justify-between w-full no-wrap"):
                    with ui.column().classes("gap-0"):
                        ui.label(cfg.name).classes("font-medium")
                        ui.label(f"{cfg.where} · {cfg.env_path}").classes("text-xs text-gray-500")
                        iops = f"IOPS {cfg.iops_version}" if cfg.iops_version else "IOPS (unknown)"
                        extra = f" · {len(cfg.init_commands)} setup cmd(s)" if cfg.init_commands else ""
                        ui.label(iops + extra).classes("text-xs text-gray-500")
                    with ui.row().classes("items-center gap-1"):
                        ui.button(icon="play_arrow", on_click=lambda c=cfg: on_select(c)) \
                            .props("flat round").tooltip("Use this setup")
                        ui.button(icon="edit", on_click=lambda c=cfg: on_edit(c)) \
                            .props("flat round").tooltip("Edit this setup")
                        ui.button(icon="delete", on_click=lambda c=cfg: on_delete(c)) \
                            .props("flat round color=negative").tooltip("Delete this setup")
    ui.button("Add setup", icon="add", on_click=on_add).classes("mt-2")


def _parse_commands(text: str) -> list:
    """Split a textarea into a clean command list: non-empty, comments dropped."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


async def _run_setup_commands(session: TerminalSession, commands: list, note) -> bool:
    """Run each setup command in the persistent shell (so env changes stick).

    Returns True if all succeeded. Failures are noted but not fatal: a bad
    ``module load`` just means discovery/validation will not find the env, which
    the user then sees and can fix.
    """
    ok = True
    for cmd in commands:
        code, _ = await session.run(cmd, display=cmd, timeout=120, subshell=False)
        if code != 0:
            ok = False
            note(f"setup command failed (exit {code}): {cmd}")
    return ok


def _build_wizard(session: TerminalSession, state: dict, host_options: dict, note,
                  on_complete, on_cancel=None, on_status=None):
    """Build the left-pane setup wizard. ``note`` writes a line to the terminal.

    ``on_complete`` is called (no args) once the setup is finished, either by a
    successful install or by finishing on an environment that already has IOPS.
    It reads the shared ``state`` to persist and switch to the ready view.
    ``on_cancel`` closes this wizard's terminal and returns to the setups hub.
    ``on_status(status)`` (optional) reports the shell's connection status so the
    caller can repaint this session's tab (e.g. green once verified).
    """

    def _status(s):
        if on_status is not None:
            on_status(s)

    if on_cancel is not None:
        with ui.row().classes("items-center gap-2 w-full"):
            ui.button("Back to setups", icon="arrow_back", on_click=on_cancel).props("flat dense")
        ui.label("New setup").classes("text-lg font-semibold")

    with ui.stepper().props("vertical").classes("w-full") as stepper:

        # ---- Step 1: connection ------------------------------------------- #
        with ui.step("Connection"):
            ui.label("Run locally, or open an SSH session to a cluster. Every "
                     "command runs in the terminal on the right.").classes("text-gray-600 text-sm")
            conn_type = ui.toggle({"local": "Local machine", "ssh": "SSH host"}, value="local")
            ssh_select = ui.select(host_options, label="Host from ~/.ssh/config",
                                   with_input=True).classes("w-96")
            ssh_select.bind_visibility_from(conn_type, "value", backward=lambda v: v == "ssh")

            init_input = ui.textarea(
                "Setup commands (one per line, run after connecting)",
                value="\n".join(state.get("init_commands") or []),
                on_change=lambda: state.update(init_commands=_parse_commands(init_input.value)),
            ).classes("w-96").props("autogrow")
            init_input.tooltip("Run in the shell right after connecting, before discovery. "
                               "Use for 'module load python3/3.12', 'export PATH=...', etc. "
                               "Their effect (PATH, modules) carries into the whole setup.")
            workdir_input = ui.input(
                "Workdir (folder to run IOPS from)",
                value=state.get("workdir") or "~/iops_workdir",
                on_change=lambda e: state.update(workdir=(e.value or "").strip() or "~/iops_workdir"),
            ).classes("w-96")
            workdir_input.tooltip("Studio always cd's here before running IOPS and saves your "
                                  "configs under it. Created on connect if missing.")
            conn_status = ui.row().classes("items-center gap-2 min-h-8")

            async def do_verify():
                code, out = await session.run(
                    'printf "WHO=%s@%s\\n" "$(whoami)" "$(hostname)"',
                    display="verify shell", timeout=30)
                if not _alive(conn_status):
                    return
                who = next((l[4:] for l in out.splitlines() if l.startswith("WHO=")), None)
                if not (code == 0 and who):
                    conn_status.clear()
                    with conn_status:
                        ui.icon("error", color="negative")
                        ui.label("Shell not ready. Check the terminal.").classes("text-negative")
                    return
                state["connected"] = True
                state["init_commands"] = _parse_commands(init_input.value)
                if state["init_commands"]:
                    conn_status.clear()
                    with conn_status:
                        ui.spinner(size="sm")
                        ui.label("Running setup commands...")
                    await _run_setup_commands(session, state["init_commands"], note)
                    if not _alive(conn_status):
                        return
                state["init_ran"] = True  # already applied to this shell session
                state["workdir"] = (workdir_input.value or "").strip() or "~/iops_workdir"
                await _ensure_workdir(session, state["workdir"])
                if not _alive(conn_status):
                    return
                conn_status.clear()
                with conn_status:
                    ui.icon("check_circle", color="positive")
                    ui.label(f"Connected: {who}").classes("text-positive")
                    conn_next.set_enabled(True)
                _status(CONNECTED)

            async def on_connect():
                if conn_type.value == "ssh":
                    alias = ssh_select.value
                    if not alias:
                        ui.notify("Select an SSH host", type="warning")
                        return
                    session.start_ssh(alias, ssh_interactive_opts(alias))
                    state["target"] = {"kind": "ssh", "alias": alias}
                    _status(CONNECTING)
                    conn_status.clear()
                    with conn_status:
                        ui.icon("info", color="warning")
                        ui.label("Authenticate in the terminal if prompted, then click Verify.")
                    verify_btn.set_visibility(True)
                else:
                    state["target"] = {"kind": "local", "alias": None}
                    await do_verify()

            with ui.row().classes("gap-2 mt-2"):
                ui.button("Connect", icon="cable", on_click=on_connect)
                verify_btn = ui.button("Verify", icon="check", on_click=do_verify)
                verify_btn.set_visibility(False)
            with ui.stepper_navigation():
                conn_next = ui.button("Next", icon="arrow_forward", on_click=stepper.next)
                conn_next.set_enabled(False)

        # ---- Step 2: python environment ----------------------------------- #
        with ui.step("Python environment"):
            ui.label("Choose the Python environment IOPS will use on the target, "
                     "or create a new one.").classes("text-gray-600 text-sm")
            env_area = ui.column().classes("gap-1 w-full")
            env_radio = {"widget": None}

            def render_envs(envs):
                state["envs"] = envs
                env_area.clear()
                with env_area:
                    if not envs:
                        ui.label("No environments found. Create one below.") \
                            .classes("text-gray-400 text-sm italic")
                        env_radio["widget"] = None
                        env_next.set_enabled(False)
                        return
                    options = {i: e.label for i, e in enumerate(envs)}
                    radio = ui.radio(options, on_change=lambda: env_next.set_enabled(True))
                    env_radio["widget"] = radio

            async def on_discover():
                if not state["connected"]:
                    ui.notify("Connect first", type="warning")
                    return
                extra = [custom_path.value] if custom_path.value.strip() else None
                try:
                    script = build_discovery_script(extra)
                except ValueError as e:
                    ui.notify(f"Invalid folder: {e}", type="negative")
                    return
                env_area.clear()
                with env_area:
                    with ui.row().classes("items-center gap-2"):
                        ui.spinner(size="sm")
                        ui.label("Discovering environments...")
                _, out = await session.run(script, display="discover Python environments", timeout=90)
                if not _alive(env_area):
                    return
                render_envs(parse_env_lines(out))

            async def on_create():
                if not state["connected"]:
                    ui.notify("Connect first", type="warning")
                    return
                try:
                    cmd = build_venv_command(path_input.value)
                except ValueError as e:
                    ui.notify(f"Invalid path: {e}", type="negative")
                    return
                code, _ = await session.run(cmd, display=f"create venv {path_input.value.strip()}",
                                            timeout=300)
                if code == 0:
                    ui.notify("Environment created", type="positive")
                    await on_discover()
                else:
                    ui.notify("Environment creation failed (see terminal)", type="negative")

            custom_path = ui.input(
                "Custom folder to scan (optional)",
                placeholder="e.g. /scratch/me/envs or /scratch/me/envs/myenv",
            ).classes("w-96")
            custom_path.tooltip("A directory of venvs, a single venv root, or a "
                                "direct interpreter path. Scanned in addition to the defaults.")
            with ui.row().classes("gap-2"):
                ui.button("Discover environments", icon="search", on_click=on_discover)
            with ui.expansion("Create a new environment", icon="add").classes("w-full"):
                path_input = ui.input("Virtual environment path", value="~/.venvs/iops_env") \
                    .classes("w-96")
                ui.button("Create", icon="build", on_click=on_create)

            def on_env_next():
                radio = env_radio["widget"]
                if radio is None or radio.value is None:
                    ui.notify("Select an environment", type="warning")
                    return
                state["env"] = state["envs"][radio.value]
                refresh_install()
                stepper.next()

            with ui.stepper_navigation():
                ui.button("Back", on_click=stepper.previous).props("flat")
                env_next = ui.button("Next", icon="arrow_forward", on_click=on_env_next)
                env_next.set_enabled(False)

        # ---- Step 3: install IOPS ----------------------------------------- #
        with ui.step("Install IOPS"):
            ui.label("Ensure IOPS is available in the selected environment. Studio "
                     "installs with pip, falling back to an offline wheelhouse. "
                     "Watch it run in the terminal.").classes("text-gray-600 text-sm")
            install_status = ui.row().classes("items-center gap-2 min-h-8")
            version_input = ui.input("Version to install", value=CLIENT_VERSION).classes("w-64")
            version_input.tooltip("Defaults to this client's version so the remote "
                                  "runner matches. Clear to install the latest.")
            name_input = ui.input(
                "Save setup as",
                on_change=lambda: state.update(setup_name=name_input.value.strip()),
            ).classes("w-96")
            name_input.tooltip("A name for this setup so you can pick it next time. "
                               "Reusing a name overwrites that setup.")
            install_outcome = ui.column().classes("w-full")

            def refresh_install():
                env = state["env"]
                install_status.clear()
                install_outcome.clear()
                with install_status:
                    if env and env.has_iops:
                        ui.icon("check_circle", color="positive")
                        ui.label(f"IOPS {env.iops_version} already installed in {env.path}")
                    else:
                        ui.icon("info", color="warning")
                        ui.label("IOPS is not installed in the selected environment.")
                install_btn.set_text("Reinstall IOPS" if (env and env.has_iops) else "Install IOPS")
                finish_btn.set_enabled(bool(env and env.has_iops))
                if env and not name_input.value.strip():
                    name_input.value = _suggest_name(state["target"], env)
                    state["setup_name"] = name_input.value

            async def on_install():
                env = state["env"]
                if env is None:
                    ui.notify("Select an environment first", type="warning")
                    return
                version = version_input.value.strip() or None
                install_btn.disable()
                install_outcome.clear()
                with install_outcome:
                    with ui.row().classes("items-center gap-2"):
                        ui.spinner(size="sm")
                        ui.label("Installing... (watch the terminal)")
                scp_conn = build_connection(state["target"]["kind"], state["target"]["alias"])
                res = await install_iops_session(session, env.path, version=version,
                                                 scp_conn=scp_conn, emit=note)
                if not _alive(install_outcome):
                    return
                if res.ok:
                    env.iops_version = res.version
                    install_btn.enable()
                    on_complete()  # persist and switch to the ready view
                    return
                install_outcome.clear()
                with install_outcome:
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("error", color="negative")
                        ui.label("Install failed. Fix it in the terminal, then retry.") \
                            .classes("text-negative")
                    if res.steps:
                        ui.label("(" + " → ".join(res.steps) + ")").classes("text-xs text-gray-500")
                install_btn.enable()
                refresh_install()

            with ui.row().classes("gap-2 mt-2"):
                install_btn = ui.button("Install IOPS", icon="download", on_click=on_install)
            with ui.stepper_navigation():
                ui.button("Back", on_click=stepper.previous).props("flat")
                finish_btn = ui.button("Finish", icon="check", on_click=lambda: on_complete())
                finish_btn.set_enabled(False)


async def _validate_setup(session: TerminalSession, saved: SetupConfig) -> tuple[bool, str]:
    """Re-probe a saved setup on the live shell. Returns ``(ok, detail)``.

    Valid means the interpreter still exists and IOPS is importable there. A
    version drift from what was saved is reported but still counts as valid.
    """
    _, out = await session.run(iops_version_command(saved.env_path),
                               display="validate setup", timeout=60)
    version = parse_iops_version(out)
    if not version:
        return False, f"IOPS not found in {saved.env_path}"
    if saved.iops_version and version != saved.iops_version:
        return True, f"IOPS {version} present (setup saved {saved.iops_version})"
    return True, f"IOPS {version} ready in {saved.env_path}"


def _run_badge(status):
    """Small colored chip for a run's status: running / finished / unchecked."""
    label, color = {
        "running": ("running", "positive"),
        "finished": ("finished", "blue"),
        "unknown": ("status unknown", "grey"),
    }.get(status, ("not checked", "grey"))
    ui.badge(label, color=color).props("outline" if status != "running" else "")


def _build_ready(session: TerminalSession, state: dict, saved: SetupConfig,
                 note, on_back, validate: bool, *, on_new_config, on_edit_config,
                 on_run_config, on_delete_config, on_import_config, on_export_config,
                 on_reconnect_run, on_stop_run, on_dismiss_run, on_refresh_runs,
                 on_browse_runs, on_view_report, on_pull_results,
                 on_close=None, on_status=None):
    """Left-pane view for one selected setup: summary, validation, runs, configs.

    ``on_back`` returns to the setups hub *without* closing this runtime's
    terminal (it keeps running in its tab). ``on_close`` tears the terminal down.
    ``on_status(status)`` reports connection status so the caller repaints the tab.
    """

    def _status(s):
        if on_status is not None:
            on_status(s)

    with ui.card().classes("studio-card w-full p-4 gap-1"):
        with ui.row().classes("items-center justify-between w-full no-wrap"):
            ui.label(saved.name).classes("text-lg font-semibold")
            with ui.row().classes("items-center gap-1 no-wrap"):
                if on_close is not None:
                    ui.button(icon="tab_unselected", on_click=on_close) \
                        .props("flat round dense").tooltip("Close this terminal")
                ui.button(icon="arrow_back", on_click=on_back).props("flat round dense") \
                    .tooltip("Back to setups (keeps the terminal open)")
        ui.label(saved.where).classes("text-sm text-gray-600")
        ui.label(f"Environment: {saved.env_path}").classes("text-sm text-gray-600")
        ui.label(f"Workdir: {saved.workdir}").classes("text-sm text-gray-600")
        py = f"Python {saved.env_version}" if saved.env_version else "Python"
        iops = f" · IOPS {saved.iops_version}" if saved.iops_version else " · IOPS (unknown)"
        ui.label(py + iops).classes("text-sm text-gray-600")

        if saved.init_commands:
            with ui.expansion(f"Setup commands ({len(saved.init_commands)})", icon="terminal") \
                    .classes("w-full text-sm"):
                for cmd in saved.init_commands:
                    ui.label(cmd).classes("text-xs font-mono text-gray-600")

        status = ui.row().classes("items-center gap-2 min-h-8 mt-2")

        def working(text: str):
            status.clear()
            with status:
                ui.spinner(size="sm")
                ui.label(text)

        def result(ok: bool, text: str):
            status.clear()
            with status:
                ui.icon("check_circle" if ok else "error",
                        color="positive" if ok else "negative")
                ui.label(text).classes("text-positive" if ok else "text-negative")

        def notice(text: str):
            status.clear()
            with status:
                ui.icon("info", color="warning")
                ui.label(text)

        async def do_validate():
            validate_btn.disable()
            try:
                await _detach_if_attached(session, state)
                # For ssh, open the connection and STOP: the host may prompt for a
                # password / 2FA in the terminal, and running any command now would
                # lock input and be typed into that prompt. The user authenticates,
                # then clicks Validate again to run the checks (ssh_started gates it).
                if saved.target_kind == "ssh" and not state.get("ssh_started"):
                    session.start_ssh(saved.target_alias, ssh_interactive_opts(saved.target_alias))
                    state["ssh_started"] = True
                    state["connected"] = True
                    _status(CONNECTING)
                    notice("Authenticate in the terminal if prompted, then click Validate now.")
                    return
                # Restore the saved environment (modules, PATH) once per shell.
                if saved.init_commands and not state.get("init_ran"):
                    working("Running setup commands...")
                    await _run_setup_commands(session, saved.init_commands, note)
                    if not _alive(status):
                        return
                    state["init_ran"] = True
                working("Preparing workdir...")
                await _ensure_workdir(session, saved.workdir)
                if not _alive(status):
                    return
                working("Validating environment...")
                ok, detail = await _validate_setup(session, saved)
                msg = detail if ok else detail + " — fix it and re-validate, or delete this setup."
                state["validation"] = (ok, msg)
                if not _alive(status):
                    return
                result(ok, msg)
                if ok:
                    _status(CONNECTED)
                # Probe active runs now that we are connected (rebuilds the view).
                await on_refresh_runs()
            finally:
                if _alive(validate_btn):
                    validate_btn.enable()

        with ui.row().classes("gap-2 mt-3"):
            validate_btn = ui.button("Validate now", icon="verified", on_click=do_validate)
            ui.button("Back to setups", icon="arrow_back", on_click=on_back).props("flat")

        if validate:
            ui.timer(0.4, do_validate, once=True)
        else:
            prev = state.get("validation")
            if prev:
                result(prev[0], prev[1])
            else:
                result(True, f"Setup saved. IOPS {saved.iops_version or ''} ready.".rstrip())

    # ---- active runs (screens that may still be executing) ----------------- #
    active_runs = load_runs(saved.name)
    if active_runs:
        run_status = state.get("run_status", {})
        with ui.card().classes("studio-card w-full p-4 gap-2 mt-3"):
            with ui.row().classes("items-center justify-between w-full no-wrap"):
                ui.label("Active runs").classes("text-md font-semibold")
                ui.button(icon="refresh", on_click=on_refresh_runs) \
                    .props("flat round dense").tooltip("Refresh status")
            ui.label("Reattach hops to the run's login node if needed.") \
                .classes("text-xs text-gray-500")
            for run in active_runs:
                st = run_status.get(run.screen_name)
                with ui.card().classes("w-full p-2"):
                    with ui.row().classes("items-center justify-between w-full no-wrap"):
                        with ui.column().classes("gap-0"):
                            with ui.row().classes("items-center gap-2 no-wrap"):
                                ui.label(run.config_name).classes("font-medium")
                                _run_badge(st)
                            ui.label(f"screen {run.screen_name} · node {run.node}"
                                     + (f" · {run.started_at}" if run.started_at else "")) \
                                .classes("text-xs text-gray-500")
                        with ui.row().classes("items-center gap-1"):
                            ui.button(icon="cable", on_click=lambda r=run: on_reconnect_run(r)) \
                                .props("flat round dense").tooltip("Reattach")
                            ui.button(icon="stop_circle", on_click=lambda r=run: on_stop_run(r)) \
                                .props("flat round dense color=negative").tooltip("Kill run")
                            ui.button(icon="close", on_click=lambda r=run: on_dismiss_run(r)) \
                                .props("flat round dense").tooltip("Dismiss (stop tracking)")

    # ---- results (reports + pull) ------------------------------------------ #
    runs_list = state.get("runs_list")
    with ui.card().classes("studio-card w-full p-4 gap-2 mt-3"):
        with ui.row().classes("items-center justify-between w-full no-wrap"):
            ui.label("Results").classes("text-md font-semibold")
            ui.button("Browse runs", icon="folder_open", on_click=on_browse_runs) \
                .props("flat dense").tooltip("List completed runs in the workdir")
        ui.label("View a run's report in Studio, or pull its results (CSVs, "
                 "metadata, report) to the host.").classes("text-xs text-gray-500")
        if runs_list is None:
            ui.label("Click 'Browse runs' to list runs under the workdir.") \
                .classes("text-xs text-gray-400 italic")
        elif not runs_list:
            ui.label("No runs found under the workdir yet.") \
                .classes("text-xs text-gray-400 italic")
        else:
            for rd in runs_list:
                with ui.card().classes("w-full p-2"):
                    with ui.row().classes("items-center justify-between w-full no-wrap"):
                        with ui.column().classes("gap-0 min-w-0"):
                            ui.label(Path(rd).name).classes("font-medium")
                            ui.label(rd).classes("text-xs text-gray-500 truncate")
                        with ui.row().classes("items-center gap-1"):
                            ui.button(icon="assessment", on_click=lambda r=rd: on_view_report(r)) \
                                .props("flat round dense").tooltip("Generate & view report")
                            ui.button(icon="download", on_click=lambda r=rd: on_pull_results(r)) \
                                .props("flat round dense").tooltip("Pull results to the host")

    # ---- configs for this target ------------------------------------------- #
    with ui.card().classes("studio-card w-full p-4 gap-2 mt-3"):
        with ui.row().classes("items-center justify-between w-full no-wrap"):
            ui.label("Configs for this target").classes("text-md font-semibold")
            with ui.row().classes("items-center gap-1"):
                ui.button("Import", icon="file_upload", on_click=on_import_config) \
                    .props("flat dense").tooltip("Load a YAML file from the host as a new config")
                ui.button("New config", icon="add", on_click=on_new_config).props("flat dense")
        cfgs = load_configs(saved.name)
        if not cfgs:
            ui.label("No configs yet. Build one to run a benchmark.") \
                .classes("text-xs text-gray-400 italic")
        for sc in cfgs:
            with ui.card().classes("w-full p-2"):
                with ui.row().classes("items-center justify-between w-full no-wrap"):
                    with ui.column().classes("gap-0"):
                        ui.label(sc.name).classes("font-medium")
                        ui.label(config_workdir(sc.yaml_text) or "(workdir in YAML)") \
                            .classes("text-xs text-gray-500")
                    with ui.row().classes("items-center gap-1"):
                        ui.button(icon="play_arrow", on_click=lambda s=sc: on_run_config(s)) \
                            .props("flat round dense").tooltip("Run on target")
                        ui.button(icon="edit", on_click=lambda s=sc: on_edit_config(s)) \
                            .props("flat round dense").tooltip("Edit")
                        ui.button(icon="file_download", on_click=lambda s=sc: on_export_config(s)) \
                            .props("flat round dense").tooltip("Export to a file on the host")
                        ui.button(icon="delete", on_click=lambda s=sc: on_delete_config(s)) \
                            .props("flat round dense color=negative").tooltip("Delete")


def _page():
    ui.add_head_html(_STUDIO_HEAD)
    ui.query(".nicegui-content").classes("p-0 gap-0")

    host_options = {h.alias: h.label for h in parse_ssh_hosts()}

    # Every runtime is its own StudioSession (shell + state + terminal tab). The
    # registry is per browser tab so distinct clients never share PTYs.
    registry = SessionRegistry()
    active = {"key": None}                # key of the session whose tab is focused
    suppress_tab_event = {"on": False}    # gate our own programmatic tab switches

    # All shells start as a local bash before any ssh, so the local hostname is
    # the same for every session; probe it once (matching the shell's $(hostname)
    # so `_is_on_target` can tell "still local" from "on the cluster").
    try:
        page_local_host = subprocess.check_output(
            ["bash", "-lc", "hostname"], text=True, timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        page_local_host = ""

    # Header
    with ui.row().classes("items-center gap-3 px-4 py-2 w-full").style("background:#fff;border-bottom:1px solid #e0e0e0"):
        if _STUDIO_LOGO:
            ui.image(_STUDIO_LOGO).classes("w-8 h-8").style("border-radius:6px")
        ui.label("IOPS Studio").classes("text-2xl font-bold")
        ui.label(f"v{STUDIO_VERSION}").classes("text-sm text-gray-500 self-end")
        ui.label(f"core {load_version()}").classes("text-xs text-gray-400 self-end")

    # Two panes: left (wizard or ready view) + the terminal tab bar (right). Each
    # connected runtime gets its own tab + xterm; all stay mounted so their shells
    # and scrollback persist, and only the active one is made visible.
    main_splitter = ui.splitter(value=45).classes("w-full").style("height: calc(100vh - 3rem)")
    with main_splitter:
        with main_splitter.before:
            left = ui.column().classes("p-4 gap-4 w-full h-full").style("overflow:auto")
        with main_splitter.after:
            with ui.column().classes("w-full h-full gap-0").style("background:#1e1e1e"):
                term_tabs = ui.tabs().props("dense active-color=white indicator-color=cyan "
                                            "align=left inline-label").classes("w-full") \
                    .style("background:#2d2d2d;color:#cfcfcf;min-height:2rem")
                term_tabs.on_value_change(lambda e: _on_tab_change())
                terminals_stack = ui.column().classes("w-full gap-0") \
                    .style("flex:1; min-height:0")
                with terminals_stack:
                    empty_hint = ui.label("Select or add a setup to open a terminal.") \
                        .classes("text-grey text-sm p-4")

    # Full-width editor area, shown in place of the split view while building a
    # config so the form + YAML get the whole page side by side. It fills the
    # viewport height and scrolls as a fallback if the inner panes cannot.
    editor_area = ui.column().classes("w-full p-3") \
        .style("height: calc(100vh - 3rem); overflow:auto")
    editor_area.set_visibility(False)

    # Full-width report viewer, shown in place of the split view. A flex column so
    # the iframe fills the height under its header.
    results_area = ui.column().classes("w-full gap-0") \
        .style("height: calc(100vh - 3rem); min-height:0")
    results_area.set_visibility(False)

    # The PTY reader fires from a bare asyncio callback (no request context), so
    # route UI updates through the client context, the supported way to update
    # the UI from a background task.
    client = ui.context.client

    # ---- per-session state helpers ---------------------------------------- #
    def _clean_state() -> dict:
        return {"env": None, "envs": [], "target": {"kind": "local", "alias": None},
                "connected": False, "init_commands": [], "workdir": "~/iops_workdir",
                "local_host": page_local_host}

    def _reset_state(st: dict) -> None:
        # Keep init_commands (the user's module/PATH setup) so a disconnect does
        # not make them retype it; drop only per-shell-session flags.
        st.update(env=None, envs=[], target={"kind": "local", "alias": None}, connected=False)
        for k in ("ssh_started", "init_ran", "attached"):
            st.pop(k, None)

    def _state_from(cfg: SetupConfig) -> dict:
        st = _clean_state()
        st["target"] = {"kind": cfg.target_kind, "alias": cfg.target_alias}
        st["env"] = PyEnv(cfg.env_path, cfg.env_kind, cfg.env_version, cfg.iops_version)
        st["init_commands"] = list(cfg.init_commands)
        st["workdir"] = cfg.workdir
        return st

    # ---- session / tab plumbing ------------------------------------------- #
    def _set_status(sess: StudioSession, status: str) -> None:
        sess.status = status
        if sess.tab is not None:
            sess.tab.classes(replace=_STATUS_CLASS.get(status, "text-grey"))

    def _set_tab_label(sess: StudioSession, label: str) -> None:
        if sess.tab is not None:
            sess.tab._props["label"] = label
            sess.tab.update()

    def _make_on_output(sess: StudioSession):
        def _out(data: bytes):
            # Keep the "attached to a screen" flag accurate: screen prints these
            # when the session detaches or ends, whether we or the user triggered it.
            if b"[detached from" in data or b"[screen is terminating" in data:
                sess.state["attached"] = False
            with client:
                sess.xterm.write(data)
        return _out

    def _make_note(sess: StudioSession):
        # Called from request/`_guarded` contexts (ambient client), like the old
        # single-session note; writes a yellow shell comment into this terminal.
        def _note(msg: str):
            if sess.xterm is not None:
                sess.xterm.write(f"\r\n\x1b[33m# {msg}\x1b[0m\r\n")
        return _note

    def _update_empty_hint():
        empty_hint.set_visibility(not registry.all())

    def _attach_autofit(sess: StudioSession):
        """Keep this terminal sized to its container, for as long as it lives.

        NiceGUI's xterm resizes only on an explicit ``fit()``, and FitAddon's fit
        is a no-op while the element has no layout box. Terminals are created
        inside a hidden column, so a fit scheduled at creation lands before the
        column is laid out and the terminal stays stuck at xterm's default 80x24.
        A ResizeObserver instead fits it the moment it gets a real size, and again
        on every later size change (tab switch, splitter drag, window resize).

        The script is injected directly rather than from a ``ui.timer``: handlers
        run in the slot of the element that triggered them, so a timer created
        here would be a child of the left pane and ``show_ready`` would clear it
        away before it fired. The retry loop covers the element not being mounted
        client-side yet; the rAF hop coalesces bursts and avoids a fit/resize loop.
        """
        js = f"""
        (() => {{
          const attach = (tries) => {{
            const c = getElement({sess.xterm.id});
            if (!c || !c.$el) {{
              if (tries > 0) setTimeout(() => attach(tries - 1), 100);
              return;
            }}
            if (c.__iopsAutoFit) return;
            let pending = null;
            const doFit = () => {{
              pending = null;
              const el = c.$el;
              if (el && el.clientWidth > 0 && el.clientHeight > 0) {{
                try {{ c.fit(); }} catch (e) {{}}
              }}
            }};
            const obs = new ResizeObserver(() => {{
              if (pending) cancelAnimationFrame(pending);
              pending = requestAnimationFrame(doFit);
            }});
            obs.observe(c.$el);
            c.__iopsAutoFit = obs;
            doFit();
          }};
          attach(50);
        }})();
        """
        ui.run_javascript(js)

    def _create_session(cfg: Optional[SetupConfig], label: str) -> StudioSession:
        """Mint a runtime: shell + state + tab + terminal column, all wired up."""
        term = TerminalSession()
        st = _state_from(cfg) if cfg is not None else _clean_state()
        sess = StudioSession(key=uuid.uuid4().hex, term=term, state=st,
                             setup_name=(cfg.name if cfg is not None else None))
        logger.debug("create session '%s' (key=%s)", label, sess.key[:8])
        with term_tabs:
            sess.tab = ui.tab(name=sess.key, label=label, icon="circle") \
                .classes(_STATUS_CLASS[NEW]).props("no-caps")
        with terminals_stack:
            sess.column = ui.column().classes("w-full h-full gap-0 p-1")
            sess.column.set_visibility(False)  # focus() reveals the right one
            with sess.column:
                sess.drop_banner = ui.row().classes("w-full items-center gap-2 px-2 py-1 rounded") \
                    .style("background:#fdecea")
                sess.drop_banner.set_visibility(False)
                with sess.drop_banner:
                    ui.icon("link_off", color="negative")
                    ui.label("Terminal disconnected.").classes("text-negative text-sm")
                    ui.button("Reconnect", icon="restart_alt",
                              on_click=lambda s=sess: reconnect(s)).props("flat dense")
                sess.xterm = ui.xterm(options=_XTERM_OPTIONS).classes("w-full") \
                    .style("flex:1; min-height:0")
        sess.note = _make_note(sess)
        sess.xterm.on_data(lambda e, s=sess: s.term.write(e.data)
                           if not s.term.input_locked else None)
        sess.xterm.on_resize(lambda e, s=sess: s.term.resize(e.cols, e.rows))
        sess.term.start(on_output=_make_on_output(sess),
                        on_exit=lambda s=sess: _on_shell_exit(s))
        _attach_autofit(sess)
        registry.add(sess)
        _update_empty_hint()
        return sess

    def _on_tab_change():
        # User clicked a tab. Programmatic switches suppress this and drive focus()
        # directly (so they can pass validate=True for a first connect).
        if suppress_tab_event["on"]:
            return
        focus(term_tabs.value, validate=False)

    def focus(key: Optional[str], *, validate: bool) -> None:
        """Make ``key`` the active tab: show its terminal and sync the left pane."""
        active["key"] = key
        for s in registry.all():
            s.column.set_visibility(s.key == key)
        sess = registry.get(key)
        if sess is None:
            return
        if sess.setup_name is None:
            show_wizard(sess)
        else:
            cfg = get_setup(sess.setup_name)
            if cfg is None:
                show_setups()
            else:
                show_ready(cfg, validate=validate)

    def _focus_programmatic(key: str, *, validate: bool) -> None:
        # Update the tab-bar highlight without re-triggering our click handler.
        suppress_tab_event["on"] = True
        term_tabs.value = key
        suppress_tab_event["on"] = False
        focus(key, validate=validate)

    def _close_session(sess: StudioSession) -> None:
        # Tear down the shell (removes its event-loop reader) before its elements.
        # Screen-wrapped runs on the target survive: their RunRecords are kept.
        sess.term.close()
        for el in (sess.tab, sess.column):
            try:
                el.delete()
            except Exception:
                pass
        registry.remove(sess.key)
        _update_empty_hint()

    def close_tab(sess: StudioSession) -> None:
        logger.debug("close_tab: %s", sess.setup_name or "(wizard)")
        was_active = active["key"] == sess.key
        _close_session(sess)
        if not was_active:
            return
        remaining = registry.all()
        if remaining:
            _focus_programmatic(remaining[-1].key, validate=False)
        else:
            active["key"] = None
            show_setups()

    def show_setups():
        """Hub view: the saved setups (or an empty-state prompt)."""
        left.clear()
        setups = load_setups()
        with left:
            if not setups:
                ui.label("No setups yet.").classes("text-lg font-semibold")
                ui.label("Add a target to validate and use.").classes("text-gray-600 text-sm")
                ui.button("Add setup", icon="add", on_click=add_setup).classes("mt-2")
            else:
                _build_setup_list(setups, on_select=select_setup, on_add=add_setup,
                                  on_delete=remove_setup,
                                  on_edit=lambda c: _guarded(edit_setup(c)))

    async def _guarded(coro):
        # Run an async handler within the page's client context so its UI calls
        # (ui.notify, view rebuilds) still work even if the element that triggered
        # it was deleted meanwhile (e.g. the view was rebuilt).
        with client:
            await coro

    def show_ready(cfg: SetupConfig, *, validate: bool):
        sess = registry.by_setup(cfg.name)
        if sess is None:
            show_setups()
            return
        # A background handler may finish after the user switched tabs; don't let
        # it repaint the left pane for a runtime that is no longer focused.
        if active["key"] != sess.key:
            return
        left.clear()
        with left:
            _build_ready(
                sess.term, sess.state, cfg, sess.note, on_back=show_setups, validate=validate,
                on_close=lambda s=sess: close_tab(s),
                on_status=lambda st, s=sess: _set_status(s, st),
                on_new_config=lambda: show_editor(cfg, None),
                on_edit_config=lambda sc: show_editor(cfg, sc),
                on_run_config=lambda sc: _guarded(run_config(cfg, sc.name, sc.yaml_text)),
                on_delete_config=lambda sc: remove_config(cfg, sc),
                on_import_config=lambda: _guarded(import_config(cfg)),
                on_export_config=lambda sc: _guarded(
                    _export_yaml(f"{_slug(sc.name)}.yaml", sc.yaml_text)),
                on_reconnect_run=lambda r: _guarded(reconnect_run(cfg, r)),
                on_stop_run=lambda r: _guarded(stop_run(cfg, r)),
                on_dismiss_run=lambda r: dismiss_run(cfg, r),
                on_refresh_runs=lambda: _guarded(refresh_runs(cfg)),
                on_browse_runs=lambda: _guarded(browse_runs(cfg)),
                on_view_report=lambda rd: _guarded(view_report(cfg, rd)),
                on_pull_results=lambda rd: _guarded(pull_results(cfg, rd)),
            )

    def _exit_editor():
        editor_area.clear()
        editor_area.set_visibility(False)
        main_splitter.set_visibility(True)
        # The active xterm was hidden while the editor overlay was up; re-fit it
        # now that it is visible again (a hidden xterm sizes to zero cols/rows).

    def _default_config_name(setup_cfg: SetupConfig) -> str:
        """A unique default name for a new config (benchmark, benchmark_2, ...)."""
        existing = {c.name for c in load_configs(setup_cfg.name)}
        base, name, i = "benchmark", "benchmark", 2
        while name in existing:
            name, i = f"{base}_{i}", i + 1
        return name

    def show_editor(setup_cfg: SetupConfig, studio_cfg):
        """Open the full-width config builder for a new or existing config."""
        is_new = studio_cfg is None
        initial = (studio_cfg.yaml_text if not is_new
                   else starter_yaml("My benchmark", setup_cfg.workdir,
                                     "local" if setup_cfg.target_kind == "local" else "slurm"))
        cfg_name = _default_config_name(setup_cfg) if is_new else studio_cfg.name

        def save(name: str, yaml_text: str):
            name = (name or "").strip()
            if not name:
                ui.notify("Give the config a name", type="warning")
                return
            upsert_config(StudioConfig(name, setup_cfg.name, yaml_text))
            ui.notify(f"Saved config '{name}'", type="positive")
            _exit_editor()
            show_ready(setup_cfg, validate=False)

        def cancel():
            _exit_editor()
            show_ready(setup_cfg, validate=False)

        async def run_from_editor(name: str, yaml_text: str):
            # Save, leave the full-width editor (so the terminal is visible), then
            # run so the user lands directly on the live run in the terminal.
            name = (name or "").strip()
            if not name:
                ui.notify("Give the config a name", type="warning")
                return
            upsert_config(StudioConfig(name, setup_cfg.name, yaml_text))
            _exit_editor()
            # _exit_editor deleted the button this handler runs under, so re-enter
            # the page's client context before touching the UI again.
            with client:
                show_ready(setup_cfg, validate=False)
                await run_config(setup_cfg, name, yaml_text)

        main_splitter.set_visibility(False)
        editor_area.clear()
        editor_area.set_visibility(True)
        with editor_area:
            build_editor(
                cfg_name, initial,
                on_save=save,
                on_cancel=cancel,
                on_run=run_from_editor,
                on_check=lambda name, text: check_config(setup_cfg, name, text),
                on_export=lambda name, text: _export_yaml(
                    f"{_slug(name) or 'config'}.yaml", text),
            )

    async def _is_on_target(sess: StudioSession, setup_cfg: SetupConfig) -> bool:
        """Whether the shell is actually on the target (not fallen back to local).

        Probes the live hostname rather than trusting ``state['connected']``,
        which goes stale when the user exits ssh manually.
        """
        if setup_cfg.target_kind == "local":
            return True
        cur = await _remote_value(sess.term, "$(hostname)", "NODE")
        return bool(cur) and cur != sess.state.get("local_host")

    async def _ask_run_options() -> Optional[str]:
        """Pick `iops run` flags in a dialog. Returns a leading flags string
        (e.g. " --use-cache"), "" for a plain run, or None if cancelled."""
        picks = {"--use-cache": False, "--cache-only": False,
                 "--dry-run": False, "--fail-fast": False}
        labels = {
            "--use-cache": "Use cache: skip tests already cached (--use-cache)",
            "--cache-only": "Cache only: read cached results, run nothing new (--cache-only)",
            "--dry-run": "Dry run: preview the plan, execute nothing (--dry-run)",
            "--fail-fast": "Fail fast: stop at the first failed test (--fail-fast)",
        }
        with ui.dialog() as dialog, ui.card().classes("gap-2").style("width:500px;max-width:92vw"):
            ui.label("Run options").classes("text-lg font-semibold")
            ui.label("Choose flags for this run.").classes("text-xs text-gray-500")
            for flag, label in labels.items():
                ui.checkbox(label, value=False,
                            on_change=lambda e, f=flag: picks.__setitem__(f, e.value))
            with ui.row().classes("justify-end gap-2 w-full items-center"):
                ui.space()
                ui.button("Cancel", on_click=lambda: dialog.submit("cancel")).props("flat")
                ui.button("Run", icon="play_arrow",
                          on_click=lambda: dialog.submit("run")).props("unelevated")
        if await dialog != "run":
            return None
        return "".join(f" {f}" for f, on in picks.items() if on)

    async def run_config(setup_cfg: SetupConfig, name: str, yaml_text: str):
        sess = registry.by_setup(setup_cfg.name)
        if sess is None:
            ui.notify("No terminal for this setup", type="warning")
            return
        flags = await _ask_run_options()
        if flags is None:
            return
        logger.info("run_config: '%s' on %s (flags:%s)", name, setup_cfg.name, flags or " none")
        await _detach_if_attached(sess.term, sess.state)  # run in the login shell
        if not await _is_on_target(sess, setup_cfg):
            ui.notify("Not connected to the target. Reattach a run, or go back and "
                      "re-select the setup to connect.", type="warning")
            return
        await _ensure_workdir(sess.term, setup_cfg.workdir)
        remote = await _write_config_to_target(sess.term, sess.note, setup_cfg.workdir,
                                               name, yaml_text)
        if not remote:
            ui.notify("Could not write config to target", type="negative")
            return

        has_screen = (await _remote_value(
            sess.term, "$(command -v screen >/dev/null && echo yes || echo no)",
            "SCREEN")) == "yes"
        if not has_screen:
            sess.note("screen not found in this environment; in case of interruption "
                      "IOPS will be cancelled")
            sess.term.write(f'cd "{_shell_workdir(setup_cfg.workdir)}" && '
                            f'"{setup_cfg.env_path}" -m iops run "{remote}"{flags}\n')
            ui.notify("Running in the terminal (no screen — not resilient)", type="warning")
            return

        # Screen-wrapped, resilient run. Record the node so we can hop back.
        node = await _remote_value(sess.term, "$(hostname)", "NODE") or "?"
        session_name = f"iops_{_slug(name)}_{uuid.uuid4().hex[:6]}"
        runner = _runner_script(setup_cfg, remote, session_name, flags)
        rb64 = base64.b64encode(runner.encode()).decode()
        runner_path = f"{_shell_workdir(setup_cfg.workdir)}/.iops-studio/{session_name}.sh"
        start = (
            f'mkdir -p "{_shell_workdir(setup_cfg.workdir)}/.iops-studio" && '
            f"printf %s '{rb64}' | base64 -d > \"{runner_path}\" && "
            f'screen -dmS {session_name} bash "{runner_path}" && echo __STARTED__'
        )
        code, out = await sess.term.run(start, display=f"start screen {session_name}", timeout=60)
        if code != 0 or "__STARTED__" not in out:
            ui.notify("Could not start the screen session (see terminal)", type="negative")
            return
        logger.info("run_config -> started screen %s on node %s", session_name, node)
        add_run(RunRecord(setup_name=setup_cfg.name, config_name=name,
                          screen_name=session_name, node=node,
                          started_at=datetime.now().strftime("%Y-%m-%d %H:%M")))
        sess.state.setdefault("run_status", {})[session_name] = "running"
        sess.note(f"running '{name}' in screen {session_name} on {node}")
        sess.state["attached"] = True
        sess.term.write(f"screen -r {session_name}\n")  # attach live
        ui.notify(f"Running in screen on {node}. Detach with Ctrl-A D; "
                  "reattach from the setup if the connection drops.", type="info")
        _refresh_ready(setup_cfg)

    async def check_config(setup_cfg: SetupConfig, name: str, yaml_text: str):
        sess = registry.by_setup(setup_cfg.name)
        if sess is None:
            ui.notify("No terminal for this setup", type="warning")
            return
        await _detach_if_attached(sess.term, sess.state)
        remote = await _write_config_to_target(sess.term, sess.note, setup_cfg.workdir,
                                               name, yaml_text)
        if not remote:
            ui.notify("Could not write config to target", type="negative")
            return
        code, _ = await sess.term.run(f'"{setup_cfg.env_path}" -m iops check "{remote}"',
                                      display=f"iops check {name}", timeout=120)
        ui.notify("Config valid on target" if code == 0
                  else "Config invalid on target (see terminal)",
                  type="positive" if code == 0 else "negative")

    async def reconnect_run(setup_cfg: SetupConfig, run: RunRecord):
        """Reattach to a run's screen.

        The run's node is reachable from inside the cluster; the alias only from
        the local machine, so ``_node_command`` figures out how to get there. We
        detach from any current screen first so the reattach command runs in the
        login shell rather than being typed into the screen we are watching.
        """
        sess = registry.by_setup(setup_cfg.name)
        if sess is None:
            ui.notify("No terminal for this setup", type="warning")
            return
        await _detach_if_attached(sess.term, sess.state)
        sess.note(f"reattaching to {run.screen_name} on {run.node}")
        cmd = _node_command(setup_cfg, run.node, f"screen -d -r {run.screen_name}", tty=True)
        sess.state["attached"] = True
        sess.term.write(cmd + "\n")
        ui.notify(f"Reattaching to {run.screen_name} on {run.node} "
                  "(authenticate if prompted)", type="info")

    def dismiss_run(setup_cfg: SetupConfig, run: RunRecord):
        remove_run(setup_cfg.name, run.screen_name)
        ui.notify(f"Dismissed run '{run.config_name}'", type="info")
        _refresh_ready(setup_cfg)

    async def stop_run(setup_cfg: SetupConfig, run: RunRecord):
        """Confirm, then kill the run's screen (terminating IOPS on the target)."""
        sess = registry.by_setup(setup_cfg.name)
        if sess is None:
            ui.notify("No terminal for this setup", type="warning")
            return
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Kill run '{run.config_name}'?").classes("font-medium")
            ui.label(f"Terminates screen {run.screen_name} on {run.node} and the "
                     "IOPS process it is running.").classes("text-xs text-negative")
            with ui.row().classes("gap-2 justify-end w-full"):
                ui.button("Cancel", on_click=lambda: dialog.submit("no")).props("flat")
                ui.button("Kill run", color="negative", on_click=lambda: dialog.submit("yes"))
        if await dialog != "yes":
            return
        await _detach_if_attached(sess.term, sess.state)
        sess.note(f"killing {run.screen_name} on {run.node}")
        cmd = _node_command(setup_cfg, run.node, f"screen -S {run.screen_name} -X quit")
        sess.term.write(cmd + "\n")
        remove_run(setup_cfg.name, run.screen_name)
        ui.notify(f"Killing {run.screen_name} on {run.node}", type="warning")
        _refresh_ready(setup_cfg)

    async def refresh_runs(setup_cfg: SetupConfig):
        """Recompute each run's status from two signals.

        1. Completion marker ``<workdir>/.iops-studio/<screen>.exit`` written by
           the runner when IOPS finishes. It lives on the shared filesystem, so it
           is readable from any login node (the screen itself stays alive for
           review, so screen presence alone is not enough).
        2. Whether the screen is still alive on the *current* node. This catches
           runs that finished/were killed before the marker existed.

        Run this only at a shell prompt (not while attached to a screen), e.g. via
        the Refresh button after detaching.
        """
        sess = registry.by_setup(setup_cfg.name)
        if sess is None:
            return
        runs = load_runs(setup_cfg.name)
        if not runs:
            return
        await _detach_if_attached(sess.term, sess.state)  # so checks run in the login shell
        if not await _is_on_target(sess, setup_cfg):
            ui.notify("Reconnect to the target (Reattach, or re-select the setup) "
                      "to refresh run status", type="warning")
            return
        node = await _remote_value(sess.term, "$(hostname)", "NODE")
        screens = await _screen_sessions(sess.term)
        d = f"{_shell_workdir(setup_cfg.workdir)}/.iops-studio"
        checks = "\n".join(
            f'[ -f "{d}/{r.screen_name}.exit" ] && echo "DONE={r.screen_name}"'
            for r in runs
        )
        _, out = await sess.term.run(checks, display="check run status", timeout=30)
        done = {ln[len("DONE="):].strip() for ln in out.splitlines()
                if ln.strip().startswith("DONE=")}
        status = {}
        for r in runs:
            if r.screen_name in done:
                status[r.screen_name] = "finished"
            elif r.node == node and r.screen_name not in screens:
                status[r.screen_name] = "finished"  # screen gone on this node
            else:
                status[r.screen_name] = "running"
        sess.state["run_status"] = status
        _refresh_ready(setup_cfg)

    def _refresh_ready(setup_cfg: SetupConfig):
        show_ready(setup_cfg, validate=False)

    def remove_config(setup_cfg: SetupConfig, sc):
        delete_config(setup_cfg.name, sc.name)
        ui.notify(f"Deleted config '{sc.name}'", type="info")
        show_ready(setup_cfg, validate=False)

    async def import_config(setup_cfg: SetupConfig):
        """Import a host YAML as a new config (a copy), then open it for editing.

        The source file is only read: the copy is stored in Studio's config
        library, so edits never touch the original on disk.
        """
        path = await open_yaml()
        if not path:
            return
        try:
            text = Path(path).read_text()
        except (OSError, UnicodeDecodeError) as e:
            ui.notify(f"Could not read file: {e}", type="negative")
            return
        base = Path(path).stem or "imported"
        existing = {c.name for c in load_configs(setup_cfg.name)}
        name, i = base, 2
        while name in existing:
            name, i = f"{base} ({i})", i + 1
        upsert_config(StudioConfig(name, setup_cfg.name, text))
        ui.notify(f"Imported '{Path(path).name}' as config '{name}'", type="positive")
        show_editor(setup_cfg, get_config(setup_cfg.name, name))

    async def _export_yaml(default_name: str, text: str):
        """Write ``text`` to a host path chosen in the save dialog."""
        dest = await save_yaml(default_name=default_name)
        if not dest:
            return
        try:
            p = Path(dest)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        except OSError as e:
            ui.notify(f"Could not write file: {e}", type="negative")
            return
        ui.notify(f"Exported to {dest}", type="positive")

    # ---- results: browse runs, view report, pull results ------------------- #
    def _exit_report_viewer():
        results_area.clear()
        results_area.set_visibility(False)
        main_splitter.set_visibility(True)

    def show_report_viewer(setup_cfg: SetupConfig, run_dir: str, url: str):
        main_splitter.set_visibility(False)
        editor_area.set_visibility(False)
        results_area.clear()
        results_area.set_visibility(True)
        with results_area:
            with ui.row().classes("items-center gap-2 w-full no-wrap px-2 py-1") \
                    .style("border-bottom:1px solid #e0e0e0"):
                ui.button(icon="arrow_back", on_click=_exit_report_viewer) \
                    .props("flat round dense").tooltip("Back")
                ui.label(f"{setup_cfg.name} · {Path(run_dir).name}") \
                    .classes("text-md font-semibold truncate")
                ui.space()
                ui.button("Edit report config", icon="edit",
                          on_click=lambda: _guarded(edit_report_config(setup_cfg, run_dir))) \
                    .props("flat dense").tooltip("Edit the report YAML and regenerate")
                ui.button("Open in new tab", icon="open_in_new",
                          on_click=lambda: ui.navigate.to(url, new_tab=True)).props("flat dense")
            ui.element("iframe").props(f'src="{url}"').classes("w-full") \
                .style("flex:1; min-height:0; border:0; background:white")

    def _show_report_config_editor(setup_cfg: SetupConfig, run_dir: str, initial: str):
        """Full-width YAML editor for a run's report_config.yaml."""
        main_splitter.set_visibility(False)
        editor_area.set_visibility(False)
        results_area.clear()
        results_area.set_visibility(True)
        with results_area:
            with ui.row().classes("items-center gap-2 w-full no-wrap px-2 py-1") \
                    .style("border-bottom:1px solid #e0e0e0"):
                ui.button(icon="arrow_back",
                          on_click=lambda: _guarded(view_report(setup_cfg, run_dir))) \
                    .props("flat round dense").tooltip("Back to report (discard edits)")
                ui.label(f"Report config · {Path(run_dir).name}") \
                    .classes("text-md font-semibold truncate")
                ui.space()
                ui.button("Save & regenerate", icon="autorenew",
                          on_click=lambda: _guarded(_save_report_config(setup_cfg, run_dir, cm.value))) \
                    .props("unelevated")
            cm = ui.codemirror(value=initial, language="YAML").classes("w-full") \
                .style("flex:1; min-height:0; overflow:auto; border:1px solid #e0e0e0; "
                       "border-radius:6px; margin:6px")

    async def edit_report_config(setup_cfg: SetupConfig, run_dir: str):
        sess = registry.by_setup(setup_cfg.name)
        if sess is None:
            ui.notify("No terminal for this setup", type="warning")
            return
        logger.debug("edit_report_config: %s", run_dir)
        await _detach_if_attached(sess.term, sess.state)
        if not await _is_on_target(sess, setup_cfg):
            ui.notify("Not connected to the target. Reattach a run, or re-select the "
                      "setup to connect.", type="warning")
            return
        raw = await _fetch_remote(sess, setup_cfg.target_kind,
                                  report_config_path(run_dir), timeout=60)
        text = raw.decode("utf-8", "replace") if raw else DEFAULT_REPORT_CONFIG
        _show_report_config_editor(setup_cfg, run_dir, text)

    async def _write_text_to_target(sess: StudioSession, target_kind: str,
                                    remote_path: str, text: str) -> bool:
        """Write ``text`` to ``remote_path``: to disk for local, base64 for ssh."""
        if target_kind == "local":
            try:
                Path(remote_path).write_text(text)
                return True
            except OSError:
                return False
        b64 = base64.b64encode(text.encode()).decode()
        cmd = f'printf %s \'{b64}\' | base64 -d > "{remote_path}" && echo __WROTE__'
        code, out = await sess.term.run(cmd, display=f"write {Path(remote_path).name}", timeout=60)
        return code == 0 and "__WROTE__" in out

    async def _save_report_config(setup_cfg: SetupConfig, run_dir: str, text: str):
        sess = registry.by_setup(setup_cfg.name)
        if sess is None:
            ui.notify("No terminal for this setup", type="warning")
            return
        await _detach_if_attached(sess.term, sess.state)
        if not await _write_text_to_target(sess, setup_cfg.target_kind,
                                           report_config_path(run_dir), text):
            ui.notify("Could not write the report config to the target", type="negative")
            return
        ui.notify("Saved report config; regenerating the report...", type="info")
        await _generate_and_show(setup_cfg, run_dir)

    async def _generate_and_show(setup_cfg: SetupConfig, run_dir: str):
        """Run `iops report` on the target (auto-detecting report_config.yaml), then
        pull the HTML back and show it in the viewer."""
        sess = registry.by_setup(setup_cfg.name)
        if sess is None:
            ui.notify("No terminal for this setup", type="warning")
            return
        await _detach_if_attached(sess.term, sess.state)
        if not await _is_on_target(sess, setup_cfg):
            ui.notify("Not connected to the target. Reattach a run, or re-select the "
                      "setup to connect.", type="warning")
            return
        ui.notify("Generating the report on the target...", type="info")
        await sess.term.run(f'"{setup_cfg.env_path}" -m iops report "{run_dir}"',
                            display=f"iops report {Path(run_dir).name}", timeout=300)
        # iops report exits 0 even on failure; the real signal is the HTML's presence.
        html = await _fetch_remote(sess, setup_cfg.target_kind,
                                   report_html_path(run_dir), timeout=300)
        if not html:
            ui.notify("No report was produced (see the terminal).", type="negative")
            return
        logger.debug("report is %d bytes", len(html))
        html = localize_report_html(html, _PLOTLY_ASSET_URL)  # offline-render charts
        rel = f"{_result_slug(setup_cfg.name)}/{_result_slug(Path(run_dir).name)}"
        dest_dir = _results_root() / rel
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / REPORT_FILENAME).write_bytes(html)
        except OSError as e:
            ui.notify(f"Could not cache the report: {e}", type="negative")
            return
        url = f"{_RESULTS_URL}/{rel}/{REPORT_FILENAME}?v={uuid.uuid4().hex[:8]}"
        show_report_viewer(setup_cfg, run_dir, url)

    async def browse_runs(setup_cfg: SetupConfig):
        sess = registry.by_setup(setup_cfg.name)
        if sess is None:
            ui.notify("No terminal for this setup", type="warning")
            return
        logger.debug("browse_runs: %s under %s", setup_cfg.name, setup_cfg.workdir)
        await _detach_if_attached(sess.term, sess.state)
        if not await _is_on_target(sess, setup_cfg):
            ui.notify("Not connected to the target. Reattach a run, or re-select the "
                      "setup to connect.", type="warning")
            return
        _, out = await sess.term.run(list_runs_command(_shell_workdir(setup_cfg.workdir)),
                                     display="list runs", timeout=60)
        runs = parse_run_list(out)
        logger.debug("browse_runs -> %d run(s) found", len(runs))
        sess.state["runs_list"] = runs
        _refresh_ready(setup_cfg)

    async def _fetch_remote(sess: StudioSession, target_kind: str, remote_path: str,
                            timeout: float) -> Optional[bytes]:
        """Read a remote artifact's bytes: off disk for local, pull_file for ssh."""
        if target_kind == "local":
            try:
                return Path(remote_path).read_bytes()
            except OSError:
                return None
        return await sess.term.pull_file(remote_path, timeout=timeout)

    async def view_report(setup_cfg: SetupConfig, run_dir: str):
        logger.debug("view_report: %s", run_dir)
        await _generate_and_show(setup_cfg, run_dir)

    async def pull_results(setup_cfg: SetupConfig, run_dir: str):
        sess = registry.by_setup(setup_cfg.name)
        if sess is None:
            ui.notify("No terminal for this setup", type="warning")
            return
        dest_parent = await choose_dir(
            title=f"Choose where to save results for {Path(run_dir).name}")
        if not dest_parent:
            return
        logger.debug("pull_results: %s -> %s", run_dir, dest_parent)
        await _detach_if_attached(sess.term, sess.state)
        if not await _is_on_target(sess, setup_cfg):
            ui.notify("Not connected to the target. Reattach a run, or re-select the "
                      "setup to connect.", type="warning")
            return
        # Build a small, name-filtered tar on the target (never the raw scratch data).
        tmp_remote = (f'{_shell_workdir(setup_cfg.workdir)}/.iops-studio/'
                      f'results_{uuid.uuid4().hex[:8]}.tar.gz')
        await sess.term.run(f'mkdir -p "{_shell_workdir(setup_cfg.workdir)}/.iops-studio"',
                            display="prepare results bundle", timeout=30)
        code, _ = await sess.term.run(light_tar_command(run_dir, tmp_remote),
                                      display=f"bundle results {Path(run_dir).name}", timeout=180)
        if code != 0:
            ui.notify("Could not bundle results on the target (see terminal)", type="negative")
            return
        ui.notify("Transferring results to the host...", type="info")
        tar_bytes = await _fetch_remote(sess, setup_cfg.target_kind, tmp_remote, timeout=600)
        await sess.term.run(f'rm -f "{tmp_remote}"', display="clean up bundle", timeout=30)
        if not tar_bytes:
            ui.notify("Could not transfer the results bundle", type="negative")
            return
        dest = Path(dest_parent) / _result_slug(f"{setup_cfg.name}_{Path(run_dir).name}")
        try:
            dest.mkdir(parents=True, exist_ok=True)
            with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tf:
                tf.extractall(dest, filter="data")  # path-traversal-safe (PEP 706)
        except (OSError, tarfile.TarError) as e:
            ui.notify(f"Could not extract results: {e}", type="negative")
            return
        ui.notify(f"Results saved to {dest}", type="positive")

    def show_wizard(sess: StudioSession):
        # Only paint the left pane if this wizard's tab is the focused one.
        if active["key"] != sess.key:
            return
        left.clear()
        with left:
            _build_wizard(sess.term, sess.state, host_options, sess.note,
                          on_complete=lambda: complete(sess),
                          on_cancel=lambda: close_tab(sess),
                          on_status=lambda st: _set_status(sess, st))

    def complete(sess: StudioSession):
        """Persist the finished setup, bind this session to it, show its ready view."""
        st = sess.state
        env = st["env"]
        name = st.get("setup_name") or _suggest_name(st["target"], env)
        cfg = SetupConfig(
            name=name,
            target_kind=st["target"]["kind"],
            target_alias=st["target"]["alias"],
            env_path=env.path,
            env_kind=env.kind,
            env_version=env.version,
            iops_version=env.iops_version,
            init_commands=list(st.get("init_commands") or []),
            workdir=st.get("workdir") or "~/iops_workdir",
        )
        logger.info("complete: saved setup '%s' (%s, IOPS %s)",
                    name, cfg.where, cfg.iops_version or "unknown")
        upsert_setup(cfg)
        # If another live terminal was already bound to this name (reusing a name
        # overwrites that setup), close it so there is one tab per setup.
        other = registry.by_setup(name)
        if other is not None and other.key != sess.key:
            _close_session(other)
        sess.setup_name = name
        _set_tab_label(sess, name)
        _set_status(sess, CONNECTED)
        active["key"] = sess.key
        # The shell is already connected and set up for this target; do not
        # revalidate (which would restart/reconnect it).
        show_ready(cfg, validate=False)

    def add_setup():
        """Open a fresh terminal and run the setup wizard in it."""
        logger.debug("add_setup: starting the wizard on a new terminal")
        sess = _create_session(None, label="New setup")
        _focus_programmatic(sess.key, validate=False)  # setup_name None -> shows wizard

    def select_setup(cfg: SetupConfig):
        """Open a saved setup: focus its live terminal, or create + connect one.

        A live terminal is reused (never restarted); a first open creates the
        session and validates once. A dropped terminal is only focused, so the
        user reconnects deliberately.
        """
        logger.debug("select_setup: %s (%s)", cfg.name, cfg.where)
        existing = registry.by_setup(cfg.name)
        if existing is not None:
            if active["key"] == existing.key:
                show_ready(cfg, validate=False)
            else:
                _focus_programmatic(existing.key, validate=False)
            return
        sess = _create_session(cfg, label=cfg.name)
        _focus_programmatic(sess.key, validate=True)  # first connect

    def remove_setup(cfg: SetupConfig):
        sess = registry.by_setup(cfg.name)
        if sess is not None:
            close_tab(sess)  # tear down its terminal; leaves any remote runs alone
        delete_setup(cfg.name)
        ui.notify(f"Deleted setup '{cfg.name}'", type="info")
        show_setups()

    async def edit_setup(cfg: SetupConfig):
        """Edit a saved setup's mutable fields via a dialog.

        Editable: name, interpreter path, workdir, setup commands. The target
        (local vs which ssh host) is fixed — changing it is really a new setup.
        Changing the interpreter clears the cached versions so the next
        validation re-probes. Any live terminal for this setup is closed, since
        its cached state (workdir, env, run status) would no longer match.
        Renaming migrates this setup's saved configs and tracked runs.
        """
        with ui.dialog() as dialog, ui.card().classes("gap-2").style("width:560px;max-width:92vw"):
            ui.label("Edit setup").classes("text-lg font-semibold")
            ui.label(cfg.where).classes("text-xs text-gray-500")
            name_in = ui.input("Name", value=cfg.name).classes("w-full")
            env_in = ui.input("Python interpreter path", value=cfg.env_path).classes("w-full")
            env_in.tooltip("The python that runs IOPS on the target. Changing it clears "
                           "the saved version; use 'Validate now' afterwards to refresh.")
            wd_in = ui.input("Workdir (folder to run IOPS from)", value=cfg.workdir).classes("w-full")
            cmds_in = ui.textarea("Setup commands (one per line)",
                                  value="\n".join(cfg.init_commands)) \
                .classes("w-full").props("autogrow")
            cmds_in.tooltip("Run in the shell after connecting (module load, export PATH, ...).")
            with ui.row().classes("justify-end gap-2 w-full items-center"):
                ui.space()
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
                ui.button("Save", icon="save", on_click=lambda: dialog.submit("save")) \
                    .props("unelevated")

        if await dialog != "save":
            return
        new_name = (name_in.value or "").strip()
        if not new_name:
            ui.notify("Give the setup a name", type="warning")
            return
        if new_name != cfg.name and get_setup(new_name) is not None:
            ui.notify(f"A setup named '{new_name}' already exists", type="negative")
            return
        new_env = (env_in.value or "").strip() or cfg.env_path
        env_changed = new_env != cfg.env_path
        updated = SetupConfig(
            name=new_name,
            target_kind=cfg.target_kind,
            target_alias=cfg.target_alias,
            env_path=new_env,
            env_kind=cfg.env_kind,
            env_version=None if env_changed else cfg.env_version,
            iops_version=None if env_changed else cfg.iops_version,
            workdir=(wd_in.value or "").strip() or "~/iops_workdir",
            init_commands=_parse_commands(cmds_in.value),
        )
        # A live terminal for this setup now holds stale state; close it.
        live = registry.by_setup(cfg.name)
        if live is not None:
            close_tab(live)
        if new_name != cfg.name:
            rename_setup_configs(cfg.name, new_name)
            rename_setup_runs(cfg.name, new_name)
            delete_setup(cfg.name)
        upsert_setup(updated)
        logger.info("edit_setup: '%s' -> '%s' (workdir=%s, env=%s)",
                    cfg.name, new_name, updated.workdir, updated.env_path)
        ui.notify(f"Saved setup '{new_name}'", type="positive")
        show_setups()

    def _on_shell_exit(sess: StudioSession):
        """A session's shell died (exit / ssh dropped / killed).

        Fired from the reader callback with no request context, so wrap UI work
        in the client context. Only this session is affected; other terminals
        keep running. The user reconnects deliberately from the drop banner.
        """
        logger.info("shell exited for %s -> marking dropped", sess.setup_name or "(wizard)")
        with client:
            _reset_state(sess.state)
            _set_status(sess, DROPPED)
            if sess.drop_banner is not None:
                sess.drop_banner.set_visibility(True)

    def reconnect(sess: StudioSession):
        """Drop-banner action: spawn a clean shell and re-run this session's flow."""
        logger.debug("reconnect: %s", sess.setup_name or "(wizard)")
        if sess.drop_banner is not None:
            sess.drop_banner.set_visibility(False)
        _reset_state(sess.state)
        sess.term.restart()  # reuses the same on_output/on_exit, so the xterm stays wired
        _set_status(sess, CONNECTING)
        if sess.setup_name:
            cfg = get_setup(sess.setup_name)
            if cfg is not None:
                show_ready(cfg, validate=True)
        else:
            show_wizard(sess)

    # Tear down every shell when the browser tab closes (snapshot the list first).
    client.on_disconnect(lambda: [s.term.close() for s in registry.all()])

    # Land on the setups hub, or straight into the wizard for first-time onboarding.
    if load_setups():
        show_setups()
    else:
        add_setup()


# Where pulled reports are cached and served from, and the URL they mount under.
_RESULTS_URL = "/studio-results"
_PLOTLY_ASSET_URL = f"{_RESULTS_URL}/_assets/plotly.min.js"


def _results_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "iops-studio" / "results"


def _ensure_results_assets() -> Path:
    """Create the results cache and drop in a local Plotly so reports render offline."""
    root = _results_root()
    (root / "_assets").mkdir(parents=True, exist_ok=True)
    bundle = plotly_bundle_path()
    if bundle is not None:
        dest = root / "_assets" / "plotly.min.js"
        try:
            if not dest.exists() or dest.stat().st_size != bundle.stat().st_size:
                shutil.copyfile(bundle, dest)
        except OSError:
            pass
    return root


def build_app():
    """Register Studio's NiceGUI pages. Call before ``ui.run``."""

    # Serve pulled reports (and the bundled Plotly) so the viewer iframe can load
    # them same-origin.
    root = _ensure_results_assets()
    app.add_static_files(_RESULTS_URL, str(root))

    @ui.page("/")
    async def index():
        await ui.context.client.connected()
        _page()
