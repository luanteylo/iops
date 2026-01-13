"""IOPS Archive module for compressing and extracting workdirs and runs."""

from pathlib import Path
from typing import Dict, Optional, Union

from iops.archive.core import ArchiveReader, ArchiveWriter
from iops.archive.manifest import ArchiveManifest, RunInfo

__all__ = [
    "ArchiveWriter",
    "ArchiveReader",
    "ArchiveManifest",
    "RunInfo",
    "create_archive",
    "extract_archive",
]


def create_archive(
    source: Union[str, Path],
    output: Union[str, Path],
    compression: str = "gz",
    show_progress: bool = True,
    partial: bool = False,
    status_filter: Optional[str] = None,
    cached_filter: Optional[bool] = None,
    param_filters: Optional[Dict[str, str]] = None,
    min_completed_reps: Optional[int] = None,
) -> Path:
    """
    Create an IOPS archive from a run directory or workdir.

    Args:
        source: Path to the run directory or workdir to archive.
        output: Path for the output archive file.
        compression: Compression type ("gz", "bz2", "xz", or "none").
        show_progress: Whether to show a progress bar (requires rich).
        partial: If True, create a partial archive with only filtered executions.
        status_filter: Filter by execution status (e.g., "SUCCEEDED", "FAILED").
        cached_filter: Filter by cache status (True=cached only, False=non-cached).
        param_filters: Filter by parameter values (e.g., {"nodes": "4"}).
        min_completed_reps: Minimum number of completed repetitions required.
                           Includes executions with at least this many finished reps.

    Returns:
        Path to the created archive.

    Raises:
        FileNotFoundError: If source does not exist.
        ValueError: If source is not a valid IOPS directory, compression is invalid,
                   or no executions match the filters (for partial archives).

    Example:
        >>> create_archive("./workdir/run_001", "study.tar.gz")
        PosixPath('/path/to/study.tar.gz')

        >>> create_archive("./workdir", "all_studies.tar.xz", compression="xz")
        PosixPath('/path/to/all_studies.tar.xz')

        >>> create_archive("./workdir/run_001", "partial.tar.gz",
        ...                partial=True, status_filter="SUCCEEDED")
        PosixPath('/path/to/partial.tar.gz')

        >>> create_archive("./workdir/run_001", "partial.tar.gz",
        ...                partial=True, min_completed_reps=1)
        PosixPath('/path/to/partial.tar.gz')
    """
    # min_completed_reps implies partial=True
    if min_completed_reps is not None:
        partial = True

    writer = ArchiveWriter(
        Path(source),
        partial=partial,
        status_filter=status_filter,
        cached_filter=cached_filter,
        param_filters=param_filters,
        min_completed_reps=min_completed_reps,
    )
    return writer.write(Path(output), compression, show_progress=show_progress)


def extract_archive(
    archive: Union[str, Path],
    dest: Union[str, Path],
    verify: bool = True,
    show_progress: bool = True,
) -> Path:
    """
    Extract an IOPS archive to a directory.

    Args:
        archive: Path to the archive file.
        dest: Directory to extract to.
        verify: Whether to verify checksums after extraction.
        show_progress: Whether to show a progress bar (requires rich).

    Returns:
        Path to the extracted directory.

    Raises:
        FileNotFoundError: If archive does not exist.
        ValueError: If archive is not valid or integrity verification fails.

    Example:
        >>> extract_archive("study.tar.gz", "./extracted")
        PosixPath('/path/to/extracted')

        >>> extract_archive("study.tar.gz", "./extracted", verify=False)
        PosixPath('/path/to/extracted')
    """
    reader = ArchiveReader(Path(archive))
    return reader.extract(Path(dest), verify, show_progress=show_progress)
