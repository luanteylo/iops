"""NiceGUI page definitions for IOPS Studio.

This module is imported lazily (only after the NiceGUI availability check in
``iops.studio.server``), so importing ``nicegui`` at module top is safe here.

Layout: a two-pane page. The left pane is the setup wizard (Connection, Python
environment, Install IOPS); the right pane is a persistent, interactive terminal
(``ui.xterm``) backed by one shell session. The wizard drives its steps by
sending commands into that same shell, so everything shows up live and, on
failure, the user can take over in the exact same context.
"""

from pathlib import Path

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


def _build_ready(session: TerminalSession, state: dict, saved: SetupConfig,
                 note, on_back, validate: bool):
    """Left-pane view for one selected setup: summary + live validation."""
    with ui.card().classes("studio-card w-full p-4 gap-1"):
        with ui.row().classes("items-center justify-between w-full no-wrap"):
            ui.label(saved.name).classes("text-lg font-semibold")
            ui.button(icon="arrow_back", on_click=on_back).props("flat round dense") \
                .tooltip("Back to setups")
        ui.label(saved.where).classes("text-sm text-gray-600")
        ui.label(f"Environment: {saved.env_path}").classes("text-sm text-gray-600")
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
                working("Validating environment...")
                ok, detail = await _validate_setup(session, saved)
                if not _alive(status):
                    return
                if ok:
                    result(True, detail)
                else:
                    result(False, detail + " — fix it and re-validate, or delete this setup.")
            finally:
                if _alive(validate_btn):
                    validate_btn.enable()

        with ui.row().classes("gap-2 mt-3"):
            validate_btn = ui.button("Validate now", icon="verified", on_click=do_validate)
            ui.button("Back to setups", icon="arrow_back", on_click=on_back).props("flat")

        if validate:
            ui.timer(0.4, do_validate, once=True)
        else:
            result(True, f"Setup saved. IOPS {saved.iops_version or ''} ready.".rstrip())


def _page():
    ui.add_head_html(_STUDIO_HEAD)
    ui.query(".nicegui-content").classes("p-0 gap-0")

    session = TerminalSession()
    state = {"env": None, "envs": [], "target": {"kind": "local", "alias": None},
             "connected": False, "init_commands": []}
    host_options = {h.alias: h.label for h in parse_ssh_hosts()}

    # Header
    with ui.row().classes("items-baseline gap-3 px-4 py-2 w-full").style("background:#fff;border-bottom:1px solid #e0e0e0"):
        ui.label("IOPS Studio").classes("text-2xl font-bold")
        ui.label(f"v{STUDIO_VERSION}").classes("text-sm text-gray-500")
        ui.label(f"core {load_version()}").classes("text-xs text-gray-400")

    # Persistent recovery banner, shown when the shell session dies. Lives above
    # the splitter so it survives left-pane view swaps.
    disconnect_banner = ui.row().classes("w-full items-center gap-3 px-4 py-2") \
        .style("background:#fdecea;border-bottom:1px solid #f5c6cb")
    disconnect_banner.set_visibility(False)

    # Two panes: left (wizard or ready view) + persistent terminal (right)
    with ui.splitter(value=45).classes("w-full").style("height: calc(100vh - 3rem)") as splitter:
        with splitter.before:
            left = ui.column().classes("p-4 gap-4 w-full h-full").style("overflow:auto")
        with splitter.after:
            with ui.column().classes("w-full h-full p-1").style("background:#1e1e1e"):
                term = ui.xterm(options=_XTERM_OPTIONS).classes("w-full h-full")

    # The PTY reader fires from a bare asyncio callback (no request context), so
    # route UI updates through the client context, the supported way to update
    # the UI from a background task.
    client = ui.context.client

    def on_output(data: bytes):
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

    def show_ready(cfg: SetupConfig, *, validate: bool):
        left.clear()
        with left:
            _build_ready(session, state, cfg, note, on_back=show_setups, validate=validate)

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

    def _load_state_from(cfg: SetupConfig):
        state["target"] = {"kind": cfg.target_kind, "alias": cfg.target_alias}
        state["env"] = PyEnv(cfg.env_path, cfg.env_kind, cfg.env_version, cfg.iops_version)
        state["init_commands"] = list(cfg.init_commands)
        state.pop("ssh_started", None)
        state.pop("init_ran", None)
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
