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

import fnmatch
import os
import time
from collections import deque
from pathlib import Path
from typing import Optional

YAML_EXTS = (".yaml", ".yml")

# Bounds for the recursive search, so a query typed in a huge tree (a home
# directory, a parallel filesystem mount) returns promptly instead of walking
# everything.
SEARCH_MAX_RESULTS = 200
SEARCH_MAX_DIRS = 20000
SEARCH_TIME_LIMIT = 5.0
# Folders that are large, never hold user configs, and dominate search time.
SEARCH_SKIP_DIRS = {"node_modules", "__pycache__", ".git", ".venv", "venv",
                    "site-packages", ".tox", ".mypy_cache", ".pytest_cache"}


def _name_matcher(query: str):
    """Case-insensitive name test: a glob when ``*``/``?`` is present, else a substring."""
    q = (query or "").strip().lower()
    if not q:
        return lambda name: True
    if any(c in q for c in "*?["):
        return lambda name: fnmatch.fnmatch(name.lower(), q)
    return lambda name: q in name.lower()


def _filter_entries(dirs: list, files: list, query: str) -> tuple[list, list]:
    """Keep the entries of one listing whose name matches ``query``."""
    match = _name_matcher(query)
    return [d for d in dirs if match(d.name)], [f for f in files if match(f.name)]


def _search(root: Path, query: str, show_hidden: bool, extensions: tuple, *,
            include_files: bool = True, max_results: int = SEARCH_MAX_RESULTS,
            max_dirs: int = SEARCH_MAX_DIRS,
            time_limit: float = SEARCH_TIME_LIMIT) -> tuple[list, bool]:
    """Find folders (and matching files) below ``root`` whose name matches ``query``.

    Breadth-first, so shallow matches come first. Symlinked folders are listed
    but not entered (no loops), unreadable folders are skipped, and
    ``SEARCH_SKIP_DIRS`` are never entered. Returns ``(matches, truncated)``:
    ``matches`` is a list of ``(path, is_dir)`` and ``truncated`` is True when a
    bound (results, folders visited, or time) stopped the walk early.
    """
    match = _name_matcher(query)
    matches: list = []
    queue = deque([root])
    visited = 0
    deadline = time.monotonic() + time_limit
    while queue:
        if visited >= max_dirs or time.monotonic() > deadline:
            return matches, True
        current = queue.popleft()
        visited += 1
        try:
            with os.scandir(current) as it:
                children = sorted(it, key=lambda e: e.name.lower())
        except OSError:
            continue
        for entry in children:
            name = entry.name
            if not show_hidden and name.startswith("."):
                continue
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            if is_dir:
                if match(name):
                    matches.append((Path(entry.path), True))
                try:
                    is_link = entry.is_symlink()
                except OSError:
                    is_link = True
                if not is_link and name not in SEARCH_SKIP_DIRS:
                    queue.append(Path(entry.path))
            elif include_files and (not extensions or Path(name).suffix.lower() in extensions) \
                    and match(name):
                matches.append((Path(entry.path), False))
            if len(matches) >= max_results:
                return matches, True
    return matches, False


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
    from nicegui import run, ui

    start_dir = Path(start).expanduser() if start else Path.cwd()
    if not start_dir.is_dir():
        start_dir = Path.home()
    # `results` is None while browsing, or the list of (path, is_dir) matches of
    # the last recursive search; `token` discards a search that finishes after
    # the user has already moved on.
    state = {"dir": start_dir.resolve(), "hidden": False, "query": "",
             "results": None, "truncated": False, "searching": False, "token": 0}
    name_holder = {"value": default_name}

    with ui.dialog() as dialog, ui.card().classes("gap-2").style("width:640px;max-width:90vw"):
        ui.label(title).classes("text-lg font-semibold")

        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            path_input = ui.input("Folder", value=str(state["dir"])).classes("grow")
            path_input.on("keydown.enter", lambda: go(path_input.value))
            ui.button(icon="arrow_forward", on_click=lambda: go(path_input.value)) \
                .props("flat round dense").tooltip("Go to folder")
            ui.checkbox("Hidden", value=False,
                        on_change=lambda e: (state.update(hidden=e.value), reset_search(), render()))

        with ui.row().classes("items-center gap-2 w-full no-wrap"):
            search_input = ui.input(
                "Search", placeholder="Type to filter this folder, Enter to search subfolders") \
                .props("clearable dense").classes("grow")
            with search_input.add_slot("prepend"):
                ui.icon("search")
            search_input.on_value_change(
                lambda e: (state.update(query=(e.value or "").strip()), reset_search(), render()))
            search_input.on("keydown.enter", lambda: run_search())
            ui.button("Search subfolders", icon="manage_search", on_click=lambda: run_search()) \
                .props("flat dense no-caps") \
                .tooltip("Search every folder below this one by name (* and ? wildcards allowed)")

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
                reset_search()
                if state["query"]:
                    state["query"] = ""
                    search_input.value = ""  # its change handler re-renders
                else:
                    render()
            else:
                ui.notify("No such folder", type="warning")

        def reset_search():
            state.update(results=None, truncated=False, searching=False,
                         token=state["token"] + 1)

        async def run_search():
            query = state["query"]
            if not query:
                ui.notify("Type a name to search for", type="info")
                return
            reset_search()
            token = state["token"]
            state["searching"] = True
            render()
            matches, truncated = await run.io_bound(
                _search, state["dir"], query, state["hidden"], extensions,
                include_files=(mode != "dir"))
            if token != state["token"]:
                return  # the user navigated or changed the query meanwhile
            state.update(results=matches, truncated=truncated, searching=False)
            render()

        def _relative(p: Path) -> str:
            try:
                return str(p.relative_to(state["dir"]))
            except ValueError:
                return str(p)

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

        def _file_action(f: Path):
            if mode == "open":
                return lambda: dialog.submit(str(f.resolve()))
            return lambda: go(str(f))  # save mode: adopt the name, browse its folder

        def render_results():
            results = state["results"]
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                count = f"{len(results)} match{'es' if len(results) != 1 else ''}"
                ui.label(f"{count} for '{state['query']}' under {state['dir']}") \
                    .classes("text-xs text-grey truncate grow")
                ui.button("Back to folder", icon="close",
                          on_click=lambda: (reset_search(), render())) \
                    .props("flat dense no-caps size=sm")
            if state["truncated"]:
                ui.label("Search stopped early; showing the first matches. "
                         "Refine the name or start from a deeper folder.") \
                    .classes("text-xs text-warning")
            with ui.scroll_area().classes("h-64 w-full") \
                    .style("border:1px solid #e0e0e0;border-radius:6px"):
                for path, is_dir in results:
                    if is_dir:
                        _row("folder", _relative(path), lambda p=path: go(str(p)), color="amber")
                    else:
                        _row("description", _relative(path), _file_action(path))
                if not results:
                    ui.label("(nothing found)").classes("text-xs text-grey italic p-1")

        def render():
            body.clear()
            d = state["dir"]
            if state["searching"]:
                with body:
                    with ui.row().classes("items-center gap-2 p-2"):
                        ui.spinner(size="sm")
                        ui.label(f"Searching under {d} ...").classes("text-xs text-grey")
                update_hint()
                return
            if state["results"] is not None:
                with body:
                    render_results()
                update_hint()
                return
            dirs, files = _entries(d, state["hidden"], extensions)
            dirs, files = _filter_entries(dirs, files, state["query"])
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
                        elif mode == "save":
                            _row("description", f.name, lambda ff=f: pick_name(ff))
                        # "dir" mode: files shown for context only, not selectable.
                        else:
                            with ui.row().classes("items-center gap-2 w-full no-wrap p-1 opacity-50"):
                                ui.icon("description")
                                ui.label(f.name).classes("truncate")
                    if not dirs and not files:
                        ui.label(f"(nothing here matches '{state['query']}'; press Enter "
                                 f"to search subfolders)" if state["query"]
                                 else "(no folders or matching files here)") \
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
            elif mode == "dir":
                ui.button("Use this folder", icon="check",
                          on_click=lambda: dialog.submit(str(state["dir"]))).props("unelevated")

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


async def choose_dir(title: str = "Choose a destination folder",
                     start: Optional[str] = None) -> Optional[str]:
    """Pick an existing folder on the host. Returns its path, or None."""
    return await _browse("dir", title=title, start=start, extensions=(), default_name="")
