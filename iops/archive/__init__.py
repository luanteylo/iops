"""IOPS Archive module for compressing and extracting workdirs and runs."""

from pathlib import Path
from typing import Union

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
) -> Path:
    """
    Create an IOPS archive from a run directory or workdir.

    Args:
        source: Path to the run directory or workdir to archive.
        output: Path for the output archive file.
        compression: Compression type ("gz", "bz2", "xz", or "none").
        show_progress: Whether to show a progress bar (requires rich).

    Returns:
        Path to the created archive.

    Raises:
        FileNotFoundError: If source does not exist.
        ValueError: If source is not a valid IOPS directory or compression is invalid.

    Example:
        >>> create_archive("./workdir/run_001", "study.tar.gz")
        PosixPath('/path/to/study.tar.gz')

        >>> create_archive("./workdir", "all_studies.tar.xz", compression="xz")
        PosixPath('/path/to/all_studies.tar.xz')
    """
    writer = ArchiveWriter(Path(source))
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
