"""Interactive wizard for creating IOPS benchmark configurations."""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
import yaml

from iops.setup import templates, validators


class BenchmarkWizard:
    """Interactive wizard for creating benchmark configurations."""

    def __init__(self):
        self.config: Dict[str, Any] = {}
        self.variables: List[Dict] = []
        self.metrics: List[Dict] = []
        self.template = None

    def run(self) -> Optional[str]:
        """Run the interactive wizard and return the path to the generated file."""
        self._print_header()

        # Step 1: Choose template or start from scratch
        if not self._choose_template():
            return None

        # Step 2: Basic configuration
        if not self._configure_basics():
            return None

        # Step 3: Search strategy
        if not self._configure_search():
            return None

        # Step 4: Variables
        if not self._configure_variables():
            return None

        # Step 5: Command
        if not self._configure_command():
            return None

        # Step 6: Script configuration
        if not self._configure_script():
            return None

        # Step 7: Metrics & Parsing
        if not self._configure_metrics():
            return None

        # Step 8: Output
        if not self._configure_output():
            return None

        # Step 9: Advanced options
        if not self._configure_advanced():
            return None

        # Step 10: Review and save
        return self._review_and_save()

    def _print_header(self):
        """Print wizard header."""
        print("\n" + "=" * 70)
        print("           IOPS Benchmark Configuration Wizard")
        print("=" * 70)
        print("\nLet's create your benchmark configuration step by step.")
        print("Press Ctrl+C at any time to cancel.\n")

    def _print_section(self, step: int, total: int, title: str):
        """Print section header."""
        print(f"\n[{step}/{total}] {title}")
        print("━" * 70)

    def _ask(self, prompt: str, default: str = None, validator=None) -> Optional[str]:
        """Ask a question and return the answer."""
        try:
            if default:
                prompt_text = f"→ {prompt} [default: {default}]: "
            else:
                prompt_text = f"→ {prompt}: "

            while True:
                answer = input(prompt_text).strip()

                # Use default if empty
                if not answer and default is not None:
                    answer = default

                # Validate if validator provided
                if validator:
                    valid, error = validator(answer)
                    if not valid:
                        print(f"  ✗ {error}")
                        continue

                return answer

        except (KeyboardInterrupt, EOFError):
            print("\n\n✗ Setup cancelled by user")
            sys.exit(0)

    def _ask_yes_no(self, prompt: str, default: bool = True) -> bool:
        """Ask a yes/no question."""
        default_str = "Y/n" if default else "y/N"
        answer = self._ask(f"{prompt} ({default_str})").lower()

        if not answer:
            return default

        return answer.startswith('y')

    def _ask_choice(self, prompt: str, choices: List[tuple], show_descriptions: bool = True) -> Optional[int]:
        """Ask user to choose from a list of options."""
        print(f"→ {prompt}")
        for i, choice in enumerate(choices, 1):
            if isinstance(choice, tuple):
                key, desc = choice
                if show_descriptions:
                    print(f"  {i}. {key:<12} - {desc}")
                else:
                    print(f"  {i}. {key}")
            else:
                print(f"  {i}. {choice}")

        while True:
            answer = input(f"  Choice [1-{len(choices)}]: ").strip()
            valid, error, value = validators.validate_choice(answer, 1, len(choices))

            if not valid:
                print(f"  ✗ {error}")
                continue

            return value - 1  # Return 0-indexed

    def _choose_template(self) -> bool:
        """Choose a benchmark template."""
        self._print_section(1, 10, "Benchmark Template")

        print("\nStart from a template or create from scratch?\n")

        template_list = templates.list_templates()
        choices = [(name, desc) for key, name, desc in template_list]
        choices.append(("scratch", "Start from scratch (empty configuration)"))

        choice_idx = self._ask_choice("Choose a template", choices)

        if choice_idx < len(template_list):
            template_key = template_list[choice_idx][0]
            self.template = templates.get_template(template_key)
            print(f"\n✓ Using template: {self.template['name']}")
        else:
            print("\n✓ Starting from scratch")

        return True

    def _configure_basics(self) -> bool:
        """Configure basic benchmark settings."""
        self._print_section(2, 10, "Benchmark Basics")

        # Name
        default_name = self.template['name'] if self.template else None
        name = self._ask(
            "Benchmark name",
            default=default_name,
            validator=lambda x: validators.validate_name(x)[:2]
        )

        # Description
        default_desc = self.template['description'] if self.template else None
        description = self._ask("Description (optional)", default=default_desc)

        # Working directory
        workdir = self._ask(
            "Working directory",
            default="./workdir",
            validator=lambda x: validators.validate_directory(x, create_if_missing=True)[:2]
        )

        # Executor
        print("\n→ Executor type:")
        executor_choices = [
            ("local", "Run scripts locally"),
            ("slurm", "Submit to SLURM cluster")
        ]
        executor_idx = self._ask_choice("", executor_choices)
        executor = ["local", "slurm"][executor_idx]

        self.config['benchmark'] = {
            'name': name,
            'description': description or "",
            'workdir': workdir,
            'executor': executor
        }

        print(f"\n✓ Basics configured")
        return True

    def _configure_search(self) -> bool:
        """Configure search strategy."""
        self._print_section(3, 10, "Search Strategy")

        print("\n→ How should parameters be explored?")
        search_choices = [
            ("exhaustive", "Try all combinations (full sweep)"),
            ("bayesian", "Intelligent optimization (fewer tests)"),
            ("random", "Random sampling")
        ]

        search_idx = self._ask_choice("", search_choices)
        search_method = ["exhaustive", "bayesian", "random"][search_idx]

        self.config['benchmark']['search_method'] = search_method

        # Bayesian-specific configuration
        if search_method == "bayesian":
            print("\n→ Bayesian optimization settings:")

            target_metric = self._ask("  Target metric to optimize", default="bwMiB")
            objective = self._ask("  Objective (maximize/minimize)", default="maximize")

            while objective not in ["maximize", "minimize"]:
                print("  ✗ Must be 'maximize' or 'minimize'")
                objective = self._ask("  Objective (maximize/minimize)", default="maximize")

            n_initial = self._ask("  Number of initial random points", default="5")
            n_iterations = self._ask("  Total number of iterations", default="20")

            self.config['benchmark']['bayesian_config'] = {
                'target_metric': target_metric,
                'objective': objective,
                'n_initial_points': int(n_initial),
                'n_iterations': int(n_iterations),
                'acquisition_func': 'EI'
            }

        print(f"\n✓ Search strategy: {search_method}")
        return True

    def _configure_variables(self) -> bool:
        """Configure variables."""
        self._print_section(4, 10, "Variables")

        print("\nDefine the parameters for your benchmark.")

        # Load suggested variables from template
        if self.template and self.template.get('suggested_vars'):
            if self._ask_yes_no("\nUse suggested variables from template?", default=True):
                for var_def in self.template['suggested_vars']:
                    self.variables.append(var_def)
                    print(f"  ✓ Added variable '{var_def['name']}'")

        # Allow adding more variables
        print()
        while self._ask_yes_no("Add a variable?", default=len(self.variables) == 0):
            var_config = self._configure_single_variable()
            if var_config:
                self.variables.append(var_config)
                print(f"  ✓ Variable '{var_config['name']}' added\n")

        print(f"\n✓ {len(self.variables)} variable(s) configured")
        return True

    def _configure_single_variable(self) -> Optional[Dict]:
        """Configure a single variable."""
        existing_names = [v['name'] for v in self.variables]

        # Variable name
        name = self._ask(
            "  Variable name",
            validator=lambda x: validators.validate_variable_name(x, existing_names)[:2]
        )

        # Variable type
        print("  Type:")
        type_choices = [("int", ""), ("float", ""), ("str", "")]
        type_idx = self._ask_choice("", type_choices, show_descriptions=False)
        var_type = ["int", "float", "str"][type_idx]

        # Swept or derived
        print("  Is this swept or derived?")
        mode_choices = [
            ("swept", "Test different values"),
            ("derived", "Computed from other variables")
        ]
        mode_idx = self._ask_choice("", mode_choices)

        var_config = {
            'name': name,
            'type': var_type
        }

        if mode_idx == 0:  # Swept
            var_config['sweep'] = self._configure_sweep(var_type)
        else:  # Derived
            expr = self._ask("  Expression (Jinja2 template)")
            var_config['expr'] = expr

        return var_config

    def _configure_sweep(self, var_type: str) -> Dict:
        """Configure sweep parameters."""
        if var_type == "str":
            # String variables can only use list mode
            values_str = self._ask("  Values (comma-separated)")
            values = [v.strip() for v in values_str.split(',')]
            return {'mode': 'list', 'values': values}

        # Numeric types can use list or range
        print("  Sweep mode:")
        sweep_choices = [
            ("list", "Specify exact values [4, 8, 16]"),
            ("range", "Start, end, step (e.g., 1 to 10 step 2)")
        ]
        sweep_idx = self._ask_choice("", sweep_choices)

        if sweep_idx == 0:  # List
            while True:
                values_str = self._ask("  Values (comma-separated)")
                valid, error, values = validators.validate_number_list(values_str, var_type)
                if valid:
                    return {'mode': 'list', 'values': values}
                print(f"  ✗ {error}")

        else:  # Range
            while True:
                start = self._ask("  Start value")
                end = self._ask("  End value")
                step = self._ask("  Step value")

                valid, error = validators.validate_range(start, end, step, var_type)
                if valid:
                    if var_type == "int":
                        return {
                            'mode': 'range',
                            'start': int(start),
                            'end': int(end),
                            'step': int(step)
                        }
                    else:
                        return {
                            'mode': 'range',
                            'start': float(start),
                            'end': float(end),
                            'step': float(step)
                        }
                print(f"  ✗ {error}")

    def _configure_command(self) -> bool:
        """Configure command template."""
        self._print_section(5, 10, "Command Template")

        print("\nWhat command should be executed for each test?")
        print("You can use variables with {{ variable_name }} syntax.\n")

        default_cmd = self.template['command_template'] if self.template else None
        if default_cmd:
            print(f"Template suggestion:\n{default_cmd}\n")

        command = self._ask("Command template", default=default_cmd)

        self.config['command'] = {'template': command}

        print("\n✓ Command configured")
        return True

    def _configure_script(self) -> bool:
        """Configure script settings."""
        self._print_section(6, 10, "Script Configuration")

        if self.config['benchmark']['executor'] == 'slurm':
            return self._configure_slurm_script()
        else:
            return self._configure_local_script()

    def _configure_slurm_script(self) -> bool:
        """Configure SLURM script."""
        print("\n→ SLURM script configuration")

        print("\n  Choose an option:")
        script_choices = [
            ("generate", "Generate SLURM script template"),
            ("existing", "Use existing script file"),
            ("skip", "Skip (use command only)")
        ]

        choice_idx = self._ask_choice("", script_choices)

        if choice_idx == 2:  # Skip
            print("\n✓ Skipping script configuration")
            return True

        if choice_idx == 1:  # Existing file
            script_path = self._ask(
                "  Script file path",
                validator=lambda x: validators.validate_file_path(x, must_exist=True)[:2]
            )

            self.config['scripts'] = [{
                'name': 'main',
                'submit': 'sbatch',
                'script_template': script_path
            }]

            print("\n✓ Using existing script")
            return True

        # Generate SLURM script
        print("\n  SLURM options:")
        time_limit = self._ask("  Time limit [HH:MM:SS]", default="00:30:00")
        partition = self._ask("  Partition (optional)", default="")
        constraint = self._ask("  Constraint (optional)", default="")
        exclusive = self._ask_yes_no("  Exclusive nodes?", default=False)

        # Generate script template
        script_template = self._generate_slurm_script(
            time_limit=time_limit,
            partition=partition,
            constraint=constraint,
            exclusive=exclusive
        )

        self.config['scripts'] = [{
            'name': 'main',
            'submit': 'sbatch',
            'script_template': script_template
        }]

        print("\n✓ SLURM script configured")
        return True

    def _configure_local_script(self) -> bool:
        """Configure local script."""
        if self._ask_yes_no("\nUse a script file?", default=False):
            script_path = self._ask(
                "  Script file path",
                validator=lambda x: validators.validate_file_path(x, must_exist=True)[:2]
            )

            self.config['scripts'] = [{
                'name': 'main',
                'script_template': script_path
            }]

            print("\n✓ Script configured")
        else:
            print("\n✓ Using command only")

        return True

    def _generate_slurm_script(self, time_limit: str, partition: str, constraint: str, exclusive: bool) -> str:
        """Generate a SLURM script template."""
        script_lines = [
            "#!/bin/bash",
            "",
            "#SBATCH --job-name={{ benchmark.name }}_{{ execution_id }}_{{ repetition }}",
        ]

        # Check if nodes/processes_per_node variables exist
        has_nodes = any(v['name'] == 'nodes' for v in self.variables)
        has_ppn = any(v['name'] == 'processes_per_node' for v in self.variables)

        if has_nodes:
            script_lines.append("#SBATCH --nodes={{ nodes }}")
        if has_ppn:
            script_lines.append("#SBATCH --ntasks-per-node={{ processes_per_node }}")

        script_lines.extend([
            f"#SBATCH --time={time_limit}",
            "#SBATCH -o batch%j.out",
            "#SBATCH -e batch%j.err",
        ])

        if partition:
            script_lines.append(f"#SBATCH --partition={partition}")
        if constraint:
            script_lines.append(f"#SBATCH --constraint={constraint}")
        if exclusive:
            script_lines.append("#SBATCH --exclusive")

        script_lines.extend([
            "",
            "# Load required modules",
            "# module load ...",
            "",
            "# Execute benchmark command",
            "{{ command.template }}",
            "",
            "# Capture exit code",
            "exit_code=$?",
            "echo \"Exit code: $exit_code\"",
            "exit $exit_code",
        ])

        return "\n".join(script_lines)

    def _configure_metrics(self) -> bool:
        """Configure metrics and parsing."""
        self._print_section(7, 10, "Metrics & Parsing")

        print("\nHow should results be collected?\n")

        # Output file pattern
        default_output = "{{ execution_dir }}/output_{{ execution_id }}_{{ repetition }}.txt"
        output_file = self._ask("Output file pattern", default=default_output)

        # Load suggested metrics from template
        if self.template and self.template.get('metrics'):
            if self._ask_yes_no("\nUse suggested metrics from template?", default=True):
                for metric_def in self.template['metrics']:
                    self.metrics.append(metric_def)
                    desc = metric_def.get('description', '')
                    print(f"  ✓ Added metric '{metric_def['name']}' - {desc}")

        # Allow adding more metrics
        print()
        while self._ask_yes_no("Add a metric?", default=len(self.metrics) == 0):
            existing_names = [m['name'] for m in self.metrics]
            name = self._ask(
                "  Metric name",
                validator=lambda x: validators.validate_metric_name(x, existing_names)[:2]
            )
            self.metrics.append({'name': name})
            print(f"  ✓ Added metric '{name}'\n")

        # Parser configuration
        if self.metrics:
            print("\n→ Parser script:")
            parser_choices = [
                ("existing", "Use existing parser script"),
                ("generate", "Generate simple parser template"),
                ("skip", "Skip (manual parsing)")
            ]

            parser_idx = self._ask_choice("", parser_choices)

            parser_config = {
                'file': output_file,
                'metrics': [{'name': m['name']} for m in self.metrics]
            }

            if parser_idx == 0:  # Existing
                parser_path = self._ask(
                    "  Parser script path",
                    validator=lambda x: validators.validate_file_path(x, must_exist=True)[:2]
                )
                parser_config['parser_script'] = parser_path

            elif parser_idx == 1:  # Generate
                if self.template and self.template.get('parser_script'):
                    parser_config['parser_script'] = self.template['parser_script']
                else:
                    # Generate simple parser template
                    parser_config['parser_script'] = self._generate_parser_template()

            # Add parser to script config
            if 'scripts' not in self.config:
                self.config['scripts'] = [{'name': 'main'}]

            self.config['scripts'][0]['parser'] = parser_config

        print(f"\n✓ {len(self.metrics)} metric(s) configured")
        return True

    def _generate_parser_template(self) -> str:
        """Generate a simple parser template."""
        metric_names = [m['name'] for m in self.metrics]
        metrics_dict = "{" + ", ".join([f"'{m}': None" for m in metric_names]) + "}"

        return f"""def parse(file_path):
    # TODO: Implement parsing logic
    # Read output file and extract metrics

    with open(file_path) as f:
        content = f.read()

    # Example: parse metrics from output
    metrics = {metrics_dict}

    # TODO: Extract actual values from content
    # metrics['metric_name'] = extracted_value

    return metrics
"""

    def _configure_output(self) -> bool:
        """Configure output settings."""
        self._print_section(8, 10, "Output Configuration")

        print("\n→ Output format:")
        output_choices = [
            ("csv", "CSV file"),
            ("sqlite", "SQLite database"),
            ("parquet", "Parquet file")
        ]

        output_idx = self._ask_choice("", output_choices)
        output_type = ["csv", "sqlite", "parquet"][output_idx]

        # Output path
        default_ext = {"csv": ".csv", "sqlite": ".db", "parquet": ".parquet"}[output_type]
        default_path = f"{{{{ workdir }}}}/results{default_ext}"
        output_path = self._ask("Output path", default=default_path)

        output_config = {
            'type': output_type,
            'path': output_path,
            'mode': 'append'
        }

        # SQLite-specific: table name
        if output_type == 'sqlite':
            table_name = self._ask("Table name", default="results")
            output_config['table'] = table_name

        self.config['output'] = {'sink': output_config}

        print(f"\n✓ Output configured: {output_type}")
        return True

    def _configure_advanced(self) -> bool:
        """Configure advanced options."""
        self._print_section(9, 10, "Advanced Options")

        if not self._ask_yes_no("\nConfigure advanced options?", default=False):
            # Set defaults
            self.config['benchmark']['repetitions'] = 3
            print("\n✓ Using defaults")
            return True

        # Repetitions
        repetitions = self._ask("  Repetitions per test", default="3")
        self.config['benchmark']['repetitions'] = int(repetitions)

        # Random seed
        if self.config['benchmark']['search_method'] in ['bayesian', 'random']:
            seed = self._ask("  Random seed (optional)", default="42")
            if seed:
                self.config['benchmark']['random_seed'] = int(seed)

        # Budget
        if self._ask_yes_no("  Set budget limit (core-hours)?", default=False):
            budget = self._ask("    Maximum core-hours")
            self.config['benchmark']['max_core_hours'] = float(budget)

            cores_expr = self._ask(
                "    Cores expression",
                default="{{ nodes * processes_per_node }}" if any(v['name'] == 'nodes' for v in self.variables) else "1"
            )
            self.config['benchmark']['cores_expr'] = cores_expr

        # Caching
        if self._ask_yes_no("  Enable caching?", default=False):
            cache_db = self._ask("    SQLite cache database path")
            self.config['benchmark']['sqlite_db'] = cache_db

        print("\n✓ Advanced options configured")
        return True

    def _review_and_save(self) -> Optional[str]:
        """Review configuration and save to file."""
        self._print_section(10, 10, "Review & Save")

        # Build final configuration
        final_config = self._build_final_config()

        # Show preview
        print("\n→ Generated configuration preview:")
        print("━" * 70)
        preview_yaml = yaml.dump(final_config, default_flow_style=False, sort_keys=False)
        lines = preview_yaml.split('\n')[:20]
        for line in lines:
            print(line)
        if len(preview_yaml.split('\n')) > 20:
            print("... (truncated)")
        print("━" * 70)

        # Ask for filename
        default_name = self.config['benchmark']['name'].lower().replace(' ', '_')
        filename = self._ask("\nSave to", default=f"{default_name}.yaml")

        if not filename.endswith('.yaml'):
            filename += '.yaml'

        # Confirm
        if not self._ask_yes_no("\nConfirm and save?", default=True):
            print("\n✗ Configuration not saved")
            return None

        # Save file
        try:
            output_path = Path(filename)
            with open(output_path, 'w') as f:
                yaml.dump(final_config, f, default_flow_style=False, sort_keys=False)

            print(f"\n✓ Saved to {output_path.absolute()}")

            # Show next steps
            print("\n" + "=" * 70)
            print("Next steps:")
            print(f"  • Review: cat {filename}")
            print(f"  • Dry run: iops run {filename} --dry-run")
            print(f"  • Execute: iops run {filename}")
            print("=" * 70 + "\n")

            return str(output_path.absolute())

        except Exception as e:
            print(f"\n✗ Error saving file: {e}")
            return None

    def _build_final_config(self) -> Dict:
        """Build the final configuration dictionary."""
        config = {'benchmark': self.config['benchmark'].copy()}

        # Add variables
        if self.variables:
            vars_dict = {}
            for var in self.variables:
                var_config = {'type': var['type']}

                if 'sweep' in var:
                    var_config['sweep'] = var['sweep']
                if 'expr' in var:
                    var_config['expr'] = var['expr']

                vars_dict[var['name']] = var_config

            config['vars'] = vars_dict

        # Add command
        if 'command' in self.config:
            config['command'] = self.config['command']

        # Add scripts
        if 'scripts' in self.config:
            config['scripts'] = self.config['scripts']

        # Add output
        if 'output' in self.config:
            config['output'] = self.config['output']

        return config
