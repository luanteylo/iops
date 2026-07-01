"""NiceGUI page definitions for IOPS Studio.

This module is imported lazily (only after the NiceGUI availability check in
``iops.studio.server``), so importing ``nicegui`` at module top is safe here.

Layout: a two-pane page. The left pane is the setup wizard (Connection, Python
environment, Install IOPS); the right pane is a persistent, interactive terminal
(``ui.xterm``) backed by one shell session. The wizard drives its steps by
sending commands into that same shell, so everything shows up live and, on
failure, the user can take over in the exact same context.
"""

from nicegui import ui

from iops.main import load_version
from iops.studio import __version__ as STUDIO_VERSION
from iops.studio.connections import build_connection, parse_ssh_hosts
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
from iops.studio.settings import SetupConfig, clear_setup, load_setup, save_setup
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


def _build_wizard(session: TerminalSession, state: dict, host_options: dict, note, on_complete):
    """Build the left-pane setup wizard. ``note`` writes a line to the terminal.

    ``on_complete`` is called (no args) once the setup is finished, either by a
    successful install or by finishing on an environment that already has IOPS.
    It reads the shared ``state`` to persist and switch to the ready view.
    """

    with ui.stepper().props("vertical").classes("w-full") as stepper:

        # ---- Step 1: connection ------------------------------------------- #
        with ui.step("Connection"):
            ui.label("Run locally, or open an SSH session to a cluster. Every "
                     "command runs in the terminal on the right.").classes("text-gray-600 text-sm")
            conn_type = ui.toggle({"local": "Local machine", "ssh": "SSH host"}, value="local")
            ssh_select = ui.select(host_options, label="Host from ~/.ssh/config",
                                   with_input=True).classes("w-96")
            ssh_select.bind_visibility_from(conn_type, "value", backward=lambda v: v == "ssh")
            conn_status = ui.row().classes("items-center gap-2 min-h-8")

            async def do_verify():
                code, out = await session.run(
                    'printf "WHO=%s@%s\\n" "$(whoami)" "$(hostname)"',
                    display="verify shell", timeout=30)
                who = next((l[4:] for l in out.splitlines() if l.startswith("WHO=")), None)
                conn_status.clear()
                with conn_status:
                    if code == 0 and who:
                        ui.icon("check_circle", color="positive")
                        ui.label(f"Connected: {who}").classes("text-positive")
                        state["connected"] = True
                        conn_next.set_enabled(True)
                    else:
                        ui.icon("error", color="negative")
                        ui.label("Shell not ready. Check the terminal.").classes("text-negative")

            async def on_connect():
                if conn_type.value == "ssh":
                    alias = ssh_select.value
                    if not alias:
                        ui.notify("Select an SSH host", type="warning")
                        return
                    session.start_ssh(alias)
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
                 note, on_reset, validate: bool):
    """Left-pane view shown when a saved setup exists: summary + live validation."""
    with ui.card().classes("studio-card w-full p-4 gap-1"):
        ui.label("Setup ready").classes("text-lg font-semibold")
        ui.label(saved.where).classes("text-sm text-gray-600")
        ui.label(f"Environment: {saved.env_path}").classes("text-sm text-gray-600")
        py = f"Python {saved.env_version}" if saved.env_version else "Python"
        iops = f" · IOPS {saved.iops_version}" if saved.iops_version else " · IOPS (unknown)"
        ui.label(py + iops).classes("text-sm text-gray-600")

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

        async def do_validate():
            validate_btn.disable()
            try:
                if saved.target_kind == "ssh" and not state.get("ssh_started"):
                    working(f"Reconnecting to {saved.target_alias} (authenticate in terminal if prompted)...")
                    session.start_ssh(saved.target_alias)
                    state["ssh_started"] = True
                    state["connected"] = True
                working("Validating environment...")
                ok, detail = await _validate_setup(session, saved)
                if ok:
                    result(True, detail)
                else:
                    result(False, detail + " — re-run setup, or fix it and re-validate.")
            finally:
                validate_btn.enable()

        with ui.row().classes("gap-2 mt-3"):
            validate_btn = ui.button("Validate now", icon="verified", on_click=do_validate)
            ui.button("Re-run setup", icon="refresh", on_click=on_reset).props("flat")

        if validate:
            ui.timer(0.4, do_validate, once=True)
        else:
            result(True, f"Setup saved. IOPS {saved.iops_version or ''} ready.".rstrip())


def _page():
    ui.add_head_html(_STUDIO_HEAD)
    ui.query(".nicegui-content").classes("p-0 gap-0")

    session = TerminalSession()
    state = {"env": None, "envs": [], "target": {"kind": "local", "alias": None}, "connected": False}
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

    def show_ready(saved: SetupConfig, *, validate: bool):
        left.clear()
        with left:
            _build_ready(session, state, saved, note, on_reset=reset, validate=validate)

    def show_wizard():
        left.clear()
        with left:
            _build_wizard(session, state, host_options, note, on_complete=complete)

    def complete():
        """Persist the finished setup (read from state) and show the ready view."""
        env = state["env"]
        cfg = SetupConfig(
            target_kind=state["target"]["kind"],
            target_alias=state["target"]["alias"],
            env_path=env.path,
            env_kind=env.kind,
            env_version=env.version,
            iops_version=env.iops_version,
        )
        save_setup(cfg)
        show_ready(cfg, validate=False)

    def _reset_state():
        state.update(env=None, envs=[], target={"kind": "local", "alias": None},
                     connected=False)
        state.pop("ssh_started", None)

    def reset():
        """Delete the saved setup and return to a fresh wizard on a clean shell."""
        clear_setup()
        _reset_state()
        session.restart()  # drop any ssh session so the wizard starts local again
        show_wizard()

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
        """Restart button: spawn a clean local shell and restart the wizard."""
        disconnect_banner.set_visibility(False)
        _reset_state()
        session.restart()
        show_wizard()

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

    saved = load_setup()
    if saved is not None:
        state["target"] = {"kind": saved.target_kind, "alias": saved.target_alias}
        state["env"] = PyEnv(saved.env_path, saved.env_kind, saved.env_version, saved.iops_version)
        show_ready(saved, validate=True)
    else:
        show_wizard()


def build_app():
    """Register Studio's NiceGUI pages. Call before ``ui.run``."""

    @ui.page("/")
    async def index():
        await ui.context.client.connected()
        _page()
