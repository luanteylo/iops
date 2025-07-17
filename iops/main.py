import argparse
import logging
from pathlib import Path

from iops.utils.file_utils import FileUtils
from iops.utils.logger import setup_logger
from iops.controller.runner import IOPSRunner
from iops.utils.config_loader import ConfigValidationError, to_dictionary, IOPSConfig


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


def log_execution_context(config: IOPSConfig, args, logger):
    """
    Logs the initial parameters before execution, including command-line arguments and the setup configuration.
    """
    logger.info("==== Execution Arguments ====")
    logger.info(f"Setup file: {args.setup_file}")
    logger.info(f"Log file: {args.log_file}")
    logger.info(f"Use cache: {args.use_cache}")
    

    logger.info("==== Setup Configuration ====")

    config_dict = to_dictionary(config)

    for section, params in config_dict.items():
        logger.info(f"{section.capitalize()} settings:")
        if isinstance(params, dict):
            for key, value in params.items():
                logger.info(f"  {key}: {value}")
        else:
            logger.info(f"  {section}: {params}")


def main():
    args = parse_arguments()
    logger = initialize_logger(args)

    if handle_generate_setup(args, logger):
        return

    if not args.setup_file:
        logger.error("No setup file provided for validation or execution.")
        return

    fu = FileUtils()
    config = fu.load_iops_config(args.setup_file)
    logger.debug(f"Configuration loaded: {config}")

    try:
        fu.validate_iops_config(config)
        if args.check_setup:
            logger.info("Setup file validation successful.")
            return
        fu.create_workdir(config)
    except ConfigValidationError as e:
        logger.exception(f"Configuration validation failed: {e}" if args.verbose else f"Configuration validation failed:\n  → {e}")
        return
    except Exception as e:
        logger.exception("Unexpected error during setup.") if args.verbose else logger.error(f"Unexpected error: {e}")
        return

    log_execution_context(config, args, logger)
    IOPSRunner(config, args).run()



if __name__ == "__main__":
    main()
