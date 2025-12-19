from __future__ import annotations

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

    @abstractmethod
    def wait_and_collect(self, test: ExecutionInstance):
        """
        wait the execution to complete, collect the metrics
        """
        pass
