"""
Executor module for IOPS benchmark framework.

Provides execution backends for running benchmarks locally or on SLURM clusters.
"""

from iops.execution.executors.base import BaseExecutor
from iops.execution.executors.local import LocalExecutor
from iops.execution.executors.slurm import SlurmExecutor

__all__ = ["BaseExecutor", "LocalExecutor", "SlurmExecutor"]
