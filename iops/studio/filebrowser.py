"""Server-side file browser dialogs for IOPS Studio.

Studio runs as a local web app, so "the host machine" is the machine serving
Studio (not the browser). These dialogs browse the real local filesystem so the
user can pick an existing YAML file to import (read server-side) or choose a
destination to export a config to (written server-side).

Both entry points return an absolute path string, or None if the user cancels:
- ``open_yaml()``  -> path of an existing ``.yaml``/``.yml`` file to import.
- ``save_yaml()``  -> path (folder + file name) to write a config to.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

YAML_EXTS = (".yaml", ".yml")


def _entries(directory: Path, show_hidden: bool, extensions: tuple) -> tuple[list, list]:
    """Return ``(subdirs, files)`` in ``directory``: sorted, filtered by ext.

    Unreadable entries and directories are skipped rather than raising, so a
    single permission-denied child never breaks the listing.
    """
    dirs, files = [], []
    try:
        children = list(directory.iterdir())
    except (OSError, PermissionError):
        return dirs, files
    for child in children:
        if not show_hidden and child.name.startswith("."):
            continue
        try:
            is_dir = child.is_dir()
        except OSError:
            continue
        if is_dir:
            dirs.append(child)
        elif not extensions or child.suffix.lower() in extensions:
            files.append(child)
    dirs.sort(key=lambda p: p.name.lower())
    files.sort(key=lambda p: p.name.lower())
    return dirs, files


async def _browse(mode: str, *, title: str, start: Optional[str],
                  extensions: tuple, default_name: str) -> Optional[str]:
    """Shared dialog for ``open`` and ``save`` modes. Returns a path or None."""
    from nicegui import ui

    start_dir = Path(start).expanduser() if start else Path.cwd()
    if not start_dir.is_dir():
        start_dir = Path.home()
    state = {"dir": start_dir.resolve(), "hidden": False}
    name_holder = {"value": default_name}

    with ui.dialog() as dialog, ui.card().classes("gap-2").style("width:640px;max-width:90vw"):
        ui.label(title).classes("text-lg font-semibold")

        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            path_input = ui.input("Folder", value=str(state["dir"])).classes("grow")
            path_input.on("keydown.enter", lambda: go(path_input.value))
            ui.button(icon="arrow_forward", on_click=lambda: go(path_input.value)) \
                .props("flat round dense").tooltip("Go to folder")
            ui.checkbox("Hidden", value=False,
                        on_change=lambda e: (state.update(hidden=e.value), render()))

        body = ui.column().classes("w-full gap-0")

        name_input = None
        save_hint = None
        if mode == "save":
            name_input = ui.input("File name", value=default_name).classes("w-full")
            name_input.on_value_change(
                lambda e: (name_holder.update(value=(e.value or "").strip()), update_hint()))
            save_hint = ui.label("").classes("text-xs text-warning")

        def go(where):
            p = Path(str(where) or "").expanduser()
            if p.is_file():
                if mode == "open":
                    dialog.submit(str(p.resolve()))
                    return
                pick_name(p)  # save mode: adopt the name, browse its folder
                p = p.parent
            if p.is_dir():
                state["dir"] = p.resolve()
                path_input.value = str(state["dir"])
                render()
            else:
                ui.notify("No such folder", type="warning")

        def pick_name(f: Path):
            name_holder["value"] = f.name
            if name_input is not None:
                name_input.value = f.name
            update_hint()

        def update_hint():
            if save_hint is None:
                return
            fn = (name_holder["value"] or "").strip()
            target = state["dir"] / fn
            save_hint.text = (f"{fn} exists in this folder and will be overwritten."
                              if fn and target.exists() else "")

        def _row(icon: str, text: str, on_click, color: Optional[str] = None):
            row = ui.row().classes(
                "items-center gap-2 w-full no-wrap cursor-pointer p-1 rounded hover:bg-gray-100")
            row.on("click", on_click)
            with row:
                ui.icon(icon, color=color) if color else ui.icon(icon)
                ui.label(text).classes("truncate")

        def render():
            body.clear()
            d = state["dir"]
            dirs, files = _entries(d, state["hidden"], extensions)
            with body:
                with ui.scroll_area().classes("h-64 w-full") \
                        .style("border:1px solid #e0e0e0;border-radius:6px"):
                    parent = d.parent
                    if parent != d:
                        _row("arrow_upward", "..", lambda: go(str(parent)))
                    for sub in dirs:
                        _row("folder", sub.name, lambda s=sub: go(str(s)), color="amber")
                    for f in files:
                        if mode == "open":
                            _row("description", f.name, lambda ff=f: dialog.submit(str(ff.resolve())))
                        else:
                            _row("description", f.name, lambda ff=f: pick_name(ff))
                    if not dirs and not files:
                        ui.label("(no folders or matching files here)") \
                            .classes("text-xs text-grey italic p-1")
            update_hint()

        def _do_save():
            fn = (name_holder["value"] or "").strip()
            if not fn:
                ui.notify("Enter a file name", type="warning")
                return
            dialog.submit(str((state["dir"] / fn).resolve()))

        with ui.row().classes("justify-end gap-2 w-full items-center"):
            ui.space()
            ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
            if mode == "save":
                ui.button("Save here", icon="save", on_click=_do_save).props("unelevated")

        render()

    return await dialog


async def open_yaml(start: Optional[str] = None) -> Optional[str]:
    """Pick an existing YAML file to import. Returns its path, or None."""
    return await _browse("open", title="Import a YAML config", start=start,
                         extensions=YAML_EXTS, default_name="")


async def save_yaml(default_name: str = "config.yaml",
                    start: Optional[str] = None) -> Optional[str]:
    """Pick a folder + file name to export a config to. Returns the path, or None."""
    return await _browse("save", title="Export config to a file", start=start,
                         extensions=YAML_EXTS, default_name=default_name)
