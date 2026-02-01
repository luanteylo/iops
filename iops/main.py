import argparse
import logging
from pathlib import Path

from iops.logger import setup_logger
from iops.execution.runner import IOPSRunner
from iops.config.loader import load_generic_config, validate_generic_config, check_system_probe_compatibility, check_resource_sampler_compatibility
from iops.config.models import ConfigValidationError, GenericBenchmarkConfig
from iops.execution.matrix import build_execution_matrix
from iops.results.find import find_executions


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
    known_commands = {'run', 'check', 'find', 'report', 'generate', 'archive', 'cache'}
    if first_arg in known_commands or first_arg.startswith('-'):
        return

    # If first arg looks like a YAML file, insert 'run' command
    if first_arg.endswith('.yaml') or first_arg.endswith('.yml'):
        sys.argv.insert(1, 'run')


def _validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser):
    """
    Validate command-line arguments for specific commands.
    Uses parser.error() for clean error messages.
    """
    if args.command == 'run':
        if args.max_core_hours is not None and args.max_core_hours <= 0:
            parser.error("--max-core-hours must be positive")

        if args.time_estimate is not None:
            for part in args.time_estimate.split(','):
                part = part.strip()
                try:
                    val = float(part)
                    if val <= 0:
                        raise ValueError
                except ValueError:
                    parser.error(f"Invalid --time-estimate value: '{part}' (expected positive number)")

        # --cache-only implies --use-cache
        if getattr(args, 'cache_only', False):
            args.use_cache = True

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
    run_parser.add_argument('--cache-only', action='store_true',
                            help="Only use cached results; skip tests not in cache (requires cache_file)")
    run_parser.add_argument('--fail-fast', action='store_true',
                            help="Stop execution on first test failure")
    run_parser.add_argument('--meline', action='store_true',
                            help=argparse.SUPPRESS)  # Easter egg: hide banner
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
    find_parser.add_argument('--cached', type=str, default=None, choices=['yes', 'no'],
                             help="Filter by cache status (yes=only cached, no=only executed)")
    find_parser.add_argument('--watch', '-w', action='store_true',
                             help="Continuously monitor execution status (requires: pip install iops-benchmark[watch])")
    find_parser.add_argument('--interval', type=int, default=5, metavar='SECONDS',
                             help="Refresh interval in seconds for watch mode (default: 5)")
    find_parser.add_argument('--metrics', '-m', action='store_true',
                             help="Show metric columns with average values (watch mode only)")
    find_parser.add_argument('--filter-metric', type=str, action='append', metavar='METRIC<OP>VALUE',
                             help="Filter by metric value, e.g., 'bwMiB>1000' (watch mode only, can repeat)")
    _add_common_args(find_parser)

    # ---- report command ----
    report_parser = subparsers.add_parser('report', help='Generate HTML report from completed run',
                                           description='Generate an interactive HTML report from benchmark results.')
    report_parser.add_argument('path', type=Path, help="Path to the run directory (e.g., ./workdir/run_001)")
    report_parser.add_argument('--report-config', type=Path, default=None, metavar='PATH',
                               help="Custom report config YAML (auto-detects report_config.yaml in workdir)")
    report_parser.add_argument('--export-plots', action='store_true',
                               help="Export plots as image files to __iops_plots folder")
    report_parser.add_argument('--plot-format', type=str, default='pdf',
                               choices=['pdf', 'png', 'svg', 'jpg', 'webp'],
                               help="Image format for exported plots (default: pdf)")
    _add_common_args(report_parser)

    # ---- generate command ----
    generate_parser = subparsers.add_parser('generate', help='Generate a default config template',
                                             description='Generate a YAML configuration template to get started.')
    generate_parser.add_argument('output', type=Path, nargs='?', default=Path("iops_config.yaml"),
                                 help="Output file path (default: iops_config.yaml)")

    # Executor type (mutually exclusive)
    executor_group = generate_parser.add_mutually_exclusive_group()
    executor_group.add_argument('--local', action='store_true', dest='executor_local',
                                help="Generate template for local execution")
    executor_group.add_argument('--slurm', action='store_true', dest='executor_slurm',
                                help="Generate template for SLURM cluster execution (default)")

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

    # ---- archive command with subcommands ----
    archive_parser = subparsers.add_parser('archive', help='Archive and extract IOPS workdirs',
                                            description='Create and extract IOPS archives for portability.')
    archive_subparsers = archive_parser.add_subparsers(dest='archive_command', title='archive commands',
                                                        metavar='<archive-command>')

    # archive create
    archive_create_parser = archive_subparsers.add_parser('create', help='Create archive from workdir or run',
                                                           description='Create a compressed archive from an IOPS run or workdir.')
    archive_create_parser.add_argument('source', type=Path, help='Path to workdir or run directory')
    archive_create_parser.add_argument('filter', type=str, nargs='*', metavar='VAR=VALUE',
                                       help='Filter by variable values (e.g., nodes=4)')
    archive_create_parser.add_argument('-o', '--output', type=Path, default=None, metavar='PATH',
                                       help='Output archive path (default: <source>.tar.gz)')
    archive_create_parser.add_argument('--compression', choices=['gz', 'bz2', 'xz', 'none'],
                                       default='gz', help='Compression format (default: gz)')
    archive_create_parser.add_argument('--no-progress', action='store_true',
                                       help='Disable progress bar')
    archive_create_parser.add_argument('--partial', action='store_true',
                                       help='Create partial archive with only filtered executions')
    archive_create_parser.add_argument('--status', type=str, default=None, metavar='STATUS',
                                       help='Filter by execution status (SUCCEEDED, FAILED, etc.)')
    archive_create_parser.add_argument('--cached', type=str, choices=['yes', 'no'], default=None,
                                       help='Filter by cache status')
    archive_create_parser.add_argument('--min-reps', type=int, default=None, metavar='N',
                                       help='Include executions with at least N completed repetitions')
    _add_common_args(archive_create_parser)

    # archive extract
    archive_extract_parser = archive_subparsers.add_parser('extract', help='Extract archive to directory',
                                                            description='Extract an IOPS archive to a directory.')
    archive_extract_parser.add_argument('archive', type=Path, help='Path to archive file')
    archive_extract_parser.add_argument('-o', '--output', type=Path, default=None, metavar='PATH',
                                        help='Output directory (default: current directory)')
    archive_extract_parser.add_argument('--no-verify', action='store_true',
                                        help='Skip integrity verification')
    archive_extract_parser.add_argument('--no-progress', action='store_true',
                                        help='Disable progress bar')
    _add_common_args(archive_extract_parser)

    # ---- cache command with subcommands ----
    cache_parser = subparsers.add_parser('cache', help='Cache management commands',
                                          description='Manage IOPS execution cache.')
    cache_subparsers = cache_parser.add_subparsers(dest='cache_command', title='cache commands',
                                                    metavar='<cache-command>')

    # cache rebuild
    cache_rebuild_parser = cache_subparsers.add_parser('rebuild', help='Rebuild cache with different excluded variables',
                                                        description='Rebuild a cache database excluding additional variables from the hash.')
    cache_rebuild_parser.add_argument('source', type=Path, help='Path to source cache database')
    cache_rebuild_parser.add_argument('--exclude', type=str, required=True, metavar='VAR1,VAR2',
                                      help='Comma-separated list of variables to exclude from hash')
    cache_rebuild_parser.add_argument('-o', '--output', type=Path, default=None, metavar='PATH',
                                      help='Output database path (default: <source>_rebuilt.db)')
    _add_common_args(cache_rebuild_parser)

    args = parser.parse_args()

    # Show help if no command provided
    if args.command is None:
        parser.print_help()
        parser.exit()
    
    # validate args for specific commands
    _validate_args(args, parser)

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

    # Easter egg: --meline hides the banner
    if not getattr(args, 'meline', False):
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

    swept_vars = []
    derived_vars = []
    for name, var in cfg.vars.items():
        if var.sweep:
            swept_vars.append(name)
        elif var.expr:
            derived_vars.append(name)

    if swept_vars:
        logger.debug(f"  Swept: {', '.join(swept_vars)}")
    if derived_vars:
        logger.debug(f"  Derived: {', '.join(derived_vars)}")

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
    cmd_lines = cfg.command.template.strip().split('\n')
    logger.debug(f"  Template: {len(cmd_lines)} lines")
    if cfg.command.env:
        logger.debug(f"  Environment: {len(cfg.command.env)} variables")
    if cfg.command.labels:
        logger.debug(f"  Labels: {len(cfg.command.labels)} defined")

    # ------------------------------------------------------------------
    logger.debug(sub)
    logger.debug("Execution Scripts")
    logger.debug(sub)

    for i, script in enumerate(cfg.scripts, start=1):
        script_lines = script.script_template.strip().split('\n')
        logger.debug(f"  Script #{i}: {script.name} ({len(script_lines)} lines)")

        if script.post:
            post_lines = script.post.script.strip().split('\n')
            logger.debug(f"    Post-script: {len(post_lines)} lines")

        if script.parser:
            logger.debug(f"    Parser: file={script.parser.file}")
            logger.debug(f"    Metrics: {[m.name for m in script.parser.metrics]}")

    # ------------------------------------------------------------------    
    logger.debug(sub)
    logger.debug("Output")
    logger.debug(sub)

    sink = cfg.output.sink
    logger.debug(f"  Type : {sink.type}")
    logger.debug(f"  Path : {sink.path}")

    if sink.type == "sqlite":
        logger.debug(f"  Table: {sink.table}")

    # Field selection policy
    if sink.exclude:
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
            # Determine executor (default: slurm)
            executor = "local" if args.executor_local else "slurm"

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

        # Parse cached filter (convert string to bool)
        cached_filter = None
        if args.cached:
            cached_filter = args.cached == 'yes'

        if args.watch:
            # Watch mode - requires rich library
            from iops.results.watch import watch_executions, WatchModeError
            try:
                watch_executions(
                    args.path,
                    args.filter,
                    show_command=args.show_command,
                    show_full=args.full,
                    hide_columns=hide_columns,
                    status_filter=args.status,
                    interval=args.interval,
                    cached_filter=cached_filter,
                    show_metrics=args.metrics,
                    metric_filters=getattr(args, 'filter_metric', None)
                )
            except WatchModeError as e:
                logger.error(str(e))
                return
        else:
            find_executions(
                args.path,
                args.filter,
                show_command=args.show_command,
                show_full=args.full,
                hide_columns=hide_columns,
                status_filter=args.status,
                cached_filter=cached_filter
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
            report_path = generate_report_from_workdir(
                args.path,
                report_config=report_config,
                export_plots=args.export_plots,
                plot_format=args.plot_format
            )
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

    # ---- archive command ----
    if args.command == 'archive':
        from iops.archive import create_archive, extract_archive
        from iops.archive.core import COMPRESSION_EXTENSIONS

        if args.archive_command == 'create':
            try:
                # Parse parameter filters from VAR=VALUE arguments
                param_filters = {}
                if hasattr(args, 'filter') and args.filter:
                    for f in args.filter:
                        if '=' in f:
                            key, value = f.split('=', 1)
                            param_filters[key] = value
                        else:
                            logger.warning(f"Ignoring invalid filter (expected VAR=VALUE): {f}")

                # Parse cached filter
                cached_filter = None
                if args.cached:
                    cached_filter = args.cached == 'yes'

                # --min-reps implies --partial
                min_reps = getattr(args, 'min_reps', None)
                is_partial = args.partial or min_reps is not None

                # Determine output path
                if args.output:
                    output_path = args.output
                else:
                    ext = COMPRESSION_EXTENSIONS.get(args.compression, ".tar.gz")
                    # Add -partial suffix for partial archives
                    suffix = "-partial" if is_partial else ""
                    output_path = Path(f"{args.source.name}{suffix}{ext}")

                archive_path = create_archive(
                    args.source,
                    output_path,
                    args.compression,
                    show_progress=not args.no_progress,
                    partial=is_partial,
                    status_filter=args.status,
                    cached_filter=cached_filter,
                    param_filters=param_filters if param_filters else None,
                    min_completed_reps=min_reps,
                )
                logger.info(f"Archive created: {archive_path}")
            except FileNotFoundError as e:
                logger.error(f"Source not found: {e}")
                if args.verbose:
                    raise
            except ValueError as e:
                logger.error(f"Archive creation failed: {e}")
                if args.verbose:
                    raise
            except Exception as e:
                logger.error(f"Unexpected error creating archive: {e}")
                if args.verbose:
                    raise
            return

        elif args.archive_command == 'extract':
            try:
                dest = args.output or Path.cwd()
                extracted_path = extract_archive(args.archive, dest, verify=not args.no_verify,
                                                 show_progress=not args.no_progress)
                logger.info(f"Extracted to: {extracted_path}")
            except FileNotFoundError as e:
                logger.error(f"Archive not found: {e}")
                if args.verbose:
                    raise
            except ValueError as e:
                logger.error(f"Extraction failed: {e}")
                if args.verbose:
                    raise
            except Exception as e:
                logger.error(f"Unexpected error extracting archive: {e}")
                if args.verbose:
                    raise
            return

        else:
            # No subcommand provided
            logger.error("No archive subcommand specified. Use 'iops archive create' or 'iops archive extract'.")
            logger.info("Run 'iops archive --help' for more information.")
            return

    # ---- cache command ----
    if args.command == 'cache':
        from iops.cache import rebuild_cache

        if args.cache_command == 'rebuild':
            try:
                # Parse exclude vars
                exclude_vars = [v.strip() for v in args.exclude.split(',') if v.strip()]
                if not exclude_vars:
                    logger.error("No variables specified in --exclude")
                    return

                # Determine output path
                if args.output:
                    output_path = args.output
                else:
                    source_stem = args.source.stem
                    output_path = args.source.parent / f"{source_stem}_rebuilt.db"

                stats = rebuild_cache(
                    source_db=args.source,
                    output_db=output_path,
                    exclude_vars=exclude_vars,
                    logger=logger,
                )

                logger.info("")
                logger.info(stats.summary())
                logger.info(f"Rebuilt cache saved to: {output_path}")

            except FileNotFoundError as e:
                logger.error(str(e))
                if args.verbose:
                    raise
            except ValueError as e:
                logger.error(str(e))
                if args.verbose:
                    raise
            except Exception as e:
                logger.error(f"Unexpected error rebuilding cache: {e}")
                if args.verbose:
                    raise
            return

        else:
            # No subcommand provided
            logger.error("No cache subcommand specified. Use 'iops cache rebuild'.")
            logger.info("Run 'iops cache --help' for more information.")
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

        # Validate --cache-only requires cache_file to be configured
        if getattr(args, 'cache_only', False) and not cfg.benchmark.cache_file:
            logger.error("--cache-only requires benchmark.cache_file to be configured in the YAML file")
            return

        log_execution_context(cfg, args, logger)

        # Check system probe compatibility (warns and disables if non-bash shell detected)
        check_system_probe_compatibility(cfg, logger)

        # Check resource sampler compatibility (warns and disables if non-bash shell detected)
        check_resource_sampler_compatibility(cfg, logger)

        runner = IOPSRunner(cfg=cfg, args=args)

        # Run in dry-run mode or normal mode
        try:
            if args.dry_run:
                runner.run_dry()
            else:
                runner.run()
        except KeyboardInterrupt:
            logger.info("\n\nExecution interrupted by user (Ctrl+C)")
            return
        except ConfigValidationError as e:
            logger.error(f"Configuration error: {e}")
            if args.verbose:
                raise
            return



if __name__ == "__main__":
    main()
