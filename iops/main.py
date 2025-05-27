import argparse
import logging
from pathlib import Path

from iops.utils.file_utils import FileUtils
from iops.utils.logger import setup_logger
from iops.controller.runner import IOPSRunner


def main():
    parser = argparse.ArgumentParser(description="IOPS Benchmark Tool")

    parser.add_argument(
        'setup_file',
        type=Path,
        nargs='?',
        default=None,
        help="Path to the .ini setup file to load (optional unless running execution)"
    )

    parser.add_argument(
        '--generate_setup',
        nargs='?',
        const="iops_config.ini",
        default=None,
        type=Path,
        help="Generate a default setup .ini file. Optionally specify a path (default: iops_config.ini)"
    )

    parser.add_argument(
        '--check_setup',
        action='store_true',
        help="Check the validity of the setup .ini file but do not start the execution"
    )

    parser.add_argument(
        '--log_file',
        type=Path,
        default=Path("iops.log"),
        help="Path to the log file (default: iops.log)"
    )

    parser.add_argument(
        '--log_terminal',
        action='store_true',
        help="Also print logs to terminal"
    )

    parser.add_argument(
        '--log_level',
        type=str,
        default='INFO',
        help="Set the logging level (default: INFO)"
    )

    args = parser.parse_args()

    logger = setup_logger(
        name="iops",
        log_file=args.log_file,
        to_stdout=args.log_terminal,
        to_file=args.log_file is not None,
        level=getattr(logging, args.log_level.upper(), logging.INFO)
    )

    fu = FileUtils()

    if args.generate_setup is not None:
        logger.info(f"Generating setup file at: {args.generate_setup}")
        fu.generate_iops_config(args.generate_setup)
        logger.info("Setup file generated successfully.")
        return

    if args.setup_file is None:
        logger.error("No setup file provided for validation or execution.")
        return

    logger.info(f"Loading configuration from: {args.setup_file}")
    config = fu.load_iops_config(args.setup_file)
    logger.info("Configuration loaded successfully.")

    try:
        fu.validate_iops_config(config)
        logger.info("Configuration is valid.")
        if args.check_setup:
            return
    except ValueError as e:
        logger.error(f"Configuration validation failed: {e}")
        return

    logger.info("Starting IOPS execution with the provided configuration.")
    runner = IOPSRunner(config)
    runner.run()


if __name__ == "__main__":
    main()
