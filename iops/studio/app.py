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
import re
import shlex
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from nicegui import ui

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
    upsert_config,
)
from iops.studio.filebrowser import open_yaml, save_yaml
from iops.studio.runs import RunRecord, add_run, load_runs, remove_run
from iops.studio.settings import (
    SetupConfig,
    delete_setup,
    load_setups,
    upsert_setup,
)
from iops.studio.terminal import TerminalSession

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


def _runner_script(setup: SetupConfig, remote_config: str, session_name: str) -> str:
    """Bash the screen runs: apply setup commands, cd to workdir, run IOPS.

    Writes an exit-code marker to the shared workdir when IOPS finishes, so the
    status can be read from any login node even though the screen stays alive
    (``exec bash``) for the user to review the output.
    """
    wd = _shell_workdir(setup.workdir)
    marker = f"{wd}/.iops-studio/{session_name}.exit"
    lines = ["#!/bin/bash"]
    lines += list(setup.init_commands or [])
    lines += [
        f'cd "{wd}" || exit 1',
        f'"{setup.env_path}" -m iops run "{remote_config}"',
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


def _build_setup_list(setups: list, on_select, on_add, on_delete):
    """Left-pane hub: the saved setups with select/delete, plus 'Add setup'."""
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
                  on_complete, on_cancel=None):
    """Build the left-pane setup wizard. ``note`` writes a line to the terminal.

    ``on_complete`` is called (no args) once the setup is finished, either by a
    successful install or by finishing on an environment that already has IOPS.
    It reads the shared ``state`` to persist and switch to the ready view.
    ``on_cancel`` (when other setups already exist) returns to the setups hub.
    """

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

            async def on_connect():
                if conn_type.value == "ssh":
                    alias = ssh_select.value
                    if not alias:
                        ui.notify("Select an SSH host", type="warning")
                        return
                    session.start_ssh(alias, ssh_interactive_opts(alias))
                    state["target"] = {"kind": "ssh", "alias": alias}
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
                 on_reconnect_run, on_stop_run, on_dismiss_run, on_refresh_runs):
    """Left-pane view for one selected setup: summary, validation, runs, configs."""
    with ui.card().classes("studio-card w-full p-4 gap-1"):
        with ui.row().classes("items-center justify-between w-full no-wrap"):
            ui.label(saved.name).classes("text-lg font-semibold")
            ui.button(icon="arrow_back", on_click=on_back).props("flat round dense") \
                .tooltip("Back to setups")
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

    session = TerminalSession()
    state = {"env": None, "envs": [], "target": {"kind": "local", "alias": None},
             "connected": False, "init_commands": [], "workdir": "~/iops_workdir"}
    host_options = {h.alias: h.label for h in parse_ssh_hosts()}

    # Header
    with ui.row().classes("items-center gap-3 px-4 py-2 w-full").style("background:#fff;border-bottom:1px solid #e0e0e0"):
        if _STUDIO_LOGO:
            ui.image(_STUDIO_LOGO).classes("w-8 h-8").style("border-radius:6px")
        ui.label("IOPS Studio").classes("text-2xl font-bold")
        ui.label(f"v{STUDIO_VERSION}").classes("text-sm text-gray-500 self-end")
        ui.label(f"core {load_version()}").classes("text-xs text-gray-400 self-end")

    # Persistent recovery banner, shown when the shell session dies. Lives above
    # the splitter so it survives left-pane view swaps.
    disconnect_banner = ui.row().classes("w-full items-center gap-3 px-4 py-2") \
        .style("background:#fdecea;border-bottom:1px solid #f5c6cb")
    disconnect_banner.set_visibility(False)

    # Two panes: left (wizard or ready view) + persistent terminal (right)
    main_splitter = ui.splitter(value=45).classes("w-full").style("height: calc(100vh - 3rem)")
    with main_splitter:
        with main_splitter.before:
            left = ui.column().classes("p-4 gap-4 w-full h-full").style("overflow:auto")
        with main_splitter.after:
            with ui.column().classes("w-full h-full p-1").style("background:#1e1e1e"):
                term = ui.xterm(options=_XTERM_OPTIONS).classes("w-full h-full")

    # Full-width editor area, shown in place of the split view while building a
    # config so the form + YAML get the whole page side by side. It fills the
    # viewport height and scrolls as a fallback if the inner panes cannot.
    editor_area = ui.column().classes("w-full p-3") \
        .style("height: calc(100vh - 3rem); overflow:auto")
    editor_area.set_visibility(False)

    # The PTY reader fires from a bare asyncio callback (no request context), so
    # route UI updates through the client context, the supported way to update
    # the UI from a background task.
    client = ui.context.client

    def on_output(data: bytes):
        # Keep the "attached to a screen" flag accurate: screen prints these when
        # the session detaches or ends, whether triggered by us or the user.
        if b"[detached from" in data or b"[screen is terminating" in data:
            state["attached"] = False
        with client:
            term.write(data)

    def note(msg: str):
        term.write(f"\r\n\x1b[33m# {msg}\x1b[0m\r\n")

    def show_setups():
        """Hub view: the list of saved setups, or the wizard if there are none."""
        setups = load_setups()
        if not setups:
            show_wizard()
            return
        left.clear()
        with left:
            _build_setup_list(setups, on_select=select_setup, on_add=add_setup,
                              on_delete=remove_setup)

    async def _guarded(coro):
        # Run an async handler within the page's client context so its UI calls
        # (ui.notify, view rebuilds) still work even if the element that triggered
        # it was deleted meanwhile (e.g. the view was rebuilt).
        with client:
            await coro

    def show_ready(cfg: SetupConfig, *, validate: bool):
        left.clear()
        with left:
            _build_ready(
                session, state, cfg, note, on_back=show_setups, validate=validate,
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
            )

    def _exit_editor():
        editor_area.clear()
        editor_area.set_visibility(False)
        main_splitter.set_visibility(True)

    def show_editor(setup_cfg: SetupConfig, studio_cfg):
        """Open the full-width config builder for a new or existing config."""
        is_new = studio_cfg is None
        initial = (studio_cfg.yaml_text if not is_new
                   else starter_yaml("My benchmark", setup_cfg.workdir,
                                     "local" if setup_cfg.target_kind == "local" else "slurm"))
        cfg_name = "" if is_new else studio_cfg.name

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

    async def _is_on_target(setup_cfg: SetupConfig) -> bool:
        """Whether the shell is actually on the target (not fallen back to local).

        Probes the live hostname rather than trusting ``state['connected']``,
        which goes stale when the user exits ssh manually.
        """
        if setup_cfg.target_kind == "local":
            return True
        cur = await _remote_value(session, "$(hostname)", "NODE")
        return bool(cur) and cur != state.get("local_host")

    async def run_config(setup_cfg: SetupConfig, name: str, yaml_text: str):
        await _detach_if_attached(session, state)  # run in the login shell, not a screen
        if not await _is_on_target(setup_cfg):
            ui.notify("Not connected to the target. Reattach a run, or go back and "
                      "re-select the setup to connect.", type="warning")
            return
        await _ensure_workdir(session, setup_cfg.workdir)
        remote = await _write_config_to_target(session, note, setup_cfg.workdir, name, yaml_text)
        if not remote:
            ui.notify("Could not write config to target", type="negative")
            return

        has_screen = (await _remote_value(
            session, "$(command -v screen >/dev/null && echo yes || echo no)", "SCREEN")) == "yes"
        if not has_screen:
            note("screen not found in this environment; in case of interruption "
                 "IOPS will be cancelled")
            session.write(f'cd "{_shell_workdir(setup_cfg.workdir)}" && '
                          f'"{setup_cfg.env_path}" -m iops run "{remote}"\n')
            ui.notify("Running in the terminal (no screen — not resilient)", type="warning")
            return

        # Screen-wrapped, resilient run. Record the node so we can hop back.
        node = await _remote_value(session, "$(hostname)", "NODE") or "?"
        session_name = f"iops_{_slug(name)}_{uuid.uuid4().hex[:6]}"
        runner = _runner_script(setup_cfg, remote, session_name)
        rb64 = base64.b64encode(runner.encode()).decode()
        runner_path = f"{_shell_workdir(setup_cfg.workdir)}/.iops-studio/{session_name}.sh"
        start = (
            f'mkdir -p "{_shell_workdir(setup_cfg.workdir)}/.iops-studio" && '
            f"printf %s '{rb64}' | base64 -d > \"{runner_path}\" && "
            f'screen -dmS {session_name} bash "{runner_path}" && echo __STARTED__'
        )
        code, out = await session.run(start, display=f"start screen {session_name}", timeout=60)
        if code != 0 or "__STARTED__" not in out:
            ui.notify("Could not start the screen session (see terminal)", type="negative")
            return
        add_run(RunRecord(setup_name=setup_cfg.name, config_name=name,
                          screen_name=session_name, node=node,
                          started_at=datetime.now().strftime("%Y-%m-%d %H:%M")))
        state.setdefault("run_status", {})[session_name] = "running"
        note(f"running '{name}' in screen {session_name} on {node}")
        state["attached"] = True
        session.write(f"screen -r {session_name}\n")  # attach live
        ui.notify(f"Running in screen on {node}. Detach with Ctrl-A D; "
                  "reattach from the setup if the connection drops.", type="info")
        _refresh_ready(setup_cfg)

    async def check_config(setup_cfg: SetupConfig, name: str, yaml_text: str):
        await _detach_if_attached(session, state)
        remote = await _write_config_to_target(session, note, setup_cfg.workdir, name, yaml_text)
        if not remote:
            ui.notify("Could not write config to target", type="negative")
            return
        code, _ = await session.run(f'"{setup_cfg.env_path}" -m iops check "{remote}"',
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
        await _detach_if_attached(session, state)
        note(f"reattaching to {run.screen_name} on {run.node}")
        cmd = _node_command(setup_cfg, run.node, f"screen -d -r {run.screen_name}", tty=True)
        state["attached"] = True
        session.write(cmd + "\n")
        ui.notify(f"Reattaching to {run.screen_name} on {run.node} "
                  "(authenticate if prompted)", type="info")

    def dismiss_run(setup_cfg: SetupConfig, run: RunRecord):
        remove_run(setup_cfg.name, run.screen_name)
        ui.notify(f"Dismissed run '{run.config_name}'", type="info")
        _refresh_ready(setup_cfg)

    async def stop_run(setup_cfg: SetupConfig, run: RunRecord):
        """Confirm, then kill the run's screen (terminating IOPS on the target)."""
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Kill run '{run.config_name}'?").classes("font-medium")
            ui.label(f"Terminates screen {run.screen_name} on {run.node} and the "
                     "IOPS process it is running.").classes("text-xs text-negative")
            with ui.row().classes("gap-2 justify-end w-full"):
                ui.button("Cancel", on_click=lambda: dialog.submit("no")).props("flat")
                ui.button("Kill run", color="negative", on_click=lambda: dialog.submit("yes"))
        if await dialog != "yes":
            return
        await _detach_if_attached(session, state)
        note(f"killing {run.screen_name} on {run.node}")
        cmd = _node_command(setup_cfg, run.node, f"screen -S {run.screen_name} -X quit")
        session.write(cmd + "\n")
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
        runs = load_runs(setup_cfg.name)
        if not runs:
            return
        await _detach_if_attached(session, state)  # so checks run in the login shell
        if not await _is_on_target(setup_cfg):
            ui.notify("Reconnect to the target (Reattach, or re-select the setup) "
                      "to refresh run status", type="warning")
            return
        node = await _remote_value(session, "$(hostname)", "NODE")
        sessions = await _screen_sessions(session)
        d = f"{_shell_workdir(setup_cfg.workdir)}/.iops-studio"
        checks = "\n".join(
            f'[ -f "{d}/{r.screen_name}.exit" ] && echo "DONE={r.screen_name}"'
            for r in runs
        )
        _, out = await session.run(checks, display="check run status", timeout=30)
        done = {ln[len("DONE="):].strip() for ln in out.splitlines()
                if ln.strip().startswith("DONE=")}
        status = {}
        for r in runs:
            if r.screen_name in done:
                status[r.screen_name] = "finished"
            elif r.node == node and r.screen_name not in sessions:
                status[r.screen_name] = "finished"  # screen gone on this node
            else:
                status[r.screen_name] = "running"
        state["run_status"] = status
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

    def show_wizard():
        left.clear()
        # Offer a way back to the hub only when there is something to go back to.
        on_cancel = show_setups if load_setups() else None
        with left:
            _build_wizard(session, state, host_options, note, on_complete=complete,
                          on_cancel=on_cancel)

    def _reset_state():
        # Keep init_commands (the user's module/PATH setup) so a disconnect does
        # not make them retype it; drop only the per-shell-session flags and
        # connection state.
        state.update(env=None, envs=[], target={"kind": "local", "alias": None},
                     connected=False)
        state.pop("ssh_started", None)
        state.pop("init_ran", None)
        state.pop("attached", None)

    def _load_state_from(cfg: SetupConfig):
        state["target"] = {"kind": cfg.target_kind, "alias": cfg.target_alias}
        state["env"] = PyEnv(cfg.env_path, cfg.env_kind, cfg.env_version, cfg.iops_version)
        state["init_commands"] = list(cfg.init_commands)
        state["workdir"] = cfg.workdir
        state.pop("ssh_started", None)
        state.pop("init_ran", None)
        state.pop("run_status", None)
        state.pop("validation", None)
        state.pop("attached", None)
        state["connected"] = False

    def complete():
        """Persist the finished setup (read from state) and show its ready view."""
        env = state["env"]
        name = state.get("setup_name") or _suggest_name(state["target"], env)
        cfg = SetupConfig(
            name=name,
            target_kind=state["target"]["kind"],
            target_alias=state["target"]["alias"],
            env_path=env.path,
            env_kind=env.kind,
            env_version=env.version,
            iops_version=env.iops_version,
            init_commands=list(state.get("init_commands") or []),
            workdir=state.get("workdir") or "~/iops_workdir",
        )
        upsert_setup(cfg)
        # The shell is already connected and set up for this target; do not
        # revalidate (which would restart/reconnect it).
        show_ready(cfg, validate=False)

    def add_setup():
        """Start the wizard for a new setup on a clean local shell."""
        state["init_commands"] = []
        state.pop("setup_name", None)
        _reset_state()
        session.restart()
        show_wizard()

    def select_setup(cfg: SetupConfig):
        """Open a saved setup: reconnect on a clean shell and validate live."""
        _load_state_from(cfg)
        session.restart()  # drop any previous target so we connect fresh
        show_ready(cfg, validate=True)

    def remove_setup(cfg: SetupConfig):
        delete_setup(cfg.name)
        ui.notify(f"Deleted setup '{cfg.name}'", type="info")
        show_setups()

    def on_shell_exit():
        """The PTY shell died (exit / ssh dropped / killed). Offer to recover.

        Fired from the reader callback with no request context, so wrap UI work
        in the client context. Connection state is cleared so nothing keeps
        assuming a live (possibly remote) shell.
        """
        with client:
            _reset_state()
            disconnect_banner.set_visibility(True)

    def reconnect():
        """Restart button: spawn a clean local shell and return to the setups hub."""
        disconnect_banner.set_visibility(False)
        _reset_state()
        session.restart()
        show_setups()

    with disconnect_banner:
        ui.icon("link_off", color="negative")
        ui.label("Terminal disconnected. The shell session ended.") \
            .classes("text-negative font-medium")
        ui.button("Restart terminal", icon="restart_alt", on_click=reconnect).props("flat")

    session.start(on_output=on_output, on_exit=on_shell_exit)
    term.on_data(lambda e: session.write(e.data) if not session.input_locked else None)
    term.on_resize(lambda e: session.resize(e.cols, e.rows))
    ui.timer(0.3, term.fit, once=True)

    async def _capture_local_host():
        # The shell starts local; record this machine's hostname so we can later
        # tell whether the shell is on the cluster or has fallen back to local.
        state["local_host"] = await _remote_value(session, "$(hostname)", "NODE")
    ui.timer(0.6, _capture_local_host, once=True)

    # Tear down the shell when the browser tab closes
    ui.context.client.on_disconnect(session.close)

    # Land on the setups hub (which shows the wizard itself when none exist).
    show_setups()


def build_app():
    """Register Studio's NiceGUI pages. Call before ``ui.run``."""

    @ui.page("/")
    async def index():
        await ui.context.client.connected()
        _page()
