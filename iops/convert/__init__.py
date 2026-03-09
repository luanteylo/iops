"""JUBE XML to IOPS YAML conversion module.

Provides the convert_jube_to_iops() function for converting JUBE benchmark
configurations to IOPS format. Requires the JUBE library to be installed
(pip install git+https://github.com/FZJ-JSC/JUBE.git).
"""

import logging
from pathlib import Path


def convert_jube_to_iops(
    input_file,
    output_file=None,
    benchmark_name=None,
    executor="local",
    dry_run=False,
    logger=None,
):
    """Convert a JUBE XML benchmark configuration to IOPS YAML format.

    Args:
        input_file: Path to the JUBE XML file.
        output_file: Path for the output YAML. If None, derives from input name.
        benchmark_name: Select a specific benchmark from the XML (if multiple).
        executor: Target executor ("local" or "slurm").
        dry_run: If True, print output to stdout instead of writing a file.
        logger: Logger instance (creates one if None).

    Returns:
        Path to the written file, or None if dry_run.

    Raises:
        ImportError: If the JUBE library is not installed.
        ValueError: If the XML cannot be parsed or benchmark not found.
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    # Lazy import to defer JUBE dependency check
    from iops.convert.jube_converter import JubeConverter

    input_path = Path(input_file)

    if output_file is None and not dry_run:
        output_file = input_path.with_name(input_path.stem + "_iops.yaml")

    converter = JubeConverter(
        input_file=input_path,
        benchmark_name=benchmark_name,
        executor=executor,
        logger=logger,
    )

    config, warnings = converter.convert()
    result = converter.write_yaml(config, output_file=output_file, dry_run=dry_run)
    converter.print_summary()

    return result
