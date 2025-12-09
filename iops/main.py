import argparse
import logging
from pathlib import Path

from iops.utils.file_utils import FileUtils
from iops.utils.logger import setup_logger
from iops.controller.runner import IOPSRunner
#from iops.utils.config_loader import ConfigValidationError, IOPSConfig
from iops.utils.generic_config import load_generic_config, validate_generic_config, ConfigValidationError, GenericBenchmarkConfig
from iops.utils.execution_matrix import build_execution_matrix

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
    parser = argparse.ArgumentParser(description="IOPS Tool")

    parser.add_argument('setup_file', type=Path, nargs='?', help="Path to the YAML setup file (e.g., iops_config.yaml)")
    parser.add_argument('--generate_setup', nargs='?', const=Path("iops_config.yaml"), type=Path,
                        help="Generate a default setup YAML file. Optionally specify a path (default: iops_config.yaml)")
    parser.add_argument('--check_setup', action='store_true', help="Validate the setup YAML file and exit")
    parser.add_argument('--log_file', type=Path, default=Path("iops.log"), help="Path to the log file")
    parser.add_argument('--log_terminal', action='store_true', help="Print logs to terminal")
    parser.add_argument('--log_level', type=str, default='INFO', help="Logging level (default: INFO)")
    parser.add_argument('--verbose', action='store_true', help="Show full traceback for errors")
    parser.add_argument('--use_cache', action='store_true',
                        help="Reuse cached results if available, skipping already executed parameter sets")
    parser.add_argument('--version', action='version', version=f'IOPS Tool v{load_version()}')

    return parser.parse_args()


def initialize_logger(args):
    return setup_logger(
        name="iops",
        log_file=args.log_file,
        to_stdout=args.log_terminal,
        to_file=args.log_file is not None,
        level=getattr(logging, args.log_level.upper(), logging.INFO)
    )


def handle_generate_setup(args, logger):
    if args.generate_setup:
        logger.info(f"Generating default YAML setup file at: {args.generate_setup}")
        FileUtils().generate_iops_config(args.generate_setup)
        logger.info("Setup file generated successfully.")
        return True
    return False


def log_execution_context(cfg: GenericBenchmarkConfig, args, logger):
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
    logger.info("  IOPS — I/O Performance Search")
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
    if cfg.benchmark.sqlite_db:
        logger.debug(f"  SQLite DB  : {cfg.benchmark.sqlite_db}")
        

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
        logger.debug(f"    Mode   : {script.mode}")
        logger.debug(f"    Submit : {script.submit}")

        logger.debug("    Script template:")
        logger.debug("    " + script.script_template.replace("\n", "\n    "))

        if script.post:
            logger.debug("    Post-processing script:")
            logger.debug("    " + script.post.script.replace("\n", "\n    "))

        if script.parser:
            logger.debug("    Parser:")
            logger.debug(f"      Type : {script.parser.type}")
            logger.debug(f"      File : {script.parser.file}")

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
    logger.debug(f"  CSV path : {cfg.output.csv.path}")
    logger.debug("  CSV fields:")
    for field in cfg.output.csv.include:
        logger.debug(f"    - {field}")

    logger.debug(sep)



def main():
    args = parse_arguments()
    logger = initialize_logger(args)

   
    if not args.setup_file:
        logger.error("No setup file provided for validation or execution.")
        return

    cfg = load_generic_config(Path(args.setup_file))
    log_execution_context(cfg, args, logger)    

    logger.info("Building execution matrix...")
    executions = build_execution_matrix(cfg)
    logger.info(f"Total executions: {len(executions)}")
    for ex in executions:
        # add a line    
       logger.debug(ex.describe())
        
    
   
    
    


if __name__ == "__main__":
    main()
