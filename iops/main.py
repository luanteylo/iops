import argparse
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from iops.logger import setup_logger
from iops.execution.runner import IOPSRunner
from iops.config.loader import load_generic_config, validate_generic_config, check_system_probe_compatibility
from iops.config.models import ConfigValidationError, GenericBenchmarkConfig
from iops.execution.matrix import build_execution_matrix

# IOPS file constants
INDEX_FILENAME = "__iops_index.json"
PARAMS_FILENAME = "__iops_params.json"


def find_executions(path: Path, filters: Optional[List[str]] = None, show_command: bool = False) -> None:
    """
    Find and display execution folders in a workdir.

    Args:
        path: Path to workdir (run root) or exec folder
        filters: Optional list of VAR=VALUE filters
        show_command: If True, display the command column
    """
    path = path.resolve()

    # Parse filters into dict
    filter_dict: Dict[str, str] = {}
    if filters:
        for f in filters:
            if '=' not in f:
                print(f"Invalid filter format: {f} (expected VAR=VALUE)")
                return
            key, value = f.split('=', 1)
            filter_dict[key] = value

    # Check if path is an exec folder (has __iops_params.json)
    params_file = path / PARAMS_FILENAME
    if params_file.exists():
        _show_single_execution(path, params_file, show_command)
        return

    # Check if path is a run root (has __iops_index.json)
    index_file = path / INDEX_FILENAME
    if index_file.exists():
        _show_executions_from_index(path, index_file, filter_dict, show_command)
        return

    # Try to find index in subdirectories (user might point to workdir containing run_XXX)
    run_dirs = sorted(path.glob("run_*"))
    if run_dirs:
        for run_dir in run_dirs:
            index_file = run_dir / INDEX_FILENAME
            if index_file.exists():
                print(f"\n=== {run_dir.name} ===")
                _show_executions_from_index(run_dir, index_file, filter_dict, show_command)
        return

    print(f"No IOPS execution data found in: {path}")
    print(f"Expected either {INDEX_FILENAME} (in run root) or {PARAMS_FILENAME} (in exec folder)")


def _show_single_execution(exec_dir: Path, params_file: Path, show_command: bool = False) -> None:
    """Show details for a single execution folder."""
    try:
        with open(params_file, 'r') as f:
            params = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading {params_file}: {e}")
        return
    print("\nParameters:")
    for key, value in sorted(params.items()):
        print(f"  {key}: {value}")

    # Count repetition folders
    rep_dirs = sorted(exec_dir.glob("repetition_*"))
    if rep_dirs:
        print(f"Repetitions: {len(rep_dirs)}")

    # Show command from index file if requested
    if show_command:
        # Try to find command in parent's index file
        index_file = exec_dir.parent.parent / INDEX_FILENAME
        if index_file.exists():
            try:
                with open(index_file, 'r') as f:
                    index = json.load(f)
                exec_name = exec_dir.name
                if exec_name in index.get("executions", {}):
                    command = index["executions"][exec_name].get("command", "")
                    if command:
                        print(f"\nCommand:\n  {command}")
            except (json.JSONDecodeError, OSError):
                pass


def _show_executions_from_index(run_root: Path, index_file: Path, filter_dict: Dict[str, str], show_command: bool = False) -> None:
    """Show executions from the index file, optionally filtered."""
    try:
        with open(index_file, 'r') as f:
            index = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading {index_file}: {e}")
        return

    benchmark_name = index.get("benchmark", "Unknown")
    executions = index.get("executions", {})

    if not executions:
        print("No executions found in index.")
        return

    # Get all variable names for header
    all_vars = set()
    for exec_data in executions.values():
        all_vars.update(exec_data.get("params", {}).keys())
    var_names = sorted(all_vars)

    # Filter executions
    matches = []
    for exec_key, exec_data in sorted(executions.items()):
        params = exec_data.get("params", {})
        rel_path = exec_data.get("path", "")
        command = exec_data.get("command", "")

        # Apply filters (partial match - only check specified vars)
        if filter_dict:
            match = True
            for fkey, fval in filter_dict.items():
                if fkey not in params:
                    match = False
                    break
                # Convert both to string for comparison
                if str(params[fkey]) != fval:
                    match = False
                    break
            if not match:
                continue

        matches.append((exec_key, rel_path, params, command))

    if not matches:
        if filter_dict:
            print(f"No executions match the filter: {filter_dict}")
        else:
            print("No executions found.")
        return

    # Display results

    # Calculate column widths
    col_widths = {"path": max(len("Path"), max(len(m[1]) for m in matches))}
    for var in var_names:
        var_values = [str(m[2].get(var, "")) for m in matches]
        col_widths[var] = max(len(var), max(len(v) for v in var_values) if var_values else 0)
    if show_command:
        col_widths["command"] = max(len("Command"), max(len(m[3]) for m in matches) if matches else 0)

    # Print header
    header = "Path".ljust(col_widths["path"])
    for var in var_names:
        header += "  " + var.ljust(col_widths[var])
    if show_command:
        header += "  " + "Command"
    print("\n")
    print(header)
    print("-" * len(header))

    # Print rows
    for exec_key, rel_path, params, command in matches:
        row = rel_path.ljust(col_widths["path"])
        for var in var_names:
            val = str(params.get(var, ""))
            row += "  " + val.ljust(col_widths[var])
        if show_command:
            row += "  " + command
        print(row)


def load_version():
    """
    Load the version of the IOPS Tool from the version file.
    """
    version_file = Path(__file__).parent / "VERSION"
    if not version_file.exists():
        raise FileNotFoundError(f"Version file not found: {version_file}")
    
    with version_file.open() as f:
        return f.read().strip()
    
def parse_arguments():
    parser = argparse.ArgumentParser(description="IOPS Tool - Benchmark Automation Framework")

    # Positional argument
    parser.add_argument('setup_file', type=Path, nargs='?',
                        help="Path to the YAML setup file")

    # Mode options
    parser.add_argument('--generate', nargs='?', const=Path("iops_config.yaml"), type=Path,
                        metavar='PATH', help="Generate a default config template")
    parser.add_argument('--check', action='store_true',
                        help="Validate the config file and exit")
    parser.add_argument('--analyze', type=Path, default=None, metavar='PATH',
                        help="Generate HTML report from a completed run")
    parser.add_argument('--find', type=Path, default=None, metavar='PATH',
                        help="Find execution folders in a workdir (use VAR=VALUE to filter)")
    parser.add_argument('--filter', type=str, nargs='*', default=None, metavar='VAR=VALUE',
                        help="Filter executions by variable values (use with --find)")
    parser.add_argument('--show-command', action='store_true',
                        help="Show the command column (use with --find)")

    # Execution options
    parser.add_argument('-n', '--dry-run', action='store_true',
                        help="Preview execution plan without running tests")
    parser.add_argument('--use-cache', action='store_true',
                        help="Reuse cached results, skip already executed tests")
    parser.add_argument('--max-core-hours', type=float, default=None, metavar='N',
                        help="Maximum CPU core-hours budget for execution")
    parser.add_argument('--time-estimate', type=str, default=None, metavar='SEC',
                        help="Estimated time per test (e.g., '120' or '60,120,300')")

    # Logging options
    parser.add_argument('--log-file', type=Path, default=Path("iops.log"), metavar='PATH',
                        help="Path to log file (default: iops.log)")
    parser.add_argument('--log-level', type=str, default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help="Logging level (default: INFO)")
    parser.add_argument('--no-log-terminal', action='store_true',
                        help="Disable logging to terminal")
    parser.add_argument('-v', '--verbose', action='store_true',
                        help="Show full traceback for errors")

    # Report options
    parser.add_argument('--report-config', type=Path, default=None, metavar='PATH',
                        help="Custom report config YAML (use with --analyze)")

    parser.add_argument('--version', action='version', version=f'IOPS Tool v{load_version()}')

    return parser.parse_args()


def initialize_logger(args):
    return setup_logger(
        name="iops",
        log_file=args.log_file,
        to_stdout=not args.no_log_terminal,
        to_file=args.log_file is not None,
        level=getattr(logging, args.log_level.upper(), logging.INFO)
    )


def log_execution_context(cfg: GenericBenchmarkConfig, args: argparse.Namespace, logger: logging.Logger):
    """
    Log the execution context in a human-readable way.
    Called once at startup.
    """

    sep = "=" * 80
    sub = "-" * 60

    IOPS_VERSION = load_version()  # ideally import from iops.__version__

    banner = r"""
        ██╗ ██████╗ ██████╗ ███████╗
        ██║██╔═══██╗██╔══██╗██╔════╝
        ██║██║   ██║██████╔╝███████╗
        ██║██║   ██║██╔═══╝ ╚════██║
        ██║╚██████╔╝██║     ███████║
        ╚═╝ ╚═════╝ ╚═╝     ╚══════╝
        """

    sep = "=" * 80

    logger.info("")
    for line in banner.strip("\n").splitlines():
        logger.info(line)

    logger.info("")
    logger.info("  IOPS")
    logger.info(f"  Version: {IOPS_VERSION}")
    logger.info(f"  Setup File: {args.setup_file}")    
    logger.info("")
    logger.info(sep)
    logger.debug("Execution Context")
    logger.debug(sep)

    # ------------------------------------------------------------------
    logger.debug("Command-line arguments:")
    logger.debug(f"  {args}")

    # ------------------------------------------------------------------
    logger.debug(sub)
    logger.debug("Benchmark")
    logger.debug(sub)
    logger.debug(f"  Name       : {cfg.benchmark.name}")
    if cfg.benchmark.description:
        logger.debug(f"  Description: {cfg.benchmark.description}")
    logger.debug(f"  Workdir    : {cfg.benchmark.workdir}")
    logger.debug(f"  Repetitions: {cfg.benchmark.repetitions}")
    logger.debug(f"  Executor   : {cfg.benchmark.executor}")
    if cfg.benchmark.sqlite_db:
        logger.debug(f"  SQLite DB  : {cfg.benchmark.sqlite_db}")

    # Budget configuration
    if cfg.benchmark.max_core_hours or args.max_core_hours:
        budget = args.max_core_hours if args.max_core_hours else cfg.benchmark.max_core_hours
        logger.info(f"  Budget     : {budget} core-hours")
        if cfg.benchmark.cores_expr:
            logger.debug(f"  Cores expr : {cfg.benchmark.cores_expr}")
        else:
            logger.debug(f"  Cores expr : 1 (default)")


    # ------------------------------------------------------------------
    logger.debug(sub)
    logger.debug("Variables (vars)")
    logger.debug(sub)

    for name, var in cfg.vars.items():
        logger.debug(f"  - {name}")
        logger.debug(f"      type : {var.type}")

        if var.sweep:
            logger.debug("      sweep:")
            logger.debug(f"        mode : {var.sweep.mode}")
            if var.sweep.mode == "range":
                logger.debug(f"        start: {var.sweep.start}")
                logger.debug(f"        end  : {var.sweep.end}")
                logger.debug(f"        step : {var.sweep.step}")
            elif var.sweep.mode == "list":
                logger.debug(f"        values: {var.sweep.values}")

        if var.expr:
            logger.debug(f"      expr : {var.expr}")

    # ------------------------------------------------------------------
    # Exhaustive vars (if specified)
    if cfg.benchmark.exhaustive_vars:
        logger.debug(sub)
        logger.debug("Exhaustive Variables")
        logger.debug(sub)
        logger.debug("  These variables will be fully tested for each search point:")
        for var_name in cfg.benchmark.exhaustive_vars:
            logger.debug(f"    - {var_name}")

    # ------------------------------------------------------------------
    logger.debug(sub)
    logger.debug("Command")
    logger.debug(sub)
    logger.debug("  Template:")
    logger.debug("  " + cfg.command.template.replace("\n", "\n  "))

    if cfg.command.env:
        logger.debug("  Environment:")
        for k, v in cfg.command.env.items():
            logger.debug(f"    {k}={v}")

    if cfg.command.metadata:
        logger.debug("  Metadata:")
        for k, v in cfg.command.metadata.items():
            logger.debug(f"    {k}: {v}")

    # ------------------------------------------------------------------
    logger.debug(sub)
    logger.debug("Execution Scripts")
    logger.debug(sub)

    for i, script in enumerate(cfg.scripts, start=1):
        logger.debug(f"  Script #{i}: {script.name}")
        logger.debug(f"    Submit : {script.submit}")

        logger.debug("    Script template:")
        logger.debug("    " + script.script_template.replace("\n", "\n    "))

        if script.post:
            logger.debug("    Post-processing script:")
            logger.debug("    " + script.post.script.replace("\n", "\n    "))

        if script.parser:
            logger.debug("    Parser:")
            logger.debug(f"      File : {script.parser.file}")
            logger.debug(f"      metrics: {[m.name for m in script.parser.metrics]}")
            logger.debug(f"      script: {script.parser.parser_script}")

            if script.parser.metrics:
                logger.debug("      Metrics:")
                for m in script.parser.metrics:
                    logger.debug(f"        - {m.name}")
                    if m.path:
                        logger.debug(f"            path: {m.path}")

            if script.parser.parser_script:
                logger.debug("      Custom parser script:")
                logger.debug(
                    "      "
                    + script.parser.parser_script.replace("\n", "\n      ")
                )

    # ------------------------------------------------------------------    
    logger.debug(sub)
    logger.debug("Output")
    logger.debug(sub)

    sink = cfg.output.sink
    logger.debug(f"  Type : {sink.type}")
    logger.debug(f"  Path : {sink.path}")
    logger.debug(f"  Mode : {sink.mode}")

    if sink.type == "sqlite":
        logger.debug(f"  Table: {sink.table}")

    # Field selection policy
    if sink.include:
        logger.debug("  Selection: include-only (only these fields will be saved)")
        logger.debug("  Include:")
        for field in sink.include:
            logger.debug(f"    - {field}")
    elif sink.exclude:
        logger.debug("  Selection: exclude (all fields will be saved except these)")
        logger.debug("  Exclude:")
        for field in sink.exclude:
            logger.debug(f"    - {field}")
    else:
        logger.debug("  Selection: default (all vars, metadata, metrics, and benchmark/execution fields will be saved)")




def main():
    args = parse_arguments()
    logger = initialize_logger(args)

    # Handle --generate mode (template generator)
    if args.generate:
        from iops.setup import BenchmarkWizard

        try:
            wizard = BenchmarkWizard()
            # Pass the output path if specified
            output_path = str(args.generate) if args.generate else None
            output_file = wizard.run(output_path=output_path)

            if output_file:
                logger.info(f"Configuration template generated successfully: {output_file}")
            else:
                logger.info("Template generation cancelled")

        except KeyboardInterrupt:
            logger.info("\n\nTemplate generation cancelled by user")
        except Exception as e:
            logger.error(f"Template generation failed: {e}")
            if args.verbose:
                raise
        return

    # Handle --find mode (find execution folders)
    if args.find:
        find_executions(args.find, args.filter, args.show_command)
        return

    # Handle --analyze mode (generate report from existing results)
    if args.analyze:
        from iops.reporting.report_generator import generate_report_from_workdir
        from iops.config.loader import load_report_config

        logger.info("=" * 70)
        logger.info("ANALYSIS MODE: Generating HTML report")
        logger.info("=" * 70)
        logger.info(f"Reading results from: {args.analyze}")

        # Load report config: explicit flag > auto-detect in workdir > metadata defaults
        report_config = None
        config_path = args.report_config

        # Auto-detect report_config.yaml in workdir if not explicitly provided
        if config_path is None:
            default_config = args.analyze / "report_config.yaml"
            if default_config.exists():
                config_path = default_config
                logger.info(f"Auto-detected report config: {config_path}")

        if config_path:
            logger.info(f"Using report config: {config_path}")
            try:
                report_config = load_report_config(config_path)
            except Exception as e:
                logger.error(f"Failed to load report config: {e}")
                if args.verbose:
                    raise
                return

        try:
            report_path = generate_report_from_workdir(args.analyze, report_config=report_config)
            logger.info(f"✓ Report generated: {report_path}")
            logger.info("=" * 70)
        except Exception as e:
            logger.error(f"Failed to generate report: {e}")
            if args.verbose:
                raise
        return

    if not args.setup_file:
        logger.error("No setup file provided for validation or execution.")
        return

    # Handle --check mode (validate only)
    if args.check:
        from iops.config.loader import validate_yaml_config
        errors = validate_yaml_config(Path(args.setup_file))
        if errors:
            logger.error(f"Configuration validation failed with {len(errors)} error(s):")
            for i, err in enumerate(errors, 1):
                logger.error(f"  {i}. {err}")
            return
        else:
            logger.info("Configuration is valid.")
            return

    try:
        cfg = load_generic_config(Path(args.setup_file), logger=logger)
    except ConfigValidationError as e:
        logger.error(f"Configuration error: {e}")
        if args.verbose:
            raise
        return
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        if args.verbose:
            raise
        return

    log_execution_context(cfg, args, logger)

    # Check system probe compatibility (warns and disables if non-bash shell detected)
    check_system_probe_compatibility(cfg, logger)

    runner = IOPSRunner(cfg=cfg, args=args)

    # Run in dry-run mode or normal mode
    if args.dry_run:
        runner.run_dry()
    else:
        runner.run()



if __name__ == "__main__":
    main()
