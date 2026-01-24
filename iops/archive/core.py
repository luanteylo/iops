"""Core archive functionality for creating and extracting IOPS archives."""

import bz2
import gzip
import hashlib
import json
import lzma
import socket
import tarfile
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from iops.archive.manifest import ArchiveManifest, RunInfo
from iops.archive.filter import (
    filter_executions,
    filter_result_file,
    create_filtered_index,
    get_result_file_paths,
)
from iops.logger import HasLogger

# Try to import rich for progress bars
try:
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskProgressColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


@contextmanager
def _get_progress_context(show_progress: bool, description: str, total: int):
    """
    Context manager that provides a progress tracker.

    If rich is available and show_progress is True, yields a rich Progress task.
    Otherwise, yields a no-op tracker.

    Args:
        show_progress: Whether to show progress bar.
        description: Description for the progress bar.
        total: Total number of items.

    Yields:
        Tuple of (progress_instance, task_id) or (None, None) if no progress.
    """
    if show_progress and RICH_AVAILABLE and total > 0:
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("[dim]{task.completed}/{task.total}"),
        )
        with progress:
            task = progress.add_task(description, total=total)
            yield progress, task
    else:
        yield None, None


# Compression mode mapping for tarfile
COMPRESSION_MODES = {
    "gz": "gz",
    "bz2": "bz2",
    "xz": "xz",
    "none": "",
}

# File extensions for each compression type
COMPRESSION_EXTENSIONS = {
    "gz": ".tar.gz",
    "bz2": ".tar.bz2",
    "xz": ".tar.xz",
    "none": ".tar",
}

# Critical IOPS metadata files to checksum
CRITICAL_METADATA_PATTERNS = [
    "__iops_index.json",
    "__iops_run_metadata.json",
    "__iops_params.json",
    "__iops_status.json",  # Repetition-level status
    "__iops_skipped",  # Test-level skipped marker
]


def _compute_checksum(file_path: Path) -> str:
    """Compute SHA256 checksum of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _load_version() -> str:
    """Load IOPS version from VERSION file."""
    version_file = Path(__file__).parent.parent / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "unknown"


class ArchiveWriter(HasLogger):
    """Creates IOPS archives with manifest."""

    def __init__(
        self,
        source_path: Path,
        partial: bool = False,
        status_filter: Optional[str] = None,
        cached_filter: Optional[bool] = None,
        param_filters: Optional[Dict[str, str]] = None,
        min_completed_reps: Optional[int] = None,
    ):
        """
        Initialize the archive writer.

        Args:
            source_path: Path to a run directory or workdir to archive.
            partial: If True, create a partial archive with only filtered executions.
            status_filter: Filter by execution status (e.g., "SUCCEEDED", "FAILED").
            cached_filter: Filter by cache status (True=cached only, False=non-cached).
            param_filters: Filter by parameter values (e.g., {"nodes": "4"}).
            min_completed_reps: Minimum number of completed repetitions required.
                               If specified, includes executions with at least this many
                               completed reps, regardless of overall status.

        Raises:
            ValueError: If source_path is not a valid IOPS run or workdir.
            FileNotFoundError: If source_path does not exist.
        """
        self.source_path = Path(source_path).resolve()

        if not self.source_path.exists():
            raise FileNotFoundError(f"Source path does not exist: {self.source_path}")

        if not self.source_path.is_dir():
            raise ValueError(f"Source path is not a directory: {self.source_path}")

        self.archive_type = self._detect_type()
        self.logger.debug(f"Detected archive type: {self.archive_type}")

        # Partial archive settings
        self.partial = partial
        self.status_filter = status_filter
        self.cached_filter = cached_filter
        self.param_filters = param_filters or {}
        self.min_completed_reps = min_completed_reps

        # Will be populated when filtering
        self._filtered_runs: Optional[Dict[str, Set[str]]] = None  # run_path -> exec_ids
        self._completed_reps_map: Optional[Dict[str, Dict[str, Set[int]]]] = None  # run_path -> exec_id -> rep_indices
        self._original_execution_count: int = 0
        self._filtered_rep_count: int = 0  # Total completed repetitions in filtered set

    def _detect_type(self) -> str:
        """
        Detect if source is a run directory or workdir.

        Returns:
            "run" if source contains __iops_index.json (single run),
            "workdir" if source contains run_* subdirectories with __iops_index.json.

        Raises:
            ValueError: If source is not a valid IOPS directory.
        """
        # Check for single run (has __iops_index.json directly)
        if (self.source_path / "__iops_index.json").exists():
            return "run"

        # Check for workdir (has run_* subdirectories with __iops_index.json)
        run_dirs = list(self.source_path.glob("run_*/__iops_index.json"))
        if run_dirs:
            return "workdir"

        raise ValueError(
            f"'{self.source_path}' is not a valid IOPS directory. "
            "Expected either a run directory (with __iops_index.json) "
            "or a workdir (with run_* subdirectories containing __iops_index.json)."
        )

    def _filter_all_runs(self) -> Dict[str, Set[str]]:
        """
        Apply filters to all runs and return matching execution IDs.

        Returns:
            Dictionary mapping run path (relative) to set of matching execution IDs.

        Raises:
            ValueError: If no executions match the filters.
        """
        filtered_runs: Dict[str, Set[str]] = {}
        completed_reps_map: Dict[str, Dict[str, Set[int]]] = {}
        total_original = 0
        total_filtered = 0

        if self.archive_type == "run":
            run_paths = [(".", self.source_path)]
        else:
            run_paths = [
                (run_dir.name, run_dir)
                for run_dir in sorted(self.source_path.glob("run_*"))
                if (run_dir / "__iops_index.json").exists()
            ]

        for rel_path, run_path in run_paths:
            matching_ids, total_count, exec_reps_map = filter_executions(
                run_path,
                status_filter=self.status_filter,
                cached_filter=self.cached_filter,
                param_filters=self.param_filters,
                min_completed_reps=self.min_completed_reps,
            )
            total_original += total_count
            total_filtered += len(matching_ids)

            if matching_ids:
                filtered_runs[rel_path] = matching_ids
                completed_reps_map[rel_path] = exec_reps_map

        self._original_execution_count = total_original
        self._completed_reps_map = completed_reps_map

        # Calculate total completed repetitions
        total_reps = 0
        for run_reps in completed_reps_map.values():
            for exec_reps in run_reps.values():
                total_reps += len(exec_reps)
        self._filtered_rep_count = total_reps

        if total_filtered == 0:
            filter_desc = []
            if self.status_filter:
                filter_desc.append(f"status={self.status_filter}")
            if self.cached_filter is not None:
                filter_desc.append(f"cached={'yes' if self.cached_filter else 'no'}")
            if self.min_completed_reps is not None:
                filter_desc.append(f"min_reps={self.min_completed_reps}")
            if self.param_filters:
                filter_desc.extend(f"{k}={v}" for k, v in self.param_filters.items())
            raise ValueError(
                f"No executions match the specified filters ({', '.join(filter_desc)}). "
                f"Total executions: {total_original}"
            )

        self.logger.info(
            f"Filtering: {total_filtered} of {total_original} executions "
            f"({total_reps} repetitions) match filters"
        )
        return filtered_runs

    def _prepare_filtered_content(self, temp_dir: Path) -> None:
        """
        Prepare filtered content in a temporary directory.

        Creates filtered index files and result files in temp_dir.

        Args:
            temp_dir: Temporary directory to store filtered content.
        """
        if self._filtered_runs is None:
            self._filtered_runs = self._filter_all_runs()

        if self.archive_type == "run":
            run_paths = [(".", self.source_path)]
        else:
            run_paths = [
                (run_dir.name, run_dir)
                for run_dir in sorted(self.source_path.glob("run_*"))
                if (run_dir / "__iops_index.json").exists()
            ]

        for rel_path, run_path in run_paths:
            if rel_path not in self._filtered_runs:
                continue

            exec_ids = self._filtered_runs[rel_path]

            # Create filtered index
            index_file = run_path / "__iops_index.json"
            if index_file.exists():
                with open(index_file) as f:
                    original_index = json.load(f)

                filtered_index = create_filtered_index(original_index, exec_ids)

                if rel_path == ".":
                    temp_index_path = temp_dir / "__iops_index.json"
                else:
                    temp_index_path = temp_dir / rel_path / "__iops_index.json"

                temp_index_path.parent.mkdir(parents=True, exist_ok=True)
                with open(temp_index_path, "w") as f:
                    json.dump(filtered_index, f, indent=2)

            # Create filtered result files
            result_files = get_result_file_paths(run_path)
            # Convert exec_ids to integers for result file filtering
            exec_ids_int = {int(eid.replace("exec_", "")) for eid in exec_ids}

            # Build completed_reps_map for result file filtering (only when min_reps specified)
            completed_reps_int = None
            if self.min_completed_reps is not None and self._completed_reps_map:
                run_reps_map = self._completed_reps_map.get(rel_path, {})
                completed_reps_int = {
                    int(eid.replace("exec_", "")): reps
                    for eid, reps in run_reps_map.items()
                }

            for result_file in result_files:
                if rel_path == ".":
                    temp_result_path = temp_dir / result_file.name
                else:
                    temp_result_path = temp_dir / rel_path / result_file.name

                filter_result_file(result_file, temp_result_path, exec_ids_int, completed_reps_int)

    def _should_include_item(self, item: Path) -> bool:
        """
        Check if an item should be included in a partial archive.

        Args:
            item: Path to the item (file or directory) to check.

        Returns:
            True if the item should be included, False otherwise.
        """
        if self._filtered_runs is None:
            return True

        item_name = item.name

        # Always skip result files and index files (we use filtered versions)
        if item_name == "__iops_index.json":
            return False

        # Check if this is a result file
        if item.is_file() and item.suffix.lower() in (".csv", ".parquet", ".db", ".sqlite", ".sqlite3"):
            if not item_name.startswith("__iops_"):
                return False

        # Check if this is an execution directory
        if item.is_dir() and item_name.startswith("exec_"):
            # For single run, check directly
            if self.archive_type == "run":
                return item_name in self._filtered_runs.get(".", set())
            # For workdir, need to check parent
            parent_name = item.parent.name
            return item_name in self._filtered_runs.get(parent_name, set())

        # For workdir, check if run directory has any matching executions
        if self.archive_type == "workdir" and item.is_dir() and item_name.startswith("run_"):
            return item_name in self._filtered_runs

        return True

    def _get_run_info(self, run_path: Path, relative_path: str = ".") -> RunInfo:
        """
        Extract run information from a run directory.

        Args:
            run_path: Path to the run directory.
            relative_path: Relative path within the archive.

        Returns:
            RunInfo with benchmark name and execution count.
        """
        benchmark_name = "unknown"
        execution_count = 0

        # Try to get info from __iops_index.json
        index_file = run_path / "__iops_index.json"
        if index_file.exists():
            try:
                with open(index_file) as f:
                    index_data = json.load(f)
                benchmark_name = index_data.get("benchmark", "unknown")
                executions = index_data.get("executions", {})
                execution_count = len(executions)
            except (json.JSONDecodeError, KeyError) as e:
                self.logger.warning(f"Failed to parse {index_file}: {e}")

        # Try to get more detailed info from __iops_run_metadata.json
        metadata_file = run_path / "__iops_run_metadata.json"
        if metadata_file.exists():
            try:
                with open(metadata_file) as f:
                    metadata = json.load(f)
                benchmark_info = metadata.get("benchmark", {})
                if "name" in benchmark_info:
                    benchmark_name = benchmark_info["name"]
            except (json.JSONDecodeError, KeyError) as e:
                self.logger.warning(f"Failed to parse {metadata_file}: {e}")

        # For partial archives, use filtered execution count
        if self.partial and self._filtered_runs is not None:
            filtered_ids = self._filtered_runs.get(relative_path, set())
            execution_count = len(filtered_ids)

        return RunInfo(
            name=run_path.name,
            benchmark_name=benchmark_name,
            execution_count=execution_count,
            path=relative_path,
        )

    def _collect_critical_files(self) -> List[Path]:
        """
        Collect paths to critical metadata files for checksumming.

        Returns:
            List of paths to critical IOPS metadata files.
        """
        critical_files = []

        for pattern in CRITICAL_METADATA_PATTERNS:
            # Find all matching files recursively
            matches = list(self.source_path.rglob(pattern))
            critical_files.extend(matches)

        return critical_files

    def _compute_checksums(self) -> Dict[str, str]:
        """
        Compute SHA256 checksums for critical metadata files.

        Returns:
            Dictionary mapping relative file paths to their SHA256 checksums.
        """
        checksums = {}
        critical_files = self._collect_critical_files()

        for file_path in critical_files:
            relative_path = str(file_path.relative_to(self.source_path))
            checksums[relative_path] = _compute_checksum(file_path)
            self.logger.debug(f"Checksum for {relative_path}: {checksums[relative_path][:16]}...")

        return checksums

    def _build_manifest(self) -> ArchiveManifest:
        """
        Build the archive manifest with run information and checksums.

        Returns:
            ArchiveManifest containing all archive metadata.
        """
        runs = []

        if self.archive_type == "run":
            # Single run - use "." as path since it's the root
            # For partial archives, only include if there are matching executions
            if not self.partial or (self._filtered_runs and "." in self._filtered_runs):
                run_info = self._get_run_info(self.source_path, ".")
                runs.append(run_info)
        else:
            # Workdir with multiple runs
            for run_dir in sorted(self.source_path.glob("run_*")):
                if (run_dir / "__iops_index.json").exists():
                    # For partial archives, only include runs with matching executions
                    if self.partial and self._filtered_runs:
                        if run_dir.name not in self._filtered_runs:
                            continue
                    run_info = self._get_run_info(run_dir, run_dir.name)
                    runs.append(run_info)

        checksums = self._compute_checksums()

        # Build filters_applied dict for partial archives
        filters_applied = None
        if self.partial:
            filters_applied = {}
            if self.status_filter:
                filters_applied["status"] = self.status_filter
            if self.cached_filter is not None:
                filters_applied["cached"] = self.cached_filter
            if self.min_completed_reps is not None:
                filters_applied["min_completed_reps"] = self.min_completed_reps
            if self.param_filters:
                filters_applied["params"] = self.param_filters

        return ArchiveManifest(
            iops_version=_load_version(),
            created_at=datetime.now().isoformat(),
            source_hostname=socket.gethostname(),
            archive_type=self.archive_type,
            original_path=str(self.source_path),
            runs=runs,
            checksums=checksums,
            partial=self.partial,
            original_execution_count=self._original_execution_count if self.partial else None,
            filters_applied=filters_applied,
        )

    def _count_files(self) -> int:
        """Count total files and directories for progress tracking."""
        return sum(1 for _ in self.source_path.rglob("*"))

    def write(
        self, output_path: Path, compression: str = "gz", show_progress: bool = True
    ) -> Path:
        """
        Create the archive at the specified path.

        Args:
            output_path: Path for the output archive file.
            compression: Compression type ("gz", "bz2", "xz", or "none").
            show_progress: Whether to show a progress bar (requires rich).

        Returns:
            Path to the created archive.

        Raises:
            ValueError: If compression type is invalid or no executions match filters.
        """
        if compression not in COMPRESSION_MODES:
            raise ValueError(
                f"Invalid compression type: {compression}. "
                f"Valid options: {list(COMPRESSION_MODES.keys())}"
            )

        output_path = Path(output_path).resolve()

        # Ensure output path has correct extension
        expected_ext = COMPRESSION_EXTENSIONS[compression]
        if not str(output_path).endswith(expected_ext):
            output_path = Path(str(output_path) + expected_ext)

        self.logger.info(f"Creating archive: {output_path}")
        self.logger.info(f"Source: {self.source_path} (type: {self.archive_type})")

        # For partial archives, filter executions first
        temp_dir = None
        if self.partial:
            self._filtered_runs = self._filter_all_runs()
            temp_dir = Path(tempfile.mkdtemp(prefix="iops_partial_"))
            self._prepare_filtered_content(temp_dir)

        try:
            # Build manifest (uses filtered counts if partial)
            manifest = self._build_manifest()

            if self.partial:
                excluded = self._original_execution_count - manifest.total_executions
                self.logger.info(
                    f"Partial archive: {manifest.total_executions} executions "
                    f"with {self._filtered_rep_count} repetitions "
                    f"({excluded} excluded by filters)"
                )
            else:
                self.logger.info(
                    f"Archive contains {len(manifest.runs)} run(s) "
                    f"with {manifest.total_executions} total execution(s)"
                )

            # Count files for progress tracking
            total_files = self._count_files() if show_progress and RICH_AVAILABLE else 0

            # For partial archives, include rep count in description
            if self.partial:
                progress_desc = f"Creating archive ({self._filtered_rep_count} reps)"
            else:
                progress_desc = "Creating archive"

            # Open compressed file with appropriate compression level
            # Use level 6 for gz/bz2 (matching system tar defaults) for better speed
            if compression == "gz":
                fileobj = gzip.open(output_path, "wb", compresslevel=6)
            elif compression == "bz2":
                fileobj = bz2.open(output_path, "wb", compresslevel=6)
            elif compression == "xz":
                fileobj = lzma.open(output_path, "wb", preset=6)
            else:
                fileobj = None

            # Create the archive
            with tarfile.open(
                output_path if fileobj is None else None,
                mode="w",
                fileobj=fileobj,
            ) as tar:
                # Add manifest first
                manifest_json = json.dumps(manifest.to_dict(), indent=2)
                manifest_bytes = manifest_json.encode("utf-8")

                # Create a tarinfo for the manifest
                manifest_info = tarfile.TarInfo(name=ArchiveManifest.MANIFEST_FILENAME)
                manifest_info.size = len(manifest_bytes)
                manifest_info.mtime = int(datetime.now().timestamp())

                import io

                tar.addfile(manifest_info, io.BytesIO(manifest_bytes))

                # Add files from source directory with progress
                with _get_progress_context(show_progress, progress_desc, total_files) as (progress, task):
                    # Use filter to track progress while keeping recursive add for performance
                    def progress_filter(tarinfo):
                        if progress is not None:
                            progress.advance(task)
                        return tarinfo

                    if self.partial:
                        # For partial archives, add files selectively
                        self._add_partial_content(tar, temp_dir, progress_filter)
                    else:
                        # For full archives, add everything
                        for item in self.source_path.iterdir():
                            arcname = item.name
                            self.logger.debug(f"Adding: {arcname}")
                            tar.add(item, arcname=arcname, filter=progress_filter)

            # Close the compression file object if we created one
            if fileobj is not None:
                fileobj.close()

            self.logger.info(f"Archive created successfully: {output_path}")
            return output_path

        finally:
            # Clean up temp directory
            if temp_dir and temp_dir.exists():
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _add_partial_content(
        self,
        tar: tarfile.TarFile,
        temp_dir: Path,
        progress_filter,
    ) -> None:
        """
        Add content for a partial archive.

        Adds filtered files from temp_dir and selected files from source.

        Args:
            tar: The tarfile to add content to.
            temp_dir: Temporary directory with filtered content.
            progress_filter: Filter function for progress tracking.
        """
        added_from_temp = set()

        # First, add filtered content from temp_dir
        for item in temp_dir.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(temp_dir)
                arcname = str(rel_path)
                self.logger.debug(f"Adding (filtered): {arcname}")
                tar.add(item, arcname=arcname, filter=progress_filter)
                added_from_temp.add(arcname)

        # Then, add non-filtered content from source
        def add_item_recursive(item: Path, arcname: str):
            """Recursively add items, skipping filtered content."""
            if not self._should_include_item(item):
                return

            # Skip if we already added a filtered version
            if arcname in added_from_temp:
                return

            if item.is_file():
                self.logger.debug(f"Adding: {arcname}")
                tar.add(item, arcname=arcname, filter=progress_filter)
            elif item.is_dir():
                # For directories, recurse but don't add the dir itself
                # (tar.add with recursive=False would add empty dir)
                for child in item.iterdir():
                    child_arcname = f"{arcname}/{child.name}"
                    add_item_recursive(child, child_arcname)

        for item in self.source_path.iterdir():
            arcname = item.name
            add_item_recursive(item, arcname)


class ArchiveReader(HasLogger):
    """Reads IOPS archives - supports inspection without full extraction."""

    def __init__(self, archive_path: Path):
        """
        Initialize the archive reader.

        Args:
            archive_path: Path to the archive file.

        Raises:
            FileNotFoundError: If archive does not exist.
            ValueError: If archive is not a valid tar archive.
        """
        self.archive_path = Path(archive_path).resolve()

        if not self.archive_path.exists():
            raise FileNotFoundError(f"Archive does not exist: {self.archive_path}")

        if not tarfile.is_tarfile(self.archive_path):
            raise ValueError(f"Not a valid tar archive: {self.archive_path}")

    def _get_tarfile_mode(self) -> str:
        """Determine the correct tarfile read mode based on file extension."""
        name = str(self.archive_path).lower()
        if name.endswith(".tar.gz") or name.endswith(".tgz"):
            return "r:gz"
        elif name.endswith(".tar.bz2") or name.endswith(".tbz2"):
            return "r:bz2"
        elif name.endswith(".tar.xz") or name.endswith(".txz"):
            return "r:xz"
        else:
            return "r:*"  # Auto-detect

    def get_manifest(self) -> Optional[ArchiveManifest]:
        """
        Read the archive manifest without full extraction.

        Returns:
            ArchiveManifest if found, None if manifest is missing.
        """
        mode = self._get_tarfile_mode()

        with tarfile.open(self.archive_path, mode) as tar:
            try:
                manifest_file = tar.extractfile(ArchiveManifest.MANIFEST_FILENAME)
                if manifest_file is None:
                    self.logger.warning("Manifest file not found in archive")
                    return None

                manifest_data = json.load(manifest_file)
                return ArchiveManifest.from_dict(manifest_data)

            except KeyError:
                self.logger.warning("Manifest file not found in archive")
                return None
            except json.JSONDecodeError as e:
                self.logger.error(f"Failed to parse manifest: {e}")
                return None

    def validate_integrity(self, extracted_path: Optional[Path] = None) -> List[str]:
        """
        Verify checksums of critical files.

        Args:
            extracted_path: Path to extracted directory. If None, validates
                          files directly from the archive.

        Returns:
            List of error messages (empty if all checksums match).
        """
        errors = []
        manifest = self.get_manifest()

        if manifest is None:
            errors.append("Cannot validate integrity: manifest not found")
            return errors

        if not manifest.checksums:
            self.logger.info("No checksums in manifest, skipping integrity check")
            return errors

        if extracted_path is not None:
            # Validate extracted files
            for relative_path, expected_checksum in manifest.checksums.items():
                file_path = extracted_path / relative_path
                if not file_path.exists():
                    errors.append(f"Missing file: {relative_path}")
                    continue

                actual_checksum = _compute_checksum(file_path)
                if actual_checksum != expected_checksum:
                    errors.append(
                        f"Checksum mismatch for {relative_path}: "
                        f"expected {expected_checksum[:16]}..., got {actual_checksum[:16]}..."
                    )
        else:
            # Validate files directly from archive
            mode = self._get_tarfile_mode()
            with tarfile.open(self.archive_path, mode) as tar:
                for relative_path, expected_checksum in manifest.checksums.items():
                    try:
                        file_obj = tar.extractfile(relative_path)
                        if file_obj is None:
                            errors.append(f"Missing file in archive: {relative_path}")
                            continue

                        sha256 = hashlib.sha256()
                        for chunk in iter(lambda: file_obj.read(8192), b""):
                            sha256.update(chunk)
                        actual_checksum = sha256.hexdigest()

                        if actual_checksum != expected_checksum:
                            errors.append(
                                f"Checksum mismatch for {relative_path}: "
                                f"expected {expected_checksum[:16]}..., got {actual_checksum[:16]}..."
                            )
                    except KeyError:
                        errors.append(f"Missing file in archive: {relative_path}")

        return errors

    def extract(
        self, dest_path: Path, verify: bool = True, show_progress: bool = True
    ) -> Path:
        """
        Extract the archive to the specified directory.

        Args:
            dest_path: Directory to extract to.
            verify: Whether to verify checksums after extraction.
            show_progress: Whether to show a progress bar (requires rich).

        Returns:
            Path to the extracted directory.

        Raises:
            ValueError: If integrity verification fails and verify=True.
        """
        dest_path = Path(dest_path).resolve()

        # Ensure destination exists
        dest_path.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"Extracting archive: {self.archive_path}")
        self.logger.info(f"Destination: {dest_path}")

        # Get manifest for information
        manifest = self.get_manifest()
        if manifest:
            self.logger.info(
                f"Archive contains {len(manifest.runs)} run(s) "
                f"with {manifest.total_executions} total execution(s)"
            )

        # Extract all files
        mode = self._get_tarfile_mode()
        with tarfile.open(self.archive_path, mode) as tar:
            members = tar.getmembers()
            total_members = len(members)

            # Extract with progress using filter for both security and progress tracking
            with _get_progress_context(show_progress, "Extracting archive", total_members) as (progress, task):
                def safe_progress_filter(member: tarfile.TarInfo, path: str) -> Optional[tarfile.TarInfo]:
                    # Track progress
                    if progress is not None:
                        progress.advance(task)
                    # Security: prevent path traversal attacks
                    if member.name.startswith("/") or ".." in member.name:
                        self.logger.warning(f"Skipping potentially unsafe path: {member.name}")
                        return None
                    return member

                tar.extractall(dest_path, filter=safe_progress_filter)

        # Verify integrity if requested
        if verify:
            self.logger.info("Verifying archive integrity...")
            errors = self.validate_integrity(dest_path)
            if errors:
                error_msg = "Archive integrity verification failed:\n" + "\n".join(f"  - {e}" for e in errors)
                raise ValueError(error_msg)
            self.logger.info("Integrity verification passed")

        self.logger.info(f"Extraction complete: {dest_path}")
        return dest_path

    def get_index(self, run_path: str = ".") -> Optional[dict]:
        """
        Read __iops_index.json from archive without extraction.

        Args:
            run_path: Relative path to the run directory within the archive.
                     Use "." for single-run archives.

        Returns:
            Index data as dict, or None if not found.
        """
        mode = self._get_tarfile_mode()

        with tarfile.open(self.archive_path, mode) as tar:
            # Determine index path based on run_path
            if run_path == ".":
                index_path = "__iops_index.json"
            else:
                index_path = f"{run_path}/__iops_index.json"

            try:
                index_file = tar.extractfile(index_path)
                if index_file:
                    return json.load(index_file)
            except KeyError:
                pass
        return None

    def get_run_metadata(self, run_path: str = ".") -> Optional[dict]:
        """
        Read __iops_run_metadata.json from archive without extraction.

        Args:
            run_path: Relative path to the run directory within the archive.

        Returns:
            Metadata as dict, or None if not found.
        """
        mode = self._get_tarfile_mode()

        with tarfile.open(self.archive_path, mode) as tar:
            if run_path == ".":
                metadata_path = "__iops_run_metadata.json"
            else:
                metadata_path = f"{run_path}/__iops_run_metadata.json"

            try:
                metadata_file = tar.extractfile(metadata_path)
                if metadata_file:
                    return json.load(metadata_file)
            except KeyError:
                pass
        return None

    def get_execution_status(self, run_path: str, exec_path: str) -> dict:
        """
        Read execution status from archive without extraction.

        Checks for test-level status and repetition statuses.

        Args:
            run_path: Relative path to the run directory.
            exec_path: Relative path to the execution directory within the run.

        Returns:
            Status dict with 'status', 'cached', 'error', etc.
        """
        mode = self._get_tarfile_mode()

        # Build base path for the execution
        if run_path == ".":
            base_path = exec_path
        else:
            base_path = f"{run_path}/{exec_path}"

        with tarfile.open(self.archive_path, mode) as tar:
            # Check for repetition folders first
            members = tar.getnames()
            rep_pattern = f"{base_path}/repetition_"
            rep_dirs = sorted(set(
                m.split("/")[len(base_path.split("/"))]
                for m in members
                if m.startswith(rep_pattern) and "/" in m[len(rep_pattern):]
            ))

            if not rep_dirs:
                # Try to find any repetition folders
                rep_dirs = sorted(set(
                    m.split("/")[len(base_path.split("/"))]
                    for m in members
                    if m.startswith(base_path + "/repetition_")
                ))

            if rep_dirs:
                statuses = []
                cached_flags = []
                error = None

                for rep_dir in rep_dirs:
                    rep_status_path = f"{base_path}/{rep_dir}/__iops_status.json"
                    try:
                        status_file = tar.extractfile(rep_status_path)
                        if status_file:
                            rep_status = json.load(status_file)
                            statuses.append(rep_status.get("status", "UNKNOWN"))
                            cached_flags.append(rep_status.get("cached", False))
                            if rep_status.get("error"):
                                error = rep_status.get("error")
                    except (KeyError, json.JSONDecodeError):
                        statuses.append("UNKNOWN")
                        cached_flags.append(False)

                # Determine overall status
                if any(s == "RUNNING" for s in statuses):
                    overall = "RUNNING"
                elif any(s == "PENDING" for s in statuses):
                    overall = "PENDING"
                elif any(s in ("FAILED", "ERROR") for s in statuses):
                    overall = "FAILED"
                elif all(s == "SUCCEEDED" for s in statuses):
                    overall = "SUCCEEDED"
                else:
                    overall = "UNKNOWN"

                # Determine cache status
                if all(cached_flags):
                    cached = True
                elif any(cached_flags):
                    cached = "partial"
                else:
                    cached = False

                return {
                    "status": overall,
                    "error": error,
                    "cached": cached,
                }

            # No repetition folders - check for skipped marker
            skipped_marker_path = f"{base_path}/__iops_skipped"
            try:
                skipped_file = tar.extractfile(skipped_marker_path)
                if skipped_file:
                    marker_data = json.load(skipped_file)
                    return {
                        "status": "SKIPPED",
                        "reason": marker_data.get("reason"),
                        "error": None,
                        "cached": False,
                    }
            except (KeyError, json.JSONDecodeError):
                pass

        # No repetition folders and no skipped marker - PENDING
        return {"status": "PENDING", "error": None, "cached": False}

    def list_executions(
        self,
        filters: Optional[Dict[str, str]] = None,
        status_filter: Optional[str] = None,
        cached_filter: Optional[bool] = None,
    ) -> List[dict]:
        """
        List executions in archive with optional filtering.

        Args:
            filters: Dict of parameter filters (e.g., {"nodes": "4"}).
            status_filter: Filter by status (e.g., "SUCCEEDED").
            cached_filter: Filter by cache status (True=only cached, False=only executed).

        Returns:
            List of execution dicts with keys: run, exec_id, path, params, command, status, cached.
        """
        manifest = self.get_manifest()
        if not manifest:
            return []

        all_executions = []

        for run in manifest.runs:
            index = self.get_index(run.path)
            if not index:
                continue

            for exec_id, exec_info in index.get("executions", {}).items():
                params = exec_info.get("params", {})
                exec_path = exec_info.get("path", exec_id)

                # Get status
                status_info = self.get_execution_status(run.path, exec_path)
                status = status_info.get("status", "UNKNOWN")
                cached = status_info.get("cached", False)

                # Apply status filter
                if status_filter and status.upper() != status_filter.upper():
                    continue

                # Apply cached filter
                if cached_filter is not None:
                    if cached_filter and not cached:
                        continue
                    if not cached_filter and cached:
                        continue

                # Apply parameter filters
                if filters:
                    match = all(
                        str(params.get(k)) == str(v)
                        for k, v in filters.items()
                    )
                    if not match:
                        continue

                all_executions.append({
                    "run": run.name,
                    "exec_id": exec_id,
                    "path": exec_path,
                    "params": params,
                    "command": exec_info.get("command", ""),
                    "status": status,
                    "skip_reason": status_info.get("reason"),
                    "cached": cached,
                })

        return all_executions
