"""NiceGUI page definitions for IOPS Studio.

This module is imported lazily (only after the NiceGUI availability check in
``iops.studio.server``), so importing ``nicegui`` at module top is safe here.
"""

from nicegui import run, ui

from iops.main import load_version
from iops.studio import __version__ as STUDIO_VERSION
from iops.studio.connections import build_connection, parse_ssh_hosts
from iops.studio.environments import create_environment, discover_environments

# Palette borrowed from the HTML report (iops/reporting/report_generator.py) so
# Studio feels consistent with generated reports. TODO(next step): factor the
# report's inline <style> block into a shared CSS asset and load it here instead
# of duplicating the values.
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


def _connect_wizard():
    """Two-step wizard: pick a connection (local/SSH), then a Python env."""
    # Per-tab session state. Each browser connection gets its own page call.
    state: dict = {"connection": None, "env": None, "envs": []}
    host_options = {h.alias: h.label for h in parse_ssh_hosts()}

    with ui.stepper().props("vertical").classes("w-full") as stepper:

        # ---- Step 1: connection ------------------------------------------- #
        with ui.step("Connection"):
            ui.label("Run locally or connect to a cluster over SSH.") \
                .classes("text-gray-600 text-sm")
            conn_type = ui.toggle(
                {"local": "Local machine", "ssh": "SSH host"}, value="local",
            )
            ssh_select = ui.select(
                host_options, label="Host from ~/.ssh/config", with_input=True,
            ).classes("w-96")
            ssh_select.bind_visibility_from(conn_type, "value", backward=lambda v: v == "ssh")
            if not host_options:
                ui.label("No hosts found in ~/.ssh/config.") \
                    .classes("text-gray-400 text-sm italic") \
                    .bind_visibility_from(conn_type, "value", backward=lambda v: v == "ssh")

            test_result = ui.row().classes("items-center gap-2 min-h-8")

            async def on_test():
                kind = conn_type.value
                alias = ssh_select.value if kind == "ssh" else None
                if kind == "ssh" and not alias:
                    ui.notify("Select an SSH host first", type="warning")
                    return
                next_btn.set_enabled(False)
                test_result.clear()
                with test_result:
                    ui.spinner(size="sm")
                    ui.label(f"Testing {alias or 'local'}...")
                conn = build_connection(kind, alias)
                res = await run.io_bound(conn.test)
                test_result.clear()
                with test_result:
                    if res.ok:
                        ui.icon("check_circle", color="positive")
                        ui.label(res.message).classes("text-positive")
                    else:
                        ui.icon("error", color="negative")
                        ui.label(res.message).classes("text-negative")
                if res.ok:
                    state["connection"] = conn
                    next_btn.set_enabled(True)

            with ui.row().classes("gap-2 mt-2"):
                ui.button("Test connection", icon="cable", on_click=on_test)
            with ui.stepper_navigation():
                next_btn = ui.button("Next", on_click=stepper.next)
                next_btn.set_enabled(False)

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
                        finish_btn.set_enabled(False)
                        return
                    options = {i: e.label for i, e in enumerate(envs)}
                    radio = ui.radio(options, on_change=lambda: finish_btn.set_enabled(True))
                    env_radio["widget"] = radio

            async def on_discover():
                conn = state["connection"]
                if conn is None:
                    ui.notify("Test a connection first", type="warning")
                    return
                extra = [custom_path.value] if custom_path.value.strip() else None
                env_area.clear()
                with env_area:
                    with ui.row().classes("items-center gap-2"):
                        ui.spinner(size="sm")
                        ui.label("Discovering environments...")
                try:
                    envs = await run.io_bound(discover_environments, conn, extra)
                except ValueError as e:
                    env_area.clear()
                    ui.notify(f"Invalid folder: {e}", type="negative")
                    return
                render_envs(envs)

            async def on_create():
                conn = state["connection"]
                if conn is None:
                    ui.notify("Test a connection first", type="warning")
                    return
                path = path_input.value.strip()
                if not path:
                    ui.notify("Enter a path for the new environment", type="warning")
                    return
                ui.notify(f"Creating environment at {path}...")
                res = await run.io_bound(create_environment, conn, path)
                if res.ok:
                    ui.notify(res.message, type="positive")
                    await on_discover()
                else:
                    ui.notify(f"Failed: {res.message}", type="negative")

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

            summary_area = ui.column().classes("w-full")

            def on_finish():
                radio = env_radio["widget"]
                if radio is None or radio.value is None:
                    ui.notify("Select an environment", type="warning")
                    return
                env = state["envs"][radio.value]
                state["env"] = env
                summary_area.clear()
                with summary_area:
                    with ui.card().classes("studio-card w-full"):
                        ui.label("Ready").classes("text-lg font-semibold text-positive")
                        ui.label(f"Connection: {state['connection'].kind} "
                                 f"({state['connection'].name})")
                        ui.label(f"Environment: {env.path}")
                        iops = f"IOPS {env.iops_version}" if env.has_iops \
                            else "IOPS not installed (remote install: next step)"
                        ui.label(iops).classes("text-gray-600 text-sm")

            with ui.stepper_navigation():
                ui.button("Back", on_click=stepper.previous).props("flat")
                finish_btn = ui.button("Finish", icon="check", on_click=on_finish)
                finish_btn.set_enabled(False)


def _landing_page():
    """Render the Studio landing page."""
    ui.add_head_html(_STUDIO_HEAD)

    with ui.column().classes("w-full max-w-3xl mx-auto p-6 gap-4"):
        with ui.row().classes("items-baseline gap-3"):
            ui.label("IOPS Studio").classes("text-3xl font-bold")
            ui.label(f"v{STUDIO_VERSION}").classes("text-sm text-gray-500")
            ui.label(f"core {load_version()}").classes("text-xs text-gray-400")
        ui.label("Local client for orchestrating IOPS benchmarks on remote clusters.") \
            .classes("text-gray-600")

        with ui.card().classes("studio-card w-full"):
            _connect_wizard()


def build_app():
    """Register Studio's NiceGUI pages. Call before ``ui.run``."""

    @ui.page("/")
    def index():
        _landing_page()
