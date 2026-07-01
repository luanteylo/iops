"""NiceGUI page definitions for IOPS Studio.

This module is imported lazily (only after the NiceGUI availability check in
``iops.studio.server``), so importing ``nicegui`` at module top is safe here.
"""

from nicegui import ui

from iops.main import load_version
from iops.studio import __version__ as STUDIO_VERSION

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


def _landing_page():
    """Render the Studio landing page."""
    ui.add_head_html(_STUDIO_HEAD)

    with ui.column().classes('w-full max-w-3xl mx-auto p-6 gap-4'):
        with ui.row().classes('items-baseline gap-3'):
            ui.label('IOPS Studio').classes('text-3xl font-bold')
            ui.label(f'v{STUDIO_VERSION}').classes('text-sm text-gray-500')
            ui.label(f'core {load_version()}').classes('text-xs text-gray-400')
        ui.label('Local client for orchestrating IOPS benchmarks on remote clusters.') \
            .classes('text-gray-600')

        # Clusters panel: the seam the SSH/orchestration step plugs into.
        with ui.card().classes('studio-card w-full'):
            ui.label('Clusters').classes('text-xl font-semibold')
            ui.label('SSH connections, remote install, and job dispatch land here.') \
                .classes('text-gray-500 text-sm')
            with ui.row().classes('items-center gap-2'):
                ui.button('Add cluster', icon='add').props('disable')
                ui.label('SSH connections: coming soon').classes('text-gray-400 text-sm italic')


def build_app():
    """Register Studio's NiceGUI pages. Call before ``ui.run``."""

    @ui.page('/')
    def index():
        _landing_page()
