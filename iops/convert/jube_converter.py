"""JUBE XML to IOPS YAML converter.

Parses JUBE benchmark XML files using the JUBE library and translates
them into IOPS YAML configuration format. The conversion is best-effort:
features that cannot be directly mapped are annotated with TODO markers.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from collections import OrderedDict

import yaml

from iops.convert.jube_syntax import (
    jube_var_to_jinja2,
    jube_python_expr_to_jinja2,
    jube_type_to_iops_type,
    jube_pattern_to_python_regex,
)


def _literal_block_dumper():
    """Return a YAML Dumper that renders multi-line strings as literal blocks."""

    class _Dumper(yaml.SafeDumper):
        pass

    def _str_representer(dumper, data):
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    # Preserve dict ordering
    def _dict_representer(dumper, data):
        return dumper.represent_mapping("tag:yaml.org,2002:map", data.items())

    _Dumper.add_representer(str, _str_representer)
    _Dumper.add_representer(OrderedDict, _dict_representer)
    return _Dumper


class JubeConverter:
    """Converts a JUBE XML benchmark to an IOPS YAML configuration.

    Uses jube.jubeio.Parser to parse the XML, then translates JUBE
    data structures (parametersets, steps, patternsets, analysers)
    into the IOPS config format.
    """

    def __init__(self, input_file, benchmark_name=None, executor="local", logger=None):
        self.input_file = Path(input_file)
        self.benchmark_name = benchmark_name
        self.executor = executor
        self.logger = logger or logging.getLogger(__name__)
        self.warnings = []

    def convert(self):
        """Run the full conversion pipeline.

        Returns:
            tuple: (config_dict, warnings_list) where config_dict is an
                OrderedDict with the IOPS YAML structure.
        """
        benchmark = self._parse_xml()
        config = self._build_config(benchmark)
        return config, self.warnings

    def _parse_xml(self):
        """Parse the JUBE XML file and return the selected Benchmark object."""
        from jube.jubeio import Parser

        parser = Parser(str(self.input_file), force=True)
        benchmarks, _, _ = parser.benchmarks_from_xml()

        if not benchmarks:
            raise ValueError(f"No benchmarks found in {self.input_file}")

        if self.benchmark_name:
            if self.benchmark_name not in benchmarks:
                available = ", ".join(benchmarks.keys())
                raise ValueError(
                    f"Benchmark '{self.benchmark_name}' not found. "
                    f"Available: {available}"
                )
            return benchmarks[self.benchmark_name]

        if len(benchmarks) == 1:
            return next(iter(benchmarks.values()))

        # Multiple benchmarks, no selection
        names = ", ".join(benchmarks.keys())
        raise ValueError(
            f"Multiple benchmarks found: {names}. "
            f"Use --benchmark to select one."
        )

    def _build_config(self, benchmark):
        """Build the full IOPS config dict from a JUBE Benchmark object."""
        config = OrderedDict()

        # benchmark section
        config["benchmark"] = self._build_benchmark_section(benchmark)

        # vars section
        config["vars"] = self._convert_parametersets(benchmark)

        # command section
        commands, script_preamble = self._convert_steps(benchmark)
        config["command"] = OrderedDict([
            ("template", commands or "# TODO: Set your benchmark command"),
        ])

        # scripts section
        config["scripts"] = self._build_scripts_section(
            benchmark, commands, script_preamble
        )

        # output section
        config["output"] = OrderedDict([
            ("sink", OrderedDict([
                ("type", "csv"),
                ("path", "{{ workdir }}/results.csv"),
            ])),
        ])

        return config

    def _build_benchmark_section(self, benchmark):
        """Build the benchmark section of the IOPS config."""
        section = OrderedDict()
        section["name"] = benchmark.name
        if benchmark.comment:
            section["description"] = benchmark.comment
        section["workdir"] = "./workdir"
        section["executor"] = self.executor
        section["search_method"] = "exhaustive"

        # Map iterations from the first step (approximate)
        max_iterations = 1
        for step in benchmark.steps.values():
            if step.iterations > max_iterations:
                max_iterations = step.iterations
        section["repetitions"] = max_iterations

        # Check for cycles
        for step in benchmark.steps.values():
            if step.cycles > 1:
                self.warnings.append(
                    f"Step '{step.name}' has cycles={step.cycles}. "
                    f"IOPS does not support repeated step cycles. "
                    f"Consider increasing repetitions or restructuring."
                )

        return section

    def _convert_parametersets(self, benchmark):
        """Convert JUBE parametersets to IOPS vars."""
        iops_vars = OrderedDict()

        for pset_name, pset in benchmark.parametersets.items():
            for param in pset.all_parameters:
                var_config = self._convert_parameter(param)
                if var_config is not None:
                    iops_vars[param.name] = var_config

        return iops_vars

    def _convert_parameter(self, param):
        """Convert a single JUBE Parameter to an IOPS var config dict."""
        iops_type = jube_type_to_iops_type(param.parameter_type)

        # Skip JUBE internal parameters
        if param.name.startswith("jube_"):
            return None

        var = OrderedDict()
        var["type"] = iops_type

        mode = param.mode

        if mode in ("shell", "perl"):
            # Cannot auto-convert shell/perl mode parameters
            self.warnings.append(
                f"Parameter '{param.name}' uses {mode} mode, which cannot "
                f"be automatically converted. Manual adjustment required."
            )
            var["type"] = "str"
            raw_value = param.value if isinstance(param.value, str) else str(param.value)
            var["expr"] = f"TODO_{mode}_mode: {raw_value}"
            return var

        if mode == "env":
            # Environment variable reference
            raw_value = param.value if isinstance(param.value, str) else str(param.value)
            var["expr"] = "{{ os_env." + raw_value.strip() + " }}"
            return var

        if mode == "tag":
            # Tag-based selection, treat as static
            raw_value = param.value if isinstance(param.value, str) else str(param.value)
            var["expr"] = jube_var_to_jinja2(raw_value)
            return var

        # Template parameters (multiple values separated by separator)
        if param.is_template:
            values = self._split_template_values(param)
            typed_values = [self._cast_value(v.strip(), iops_type) for v in values]

            var["sweep"] = OrderedDict()
            var["sweep"]["mode"] = "list"
            var["sweep"]["values"] = typed_values
            return var

        # Python-mode parameters (derived expressions)
        if mode == "python":
            raw_value = param.value if isinstance(param.value, str) else str(param.value)
            var["expr"] = jube_python_expr_to_jinja2(raw_value)
            return var

        # Static/text parameters (single value)
        raw_value = param.value if isinstance(param.value, str) else str(param.value)
        converted = jube_var_to_jinja2(raw_value)

        # Check if it references other variables
        if "{{" in converted:
            var["expr"] = converted
        else:
            # Literal value: use sweep with single value
            cast = self._cast_value(converted, iops_type)
            var["sweep"] = OrderedDict()
            var["sweep"]["mode"] = "list"
            var["sweep"]["values"] = [cast]

        return var

    def _split_template_values(self, param):
        """Split a template parameter's value by its separator."""
        sep = param.separator if param.separator else ","
        raw = param.value if isinstance(param.value, str) else str(param.value)
        return [v.strip() for v in raw.split(sep) if v.strip()]

    def _cast_value(self, value_str, iops_type):
        """Cast a string value to the appropriate Python type."""
        try:
            if iops_type == "int":
                return int(value_str)
            elif iops_type == "float":
                return float(value_str)
            elif iops_type == "bool":
                return value_str.lower() in ("true", "1", "yes")
        except (ValueError, AttributeError):
            pass
        return value_str

    def _convert_steps(self, benchmark):
        """Convert JUBE steps to IOPS command template and script preamble.

        Returns:
            tuple: (command_str, preamble_str) where command_str is the
                concatenated command operations and preamble_str contains
                file operations from filesets.
        """
        preamble_lines = []
        command_lines = []

        # Convert filesets to shell commands
        preamble_lines.extend(self._convert_filesets(benchmark))

        # Sort steps by dependencies (topological order)
        sorted_steps = self._topological_sort_steps(benchmark.steps)

        # Multi-step DAG warning
        if len(sorted_steps) > 1:
            step_names = [s.name for s in sorted_steps]
            self.warnings.append(
                f"JUBE defines {len(sorted_steps)} steps ({', '.join(step_names)}). "
                f"IOPS uses a flat script model. Steps have been concatenated "
                f"in dependency order. Review the result carefully."
            )

        for step in sorted_steps:
            # Check for shared directory
            if step.shared_link_name:
                self.warnings.append(
                    f"Step '{step.name}' uses shared directory "
                    f"'{step.shared_link_name}'. IOPS does not support "
                    f"shared workpackage directories."
                )

            for op in step.operations:
                cmd = op.do
                if not cmd:
                    continue

                # Convert variable syntax
                converted = jube_var_to_jinja2(cmd)

                # Handle active condition
                active = getattr(op, "_active", "true")
                if active and active != "true":
                    converted_active = jube_var_to_jinja2(active)
                    converted = (
                        f"{{% if {converted_active} %}}"
                        + converted
                        + "{% endif %}"
                    )

                command_lines.append(converted)

                # Stdout/stderr redirection
                if op.stdout_filename:
                    fname = jube_var_to_jinja2(op.stdout_filename)
                    command_lines[-1] += f" > {fname}"
                if op.stderr_filename:
                    fname = jube_var_to_jinja2(op.stderr_filename)
                    command_lines[-1] += f" 2> {fname}"

        preamble = "\n".join(preamble_lines) if preamble_lines else ""
        command = "\n".join(command_lines) if command_lines else ""

        return command, preamble

    def _convert_filesets(self, benchmark):
        """Convert JUBE filesets to shell commands."""
        from jube.fileset import Copy, Link, Prepare

        lines = []
        for fset_name, fset in benchmark.filesets.items():
            for item in fset:
                if isinstance(item, Copy):
                    src = jube_var_to_jinja2(item.path)
                    target = jube_var_to_jinja2(item.name) if item.name else ""
                    if target:
                        lines.append(f"cp -r {src} {target}")
                    else:
                        lines.append(f"cp -r {src} .")
                elif isinstance(item, Link):
                    src = jube_var_to_jinja2(item.path)
                    target = jube_var_to_jinja2(item.name) if item.name else ""
                    if target:
                        lines.append(f"ln -sf {src} {target}")
                    else:
                        lines.append(f"ln -sf {src} .")
                elif isinstance(item, Prepare):
                    cmd = jube_var_to_jinja2(item.do)
                    if cmd:
                        lines.append(cmd)

        return lines

    def _topological_sort_steps(self, steps_dict):
        """Sort steps in dependency order."""
        visited = set()
        result = []

        def visit(name):
            if name in visited:
                return
            visited.add(name)
            if name in steps_dict:
                step = steps_dict[name]
                for dep in step.depend:
                    visit(dep)
                result.append(step)

        for name in steps_dict:
            visit(name)

        return result

    def _build_scripts_section(self, benchmark, commands, preamble):
        """Build the scripts list for IOPS config."""
        script_body_parts = []

        if self.executor == "slurm":
            script_body_parts.append("#!/bin/bash")
            script_body_parts.append(
                "#SBATCH --job-name=iops_{{ execution_id }}"
            )
            script_body_parts.append(
                "# TODO: Add SLURM directives (--nodes, --ntasks, --time, etc.)"
            )
            script_body_parts.append("")
        else:
            script_body_parts.append("#!/bin/bash")
            script_body_parts.append("")

        if preamble:
            script_body_parts.append("# File operations from JUBE filesets")
            script_body_parts.append(preamble)
            script_body_parts.append("")

        script_body_parts.append("{{ command.template }}")

        script_template = "\n".join(script_body_parts) + "\n"

        # Build parser section from patternsets + analysers
        parser_section = self._build_parser_section(benchmark)

        submit = "sbatch" if self.executor == "slurm" else "bash"

        script = OrderedDict()
        script["name"] = "main"
        script["submit"] = submit
        script["script_template"] = script_template

        if parser_section:
            script["parser"] = parser_section

        return [script]

    def _build_parser_section(self, benchmark):
        """Build the parser section from JUBE patternsets and analysers."""
        # Collect all patterns and derived patterns
        patterns = OrderedDict()      # name -> (regex, type, unit)
        derived = OrderedDict()        # name -> (expr, type, unit)

        for pset_name, pset in benchmark.patternsets.items():
            for pname, pat in pset.pattern_storage.parameter_dict.items():
                if pname.startswith("jube_"):
                    continue
                expanded = jube_pattern_to_python_regex(pat.value)
                patterns[pname] = (expanded, pat.content_type, pat.unit)

            for pname, pat in pset.derived_pattern_storage.parameter_dict.items():
                if pname.startswith("jube_"):
                    continue
                derived[pname] = (pat.value, pat.content_type, pat.unit)

        if not patterns and not derived:
            return None

        # Determine the output file from analysers
        output_file = "stdout"
        for analyser_name, analyser in benchmark.analyser.items():
            for step_name, analyse_files in analyser.analyser.items():
                for af in analyse_files:
                    if af.path:
                        output_file = jube_var_to_jinja2(af.path)
                        break

        # Build metrics list
        metrics = []
        all_metric_names = list(patterns.keys()) + list(derived.keys())
        for name in all_metric_names:
            metrics.append(OrderedDict([("name", name)]))

        # Build parser_script
        parser_script = self._generate_parser_script(patterns, derived)

        parser = OrderedDict()
        parser["file"] = f"{{{{ execution_dir }}}}/{output_file}"
        parser["metrics"] = metrics
        parser["parser_script"] = parser_script

        return parser

    def _generate_parser_script(self, patterns, derived):
        """Generate a Python parse() function from JUBE patterns.

        Args:
            patterns: dict of name -> (regex, type, unit)
            derived: dict of name -> (expr, type, unit)

        Returns:
            String containing the parser_script code.
        """
        lines = [
            "import re",
            "",
            "def parse(file_path):",
            "    results = {}",
            "    with open(file_path) as f:",
            "        content = f.read()",
        ]

        for name, (regex, content_type, unit) in patterns.items():
            # Escape the regex for Python string
            safe_regex = regex.replace("\\", "\\\\").replace('"', '\\"')
            cast = _python_cast_for_type(content_type)
            lines.append(f'    m = re.search(r"{safe_regex}", content)')
            lines.append(f"    if m:")
            lines.append(f'        results["{name}"] = {cast}(m.group(1))')

        # Add derived patterns as computed metrics
        for name, (expr, content_type, unit) in derived.items():
            # Convert $var references to results["var"] lookups
            converted_expr = self._convert_derived_expr(expr, patterns, derived)
            lines.append(f"    # Derived metric")
            lines.append(f"    try:")
            lines.append(f'        results["{name}"] = {converted_expr}')
            lines.append(f"    except (KeyError, ZeroDivisionError, TypeError):")
            lines.append(f"        pass")

        lines.append("    return results")
        lines.append("")

        return "\n".join(lines) + "\n"

    def _convert_derived_expr(self, expr, patterns, derived):
        """Convert a JUBE derived pattern expression to Python.

        Replaces $var references with results["var"] lookups.
        """
        result = expr

        # Preserve escaped dollar signs
        placeholder = "\x00DOLLAR\x00"
        result = result.replace("$$", placeholder)

        # Replace ${var} references
        result = re.sub(
            r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}",
            r'results["\1"]',
            result,
        )

        # Replace $var references
        result = re.sub(
            r"\$([a-zA-Z_][a-zA-Z0-9_]*)",
            r'results["\1"]',
            result,
        )

        result = result.replace(placeholder, "$")
        return result

    def write_yaml(self, config, output_file=None, dry_run=False):
        """Write the IOPS config to a YAML file with header comments.

        Args:
            config: OrderedDict with the IOPS config structure.
            output_file: Path to write to. If None, prints to stdout.
            dry_run: If True, print to stdout instead of writing.

        Returns:
            Path to the written file, or None for dry_run/stdout.
        """
        yaml_str = yaml.dump(
            dict(config),
            default_flow_style=False,
            sort_keys=False,
            Dumper=_literal_block_dumper(),
            allow_unicode=True,
        )

        header = self._build_header()
        full_output = header + yaml_str

        if dry_run or output_file is None:
            print(full_output)
            return None

        output_path = Path(output_file)
        output_path.write_text(full_output)
        return output_path

    def _build_header(self):
        """Build the YAML file header with conversion metadata."""
        lines = [
            f"# IOPS Configuration",
            f"# Converted from JUBE XML: {self.input_file.name}",
            f"# Conversion date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "#",
        ]

        if self.warnings:
            lines.append("# CONVERSION WARNINGS:")
            for w in self.warnings:
                # Wrap long warnings
                wrapped = w.replace(". ", ".\n#   ")
                lines.append(f"#   - {wrapped}")
            lines.append("#")

        lines.append("# Review all TODO markers below before running.")
        lines.append("# Validate with: iops check <this_file>")
        lines.append("# Preview with:  iops run <this_file> --dry-run")
        lines.append("")

        return "\n".join(lines) + "\n"

    def print_summary(self):
        """Print a conversion summary to the logger."""
        self.logger.info("Conversion summary:")
        self.logger.info(f"  Source: {self.input_file}")
        if self.warnings:
            self.logger.info(f"  Warnings: {len(self.warnings)}")
            for w in self.warnings:
                self.logger.warning(f"    {w}")
        self.logger.info("")
        self.logger.info("Next steps:")
        self.logger.info("  1. Review and fix all TODO markers in the output")
        self.logger.info("  2. Validate: iops check <output.yaml>")
        self.logger.info("  3. Preview:  iops run <output.yaml> --dry-run")


def _python_cast_for_type(content_type):
    """Return the Python cast function name for a JUBE content type."""
    mapping = {
        "int": "int",
        "float": "float",
        "string": "str",
    }
    return mapping.get(content_type, "str")
