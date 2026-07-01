"""Launch the IOPS Studio local web server."""

from iops.studio import _check_nicegui


def launch(host: str = "127.0.0.1", port: int = 8080, open_browser: bool = True):
    """Start the Studio web server, optionally opening a browser.

    Blocks until the server is stopped (Ctrl-C). Raises a friendly ImportError
    if NiceGUI is not installed.
    """
    _check_nicegui()

    # Imported lazily: pulls in NiceGUI, so only touched once availability is confirmed.
    from nicegui import ui

    from iops.studio.app import build_app

    build_app()

    # reload=False is required when launching from within a function (avoids
    # NiceGUI's __mp_main__ auto-reload machinery, which needs a script entry point).
    ui.run(
        host=host,
        port=port,
        show=open_browser,
        native=False,
        reload=False,
        title="IOPS Studio",
    )
