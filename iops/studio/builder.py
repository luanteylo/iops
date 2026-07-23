"""IOPS config builder: a section-navigated form beside a live YAML editor.

The single source of truth is the parsed config *dict* (``model``). A left rail
selects one section at a time; its fields render in the middle pane and the YAML
shows on the right. The two are kept in sync both ways:
- editing a form field mutates ``model`` and re-serializes it into the YAML pane;
- editing the YAML (debounced) reparses it and rebuilds the active section.

Three view modes (segmented control in the header): "Form + YAML" (default),
"Form" only, and "YAML" only.

The form covers every option IOPS accepts. A handful of rarely-used, free-form
keys (e.g. ``scripts[].mpi``) round-trip untouched through ``model`` and stay
editable on the YAML pane.

Validation reuses IOPS' own ``validate_yaml_config`` on a temp file (structural +
semantic, no workdir creation, tolerant of remote paths). The authoritative check
runs on the target via ``iops check`` at run time.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import yaml

from iops.config.loader import validate_yaml_config

REQUIRED_SECTIONS = ("benchmark", "vars", "command", "scripts", "output")

EXECUTORS = ["local", "slurm"]
SEARCH_METHODS = ["exhaustive", "random", "bayesian", "adaptive"]
VAR_TYPES = ["int", "float", "str", "bool", "list"]
SINK_TYPES = ["csv", "parquet", "sqlite"]
ACQUISITION_FUNCS = ["EI", "PI", "LCB"]
BASE_ESTIMATORS = ["RF", "GP", "ET", "GBRT"]
OBJECTIVES = ["minimize", "maximize"]
VIOLATION_POLICIES = ["skip", "error", "warn"]
ALLOCATION_MODES = ["per-test", "single"]
DIRECTIONS = ["ascending", "descending"]
PLOT_STYLES = ["plotly_white", "plotly", "plotly_dark", "ggplot2", "seaborn", "simple_white"]
PLOT_TYPES = ["line", "bar", "scatter", "box", "violin", "heatmap", "surface_3d",
              "parallel_coordinates", "execution_scatter", "coverage_heatmap"]
AGGREGATIONS = ["mean", "median", "count", "std", "min", "max"]
SORT_MODES = ["index", "values"]
REPORT_SECTIONS = [
    "test_summary", "best_results", "variable_impact", "parallel_coordinates",
    "bayesian_evolution", "bayesian_parameter_evolution", "resource_sampling",
    "custom_plots", "gallery", "versions",
]


# --------------------------------------------------------------------------- #
# YAML <-> dict
# --------------------------------------------------------------------------- #
class _BlockDumper(yaml.SafeDumper):
    """Dumper that renders multi-line strings as literal ``|`` blocks."""


def _represent_str(dumper, data):
    if "\n" not in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=None)
    # Render multi-line strings (scripts, parser code, allocation scripts, ...) as
    # literal `|` blocks. YAML block scalars cannot carry CRLF or trailing spaces,
    # so PyYAML would otherwise fall back to an unreadable one-line double-quoted
    # string. Normalize newlines and strip trailing whitespace per line (never
    # meaningful in a script; leading indentation is preserved) so `|` always applies.
    normalized = "\n".join(line.rstrip()
                           for line in data.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    return dumper.represent_scalar("tag:yaml.org,2002:str", normalized, style="|")


_BlockDumper.add_representer(str, _represent_str)


def parse_yaml(text: str) -> tuple[Optional[dict], str]:
    """Parse YAML text into a dict. Returns ``(dict, "")`` or ``(None, error)``."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return None, f"YAML syntax error: {e}"
    if data is None:
        return {}, ""
    if not isinstance(data, dict):
        return None, "The top level of the config must be a mapping."
    return data, ""


def dump_yaml(model: dict) -> str:
    """Serialize a config dict to YAML, preserving key order and block scalars."""
    return yaml.dump(model, Dumper=_BlockDumper, default_flow_style=False,
                     sort_keys=False, width=100)


def validate_yaml_text(text: str) -> tuple[bool, list]:
    """Validate config text with IOPS' own validator. Returns ``(ok, messages)``."""
    data, err = parse_yaml(text)
    if err:
        return False, [err]
    missing = [s for s in REQUIRED_SECTIONS if s not in (data or {})]
    if missing:
        return False, [f"Missing required section: {s}" for s in missing]
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "config.yaml"
        path.write_text(text)
        errors = validate_yaml_config(path)
    return (not errors), list(errors)


def starter_yaml(name: str = "My benchmark", workdir: str = "./workdir",
                 executor: str = "local") -> str:
    """A minimal, valid, runnable-anywhere starter config as YAML text."""
    model = {
        "benchmark": {
            "name": name, "workdir": workdir, "executor": executor,
            "search_method": "exhaustive", "repetitions": 1,
        },
        "vars": {"size": {"type": "int", "sweep": {"mode": "list", "values": [1, 2, 4]}}},
        "command": {"template": "echo running size={{ size }}"},
        "scripts": [{
            "name": "run",
            "script_template": "#!/bin/bash\n{{ command.template }} > {{ execution_dir }}/out.txt\n",
            "parser": {
                "file": "{{ execution_dir }}/out.txt",
                "metrics": [{"name": "value"}],
                "parser_script": (
                    "def parse(file_path):\n"
                    "    with open(file_path) as f:\n"
                    "        text = f.read()\n"
                    "    return {\"value\": len(text.strip())}\n"
                ),
            },
        }],
        "output": {"sink": {"type": "csv", "path": "{{ workdir }}/results.csv"}},
    }
    return dump_yaml(model)


def config_workdir(text: str) -> str:
    """Best-effort read of ``benchmark.workdir`` from config text ("" if absent)."""
    data, err = parse_yaml(text)
    if err or not isinstance(data, dict):
        return ""
    bench = data.get("benchmark") or {}
    return str(bench.get("workdir") or "") if isinstance(bench, dict) else ""


def var_kind(vardef: dict) -> str:
    if "expr" in vardef:
        return "expr"
    if "adaptive" in vardef:
        return "adaptive"
    return "sweep"


def _parse_values(text: str) -> list:
    out = []
    for tok in (text or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        for cast in (int, float):
            try:
                out.append(cast(tok))
                break
            except ValueError:
                continue
        else:
            if tok.lower() in ("true", "false"):
                out.append(tok.lower() == "true")
            else:
                out.append(tok)
    return out


def _values_text(values) -> str:
    return ", ".join(str(v) for v in (values or []))


def _csv_list(text: str) -> list:
    return [t.strip() for t in (text or "").split(",") if t.strip()]


# Rail sections: (model key, label, icon). The key also drives item counts.
_SECTIONS = [
    ("benchmark", "Benchmark", "science"),
    ("vars", "Variables", "tune"),
    ("command", "Command", "terminal"),
    ("scripts", "Scripts", "description"),
    ("output", "Output", "save"),
    ("probes", "Probes", "sensors"),
    ("reporting", "Reporting", "assessment"),
    ("constraints", "Constraints", "rule"),
]


# --------------------------------------------------------------------------- #
# Editor UI
# --------------------------------------------------------------------------- #
def build_editor(name: str, initial_yaml: str, *, on_save, on_cancel,
                 on_run, on_check, on_export=None) -> None:
    """Render the section-navigated config editor into the current container.

    ``on_export`` (optional) is an async callback ``(name, yaml_text)`` that
    writes the *current* editor text to a file on the host; when provided, an
    Export button appears in the header.
    """
    from nicegui import ui

    data, _ = parse_yaml(initial_yaml)
    model: dict = data if isinstance(data, dict) else {}
    name_holder = {"value": name}
    debounce = {"timer": None}
    state = {"section": "benchmark", "view": "both"}
    expanded: dict = {}  # remembers each sub-expansion's open/closed state

    # ---- header ------------------------------------------------------------ #
    with ui.row().classes("items-center gap-2 w-full no-wrap"):
        ui.button(icon="arrow_back", on_click=on_cancel).props("flat round dense") \
            .tooltip("Back to configs")
        name_input = ui.input("Config name", value=name).classes("w-56")
        name_input.on_value_change(lambda e: name_holder.update(value=(e.value or "").strip()))
        ui.space()
        ui.toggle({"both": "Form + YAML", "form": "Form", "yaml": "YAML"}, value="both",
                  on_change=lambda e: _set_view(e.value)).props("no-caps dense") \
            .tooltip("Choose what to show")
        ui.button("Save", icon="save", on_click=lambda: _do_save()).props("unelevated")
        ui.button("Run", icon="play_arrow", on_click=lambda: _do_run()).props("outline")
        ui.button("Check on target", icon="fact_check", on_click=lambda: _do_check()).props("flat dense")
        if on_export is not None:
            ui.button("Export", icon="file_download", on_click=lambda: _do_export()) \
                .props("flat dense").tooltip("Save the current YAML to a file on the host")

    status = ui.row().classes("items-center gap-2 min-h-6")

    def show_status(ok: Optional[bool], text: str):
        status.clear()
        with status:
            ui.icon("check_circle" if ok else ("error" if ok is False else "info"),
                    color="positive" if ok else ("negative" if ok is False else "grey"))
            ui.label(text).classes("text-sm " + ("text-positive" if ok else
                     ("text-negative" if ok is False else "text-grey")))

    def revalidate():
        ok, msgs = validate_yaml_text(cm.value)
        if ok:
            show_status(True, "Valid config")
        else:
            extra = f"  (+{len(msgs) - 1} more)" if len(msgs) > 1 else ""
            show_status(False, (msgs[0] if msgs else "Invalid") + extra)

    # ---- sync bridge ------------------------------------------------------- #
    def sync_to_yaml():
        text = dump_yaml(model)
        if text != cm.value:
            cm.value = text
        revalidate()

    def sync_to_form():
        parsed, err = parse_yaml(cm.value)
        if err:
            show_status(False, err)
            return
        if dump_yaml(parsed or {}) == dump_yaml(model):
            revalidate()
            return
        model.clear()
        model.update(parsed or {})
        render_section()
        revalidate()

    def on_cm_change():
        t = debounce["timer"]
        if t is not None:
            t.active = False
        debounce["timer"] = ui.timer(0.6, sync_to_form, once=True)

    # ---- generic field helpers -------------------------------------------- #
    def setter(container: dict, key: str, cast=None, drop_empty=True):
        def handler(e):
            v = e.value
            if cast is not None and v not in (None, ""):
                try:
                    v = cast(v)
                except (ValueError, TypeError):
                    pass
            if drop_empty and v in (None, ""):
                container.pop(key, None)
            else:
                container[key] = v
            sync_to_yaml()
        return handler

    def restructure(fn):
        """Wrap a handler that changes structure: apply, re-render section, resync."""
        def handler(e):
            fn(e)
            render_section()
            sync_to_yaml()
        return handler

    def _expansion(key, title, icon=None, opened=False):
        exp = ui.expansion(title, icon=icon, value=expanded.get(key, opened)).classes("w-full")
        exp.on_value_change(lambda e: expanded.__setitem__(key, e.value))
        return exp

    def _text_list_input(label, container, key, placeholder=""):
        ui.input(label, value=_values_text(container.get(key)), placeholder=placeholder,
                 on_change=lambda e: (_set_list(container, key, _csv_list(e.value)),
                                      sync_to_yaml())).classes("w-full")

    def _set_list(container, key, values):
        if values:
            container[key] = values
        else:
            container.pop(key, None)

    def _dict_editor(title, parent, key):
        d = parent.get(key) or {}
        with _expansion(f"dict-{key}", f"{title} ({len(d)})"):
            with ui.column().classes("w-full gap-1"):
                for k in list(d.keys()):
                    with ui.row().classes("gap-1 w-full items-center no-wrap"):
                        kw = ui.input("key", value=k).classes("grow")
                        vw = ui.input("value", value=str(d.get(k, ""))).classes("grow")

                        def upd(_e=None, oldk=k, kwid=kw, vwid=vw):
                            dd = parent.setdefault(key, {})
                            newk = (kwid.value or "").strip()
                            dd.pop(oldk, None)
                            if newk:
                                dd[newk] = vwid.value
                            if not dd:
                                parent.pop(key, None)
                            sync_to_yaml()
                        kw.on("blur", upd)
                        vw.on("blur", upd)
                        ui.button(icon="delete",
                                  on_click=restructure(lambda e, kk=k: (d.pop(kk, None),
                                       parent.pop(key, None) if not d else None))) \
                            .props("flat round dense color=negative")

                def add(_e=None):
                    dd = parent.setdefault(key, {})
                    n, i = "key", 1
                    while n in dd:
                        i += 1
                        n = f"key{i}"
                    dd[n] = ""
                ui.button("Add", icon="add", on_click=restructure(add)).props("flat dense")

    def _card(title=None):
        c = ui.card().classes("studio-card w-full p-3 gap-2")
        if title:
            with c:
                ui.label(title).classes("text-sm font-semibold text-gray-600")
        return c

    # ---- section: benchmark ------------------------------------------------ #
    def _benchmark_section():
        bench = model.setdefault("benchmark", {})
        with _card():
            ui.input("Name", value=bench.get("name", ""),
                     on_change=setter(bench, "name")).classes("w-full")
            ui.input("Description", value=bench.get("description", ""),
                     on_change=setter(bench, "description")).classes("w-full")
            ui.input("Workdir (on the target)", value=bench.get("workdir", ""),
                     on_change=setter(bench, "workdir")).classes("w-full")
            with ui.row().classes("gap-2 w-full"):
                ui.select(EXECUTORS, label="Executor", value=bench.get("executor", "local"),
                          on_change=restructure(lambda e: bench.__setitem__("executor", e.value))).classes("grow")
                ui.select(SEARCH_METHODS, label="Search method",
                          value=bench.get("search_method", "exhaustive"),
                          on_change=restructure(lambda e: bench.__setitem__("search_method", e.value))).classes("grow")
            with ui.row().classes("gap-2 w-full"):
                ui.number("Repetitions", value=bench.get("repetitions", 1), min=1, format="%d",
                          on_change=setter(bench, "repetitions", cast=int)).classes("grow")
                ui.number("Parallel", value=bench.get("parallel"), min=1, format="%d",
                          on_change=setter(bench, "parallel", cast=int)).classes("grow") \
                    .tooltip("Max concurrent test executions (1 = sequential)")
                ui.number("Random seed", value=bench.get("random_seed"), format="%d",
                          on_change=setter(bench, "random_seed", cast=int)).classes("grow")
            ui.input("Cache file (optional)", value=bench.get("cache_file", ""),
                     on_change=setter(bench, "cache_file")).classes("w-full")
            ui.checkbox("Create all execution folders upfront",
                        value=bool(bench.get("create_folders_upfront")),
                        on_change=setter(bench, "create_folders_upfront", drop_empty=False)) \
                .tooltip("Enables SKIPPED status visibility")

        _search_config(bench)

        with _card("SLURM options"):
            _slurm_options(bench)
        with _card("Budget & variable selection"):
            with ui.row().classes("gap-2 w-full"):
                ui.number("Max core-hours", value=bench.get("max_core_hours"), step=1,
                          on_change=setter(bench, "max_core_hours", cast=float)).classes("grow") \
                    .tooltip("Budget limit; runs stop once exceeded")
                ui.number("Estimated time / test (s)", value=bench.get("estimated_time_seconds"),
                          step=1, on_change=setter(bench, "estimated_time_seconds", cast=float)).classes("grow") \
                    .tooltip("Used by --dry-run to estimate total time")
            ui.input("cores_expr (Jinja, e.g. {{ nodes * ppn }})", value=bench.get("cores_expr", ""),
                     on_change=setter(bench, "cores_expr")).classes("w-full") \
                .tooltip("Computes cores per test for the core-hour budget")
            _text_list_input("report_vars (comma-separated)", bench, "report_vars",
                             placeholder="nodes, ppn")
            _text_list_input("exhaustive_vars (comma-separated)", bench, "exhaustive_vars")
            _text_list_input("cache_exclude_vars (comma-separated)", bench, "cache_exclude_vars")

    def _slurm_options(bench):
        so = bench.get("slurm_options") or {}
        # commands
        with ui.column().classes("w-full gap-2 p-1"):
            cmds = so.get("commands") or {}
            with _expansion("slurm-cmds", f"Command overrides ({len(cmds)})", "build"):
                with ui.column().classes("w-full gap-1"):
                    for cmd_key in ("submit", "status", "info", "cancel"):
                        ui.input(cmd_key, value=cmds.get(cmd_key, ""),
                                 on_change=lambda e, k=cmd_key: (_set_nested(bench, ["slurm_options", "commands", k], e.value),
                                                                 sync_to_yaml())).classes("w-full")
                    ui.label("Templates support {job_id}. Leave blank to use SLURM defaults.") \
                        .classes("text-xs text-grey")
            ui.number("poll_interval (s)", value=so.get("poll_interval"), min=1, format="%d",
                      on_change=lambda e: (_set_nested(bench, ["slurm_options", "poll_interval"],
                                                       int(e.value) if e.value else None), sync_to_yaml())).classes("w-56") \
                .tooltip("How often to poll SLURM job status")
            # allocation (single-allocation mode)
            alloc = so.get("allocation") or {}
            with _expansion("slurm-alloc", "Single-allocation mode", "layers"):
                with ui.column().classes("w-full gap-1"):
                    ui.select(ALLOCATION_MODES, label="mode", value=alloc.get("mode", "per-test"),
                              on_change=lambda e: (_set_nested(bench, ["slurm_options", "allocation", "mode"], e.value),
                                                   sync_to_yaml())).classes("w-56")
                    ui.number("test_timeout (s)", value=alloc.get("test_timeout", 3600), min=1, format="%d",
                              on_change=lambda e: (_set_nested(bench, ["slurm_options", "allocation", "test_timeout"],
                                                              int(e.value) if e.value else 3600), sync_to_yaml())).classes("w-56")
                    ui.textarea("allocation_script (SBATCH directives + setup)",
                                value=alloc.get("allocation_script", ""),
                                on_change=lambda e: (_set_nested(bench, ["slurm_options", "allocation", "allocation_script"], e.value),
                                                     sync_to_yaml())).classes("w-full").props("autogrow")

    def _set_nested(root, path, value):
        """Set root[path...] = value; prune empty containers when value is blank."""
        if value in (None, ""):
            # walk to parent, pop leaf, then prune empty dicts back up
            node = root
            for k in path[:-1]:
                node = node.get(k) if isinstance(node, dict) else None
                if node is None:
                    return
            node.pop(path[-1], None)
            # prune empties
            for i in range(len(path) - 1, 0, -1):
                parent, k = root, None
                for kk in path[:i - 1]:
                    parent = parent.get(kk, {})
                container = parent.get(path[i - 1]) if isinstance(parent, dict) else None
                if isinstance(container, dict) and not container:
                    parent.pop(path[i - 1], None)
            return
        node = root
        for k in path[:-1]:
            node = node.setdefault(k, {})
        node[path[-1]] = value

    def _search_config(bench):
        method = bench.get("search_method", "exhaustive")
        if method == "random":
            rc = bench.setdefault("random_config", {})
            with _card("Random sampling"):
                with ui.row().classes("gap-2 w-full"):
                    ui.number("n_samples", value=rc.get("n_samples"), min=1, format="%d",
                              on_change=setter(rc, "n_samples", cast=int)).classes("grow")
                    ui.number("percentage (0-1)", value=rc.get("percentage"), step=0.05,
                              on_change=setter(rc, "percentage", cast=float)).classes("grow")
                ui.checkbox("Fallback to exhaustive", value=rc.get("fallback_to_exhaustive", True),
                            on_change=setter(rc, "fallback_to_exhaustive", drop_empty=False))
                ui.label("Set exactly one of n_samples or percentage.").classes("text-xs text-grey")
        elif method == "bayesian":
            bc = bench.setdefault("bayesian_config", {})
            with _card("Bayesian optimization"):
                with ui.row().classes("gap-2 w-full"):
                    ui.input("objective_metric (required)", value=bc.get("objective_metric", ""),
                             on_change=setter(bc, "objective_metric")).classes("grow")
                    ui.select(OBJECTIVES, label="objective", value=bc.get("objective", "minimize"),
                              on_change=setter(bc, "objective", drop_empty=False)).classes("w-40")
                with ui.row().classes("gap-2 w-full"):
                    ui.number("n_iterations", value=bc.get("n_iterations", 20), min=1, format="%d",
                              on_change=setter(bc, "n_iterations", cast=int)).classes("grow")
                    ui.number("n_initial_points", value=bc.get("n_initial_points", 5), min=1, format="%d",
                              on_change=setter(bc, "n_initial_points", cast=int)).classes("grow")
                with ui.row().classes("gap-2 w-full"):
                    ui.select(ACQUISITION_FUNCS, label="acquisition_func",
                              value=bc.get("acquisition_func", "EI"),
                              on_change=setter(bc, "acquisition_func", drop_empty=False)).classes("grow")
                    ui.select(BASE_ESTIMATORS, label="base_estimator",
                              value=bc.get("base_estimator", "RF"),
                              on_change=setter(bc, "base_estimator", drop_empty=False)).classes("grow")
                with ui.row().classes("gap-2 w-full"):
                    ui.number("xi", value=bc.get("xi", 0.01), step=0.01,
                              on_change=setter(bc, "xi", cast=float)).classes("grow")
                    ui.number("kappa", value=bc.get("kappa", 1.96), step=0.1,
                              on_change=setter(bc, "kappa", cast=float)).classes("grow")
                    ui.number("xi_boost_factor", value=bc.get("xi_boost_factor", 5.0), step=0.5,
                              on_change=setter(bc, "xi_boost_factor", cast=float)).classes("grow")
                with ui.row().classes("gap-2 w-full items-center"):
                    ui.checkbox("early_stop_on_convergence",
                                value=bool(bc.get("early_stop_on_convergence")),
                                on_change=setter(bc, "early_stop_on_convergence", drop_empty=False))
                    ui.number("convergence_patience", value=bc.get("convergence_patience", 3), min=1,
                              format="%d", on_change=setter(bc, "convergence_patience", cast=int)).classes("grow")
                    ui.number("max_retries", value=bc.get("max_retries", 10), min=0, format="%d",
                              on_change=setter(bc, "max_retries", cast=int)).classes("grow")
                ui.checkbox("fallback_to_exhaustive", value=bc.get("fallback_to_exhaustive", True),
                            on_change=setter(bc, "fallback_to_exhaustive", drop_empty=False))
        elif method == "adaptive":
            with _card():
                ui.label("Adaptive: define exactly one variable with an 'adaptive' block "
                         "in the Variables section.").classes("text-xs text-grey")

    # ---- section: variables ------------------------------------------------ #
    def _vars_section():
        variables = model.setdefault("vars", {})
        with ui.column().classes("w-full gap-2"):
            if not variables:
                ui.label("No variables yet.").classes("text-xs text-grey italic")
            for vname in list(variables.keys()):
                _var_card(variables, vname)
            ui.button("Add variable", icon="add",
                      on_click=restructure(lambda e: _add_var(variables))).props("flat dense")

    def _add_var(variables):
        i, new = 1, "var"
        while new in variables:
            i += 1
            new = f"var{i}"
        variables[new] = {"type": "int", "sweep": {"mode": "list", "values": [1, 2, 4]}}

    def _var_card(variables, vname):
        vardef = variables[vname]
        with _card():
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                nw = ui.input("Name", value=vname).classes("grow")

                def rename(_e=None, old=vname, widget=nw):
                    new = (widget.value or "").strip()
                    if new and new != old and new not in variables:
                        items = list(variables.items())
                        variables.clear()
                        for k, v in items:
                            variables[new if k == old else k] = v
                        render_section()
                        sync_to_yaml()
                nw.on("blur", rename)
                ui.select(VAR_TYPES, label="Type", value=vardef.get("type", "int"),
                          on_change=setter(vardef, "type", drop_empty=False)).classes("w-28")
                ui.select(["sweep", "expr", "adaptive"], label="Kind", value=var_kind(vardef),
                          on_change=restructure(lambda e, n=vname: _switch_kind(variables, n, e.value))).classes("w-32")
                ui.button(icon="delete",
                          on_click=restructure(lambda e, n=vname: variables.pop(n, None))) \
                    .props("flat round dense color=negative")

            k = var_kind(vardef)
            if k == "expr":
                ui.input("Expression (Jinja2 or Python)", value=vardef.get("expr", ""),
                         on_change=setter(vardef, "expr")).classes("w-full")
            elif k == "adaptive":
                _adaptive_fields(vardef)
            else:
                _sweep_fields(variables, vname, vardef)

    def _sweep_fields(variables, vname, vardef):
        sweep = vardef.setdefault("sweep", {})
        mode = sweep.get("mode", "list")
        with ui.row().classes("gap-2 w-full items-center"):
            ui.select(["list", "range"], label="Mode", value=mode,
                      on_change=restructure(lambda e, n=vname: _switch_mode(variables, n, e.value))).classes("w-32")
            if mode == "range":
                for fld in ("start", "end", "step"):
                    ui.number(fld, value=sweep.get(fld),
                              on_change=setter(sweep, fld, cast=int, drop_empty=False)).classes("grow")
            else:
                ui.input("Values (comma-separated)", value=_values_text(sweep.get("values")),
                         on_change=lambda e: (sweep.__setitem__("values", _parse_values(e.value)),
                                              sync_to_yaml())).classes("grow")
        with ui.row().classes("gap-2 w-full"):
            ui.input("when (optional Jinja2 condition)", value=vardef.get("when", ""),
                     on_change=setter(vardef, "when")).classes("grow")
            ui.input("default (when false)", value=str(vardef.get("default", "")),
                     on_change=setter(vardef, "default")).classes("w-40")

    def _adaptive_fields(vardef):
        ad = vardef.setdefault("adaptive", {})
        with ui.column().classes("w-full gap-1"):
            with ui.row().classes("gap-2 w-full"):
                ui.input("initial", value=str(ad.get("initial", "")),
                         on_change=setter(ad, "initial", cast=_num_or_str)).classes("grow")
                ui.number("factor", value=ad.get("factor"), step=0.5,
                          on_change=setter(ad, "factor", cast=float)).classes("grow")
                ui.number("increment", value=ad.get("increment"),
                          on_change=setter(ad, "increment", cast=float)).classes("grow")
            ui.input("step_expr (Jinja2, alternative to factor/increment)",
                     value=ad.get("step_expr", ""), on_change=setter(ad, "step_expr")).classes("w-full")
            ui.input("stop_when (required)", value=ad.get("stop_when", ""),
                     on_change=setter(ad, "stop_when")).classes("w-full")
            with ui.row().classes("gap-2 w-full"):
                ui.number("max_iterations", value=ad.get("max_iterations"), min=1, format="%d",
                          on_change=setter(ad, "max_iterations", cast=int)).classes("grow")
                ui.select(DIRECTIONS, label="direction", value=ad.get("direction", "ascending"),
                          on_change=setter(ad, "direction", drop_empty=False)).classes("grow")

    def _switch_kind(variables, vname, new_kind):
        vardef = variables[vname]
        for key in ("sweep", "expr", "adaptive", "when", "default"):
            vardef.pop(key, None)
        if new_kind == "expr":
            vardef["expr"] = ""
        elif new_kind == "adaptive":
            vardef["adaptive"] = {"initial": 1, "factor": 2, "stop_when": "exit_code != 0"}
        else:
            vardef["sweep"] = {"mode": "list", "values": [1, 2, 4]}

    def _switch_mode(variables, vname, new_mode):
        sweep = variables[vname].setdefault("sweep", {})
        sweep.clear()
        if new_mode == "range":
            sweep.update({"mode": "range", "start": 1, "end": 8, "step": 1})
        else:
            sweep.update({"mode": "list", "values": [1, 2, 4]})

    # ---- section: command -------------------------------------------------- #
    def _command_section():
        cmd = model.setdefault("command", {})
        with _card():
            ui.textarea("Command template (Jinja2)", value=cmd.get("template", ""),
                        on_change=setter(cmd, "template")).classes("w-full").props("autogrow")
            _dict_editor("Labels", cmd, "labels")
            _dict_editor("Environment variables", cmd, "env")

    # ---- section: scripts -------------------------------------------------- #
    def _scripts_section():
        scripts = model.setdefault("scripts", [])
        with ui.column().classes("w-full gap-2"):
            for idx in range(len(scripts)):
                _script_card(scripts, idx)

            def add(_e=None):
                scripts.append({"name": f"script{len(scripts) + 1}",
                                "script_template": "#!/bin/bash\n{{ command.template }}\n"})
            ui.button("Add script", icon="add", on_click=restructure(add)).props("flat dense")

    def _script_card(scripts, idx):
        sc = scripts[idx]
        with _card():
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                ui.input("Name", value=sc.get("name", ""),
                         on_change=setter(sc, "name")).classes("grow")
                ui.input("submit (optional)", value=sc.get("submit", ""),
                         on_change=setter(sc, "submit")).classes("w-40") \
                    .tooltip("Command to submit this script (e.g. sbatch); overrides slurm default")
                ui.button(icon="delete", on_click=restructure(lambda e, i=idx: scripts.pop(i))) \
                    .props("flat round dense color=negative")
            ui.textarea("Script template", value=sc.get("script_template", ""),
                        on_change=setter(sc, "script_template")).classes("w-full").props("autogrow")
            _parser_editor(sc, idx)
            _inputs_editor(sc, idx)
            post = sc.get("post") or {}
            with _expansion(f"post-{idx}", "Post-execution script"):
                ui.textarea("post.script", value=post.get("script", ""),
                            on_change=lambda e: (_set_post(sc, e.value), sync_to_yaml())) \
                    .classes("w-full").props("autogrow")

    def _set_post(sc, value):
        if value:
            sc.setdefault("post", {})["script"] = value
        else:
            sc.pop("post", None)

    def _parser_editor(sc, idx):
        parser = sc.get("parser")
        with _expansion(f"parser-{idx}", "Parser" + (" (set)" if parser else "")):
            with ui.column().classes("w-full gap-1"):
                if parser is None:
                    ui.button("Add parser", icon="add",
                              on_click=restructure(lambda e: sc.__setitem__(
                                  "parser", {"file": "", "metrics": [{"name": "metric"}],
                                             "parser_script": "def parse(file_path):\n    return {}\n"}))) \
                        .props("flat dense")
                    return
                ui.input("File to parse (Jinja2)", value=parser.get("file", ""),
                         on_change=setter(parser, "file")).classes("w-full")
                metrics = parser.setdefault("metrics", [])
                ui.label("Metrics").classes("text-xs font-semibold")
                for mi in range(len(metrics)):
                    with ui.row().classes("gap-1 w-full items-center no-wrap"):
                        ui.input("name", value=metrics[mi].get("name", ""),
                                 on_change=setter(metrics[mi], "name")).classes("grow")
                        ui.input("path (optional)", value=metrics[mi].get("path", ""),
                                 on_change=setter(metrics[mi], "path")).classes("grow") \
                            .tooltip("e.g. a JSON path; optional if parser_script returns the value")
                        ui.button(icon="delete",
                                  on_click=restructure(lambda e, i=mi: metrics.pop(i))) \
                            .props("flat round dense color=negative")
                ui.button("Add metric", icon="add",
                          on_click=restructure(lambda e: metrics.append({"name": "metric"}))).props("flat dense")
                ui.textarea("parser_script (def parse(file_path))",
                            value=parser.get("parser_script", ""),
                            on_change=setter(parser, "parser_script")).classes("w-full").props("autogrow")
                ui.button("Remove parser", icon="delete",
                          on_click=restructure(lambda e: sc.pop("parser", None))) \
                    .props("flat dense color=negative")

    def _inputs_editor(sc, idx):
        inputs = sc.get("inputs") or []
        with _expansion(f"inputs-{idx}", f"Input files ({len(inputs)})", "insert_drive_file"):
            with ui.column().classes("w-full gap-1"):
                ui.label("Files rendered and written before the script runs; "
                         "reference via {{ inputs.<name>.path }}.").classes("text-xs text-grey")
                for ii in range(len(inputs)):
                    inp = inputs[ii]
                    with ui.card().classes("w-full p-2 gap-1"):
                        with ui.row().classes("items-center gap-2 w-full no-wrap"):
                            ui.input("name", value=inp.get("name", ""),
                                     on_change=setter(inp, "name")).classes("grow")
                            ui.input("mode (e.g. 0644)", value=inp.get("mode", ""),
                                     on_change=setter(inp, "mode")).classes("w-32")
                            ui.button(icon="delete",
                                      on_click=restructure(lambda e, i=ii: inputs.pop(i))) \
                                .props("flat round dense color=negative")
                        ui.input("path (destination, Jinja2)", value=inp.get("path", ""),
                                 on_change=setter(inp, "path")).classes("w-full")
                        ui.textarea("template (inline content) OR use file below",
                                    value=inp.get("template", ""),
                                    on_change=setter(inp, "template")).classes("w-full").props("autogrow")
                        ui.input("file (path to a template file, alternative to template)",
                                 value=inp.get("file", ""), on_change=setter(inp, "file")).classes("w-full")

                def add(_e=None):
                    sc.setdefault("inputs", []).append({"name": f"input{len(inputs) + 1}", "path": ""})
                ui.button("Add input file", icon="add", on_click=restructure(add)).props("flat dense")

    # ---- section: output --------------------------------------------------- #
    def _output_section():
        sink = model.setdefault("output", {}).setdefault("sink", {})
        with _card():
            with ui.row().classes("gap-2 w-full"):
                ui.select(SINK_TYPES, label="Sink type", value=sink.get("type", "csv"),
                          on_change=setter(sink, "type", drop_empty=False)).classes("grow")
                ui.input("Path", value=sink.get("path", ""),
                         on_change=setter(sink, "path")).classes("grow")
                ui.input("Table (sqlite)", value=sink.get("table", ""),
                         on_change=setter(sink, "table")).classes("w-40")
            _text_list_input("Exclude fields (comma-separated, e.g. benchmark.description)",
                             sink, "exclude")

    # ---- section: probes --------------------------------------------------- #
    def _probes_section():
        bench = model.setdefault("benchmark", {})
        probes = bench.get("probes") or {}
        with _card():
            def pset(key, default):
                def handler(e):
                    p = bench.setdefault("probes", {})
                    p[key] = e.value
                    sync_to_yaml()
                return handler
            ui.checkbox("system_snapshot (collect node info)",
                        value=probes.get("system_snapshot", True), on_change=pset("system_snapshot", True))
            ui.checkbox("execution_index (metadata for 'iops find')",
                        value=probes.get("execution_index", True), on_change=pset("execution_index", True))
            ui.checkbox("resource_sampling (CPU/memory tracing)",
                        value=probes.get("resource_sampling", False), on_change=pset("resource_sampling", False))
            ui.checkbox("gpu_sampling (GPU metrics)",
                        value=probes.get("gpu_sampling", False), on_change=pset("gpu_sampling", False))
            ui.number("sampling_interval (seconds)", value=probes.get("sampling_interval", 1.0),
                      step=0.5, on_change=lambda e: (bench.setdefault("probes", {}).__setitem__(
                          "sampling_interval", float(e.value) if e.value else 1.0), sync_to_yaml())).classes("w-56")
        with _card("Version probes"):
            ui.label("Component -> shell command that prints its version "
                     "(captured once per execution).").classes("text-xs text-grey")
            _dict_editor("versions", bench.setdefault("probes", {}), "versions")
            if not (bench.get("probes") or {}).get("versions"):
                bench.get("probes", {}).pop("versions", None)

    # ---- section: reporting ------------------------------------------------ #
    def _reporting_section():
        rep = model.get("reporting") or {}
        with _card():
            ui.checkbox("Enable report generation", value=rep.get("enabled", False),
                        on_change=lambda e: _toggle_reporting(e.value))
            if not rep.get("enabled"):
                ui.label("Enable to configure the HTML report, plots and gallery.") \
                    .classes("text-xs text-grey")
                return
        rep = model.setdefault("reporting", {})
        with _card("General"):
            ui.input("Output filename", value=rep.get("output_filename", "analysis_report.html"),
                     on_change=setter(rep, "output_filename")).classes("w-full")
            ui.input("Output dir (optional)", value=rep.get("output_dir", ""),
                     on_change=setter(rep, "output_dir")).classes("w-full")
        with _card("Theme"):
            theme = rep.get("theme") or {}
            ui.select(PLOT_STYLES, label="Style", value=theme.get("style", "plotly_white"),
                      on_change=lambda e: (rep.setdefault("theme", {}).__setitem__("style", e.value), sync_to_yaml())).classes("w-64")
            ui.input("font_family", value=theme.get("font_family", ""),
                     on_change=lambda e: (_set_nested(rep, ["theme", "font_family"], e.value), sync_to_yaml())).classes("w-full")
            ui.input("colors (comma-separated hex)", value=_values_text(theme.get("colors")),
                     on_change=lambda e: (_set_nested(rep, ["theme", "colors"], _csv_list(e.value) or None), sync_to_yaml())).classes("w-full")
        with _card("Sections"):
            sections = rep.get("sections") or {}
            with ui.column().classes("gap-0 w-full"):
                for sec in REPORT_SECTIONS:
                    default = sec != "bayesian_parameter_evolution"
                    ui.checkbox(sec, value=sections.get(sec, default),
                                on_change=lambda e, s=sec: (rep.setdefault("sections", {}).__setitem__(s, e.value), sync_to_yaml()))
        with _card("Best results"):
            br = rep.get("best_results") or {}
            with ui.row().classes("gap-2 w-full items-center"):
                ui.number("top_n", value=br.get("top_n", 5), min=1, format="%d",
                          on_change=lambda e: (_set_nested(rep, ["best_results", "top_n"], int(e.value or 5)), sync_to_yaml())).classes("grow")
                ui.number("min_samples", value=br.get("min_samples", 1), min=1, format="%d",
                          on_change=lambda e: (_set_nested(rep, ["best_results", "min_samples"], int(e.value or 1)), sync_to_yaml())).classes("grow")
                ui.checkbox("show_command", value=br.get("show_command", True),
                            on_change=lambda e: (_set_nested(rep, ["best_results", "show_command"], e.value), sync_to_yaml()))
        with _card("Plot defaults"):
            pd = rep.get("plot_defaults") or {}
            with ui.row().classes("gap-2 w-full"):
                ui.number("height", value=pd.get("height", 500), min=100, format="%d",
                          on_change=lambda e: (_set_nested(rep, ["plot_defaults", "height"], int(e.value or 500)), sync_to_yaml())).classes("grow")
                ui.number("width (optional)", value=pd.get("width"), min=100, format="%d",
                          on_change=lambda e: (_set_nested(rep, ["plot_defaults", "width"], int(e.value) if e.value else None), sync_to_yaml())).classes("grow")
        _gallery_editor(rep)
        _plots_list_editor(rep)
        _metric_plots_editor(rep)

    def _toggle_reporting(enabled):
        if enabled:
            model.setdefault("reporting", {})["enabled"] = True
        else:
            model.pop("reporting", None)
        render_section()
        sync_to_yaml()

    def _gallery_editor(rep):
        with _card("Gallery"):
            g = rep.get("gallery") or {}
            ui.checkbox("Enable gallery", value=g.get("enabled", False),
                        on_change=lambda e: (_set_nested(rep, ["gallery", "enabled"], e.value), sync_to_yaml()))
            with ui.row().classes("gap-2 w-full"):
                ui.input("folder", value=g.get("folder", "images"),
                         on_change=lambda e: (_set_nested(rep, ["gallery", "folder"], e.value), sync_to_yaml())).classes("grow")
                ui.input("pattern", value=g.get("pattern", "*.png"),
                         on_change=lambda e: (_set_nested(rep, ["gallery", "pattern"], e.value), sync_to_yaml())).classes("grow")
            with ui.row().classes("gap-2 w-full"):
                ui.input("title", value=g.get("title", "Image Gallery"),
                         on_change=lambda e: (_set_nested(rep, ["gallery", "title"], e.value), sync_to_yaml())).classes("grow")
                ui.number("max_width (px)", value=g.get("max_width"), min=1, format="%d",
                          on_change=lambda e: (_set_nested(rep, ["gallery", "max_width"], int(e.value) if e.value else None), sync_to_yaml())).classes("w-40")
            ui.input("sources (comma-separated Jinja2 paths)", value=_values_text(g.get("sources")),
                     on_change=lambda e: (_set_nested(rep, ["gallery", "sources"], _csv_list(e.value) or None), sync_to_yaml())).classes("w-full")
            ui.input("caption_vars (comma-separated)", value=_values_text(g.get("caption_vars")),
                     on_change=lambda e: (_set_nested(rep, ["gallery", "caption_vars"], _csv_list(e.value) or None), sync_to_yaml())).classes("w-full")

    def _plots_list_editor(rep):
        plots = rep.get("default_plots") or []
        with _card(f"Default plots ({len(plots)})"):
            ui.label("Applied to every metric unless overridden per-metric below.") \
                .classes("text-xs text-grey")
            for i in range(len(plots)):
                _plot_card(plots, i, key_prefix=f"dp-{i}")

            def add(_e=None):
                rep.setdefault("default_plots", []).append({"type": "line"})
            ui.button("Add plot", icon="add", on_click=restructure(add)).props("flat dense")

    def _metric_plots_editor(rep):
        metrics = rep.get("metrics") or {}
        with _card(f"Per-metric plots ({len(metrics)})"):
            ui.label("Plots for a specific metric by name.").classes("text-xs text-grey")
            for mname in list(metrics.keys()):
                mplots = (metrics.get(mname) or {}).get("plots") or []
                with ui.card().classes("w-full p-2 gap-1"):
                    with ui.row().classes("items-center gap-2 w-full no-wrap"):
                        ui.label(mname).classes("font-medium")
                        ui.space()
                        ui.button(icon="delete",
                                  on_click=restructure(lambda e, m=mname: metrics.pop(m, None))) \
                            .props("flat round dense color=negative")
                    for i in range(len(mplots)):
                        _plot_card(mplots, i, key_prefix=f"mp-{mname}-{i}")
                    ui.button("Add plot", icon="add",
                              on_click=restructure(lambda e, m=mname: metrics[m].setdefault("plots", []).append({"type": "line"}))) \
                        .props("flat dense")

            new_metric = {"name": ""}
            with ui.row().classes("gap-2 w-full items-center"):
                mi = ui.input("metric name").classes("grow")
                mi.on_value_change(lambda e: new_metric.update(name=(e.value or "").strip()))

                def add_metric(_e=None):
                    n = new_metric["name"]
                    if n and n not in metrics:
                        rep.setdefault("metrics", {})[n] = {"plots": [{"type": "line"}]}
                ui.button("Add metric", icon="add", on_click=restructure(add_metric)).props("flat dense")

    def _plot_card(plots, idx, key_prefix):
        p = plots[idx]
        with ui.card().classes("w-full p-2 gap-1"):
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                ui.select(PLOT_TYPES, label="type", value=p.get("type", "line"),
                          on_change=setter(p, "type", drop_empty=False)).classes("grow")
                ui.input("title", value=p.get("title", ""),
                         on_change=setter(p, "title")).classes("grow")
                ui.button(icon="delete", on_click=restructure(lambda e, i=idx: plots.pop(i))) \
                    .props("flat round dense color=negative")
            with _expansion(f"{key_prefix}-data", "Data & grouping"):
                with ui.column().classes("w-full gap-1"):
                    with ui.row().classes("gap-2 w-full"):
                        ui.input("x_var", value=p.get("x_var", ""), on_change=setter(p, "x_var")).classes("grow")
                        ui.input("y_var", value=p.get("y_var", ""), on_change=setter(p, "y_var")).classes("grow")
                        ui.input("z_metric", value=p.get("z_metric", ""), on_change=setter(p, "z_metric")).classes("grow")
                    with ui.row().classes("gap-2 w-full"):
                        ui.input("group_by", value=p.get("group_by", ""), on_change=setter(p, "group_by")).classes("grow")
                        ui.input("color_by", value=p.get("color_by", ""), on_change=setter(p, "color_by")).classes("grow")
                        ui.input("size_by", value=p.get("size_by", ""), on_change=setter(p, "size_by")).classes("grow")
            with _expansion(f"{key_prefix}-style", "Style & axes"):
                with ui.column().classes("w-full gap-1"):
                    with ui.row().classes("gap-2 w-full"):
                        ui.input("xaxis_label", value=p.get("xaxis_label", ""), on_change=setter(p, "xaxis_label")).classes("grow")
                        ui.input("yaxis_label", value=p.get("yaxis_label", ""), on_change=setter(p, "yaxis_label")).classes("grow")
                    with ui.row().classes("gap-2 w-full"):
                        ui.input("colorscale", value=p.get("colorscale", "Viridis"), on_change=setter(p, "colorscale")).classes("grow")
                        ui.number("height", value=p.get("height"), min=100, format="%d",
                                  on_change=setter(p, "height", cast=int)).classes("grow")
                        ui.number("width", value=p.get("width"), min=100, format="%d",
                                  on_change=setter(p, "width", cast=int)).classes("grow")
                    with ui.row().classes("gap-x-4 w-full").style("flex-wrap:wrap"):
                        ui.checkbox("show_error_bars", value=p.get("show_error_bars", True),
                                    on_change=setter(p, "show_error_bars", drop_empty=False))
                        ui.checkbox("show_outliers", value=p.get("show_outliers", True),
                                    on_change=setter(p, "show_outliers", drop_empty=False))
                        ui.checkbox("per_variable", value=p.get("per_variable", False),
                                    on_change=setter(p, "per_variable", drop_empty=False))
                        ui.checkbox("include_metric", value=p.get("include_metric", True),
                                    on_change=setter(p, "include_metric", drop_empty=False))
            with _expansion(f"{key_prefix}-cov", "Coverage heatmap options"):
                with ui.column().classes("w-full gap-1"):
                    _text_list_input("row_vars (comma-separated)", p, "row_vars")
                    with ui.row().classes("gap-2 w-full"):
                        ui.input("col_var", value=p.get("col_var", ""), on_change=setter(p, "col_var")).classes("grow")
                        ui.select(AGGREGATIONS, label="aggregation", value=p.get("aggregation", "mean"),
                                  on_change=setter(p, "aggregation", drop_empty=False)).classes("grow")
                    with ui.row().classes("gap-2 w-full"):
                        ui.select(SORT_MODES, label="sort_rows_by", value=p.get("sort_rows_by", "index"),
                                  on_change=setter(p, "sort_rows_by", drop_empty=False)).classes("grow")
                        ui.select(SORT_MODES, label="sort_cols_by", value=p.get("sort_cols_by", "index"),
                                  on_change=setter(p, "sort_cols_by", drop_empty=False)).classes("grow")
                    with ui.row().classes("gap-x-4 w-full").style("flex-wrap:wrap"):
                        ui.checkbox("show_missing", value=p.get("show_missing", True),
                                    on_change=setter(p, "show_missing", drop_empty=False))
                        ui.checkbox("sort_ascending", value=p.get("sort_ascending", False),
                                    on_change=setter(p, "sort_ascending", drop_empty=False))

    # ---- section: constraints ---------------------------------------------- #
    def _constraints_section():
        constraints = model.get("constraints") or []
        with ui.column().classes("w-full gap-2"):
            for idx in range(len(constraints)):
                c = constraints[idx]
                with _card():
                    with ui.row().classes("gap-2 w-full items-center no-wrap"):
                        ui.input("name", value=c.get("name", ""),
                                 on_change=setter(c, "name")).classes("grow")
                        ui.select(VIOLATION_POLICIES, label="policy",
                                  value=c.get("violation_policy", "skip"),
                                  on_change=setter(c, "violation_policy", drop_empty=False)).classes("w-32")
                        ui.button(icon="delete", on_click=restructure(
                            lambda e, i=idx: (model.get("constraints").pop(i),
                                              model.pop("constraints", None) if not model.get("constraints") else None))) \
                            .props("flat round dense color=negative")
                    ui.input("rule (Jinja2 / Python boolean)", value=c.get("rule", ""),
                             on_change=setter(c, "rule")).classes("w-full")
                    ui.input("description (optional)", value=c.get("description", ""),
                             on_change=setter(c, "description")).classes("w-full")

            def add(_e=None):
                model.setdefault("constraints", []).append(
                    {"name": "constraint", "rule": "", "violation_policy": "skip"})
            ui.button("Add constraint", icon="add", on_click=restructure(add)).props("flat dense")

    _RENDERERS = {
        "benchmark": _benchmark_section, "vars": _vars_section, "command": _command_section,
        "scripts": _scripts_section, "output": _output_section, "probes": _probes_section,
        "reporting": _reporting_section, "constraints": _constraints_section,
    }

    def _section_count(key):
        if key == "vars":
            return len(model.get("vars") or {})
        if key == "scripts":
            return len(model.get("scripts") or [])
        if key == "constraints":
            return len(model.get("constraints") or [])
        return None

    # ---- rail + content + yaml -------------------------------------------- #
    def _build_rail():
        rail.clear()
        with rail:
            ui.label("Sections").classes("text-xs text-grey px-2 pt-1")
            for key, label, icon in _SECTIONS:
                active = key == state["section"]
                count = _section_count(key)
                text = f"{label}" + (f"  ({count})" if count is not None else "")
                btn = ui.button(text, icon=icon, on_click=lambda k=key: _select_section(k)) \
                    .props("flat align=left no-caps" + (" color=primary" if active else " color=grey-8")) \
                    .classes("w-full justify-start")
                if active:
                    btn.style("background:#e8f0fe;border-radius:6px")

    def render_section():
        content.clear()
        with content:
            with ui.row().classes("items-center gap-2 w-full"):
                label = next(l for k, l, _ in _SECTIONS if k == state["section"])
                icon = next(i for k, _, i in _SECTIONS if k == state["section"])
                ui.icon(icon).classes("text-primary")
                ui.label(label).classes("text-lg font-semibold")
            _RENDERERS[state["section"]]()
        _build_rail()

    def _select_section(key):
        state["section"] = key
        render_section()

    def _set_view(v):
        state["view"] = v
        rail.set_visibility(v in ("both", "form"))
        content.set_visibility(v in ("both", "form"))
        yaml_col.set_visibility(v in ("both", "yaml"))
        # In side-by-side, keep the form the wider pane. `min-width:0` (set on the
        # columns) lets flexbox actually shrink the CodeMirror instead of letting
        # its long lines dictate the width and squash the form to a sliver.
        content.style("flex:1.4 1 0" if v == "both" else "flex:1 1 0")

    # ---- actions ----------------------------------------------------------- #
    def _do_save():
        revalidate()
        on_save(name_holder["value"], cm.value)

    async def _do_run():
        await on_run(name_holder["value"], cm.value)

    async def _do_check():
        await on_check(name_holder["value"], cm.value)

    async def _do_export():
        await on_export(name_holder["value"], cm.value)

    # ---- layout ------------------------------------------------------------ #
    # `min-width:0` on the two flex columns is essential: without it a flex item
    # refuses to shrink below its content's intrinsic width, so the CodeMirror
    # (with long YAML lines) would keep its full width and squash the form.
    with ui.row().classes("w-full no-wrap gap-3 grow").style("min-height:0"):
        rail = ui.column().classes("gap-1") \
            .style("width:190px; height:100%; min-height:0; overflow:auto; flex:none")
        content = ui.column().classes("gap-2") \
            .style("flex:1.4 1 0; min-width:0; height:100%; min-height:0; overflow:auto; padding-right:6px")
        yaml_col = ui.column().classes("gap-1") \
            .style("flex:1 1 0; min-width:0; height:100%; min-height:0")
        with yaml_col:
            ui.label("YAML").classes("text-xs text-grey")
            cm = ui.codemirror(value=initial_yaml, language="YAML",
                               on_change=lambda e: on_cm_change()).classes("w-full") \
                .style("flex:1; min-width:0; min-height:0; overflow:auto; "
                       "border:1px solid #e0e0e0; border-radius:6px")

    render_section()
    revalidate()


def _num_or_str(v):
    for cast in (int, float):
        try:
            return cast(v)
        except (ValueError, TypeError):
            continue
    return v
