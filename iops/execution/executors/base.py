from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from iops.logger import HasLogger
from iops.config.models import GenericBenchmarkConfig
from iops.execution.matrix import ExecutionInstance

if TYPE_CHECKING:
    pass


class BaseExecutor(ABC, HasLogger):
    """
    Abstract base class for all execution environments (e.g., SLURM, local).

    Contract:
    - submit(test): submits or executes the job and sets job-related information
      (e.g., job ID) into the `test` instance (typically `test.metadata`).
    - wait_and_collect(test): waits for completion and populates `test` with
      status / timing / executor info, then performs cleanup of temp files.
    """
    STATUS_SUCCEEDED = "SUCCEEDED"  # It was submitted and finished successfully
    STATUS_FAILED = "FAILED"  # It was submitted but failed
    STATUS_RUNNING = "RUNNING"  # It is currently running
    STATUS_PENDING = "PENDING"  # It is queued but not running yet
    STATUS_ERROR = "ERROR"  # There was an error before the submission
    STATUS_UNKNOWN = "UNKNOWN"  # Status is unknown

    _registry: dict[str, type["BaseExecutor"]] = {}

    @classmethod
    def register(cls, name: str):
        def decorator(subclass: type["BaseExecutor"]):
            cls._registry[name.lower()] = subclass
            return subclass

        return decorator

    @classmethod
    def build(cls, cfg: GenericBenchmarkConfig) -> "BaseExecutor":
        executor_cls = cls._registry.get(cfg.benchmark.executor.lower())
        if executor_cls is None:
            raise ValueError(
                f"Executor '{cfg.benchmark.executor.lower()}' is not registered."
            )
        return executor_cls(cfg)

    def __init__(self, cfg: GenericBenchmarkConfig):
        """
        Initialize executor with configuration.
        """
        super().__init__()
        self.cfg = cfg
        self.last_status: str | None = None
        self.runner = None  # Will be set by runner for job tracking

    def set_runner(self, runner):
        """Set reference to the runner for job tracking (used by SLURM for Ctrl+C cleanup)."""
        self.runner = runner

    # ------------------------------------------------------------------ #
    # Abstract API
    # ------------------------------------------------------------------ #
    @abstractmethod
    def submit(self, test: ExecutionInstance):
        """
        Submit / launch the job associated with `test`.

        Implementations MUST:
        - Use test.script_file
        - Set a job identifier in the test, e.g.:
            test.metadata["__jobid"] = <job id>
        """
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Shared helpers
    # ------------------------------------------------------------------ #
    def _init_execution_metadata(self, test: ExecutionInstance) -> None:
        """
        Ensure the metadata dict has standard keys present.

        These keys are just a convention; you can extend them freely.
        """
        meta = test.metadata
        meta.setdefault("__jobid", None)
        meta.setdefault("__executor_status", None)
        meta.setdefault("__start", None)
        meta.setdefault("__end", None)
        meta.setdefault("__error", None)

    # ------------------------------------------------------------------ #
    # Filesystem helpers with retry for HPC shared filesystems
    # ------------------------------------------------------------------ #

    # Default retry settings for filesystem operations on HPC systems
    _FS_RETRY_COUNT = 3
    _FS_RETRY_DELAY = 1.0  # seconds between retries

    def _safe_fs_check(self, path, check_fn, check_name: str = "check") -> bool:
        """
        Safely perform a filesystem check with retry logic.

        On HPC systems with network filesystems (NFS/Lustre), stat() calls
        can fail with OSError/PermissionError due to:
        - Stale file handles
        - Metadata sync delays (file just created on another node)
        - Transient permission issues during propagation

        This method retries the check to handle transient sync issues.

        Args:
            path: Path object or None to check
            check_fn: Function to call on path (e.g., lambda p: p.is_file())
            check_name: Name of check for logging purposes

        Returns:
            True if check passes, False otherwise (including errors after retries)
        """
        if path is None:
            return False

        last_error = None
        for attempt in range(self._FS_RETRY_COUNT):
            try:
                return check_fn(path)
            except OSError as e:
                last_error = e
                if attempt < self._FS_RETRY_COUNT - 1:
                    self.logger.warning(
                        f"Filesystem {check_name} error on {path} "
                        f"(attempt {attempt + 1}/{self._FS_RETRY_COUNT}): {e}. "
                        f"Retrying in {self._FS_RETRY_DELAY}s... "
                        f"(possible NFS/Lustre metadata sync delay)"
                    )
                    time.sleep(self._FS_RETRY_DELAY)

        # All retries exhausted
        self.logger.warning(
            f"Filesystem {check_name} failed after {self._FS_RETRY_COUNT} "
            f"attempts on {path}: {last_error}"
        )
        return False

    def _safe_is_file(self, path) -> bool:
        """
        Safely check if a path is a file, with retry for transient errors.

        Args:
            path: Path object or None to check

        Returns:
            True if path exists and is a file, False otherwise
        """
        return self._safe_fs_check(path, lambda p: p.is_file(), "is_file")

    def _safe_exists(self, path) -> bool:
        """
        Safely check if a path exists, with retry for transient errors.

        Args:
            path: Path object or None to check

        Returns:
            True if path exists, False otherwise
        """
        return self._safe_fs_check(path, lambda p: p.exists(), "exists")

    @abstractmethod
    def wait_and_collect(self, test: ExecutionInstance):
        """
        wait the execution to complete, collect the metrics
        """
        pass
