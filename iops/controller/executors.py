from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

import subprocess
import time

from iops.utils.logger import HasLogger
from iops.utils.generic_config import GenericBenchmarkConfig
from iops.utils.execution_matrix import ExecutionInstance

if TYPE_CHECKING:
    from typing import Dict, Any


class BaseExecutor(ABC, HasLogger):
    """
    Abstract base class for all execution environments (e.g., SLURM, local).

    Contract:
    - submit(test): submits or executes the job and sets job-related information
      (e.g., job ID) into the `test` instance (typically `test.metadata`).
    - wait_and_collect(test): waits for completion and populates `test` with
      status / timing / executor info, then performs cleanup of temp files.
    """

    JOB_STATUS_FILE = "job.status"
    JOB_START_FILE = "job.start"
    JOB_END_FILE = "job.end"

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
    def submit(self, test: ExecutionInstance) -> str:
        """
        Submit / launch the job associated with `test`.

        Implementations MUST:
        - Use test.script_file (and optionally test.post_script_file, etc.).
        - Set a job identifier in the test, e.g.:
            test.metadata["__jobid"] = <job id>
        - Return the job identifier as a string.
        """
        raise NotImplementedError

    @abstractmethod
    def _wait_and_collect(self, test: ExecutionInstance) -> None:
        """
        Wait for the job referred to by `test` to complete and populate
        `test` with execution-related data, for example:

            test.metadata["__start"]
            test.metadata["__end"]
            test.metadata["__status"]
            test.metadata["__executor_status"]
            test.metadata["__error"] (optional, on failure)

        This method should NOT perform cleanup of temporary files;
        cleanup is handled by `wait_and_collect`.
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
        meta.setdefault("__status", None)
        meta.setdefault("__executor_status", None)
        meta.setdefault("__start", None)
        meta.setdefault("__end", None)
        meta.setdefault("__error", None)

    def __clean_up_temp_files(self, test: ExecutionInstance) -> None:
        """
        Remove temporary files in the test's execution directory
        after job completion.
        """
        execution_dir: Path | None = getattr(test, "execution_dir", None)
        if execution_dir is None:
            self.logger.debug(
                "No execution_dir attribute on test; skipping cleanup."
            )
            return

        self.logger.debug(f"Cleaning up temporary files in {execution_dir}")
        try:
            for file in [self.JOB_END_FILE, self.JOB_START_FILE, self.JOB_STATUS_FILE]:
                file_path = execution_dir / file
                if file_path.exists():
                    self.logger.debug(f"Removing temporary file: {file_path}")
                    file_path.unlink(missing_ok=True)
                else:
                    self.logger.debug(f"Temporary file not found, skipping: {file_path}")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")

    # ------------------------------------------------------------------ #
    # Public wrapper
    # ------------------------------------------------------------------ #
    def wait_and_collect(self, test: ExecutionInstance) -> ExecutionInstance:
        """
        Wrapper method that initializes metadata, calls the backend
        _wait_and_collect, and ensures cleanup afterwards.

        Returns:
            The same `test` instance, enriched with execution data.
        """
        self._init_execution_metadata(test)
        try:
            self._wait_and_collect(test)
            # Drop __error if None
            if test.metadata.get("__error") is None:
                test.metadata.pop("__error", None)
            return test
        finally:
            self.__clean_up_temp_files(test)


# ====================================================================== #
# Local executor
# ====================================================================== #

@BaseExecutor.register("local")
class LocalExecutor(BaseExecutor):
    """
    Executor for running benchmark jobs locally.

    Semantics:
    - submit(test): runs the script synchronously and returns "local".
      The job is already finished by the time submit() returns.
    - wait_and_collect(test): just reads the status files from test.execution_dir
      and populates test.metadata.
    """

    def submit(self, test: ExecutionInstance) -> str:
        """
        Execute the script locally and wait for it to finish.

        Returns a dummy job id "local".
        """
        script: Path | None = getattr(test, "script_file", None)
        if script is None:
            raise ValueError("test.script_file is not set.")
        self.logger.debug(f"Submitting local job script: {script}")

        if not script.exists():
            raise ValueError(f"Script not found: {script}")

        command = f"bash {script}"
        self.logger.debug(f"Executing local script with command: {command}")

        # Initialize metadata keys
        self._init_execution_metadata(test)
        test.metadata["__jobid"] = "local"

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=script.parent,  # Ensures relative files are created in the right place
            )
            self.logger.debug(f"Process completed with return code {result.returncode}")
            self.logger.debug(f"stdout:\n{result.stdout}")
            self.logger.debug(f"stderr:\n{result.stderr}")

            if result.returncode != 0:
                msg = f"Local script failed with code {result.returncode}: {result.stderr}"
                self.logger.error(msg)
                test.metadata["__status"] = "ERROR"
                test.metadata["__executor_status"] = "FAILED"
                test.metadata["__error"] = msg
            else:
                # At this point the script has presumably written the
                # JOB_* files; _wait_and_collect will read them.
                test.metadata["__executor_status"] = "FINISHED"

            return "local"

        except Exception as e:
            msg = f"Error running script {script}: {e}"
            self.logger.error(msg)
            test.metadata["__status"] = "ERROR"
            test.metadata["__executor_status"] = "FAILED"
            test.metadata["__error"] = msg
            raise

    def _wait_and_collect(self, test: ExecutionInstance) -> None:
        """
        Collect metrics from a local job that has already been executed.
        No actual waiting, just reads job status files if present.
        """
        execution_dir: Path | None = getattr(test, "execution_dir", None)
        if execution_dir is None:
            self.logger.warning(
                "LocalExecutor._wait_and_collect called but test has no execution_dir."
            )
            test.metadata["__status"] = test.metadata.get("__status") or "UNKNOWN"
            return

        self.logger.debug(
            f"Collecting local job status from directory: {execution_dir}"
        )

        try:
            job_start_path = execution_dir / self.JOB_START_FILE
            job_end_path = execution_dir / self.JOB_END_FILE
            job_status_path = execution_dir / self.JOB_STATUS_FILE

            test.metadata["__start"] = (
                job_start_path.read_text().strip()
                if job_start_path.exists()
                else None
            )
            test.metadata["__end"] = (
                job_end_path.read_text().strip()
                if job_end_path.exists()
                else None
            )
            test.metadata["__status"] = (
                job_status_path.read_text().strip()
                if job_status_path.exists()
                else test.metadata.get("__status") or "UNKNOWN"
            )

        except Exception as e:
            msg = f"Error while collecting local job status: {e}"
            self.logger.error(msg)
            test.metadata["__status"] = "ERROR"
            test.metadata["__error"] = msg


# ====================================================================== #
# SLURM executor
# ====================================================================== #

@BaseExecutor.register("slurm")
class SlurmExecutor(BaseExecutor):
    """
    Executor for submitting and managing jobs via SLURM.
    """

    SLURM_FINISHED = "FINISHED"
    SLURM_PENDING = "PENDING"
    SLURM_RUNNING = "RUNNING"

    def submit(self, test: ExecutionInstance) -> str:
        """
        Submit a SLURM job using sbatch and store the job ID in test.metadata.
        """
        script: Path | None = getattr(test, "script_file", None)
        if script is None:
            raise ValueError("test.script_file is not set.")
        if not script.exists():
            raise ValueError(f"Script not found: {script}")
     
        sbatch_cmd = ["sbatch"]        
        sbatch_cmd.append(str(script))

        self.logger.debug(f"Submitting SLURM job script: {script}")
        self.logger.debug(f"sbatch command: {' '.join(sbatch_cmd)}")

        # Initialize metadata keys
        self._init_execution_metadata(test)

        try:
            result = subprocess.run(
                sbatch_cmd,
                capture_output=True,
                text=True,
                check=True,
            )
            stdout = result.stdout.strip()
            self.logger.info(f"sbatch output: {stdout}")

            # Typical sbatch output: "Submitted batch job <jobid>"
            job_id = stdout.split()[-1]
            test.metadata["__jobid"] = job_id
            test.metadata["__executor_status"] = "SUBMITTED"

            self.logger.info(f"SLURM job submitted with ID: {job_id}")
            return job_id

        except subprocess.CalledProcessError as e:
            msg = f"Failed to submit SLURM job: {e.stderr or e}"
            self.logger.error(msg)
            test.metadata["__status"] = "ERROR"
            test.metadata["__executor_status"] = "SUBMIT_FAILED"
            test.metadata["__error"] = msg
            raise RuntimeError("SLURM job submission failed") from e

    # -- internal helper ------------------------------------------------- #
    def __check_job_status(self, job_id: str) -> str:
        """
        Check the status of a SLURM job via squeue.

        Returns:
            One of the SLURM state strings (PENDING/RUNNING/...), or
            SLURM_FINISHED if the job is no longer in the queue.
        """
        try:
            result = subprocess.run(
                ["squeue", "-j", job_id, "--noheader", "--format=%T"],  # %T gives only the state
                capture_output=True,
                text=True,
                check=True,
            )
            output = result.stdout.strip()
            if output == "":
                output = self.SLURM_FINISHED
            self.last_status = output
            return output

        except subprocess.CalledProcessError as e:
            msg = f"Failed to check SLURM job status: {e.stderr or e}"
            self.logger.error(msg)
            raise RuntimeError("SLURM job status check failed") from e

    def _wait_and_collect(self, test: ExecutionInstance) -> None:
        """
        Wait for the SLURM job to complete and populate test.metadata.
        """
        job_id = test.metadata.get("__jobid")
        if not job_id:
            raise ValueError(
                "SlurmExecutor._wait_and_collect called, but test.metadata['__jobid'] is not set."
            )

        execution_dir: Path | None = getattr(test, "execution_dir", None)
        if execution_dir is None:
            raise ValueError(
                "SlurmExecutor._wait_and_collect requires test.execution_dir."
            )

        poll_interval = getattr(self.cfg.execution, "status_check_delay", 30)
        self.logger.debug(f"Waiting for SLURM job to complete: {job_id}")
        test.metadata.setdefault("__executor_status", None)

        try:
            last_status = None
            last_log_time = 0.0
            log_interval = 3600  # 60 minutes in seconds

            while True:
                status = self.__check_job_status(job_id)

                now = time.time()
                status_changed = status != last_status
                time_exceeded = (now - last_log_time) >= log_interval

                if status_changed or time_exceeded:
                    self.logger.info(f"SLURM job {job_id} status: {status}")
                    last_log_time = now
                    last_status = status

                if status not in [self.SLURM_PENDING, self.SLURM_RUNNING]:
                    break

                time.sleep(poll_interval)

            self.logger.info(f"SLURM job {job_id} completed with status: {self.last_status}")
            test.metadata["__executor_status"] = self.last_status

            # Read the job.status/start/end files produced by the script
            job_start_path = execution_dir / self.JOB_START_FILE
            job_end_path = execution_dir / self.JOB_END_FILE
            job_status_path = execution_dir / self.JOB_STATUS_FILE

            test.metadata["__start"] = (
                job_start_path.read_text().strip()
                if job_start_path.exists()
                else None
            )
            test.metadata["__end"] = (
                job_end_path.read_text().strip()
                if job_end_path.exists()
                else None
            )
            test.metadata["__status"] = (
                job_status_path.read_text().strip()
                if job_status_path.exists()
                else "UNKNOWN"
            )

        except Exception as e:
            msg = f"Error while waiting for SLURM job {job_id}: {e}"
            self.logger.error(msg)
            test.metadata["__status"] = "ERROR"
            test.metadata["__error"] = msg
