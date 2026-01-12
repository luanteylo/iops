"""Archive manifest dataclasses for IOPS archive metadata."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class RunInfo:
    """Information about a single run within an archive."""

    name: str  # e.g., "run_001"
    benchmark_name: str  # From __iops_run_metadata.json or __iops_index.json
    execution_count: int  # Number of executions in this run
    path: str  # Relative path within archive (e.g., "run_001" or ".")

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "benchmark_name": self.benchmark_name,
            "execution_count": self.execution_count,
            "path": self.path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RunInfo":
        """Create RunInfo from dictionary."""
        return cls(
            name=data["name"],
            benchmark_name=data["benchmark_name"],
            execution_count=data["execution_count"],
            path=data["path"],
        )


@dataclass
class ArchiveManifest:
    """Manifest containing metadata about an IOPS archive."""

    iops_version: str
    created_at: str  # ISO-8601 format
    source_hostname: str
    archive_type: str  # "run" or "workdir"
    original_path: str  # Original absolute path of the source
    runs: List[RunInfo] = field(default_factory=list)
    checksums: Dict[str, str] = field(default_factory=dict)  # file path -> SHA256

    # Manifest file name constant
    MANIFEST_FILENAME = "__iops_archive_manifest.json"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "iops_version": self.iops_version,
            "created_at": self.created_at,
            "source_hostname": self.source_hostname,
            "archive_type": self.archive_type,
            "original_path": self.original_path,
            "runs": [run.to_dict() for run in self.runs],
            "checksums": self.checksums,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ArchiveManifest":
        """Create ArchiveManifest from dictionary."""
        return cls(
            iops_version=data["iops_version"],
            created_at=data["created_at"],
            source_hostname=data["source_hostname"],
            archive_type=data["archive_type"],
            original_path=data["original_path"],
            runs=[RunInfo.from_dict(r) for r in data.get("runs", [])],
            checksums=data.get("checksums", {}),
        )

    def validate(self) -> List[str]:
        """Validate the manifest and return a list of errors (empty if valid)."""
        errors = []

        if not self.iops_version:
            errors.append("Missing iops_version")

        if not self.created_at:
            errors.append("Missing created_at timestamp")
        else:
            try:
                datetime.fromisoformat(self.created_at)
            except ValueError:
                errors.append(f"Invalid created_at timestamp format: {self.created_at}")

        if self.archive_type not in ("run", "workdir"):
            errors.append(f"Invalid archive_type: {self.archive_type} (expected 'run' or 'workdir')")

        if not self.runs:
            errors.append("No runs found in manifest")

        for run in self.runs:
            if not run.name:
                errors.append("Run missing name")
            if not run.benchmark_name:
                errors.append(f"Run '{run.name}' missing benchmark_name")
            if run.execution_count < 0:
                errors.append(f"Run '{run.name}' has invalid execution_count: {run.execution_count}")

        return errors

    @property
    def total_executions(self) -> int:
        """Total number of executions across all runs."""
        return sum(run.execution_count for run in self.runs)

    @property
    def run_names(self) -> List[str]:
        """List of run names in the archive."""
        return [run.name for run in self.runs]
