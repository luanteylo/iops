"""IOPS Studio: the optional local web-UI client.

Studio is a workstation-side client (built on NiceGUI) that starts a local
web server and, in later steps, will connect to a cluster over SSH to install
IOPS, manage the remote environment, transfer files, and dispatch/monitor runs.

NiceGUI is an optional dependency. Importing this package stays cheap: the
NiceGUI import is only probed for availability here, and the app/server modules
that actually use it are imported lazily by the ``iops studio`` command.
"""

# Studio is versioned independently from the iops-benchmark core (iops/VERSION).
# The UI iterates on its own cadence; start pre-stable and bump to 1.0.0 once the
# remote SSH/orchestration workflow is functional end to end.
__version__ = "0.1.0"

# Optional nicegui for the Studio web UI
try:
    import nicegui  # noqa: F401
    NICEGUI_AVAILABLE = True
except ImportError:
    NICEGUI_AVAILABLE = False


def _check_nicegui():
    """Raise a helpful error if NiceGUI is not installed."""
    if not NICEGUI_AVAILABLE:
        raise ImportError(
            "IOPS Studio requires NiceGUI.\n"
            "Install it with: pip install nicegui\n"
            "Or install iops with Studio support: pip install iops-benchmark[studio]"
        )
