"""IOPS config builder: a side-by-side form + live YAML editor.

The single source of truth is the parsed config *dict* (``model``). The form and
the YAML editor are shown together and kept in sync both ways:
- editing a form field mutates ``model`` and re-serializes it into the YAML pane;
- editing the YAML (debounced) reparses it and rebuilds the form.

Loops are broken by comparing serialized forms: a sync is skipped when it would
not change the other side. The form renders known fields; sections it does not
cover (mpi, inputs, gallery, custom plots, slurm allocation) round-trip untouched
through ``model`` and stay editable in the always-visible YAML pane.

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
PLOT_STYLES = ["plotly_white", "plotly", "plotly_dark", "ggplot2", "seaborn", "simple_white"]
REPORT_SECTIONS = [
    "test_summary", "best_results", "variable_impact", "parallel_coordinates",
    "bayesian_evolution", "resource_sampling", "custom_plots", "gallery", "versions",
]


# --------------------------------------------------------------------------- #
# YAML <-> dict
# --------------------------------------------------------------------------- #
class _BlockDumper(yaml.SafeDumper):
    """Dumper that renders multi-line strings as literal ``|`` blocks."""


def _represent_str(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


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


# --------------------------------------------------------------------------- #
# Editor UI
# --------------------------------------------------------------------------- #
def build_editor(name: str, initial_yaml: str, *, on_save, on_cancel,
                 on_run, on_check) -> None:
    """Render the side-by-side config editor into the current container."""
    from nicegui import ui

    data, _ = parse_yaml(initial_yaml)
    model: dict = data if isinstance(data, dict) else {}
    name_holder = {"value": name}
    debounce = {"timer": None}
    expanded: dict = {}  # remembers each section's open/closed state across rebuilds

    # ---- header ------------------------------------------------------------ #
    with ui.row().classes("items-center gap-2 w-full no-wrap"):
        ui.button(icon="arrow_back", on_click=on_cancel).props("flat round dense") \
            .tooltip("Back to configs")
        name_input = ui.input("Config name", value=name).classes("w-64")
        name_input.on_value_change(lambda e: name_holder.update(value=(e.value or "").strip()))
        ui.space()
        ui.button("Save", icon="save", on_click=lambda: _do_save()).props("unelevated")
        ui.button("Run", icon="play_arrow", on_click=lambda: _do_run()).props("outline")
        ui.button("Check on target", icon="fact_check", on_click=lambda: _do_check()).props("flat")

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
        show_status(True if ok else False, "Valid config" if ok else (msgs[0] if msgs else "Invalid"))

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
        render_form()
        revalidate()

    def on_cm_change():
        t = debounce["timer"]
        if t is not None:
            t.active = False
        debounce["timer"] = ui.timer(0.6, sync_to_form, once=True)

    # ---- form helpers ------------------------------------------------------ #
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
        """Wrap a handler that changes structure: apply, rebuild form, resync.

        ``handler`` takes a required ``e`` so NiceGUI passes the event through to
        ``fn`` (a 0-required-arg handler would be called with no event, and any
        ``e.value`` inside ``fn`` would crash).
        """
        def handler(e):
            fn(e)
            render_form()
            sync_to_yaml()
        return handler

    # ---- form sections ----------------------------------------------------- #
    def render_form():
        form.clear()
        with form:
            _benchmark_section()
            _vars_section()
            _command_section()
            _scripts_section()
            _output_section()
            _probes_section()
            _reporting_section()
            _constraints_section()

    def _expansion(key, title, icon, opened=False):
        exp = ui.expansion(title, icon=icon, value=expanded.get(key, opened)) \
            .classes("w-full studio-card")
        exp.on_value_change(lambda e: expanded.__setitem__(key, e.value))
        return exp

    def _sub(key, title, opened=False):
        exp = ui.expansion(title, value=expanded.get(key, opened)).classes("w-full")
        exp.on_value_change(lambda e: expanded.__setitem__(key, e.value))
        return exp

    def _benchmark_section():
        bench = model.setdefault("benchmark", {})
        with _expansion("benchmark", "Benchmark", "science", opened=True):
            with ui.column().classes("w-full gap-2 p-1"):
                ui.input("Name", value=bench.get("name", ""),
                         on_change=setter(bench, "name")).classes("w-full")
                ui.input("Description", value=bench.get("description", ""),
                         on_change=setter(bench, "description")).classes("w-full")
                ui.input("Workdir (on the target)", value=bench.get("workdir", ""),
                         on_change=setter(bench, "workdir")).classes("w-full")
                with ui.row().classes("gap-2 w-full"):
                    ui.select(EXECUTORS, label="Executor", value=bench.get("executor", "local"),
                              on_change=setter(bench, "executor", drop_empty=False)).classes("grow")
                    ui.select(SEARCH_METHODS, label="Search method",
                              value=bench.get("search_method", "exhaustive"),
                              on_change=restructure(lambda e: bench.__setitem__("search_method", e.value))).classes("grow")
                with ui.row().classes("gap-2 w-full"):
                    ui.number("Repetitions", value=bench.get("repetitions", 1), min=1, format="%d",
                              on_change=setter(bench, "repetitions", cast=int)).classes("grow")
                    ui.number("Parallel", value=bench.get("parallel"), min=1, format="%d",
                              on_change=setter(bench, "parallel", cast=int)).classes("grow")
                    ui.number("Random seed", value=bench.get("random_seed"), format="%d",
                              on_change=setter(bench, "random_seed", cast=int)).classes("grow")
                ui.input("Cache file (optional)", value=bench.get("cache_file", ""),
                         on_change=setter(bench, "cache_file")).classes("w-full")
                ui.checkbox("Create all execution folders upfront",
                            value=bool(bench.get("create_folders_upfront")),
                            on_change=setter(bench, "create_folders_upfront", drop_empty=False))
                _search_config(bench)

    def _search_config(bench):
        method = bench.get("search_method", "exhaustive")
        if method == "random":
            rc = bench.setdefault("random_config", {})
            with ui.card().classes("w-full p-2 gap-1"):
                ui.label("Random sampling").classes("text-sm font-semibold")
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
            with ui.card().classes("w-full p-2 gap-1"):
                ui.label("Bayesian optimization").classes("text-sm font-semibold")
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
        elif method == "adaptive":
            with ui.card().classes("w-full p-2"):
                ui.label("Adaptive: define exactly one variable with an 'adaptive' block "
                         "below (or on the YAML pane).").classes("text-xs text-grey")

    # ---- variables --------------------------------------------------------- #
    def _vars_section():
        variables = model.setdefault("vars", {})
        with _expansion("vars", f"Variables ({len(variables)})", "tune", opened=True):
            with ui.column().classes("w-full gap-2 p-1"):
                if not variables:
                    ui.label("No variables yet.").classes("text-xs text-grey italic")
                for vname in list(variables.keys()):
                    _var_card(variables, vname)
                ui.button("Add variable", icon="add",
                          on_click=restructure(lambda e: _add_var(variables))).props("flat dense")

    def _add_var(variables):
        base, i, new = "var", 1, "var"
        while new in variables:
            i += 1
            new = f"var{i}"
        variables[new] = {"type": "int", "sweep": {"mode": "list", "values": [1, 2, 4]}}

    def _var_card(variables, vname):
        vardef = variables[vname]
        with ui.card().classes("w-full p-2 gap-1"):
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                nw = ui.input("Name", value=vname).classes("grow")

                def rename(_e=None, old=vname, widget=nw):
                    new = (widget.value or "").strip()
                    if new and new != old and new not in variables:
                        # preserve order
                        variables_items = list(variables.items())
                        variables.clear()
                        for k, v in variables_items:
                            variables[new if k == old else k] = v
                        render_form()
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
        # conditional
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
                ui.select(["ascending", "descending"], label="direction",
                          value=ad.get("direction", "ascending"),
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

    # ---- command ----------------------------------------------------------- #
    def _command_section():
        cmd = model.setdefault("command", {})
        with _expansion("command", "Command", "terminal", opened=True):
            with ui.column().classes("w-full gap-2 p-1"):
                ui.textarea("Command template (Jinja2)", value=cmd.get("template", ""),
                            on_change=setter(cmd, "template")).classes("w-full").props("autogrow")
                _dict_editor("Labels", cmd, "labels")
                _dict_editor("Environment variables", cmd, "env")

    def _dict_editor(title, parent, key):
        d = parent.get(key) or {}
        with _sub(f"dict-{key}", f"{title} ({len(d)})"):
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
                    n, base = "key", "key"
                    i = 1
                    while n in dd:
                        i += 1
                        n = f"{base}{i}"
                    dd[n] = ""
                ui.button("Add", icon="add", on_click=restructure(add)).props("flat dense")

    # ---- scripts ----------------------------------------------------------- #
    def _scripts_section():
        scripts = model.setdefault("scripts", [])
        with _expansion("scripts", f"Scripts ({len(scripts)})", "description", opened=True):
            with ui.column().classes("w-full gap-2 p-1"):
                for idx in range(len(scripts)):
                    _script_card(scripts, idx)

                def add(_e=None):
                    scripts.append({"name": f"script{len(scripts) + 1}",
                                    "script_template": "#!/bin/bash\n{{ command.template }}\n"})
                ui.button("Add script", icon="add", on_click=restructure(add)).props("flat dense")

    def _script_card(scripts, idx):
        sc = scripts[idx]
        with ui.card().classes("w-full p-2 gap-1"):
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                ui.input("Name", value=sc.get("name", ""),
                         on_change=setter(sc, "name")).classes("grow")
                ui.input("submit (optional)", value=sc.get("submit", ""),
                         on_change=setter(sc, "submit")).classes("w-40")
                ui.button(icon="delete", on_click=restructure(lambda e, i=idx: scripts.pop(i))) \
                    .props("flat round dense color=negative")
            ui.textarea("Script template", value=sc.get("script_template", ""),
                        on_change=setter(sc, "script_template")).classes("w-full").props("autogrow")
            _parser_editor(sc, idx)
            post = sc.get("post") or {}
            with _sub(f"post-{idx}", "Post-execution script"):
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
        with _sub(f"parser-{idx}", "Parser" + (" (set)" if parser else "")):
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
                        ui.button(icon="delete",
                                  on_click=restructure(lambda e, i=mi: metrics.pop(i))) \
                            .props("flat round dense color=negative")
                ui.button("Add metric", icon="add",
                          on_click=restructure(lambda e: metrics.append({"name": "metric"}))).props("flat dense")
                ui.textarea("parser_script (def parse(file_path))",
                            value=parser.get("parser_script", ""),
                            on_change=setter(parser, "parser_script")).classes("w-full").props("autogrow")

    # ---- output ------------------------------------------------------------ #
    def _output_section():
        sink = model.setdefault("output", {}).setdefault("sink", {})
        with _expansion("output", "Output", "save", opened=True):
            with ui.column().classes("w-full gap-2 p-1"):
                with ui.row().classes("gap-2 w-full"):
                    ui.select(SINK_TYPES, label="Sink type", value=sink.get("type", "csv"),
                              on_change=setter(sink, "type", drop_empty=False)).classes("grow")
                    ui.input("Path (optional)", value=sink.get("path", ""),
                             on_change=setter(sink, "path")).classes("grow")
                    ui.input("Table (sqlite)", value=sink.get("table", ""),
                             on_change=setter(sink, "table")).classes("w-40")
                ui.input("Exclude fields (comma-separated, e.g. benchmark.description)",
                         value=_values_text(sink.get("exclude")),
                         on_change=lambda e: (_set_list(sink, "exclude", _csv_list(e.value)),
                                              sync_to_yaml())).classes("w-full")

    def _set_list(container, key, values):
        if values:
            container[key] = values
        else:
            container.pop(key, None)

    # ---- probes ------------------------------------------------------------ #
    def _probes_section():
        bench = model.setdefault("benchmark", {})
        probes = bench.get("probes") or {}
        with _expansion("probes", "Probes (system + resource sampling)", "sensors"):
            with ui.column().classes("w-full gap-1 p-1"):
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

    # ---- reporting --------------------------------------------------------- #
    def _reporting_section():
        rep = model.get("reporting") or {}
        with _expansion("reporting", "Reporting (HTML report)", "assessment"):
            with ui.column().classes("w-full gap-2 p-1"):
                ui.checkbox("Enable report generation", value=rep.get("enabled", False),
                            on_change=lambda e: (_toggle_reporting(e.value)))
                if not rep.get("enabled"):
                    return
                rep = model.setdefault("reporting", {})
                ui.input("Output filename", value=rep.get("output_filename", "analysis_report.html"),
                         on_change=setter(rep, "output_filename")).classes("w-full")
                ui.select(PLOT_STYLES, label="Theme style", value=(rep.get("theme") or {}).get("style", "plotly_white"),
                          on_change=lambda e: (rep.setdefault("theme", {}).__setitem__("style", e.value), sync_to_yaml())).classes("w-64")
                ui.label("Sections").classes("text-xs font-semibold")
                sections = rep.get("sections") or {}
                with ui.row().classes("gap-x-4 gap-y-0 w-full").style("flex-wrap:wrap"):
                    for sec in REPORT_SECTIONS:
                        ui.checkbox(sec, value=sections.get(sec, True),
                                    on_change=lambda e, s=sec: (rep.setdefault("sections", {}).__setitem__(s, e.value), sync_to_yaml()))
                br = rep.get("best_results") or {}
                with ui.row().classes("gap-2 w-full"):
                    ui.number("best_results.top_n", value=br.get("top_n", 5), min=1, format="%d",
                              on_change=lambda e: (rep.setdefault("best_results", {}).__setitem__("top_n", int(e.value or 5)), sync_to_yaml())).classes("grow")
                    ui.number("best_results.min_samples", value=br.get("min_samples", 1), min=1, format="%d",
                              on_change=lambda e: (rep.setdefault("best_results", {}).__setitem__("min_samples", int(e.value or 1)), sync_to_yaml())).classes("grow")
                ui.label("Custom per-metric plots and gallery are edited on the YAML pane.") \
                    .classes("text-xs text-grey italic")

    def _toggle_reporting(enabled):
        if enabled:
            rep = model.setdefault("reporting", {})
            rep["enabled"] = True
        else:
            model.pop("reporting", None)
        render_form()
        sync_to_yaml()

    # ---- constraints ------------------------------------------------------- #
    def _constraints_section():
        constraints = model.get("constraints") or []
        with _expansion("constraints", f"Constraints ({len(constraints)})", "rule"):
            with ui.column().classes("w-full gap-2 p-1"):
                for idx in range(len(constraints)):
                    c = constraints[idx]
                    with ui.card().classes("w-full p-2 gap-1"):
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
                        ui.input("rule (Jinja2 boolean)", value=c.get("rule", ""),
                                 on_change=setter(c, "rule")).classes("w-full")

                def add(_e=None):
                    model.setdefault("constraints", []).append(
                        {"name": "constraint", "rule": "", "violation_policy": "skip"})
                ui.button("Add constraint", icon="add", on_click=restructure(add)).props("flat dense")

    # ---- actions ----------------------------------------------------------- #
    def _do_save():
        revalidate()
        on_save(name_holder["value"], cm.value)

    async def _do_run():
        await on_run(name_holder["value"], cm.value)

    async def _do_check():
        await on_check(name_holder["value"], cm.value)

    # ---- layout: form | yaml side by side ---------------------------------- #
    # The row flex-grows to fill the space left below the header, and
    # `min-height:0` lets the two panes actually scroll instead of overflowing
    # the page (the classic flexbox overflow gotcha).
    with ui.row().classes("w-full no-wrap gap-3 grow").style("min-height:0"):
        form = ui.column().classes("gap-2") \
            .style("width: 54%; height:100%; min-height:0; overflow-y:auto; padding-right:6px")
        with ui.column().classes("gap-1").style("width: 46%; height:100%; min-height:0"):
            ui.label("YAML").classes("text-xs text-grey")
            cm = ui.codemirror(value=initial_yaml, language="YAML",
                               on_change=lambda e: on_cm_change()).classes("w-full") \
                .style("flex:1; min-height:0; overflow:auto; border:1px solid #e0e0e0; border-radius:6px")

    render_form()
    revalidate()


def _num_or_str(v):
    for cast in (int, float):
        try:
            return cast(v)
        except (ValueError, TypeError):
            continue
    return v
