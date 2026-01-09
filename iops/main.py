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
STATUS_FILENAME = "__iops_status.json"
METADATA_FILENAME = "__iops_run_metadata.json"

# Default truncation width for parameter values
DEFAULT_TRUNCATE_WIDTH = 30


def _truncate_value(value: str, max_width: int) -> str:
    """Truncate a value to max_width, showing the end (most relevant part)."""
    if len(value) <= max_width:
        return value
    # Handle edge case where max_width is too small for "..." + content
    if max_width <= 3:
        return "..."[:max_width] if max_width > 0 else ""
    return "..." + value[-(max_width - 3):]


def _read_status(exec_path: Path) -> Dict[str, Any]:
    """
    Read execution status from the status file.

    Args:
        exec_path: Path to the exec_XXXX folder

    Returns:
        Dict with status info, or default values if file doesn't exist
    """
    status_file = exec_path / STATUS_FILENAME
    if status_file.exists():
        try:
            with open(status_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    # Default: no status file means execution hasn't completed or is from old run
    return {"status": "PENDING", "error": None, "end_time": None}


def _read_run_metadata(run_root: Path) -> Dict[str, Any]:
    """
    Read run metadata from the metadata file.

    Args:
        run_root: Path to the run root directory (e.g., workdir/run_001)

    Returns:
        Dict with run metadata, or empty dict if file doesn't exist
    """
    metadata_file = run_root / METADATA_FILENAME
    if metadata_file.exists():
        try:
            with open(metadata_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def find_executions(
    path: Path,
    filters: Optional[List[str]] = None,
    show_command: bool = False,
    show_full: bool = False,
    hide_columns: Optional[set] = None,
    status_filter: Optional[str] = None
) -> None:
    """
    Find and display execution folders in a workdir.

    Args:
        path: Path to workdir (run root) or exec folder
        filters: Optional list of VAR=VALUE filters
        show_command: If True, display the command column
        show_full: If True, show full values without truncation
        hide_columns: Set of column names to hide
        status_filter: Filter by execution status (SUCCEEDED, FAILED, etc.)
    """
    path = path.resolve()
    hide_columns = hide_columns or set()

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
        _show_single_execution(path, params_file, show_command, show_full)
        return

    # Check if path is a run root (has __iops_index.json)
    index_file = path / INDEX_FILENAME
    if index_file.exists():
        _show_executions_from_index(
            path, index_file, filter_dict, show_command,
            show_full, hide_columns, status_filter
        )
        return

    # Try to find index in subdirectories (user might point to workdir containing run_XXX or dryrun_XXX)
    run_dirs = sorted(list(path.glob("run_*")) + list(path.glob("dryrun_*")))
    if run_dirs:
        for run_dir in run_dirs:
            index_file = run_dir / INDEX_FILENAME
            if index_file.exists():
                print(f"\n=== {run_dir.name} ===")
                _show_executions_from_index(
                    run_dir, index_file, filter_dict, show_command,
                    show_full, hide_columns, status_filter
                )
        return

    print(f"No IOPS execution data found in: {path}")
    print(f"Expected either {INDEX_FILENAME} (in run root) or {PARAMS_FILENAME} (in exec folder)")


def _show_single_execution(
    exec_dir: Path,
    params_file: Path,
    show_command: bool = False,
    show_full: bool = False
) -> None:
    """Show details for a single execution folder."""
    try:
        with open(params_file, 'r') as f:
            params = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading {params_file}: {e}")
        return

    # Try to read run metadata from parent (run root is 2 levels up: exec_XXXX -> runs -> run_root)
    run_root = exec_dir.parent.parent
    run_metadata = _read_run_metadata(run_root)
    bench_meta = run_metadata.get("benchmark", {})

    # Display run header with metadata
    if bench_meta.get("name"):
        print(f"\nBenchmark: {bench_meta['name']}")
    if bench_meta.get("description"):
        print(f"Description: {bench_meta['description']}")
    if bench_meta.get("hostname"):
        print(f"Host: {bench_meta['hostname']}")
    if bench_meta.get("timestamp"):
        print(f"Executed: {bench_meta['timestamp']}")

    # Read status
    status_info = _read_status(exec_dir)
    status = status_info.get("status", "UNKNOWN")

    print(f"\nStatus: {status}")
    if status_info.get("error"):
        print(f"Error: {status_info['error']}")
    if status_info.get("end_time"):
        print(f"Completed: {status_info['end_time']}")

    print("\nParameters:")
    for key, value in sorted(params.items()):
        val_str = str(value)
        if not show_full:
            val_str = _truncate_value(val_str, DEFAULT_TRUNCATE_WIDTH)
        print(f"  {key}: {val_str}")

    # Count repetition folders
    rep_dirs = sorted(exec_dir.glob("repetition_*"))
    if rep_dirs:
        print(f"\nRepetitions: {len(rep_dirs)}")

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


def _show_executions_from_index(
    run_root: Path,
    index_file: Path,
    filter_dict: Dict[str, str],
    show_command: bool = False,
    show_full: bool = False,
    hide_columns: Optional[set] = None,
    status_filter: Optional[str] = None
) -> None:
    """Show executions from the index file, optionally filtered."""
    hide_columns = hide_columns or set()

    try:
        with open(index_file, 'r') as f:
            index = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading {index_file}: {e}")
        return

    benchmark_name = index.get("benchmark", "Unknown")
    executions = index.get("executions", {})

    # Read run metadata for additional info
    run_metadata = _read_run_metadata(run_root)
    bench_meta = run_metadata.get("benchmark", {})

    # Display run header with metadata
    print(f"Benchmark: {benchmark_name}")
    if bench_meta.get("description"):
        print(f"Description: {bench_meta['description']}")
    if bench_meta.get("hostname"):
        print(f"Host: {bench_meta['hostname']}")
    if bench_meta.get("timestamp"):
        print(f"Executed: {bench_meta['timestamp']}")

    if not executions:
        print("No executions found in index.")
        return

    # Get all variable names for header
    all_vars = set()
    for exec_data in executions.values():
        all_vars.update(exec_data.get("params", {}).keys())
    var_names = sorted(all_vars)

    # Remove hidden columns from var_names
    var_names = [v for v in var_names if v not in hide_columns]

    # Determine truncation width
    truncate_width = None if show_full else DEFAULT_TRUNCATE_WIDTH

    # Filter executions and collect status
    matches = []
    for exec_key, exec_data in sorted(executions.items()):
        params = exec_data.get("params", {})
        rel_path = exec_data.get("path", "")
        command = exec_data.get("command", "")

        # Read status from status file
        exec_path = run_root / rel_path
        status_info = _read_status(exec_path)
        status = status_info.get("status", "UNKNOWN")

        # Apply status filter
        if status_filter and status.upper() != status_filter.upper():
            continue

        # Apply parameter filters (partial match - only check specified vars)
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

        matches.append((exec_key, rel_path, params, command, status))

    if not matches:
        filter_desc = []
        if filter_dict:
            filter_desc.append(f"parameters: {filter_dict}")
        if status_filter:
            filter_desc.append(f"status: {status_filter}")
        if filter_desc:
            print(f"No executions match the filter ({', '.join(filter_desc)})")
        else:
            print("No executions found.")
        return

    # Helper to get display value (with optional truncation)
    def display_val(val: str) -> str:
        if truncate_width is None:
            return val
        return _truncate_value(val, truncate_width)

    # Calculate column widths (using truncated values if truncation is enabled)
    col_widths = {}

    # Path column
    if "path" not in hide_columns:
        path_values = [display_val(m[1]) for m in matches]
        col_widths["path"] = max(len("Path"), max(len(v) for v in path_values))

    # Status column
    if "status" not in hide_columns:
        status_values = [m[4] for m in matches]
        col_widths["status"] = max(len("Status"), max(len(v) for v in status_values))

    # Variable columns
    for var in var_names:
        var_values = [display_val(str(m[2].get(var, ""))) for m in matches]
        col_widths[var] = max(len(var), max(len(v) for v in var_values) if var_values else 0)

    # Command column
    if show_command and "command" not in hide_columns:
        cmd_values = [display_val(m[3]) for m in matches]
        col_widths["command"] = max(len("Command"), max(len(v) for v in cmd_values) if cmd_values else 0)

    # Build header
    header_parts = []
    if "path" not in hide_columns:
        header_parts.append("Path".ljust(col_widths["path"]))
    if "status" not in hide_columns:
        header_parts.append("Status".ljust(col_widths["status"]))
    for var in var_names:
        header_parts.append(var.ljust(col_widths[var]))
    if show_command and "command" not in hide_columns:
        header_parts.append("Command")

    header = "  ".join(header_parts)
    print("\n")
    print(header)
    print("-" * len(header))

    # Print rows
    for exec_key, rel_path, params, command, status in matches:
        row_parts = []

        if "path" not in hide_columns:
            row_parts.append(display_val(rel_path).ljust(col_widths["path"]))

        if "status" not in hide_columns:
            row_parts.append(status.ljust(col_widths["status"]))

        for var in var_names:
            val = display_val(str(params.get(var, "")))
            row_parts.append(val.ljust(col_widths[var]))

        if show_command and "command" not in hide_columns:
            row_parts.append(display_val(command))

        print("  ".join(row_parts))


def load_version():
    """
    Load the version of the IOPS Tool from the version file.
    """
    version_file = Path(__file__).parent / "VERSION"
    if not version_file.exists():
        raise FileNotFoundError(f"Version file not found: {version_file}")
    
    with version_file.open() as f:
        return f.read().strip()
    
def _add_common_args(parser):
    """Add common arguments shared across subcommands."""
    parser.add_argument('--log-file', type=Path, default=Path("iops.log"), metavar='PATH',
                        help="Path to log file (default: iops.log)")
    parser.add_argument('--log-level', type=str, default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help="Logging level (default: INFO)")
    parser.add_argument('--no-log-terminal', action='store_true',
                        help="Disable logging to terminal")
    parser.add_argument('-v', '--verbose', action='store_true',
                        help="Show full traceback for errors")


def _preprocess_args():
    """
    Preprocess command-line arguments to support shorthand syntax.

    If the first argument is a YAML file (ends with .yaml or .yml),
    automatically insert 'run' command. This allows:
        iops config.yaml  ->  iops run config.yaml
    """
    import sys

    if len(sys.argv) < 2:
        return

    first_arg = sys.argv[1]

    # Skip if it's already a known command, a flag, or --version/--help
    known_commands = {'run', 'check', 'find', 'report', 'generate'}
    if first_arg in known_commands or first_arg.startswith('-'):
        return

    # If first arg looks like a YAML file, insert 'run' command
    if first_arg.endswith('.yaml') or first_arg.endswith('.yml'):
        sys.argv.insert(1, 'run')


def parse_arguments():
    _preprocess_args()

    parser = argparse.ArgumentParser(
        description="IOPS - A generic benchmark orchestration framework for automated parametric experiments.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  iops config.yaml                  Execute benchmark (shorthand)
  iops run config.yaml              Execute benchmark
  iops run config.yaml --dry-run    Preview execution plan
  iops check config.yaml            Validate configuration
  iops find ./workdir               List all executions
  iops find ./workdir nodes=4       Filter by parameter
  iops report ./run_001             Generate HTML report
  iops generate                     Create config template
"""
    )
    parser.add_argument('--version', action='version', version=f'IOPS Tool v{load_version()}')

    subparsers = parser.add_subparsers(dest='command', title='commands', metavar='<command>')

    # ---- run command ----
    run_parser = subparsers.add_parser('run', help='Execute a benchmark configuration',
                                        description='Execute a benchmark from a YAML configuration file.')
    run_parser.add_argument('config_file', type=Path, help="Path to the YAML configuration file")
    run_parser.add_argument('-n', '--dry-run', action='store_true',
                            help="Preview execution plan without running tests")
    run_parser.add_argument('--use-cache', action='store_true',
                            help="Reuse cached results, skip already executed tests")
    run_parser.add_argument('--max-core-hours', type=float, default=None, metavar='N',
                            help="Maximum CPU core-hours budget for execution")
    run_parser.add_argument('--time-estimate', type=str, default=None, metavar='SEC',
                            help="Estimated time per test (e.g., '120' or '60,120,300')")
    _add_common_args(run_parser)

    # ---- find command ----
    find_parser = subparsers.add_parser('find', help='Find and explore execution folders',
                                         description='Find execution folders in a workdir and display their parameters.')
    find_parser.add_argument('path', type=Path, help="Path to workdir or execution folder")
    find_parser.add_argument('filter', type=str, nargs='*', metavar='VAR=VALUE',
                             help="Filter executions by variable values (e.g., nodes=4 ppn=8)")
    find_parser.add_argument('--show-command', action='store_true',
                             help="Show the command column")
    find_parser.add_argument('--full', action='store_true',
                             help="Show full parameter values (no truncation)")
    find_parser.add_argument('--hide', type=str, default=None, metavar='COL1,COL2',
                             help="Hide specific columns (comma-separated, e.g., --hide path,command)")
    find_parser.add_argument('--status', type=str, default=None, metavar='STATUS',
                             help="Filter by execution status (SUCCEEDED, FAILED, ERROR, UNKNOWN, PENDING)")
    _add_common_args(find_parser)

    # ---- report command ----
    report_parser = subparsers.add_parser('report', help='Generate HTML report from completed run',
                                           description='Generate an interactive HTML report from benchmark results.')
    report_parser.add_argument('path', type=Path, help="Path to the run directory (e.g., ./workdir/run_001)")
    report_parser.add_argument('--report-config', type=Path, default=None, metavar='PATH',
                               help="Custom report config YAML (auto-detects report_config.yaml in workdir)")
    _add_common_args(report_parser)

    # ---- generate command ----
    generate_parser = subparsers.add_parser('generate', help='Generate a default config template',
                                             description='Generate a YAML configuration template to get started.')
    generate_parser.add_argument('output', type=Path, nargs='?', default=Path("iops_config.yaml"),
                                 help="Output file path (default: iops_config.yaml)")

    # Executor type (mutually exclusive)
    executor_group = generate_parser.add_mutually_exclusive_group()
    executor_group.add_argument('--local', action='store_true', dest='executor_local',
                                help="Generate template for local execution (default)")
    executor_group.add_argument('--slurm', action='store_true', dest='executor_slurm',
                                help="Generate template for SLURM cluster execution")

    # Benchmark type (mutually exclusive)
    benchmark_group = generate_parser.add_mutually_exclusive_group()
    benchmark_group.add_argument('--ior', action='store_true', dest='benchmark_ior',
                                 help="Generate IOR benchmark template (default)")
    benchmark_group.add_argument('--mdtest', action='store_true', dest='benchmark_mdtest',
                                 help="Generate mdtest metadata benchmark template")

    # Template complexity
    generate_parser.add_argument('--full', action='store_true',
                                 help="Generate fully documented template with all options")

    # Examples
    generate_parser.add_argument('--examples', action='store_true',
                                 help="Copy example configurations and scripts to ./examples/")

    _add_common_args(generate_parser)

    # ---- check command ----
    check_parser = subparsers.add_parser('check', help='Validate a configuration file',
                                          description='Validate a YAML configuration file without executing.')
    check_parser.add_argument('config_file', type=Path, help="Path to the YAML configuration file")
    _add_common_args(check_parser)

    args = parser.parse_args()

    # Show help if no command provided
    if args.command is None:
        parser.print_help()
        parser.exit()

    return args


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
    logger.info(f"  Config File: {args.config_file}")    
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
    if cfg.benchmark.cache_file:
        logger.debug(f"  Cache File : {cfg.benchmark.cache_file}")

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

    # ---- generate command ----
    if args.command == 'generate':
        from iops.setup import BenchmarkWizard

        try:
            # Determine executor (default: local)
            executor = "slurm" if args.executor_slurm else "local"

            # Determine benchmark (default: ior)
            benchmark = "mdtest" if args.benchmark_mdtest else "ior"

            wizard = BenchmarkWizard()
            output_path = str(args.output) if args.output else None
            output_file = wizard.run(
                output_path=output_path,
                executor=executor,
                benchmark=benchmark,
                full_template=args.full,
                copy_examples=args.examples
            )

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

    # ---- find command ----
    if args.command == 'find':
        # Parse hide columns
        hide_columns = set()
        if args.hide:
            hide_columns = {col.strip() for col in args.hide.split(',')}

        find_executions(
            args.path,
            args.filter,
            show_command=args.show_command,
            show_full=args.full,
            hide_columns=hide_columns,
            status_filter=args.status
        )
        return

    # ---- report command ----
    if args.command == 'report':
        from iops.reporting.report_generator import generate_report_from_workdir
        from iops.config.loader import load_report_config

        logger.info("=" * 70)
        logger.info("REPORT MODE: Generating HTML report")
        logger.info("=" * 70)
        logger.info(f"Reading results from: {args.path}")

        # Load report config: explicit flag > auto-detect in workdir > metadata defaults
        report_config = None
        config_path = args.report_config

        # Auto-detect report_config.yaml in workdir if not explicitly provided
        if config_path is None:
            default_config = args.path / "report_config.yaml"
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
            report_path = generate_report_from_workdir(args.path, report_config=report_config)
            logger.info(f"✓ Report generated: {report_path}")
            logger.info("=" * 70)
        except Exception as e:
            logger.error(f"Failed to generate report: {e}")
            if args.verbose:
                raise
        return

    # ---- check command ----
    if args.command == 'check':
        from iops.config.loader import validate_yaml_config
        errors = validate_yaml_config(args.config_file)
        if errors:
            logger.error(f"Configuration validation failed with {len(errors)} error(s):")
            for i, err in enumerate(errors, 1):
                logger.error(f"  {i}. {err}")
            return
        else:
            logger.info("Configuration is valid.")
            return

    # ---- run command ----
    if args.command == 'run':
        try:
            cfg = load_generic_config(args.config_file, logger=logger, dry_run=args.dry_run)
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
        try:
            if args.dry_run:
                runner.run_dry()
            else:
                runner.run()
        except ConfigValidationError as e:
            logger.error(f"Configuration error: {e}")
            if args.verbose:
                raise
            return



if __name__ == "__main__":
    main()
