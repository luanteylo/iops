from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Optional, Dict, Any

import subprocess
import time
import shlex
import subprocess
import time


from iops.logger import HasLogger
from iops.config.models import GenericBenchmarkConfig
from iops.execution.matrix import ExecutionInstance
from iops.results.parser import parse_metrics_from_execution

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
    STATUS_SUCCEEDED = "SUCCEEDED" # It was submitted and finished successfully
    STATUS_FAILED = "FAILED" # It was submitted but failed
    STATUS_RUNNING = "RUNNING" # It is currently running
    STATUS_PENDING = "PENDING" # It is queued but not running yet
    STATUS_ERROR = "ERROR" # There was an error before the submission
    STATUS_UNKNOWN = "UNKNOWN" # Status is unknown

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
        
# ====================================================================== #
# Local executor
# ====================================================================== #
@BaseExecutor.register("local")
class LocalExecutor(BaseExecutor):
    """
    Executor for running benchmark jobs locally.

    - Always captures stdout/stderr to files named after the script:
        <script_name>.stdout
        <script_name>.stderr
    - Marks FAILED only if returncode != 0.
    """

    def submit(self, test: ExecutionInstance):
        self._init_execution_metadata(test)
        self.logger.debug(f"Submitting local job for test: {test.execution_id}")

        if test.script_file is None or not isinstance(test.script_file, Path) or not test.script_file.is_file():
            msg = "test.script_file is not set or invalid."
            self.logger.error(msg)
            test.metadata["__executor_status"] = self.STATUS_ERROR
            test.metadata["__error"] = msg
            return 
            

        # check test.execution_dir
        if test.execution_dir is None or not isinstance(test.execution_dir, Path):
            msg = "test.execution_dir is not set or invalid."
            self.logger.error(msg)
            test.metadata["__executor_status"] = self.STATUS_ERROR
            test.metadata["__error"] = msg
            return 

        script_path: Path = test.script_file
        script_base = script_path.name  # keep extension (e.g., .sh)

        stdout_path = test.execution_dir / f"stdout"
        stderr_path = test.execution_dir / f"stderr"

        test.metadata["__stdout_path"] = str(stdout_path)
        test.metadata["__stderr_path"] = str(stderr_path)

        # Prefer not using shell=True to avoid masking return codes
        # Equivalent of: bash /path/to/script.sh
        cmd = ["bash", str(script_path)]

        self.logger.debug(f"Executing local script with command: {' '.join(cmd)}")

        try:            
            
            test.metadata["__start"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            result = subprocess.run(
                cmd,
                cwd=test.execution_dir,
                capture_output=True,
                text=True,
            )
            test.metadata["__end"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

            # Always persist outputs
            stdout_path.write_text(result.stdout or "", encoding="utf-8", errors="replace")
            stderr_path.write_text(result.stderr or "", encoding="utf-8", errors="replace")
            
            test.metadata["__jobid"] = "local"
            test.metadata["__returncode"] = result.returncode

            self.logger.info(f"Process completed with return code {result.returncode}")
            self.logger.debug(f"stdout saved to: {stdout_path}")
            self.logger.debug(f"stderr saved to: {stderr_path}")

            if result.returncode != 0:
                msg = (
                    f"Local script failed with code {result.returncode}. \n"
                    f"stdout: {stdout_path} ; \n"
                    f"stderr: {stderr_path}"
                )
                self.logger.error(msg)
                self.logger.debug(f"stdout:\n{result.stdout}")
                self.logger.debug(f"stderr:\n{result.stderr}")
                test.metadata["__executor_status"] = self.STATUS_FAILED
                test.metadata["__error"] = msg
                return 

            test.metadata["__executor_status"] = self.STATUS_SUCCEEDED
            

        except Exception as e:
            msg = f"Error running script {test.script_file}: {e}"
            self.logger.error(msg)
            test.metadata["__executor_status"] = self.STATUS_FAILED
            test.metadata["__error"] = msg
            
    
    def wait_and_collect(self, test: ExecutionInstance) -> None:
        # Always create a full metrics dict first (all keys, None values)
        metrics = {m.name: None for m in test.parser.metrics}
        test.metadata["metrics"] = metrics  # <-- guarantee presence early

        # Only parse if succeeded
        if test.metadata.get("__executor_status") == self.STATUS_SUCCEEDED:
            results = parse_metrics_from_execution(test) or {}
            parsed = results.get("metrics", {}) if isinstance(results, dict) else {}

            for name, value in parsed.items():
                if name in metrics:
                    metrics[name] = value       

        self.logger.debug("Collected metrics: %s", test.metadata["metrics"])


# ====================================================================== #
# SLURM executor
# ====================================================================== #
# ====================================================================== #
# SLURM executor (NO sacct, NO sbatch --wait, NO sentinel requirements)
# Strategy:
#   1) Submit using YAML-driven test.submit_cmd (+ append script if missing)
#   2) Poll status via squeue while present
#   3) When job leaves squeue:
#        - try scontrol show job <jobid> to get JobState/ExitCode
#        - if scontrol has no record (aged out), finalize by parser outcome:
#             * if parser output exists and parsing succeeds -> SUCCEEDED
#             * else -> FAILED
# ====================================================================== #


@BaseExecutor.register("slurm")
class SlurmExecutor(BaseExecutor):
    """
    YAML-driven SLURM executor.

    Uses:
      - test.submit_cmd (rendered from YAML scripts[].submit)
      - test.script_file (rendered script already written)
      - test.execution_dir (work dir for the execution)

    Constraints honored:
      - does NOT use sacct
      - does NOT use sbatch --wait
      - does NOT require users to add sentinel files

    Finalization logic when job leaves squeue:
      - Prefer scontrol show job <jobid> (JobState/ExitCode)
      - If scontrol has no record, fall back to parser success.
    """

    SLURM_ACTIVE_STATES = {
        "PENDING", "CONFIGURING", "RUNNING", "COMPLETING",
        "SUSPENDED", "REQUEUED", "RESIZING", "SIGNALING", "STAGE_OUT",
    }

    SLURM_FAIL_STATES = {
        "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY",
        "PREEMPTED", "BOOT_FAIL",
    }

    def submit(self, test) -> None:
        self._init_execution_metadata(test)

        # Validate script_file
        if test.script_file is None or not isinstance(test.script_file, Path) or not test.script_file.is_file():
            msg = "test.script_file is not set or invalid."
            self.logger.error(msg)
            test.metadata["__executor_status"] = self.STATUS_ERROR
            test.metadata["__error"] = msg
            return

        # Validate execution_dir
        if test.execution_dir is None or not isinstance(test.execution_dir, Path):
            msg = "test.execution_dir is not set or invalid."
            self.logger.error(msg)
            test.metadata["__executor_status"] = self.STATUS_ERROR
            test.metadata["__error"] = msg
            return

        submit_cmd = (test.submit_cmd or "").strip()
        if not submit_cmd:
            msg = "test.submit_cmd is empty. It must come from YAML scripts[].submit."
            self.logger.error(msg)
            test.metadata["__executor_status"] = self.STATUS_ERROR
            test.metadata["__error"] = msg
            return

        cmd = shlex.split(submit_cmd)

        # Ensure the script path is included (unless user already put it in submit)
        script_str = str(test.script_file)
        if script_str not in cmd:
            cmd.append(script_str)

        self.logger.debug("Submitting SLURM job: %s", " ".join(cmd))

        try:
            test.metadata["__start"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

            # NOTE: check=True would raise on non-zero exit,
            # but sbatch typically returns 0 on successful submission.
            r = subprocess.run(
                cmd,
                cwd=test.execution_dir,
                capture_output=True,
                text=True,
            )

            stdout = (r.stdout or "").strip()
            stderr = (r.stderr or "").strip()

            test.metadata["__slurm_submit_stdout"] = stdout
            test.metadata["__slurm_submit_stderr"] = stderr
            test.metadata["__submit_returncode"] = r.returncode

            if r.returncode != 0:
                msg = f"SLURM submission failed (rc={r.returncode}): stderr='{stderr}' stdout='{stdout}'"
                self.logger.error(msg)
                test.metadata["__executor_status"] = self.STATUS_ERROR
                test.metadata["__error"] = msg
                return

            job_id = self._parse_jobid(stdout)
            if not job_id:
                msg = f"Could not parse SLURM jobid from submission output: stdout='{stdout}' stderr='{stderr}'"
                self.logger.error(msg)
                test.metadata["__executor_status"] = self.STATUS_ERROR
                test.metadata["__error"] = msg
                return

            test.metadata["__jobid"] = job_id
            test.metadata["__executor_status"] = self.STATUS_PENDING
            self.logger.info("SLURM job submitted: %s", job_id)

        except Exception as e:
            msg = f"Unexpected SLURM submission error: {e}"
            self.logger.error(msg)
            test.metadata["__executor_status"] = self.STATUS_ERROR
            test.metadata["__error"] = msg
            return

    def wait_and_collect(self, test) -> None:
        """
        Poll squeue until the job disappears, then finalize with:
          1) scontrol show job (JobState/ExitCode)
          2) fallback to parser outcome (file exists + parse ok)
        Always initializes test.metadata["metrics"] first.
        """
        # Always create metrics dict early (handle parser=None safely)
        parser = test.parser
        metric_names = [m.name for m in (parser.metrics if parser else [])]
        metrics = {name: None for name in metric_names}
        test.metadata["metrics"] = metrics

        job_id = test.metadata.get("__jobid")
        if not job_id:
            msg = "wait_and_collect called but test.metadata['__jobid'] is not set."
            self.logger.error(msg)
            test.metadata["__executor_status"] = self.STATUS_ERROR
            test.metadata["__error"] = msg
            return

        poll_interval = getattr(getattr(self.cfg, "execution", None), "status_check_delay", 30)

        self.logger.debug("Waiting for SLURM job %s (poll=%ss)", job_id, poll_interval)

        last_state = None
        while True:
            state = self._squeue_state(job_id)
            if state is None:
                break

            test.metadata["__slurm_state_live"] = state
            if state == "PENDING":
                test.metadata["__executor_status"] = self.STATUS_PENDING
            else:
                test.metadata["__executor_status"] = self.STATUS_RUNNING

            if state != last_state:
                self.logger.info("SLURM job %s state: %s", job_id, state)
                last_state = state

            time.sleep(poll_interval)

        # Job left squeue
        test.metadata["__end"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        # 1) Prefer scontrol (best SLURM-native final status without accounting)
        info = self._scontrol_info(job_id)
        slurm_state = info.get("state")
        exitcode = info.get("exitcode")

        test.metadata["__slurm_state"] = slurm_state
        test.metadata["__slurm_exitcode"] = exitcode

        final = self._map_final_status(slurm_state, exitcode)

        # 2) If scontrol cannot provide final outcome (aged out), fall back to parser
        if final == self.STATUS_UNKNOWN:
            if parser is None:
                test.metadata.setdefault(
                    "__error",
                    "Job left squeue; scontrol has no record; no parser configured to validate completion."
                )
                test.metadata["__executor_status"] = self.STATUS_UNKNOWN
                return

            ok = self._try_parse_metrics(test, metrics)
            final = self.STATUS_SUCCEEDED if ok else self.STATUS_FAILED
            if not ok:
                test.metadata.setdefault(
                    "__error",
                    "Job left squeue; scontrol has no record; parsing failed or output missing."
                )

        test.metadata["__executor_status"] = final

        if final != self.STATUS_SUCCEEDED:
            return

        # On success, ensure parsing filled the metrics (if we haven't parsed yet)
        if parser is not None:
            # If we already parsed during fallback, this will be a no-op (still safe)
            self._try_parse_metrics(test, metrics)

        self.logger.debug("Collected metrics: %s", test.metadata["metrics"])

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _parse_jobid(self, stdout: str) -> Optional[str]:
        """
        Supports:
          - sbatch --parsable  -> "12345" or "12345;something"
          - default sbatch     -> "Submitted batch job 12345"
        """
        if not stdout:
            return None

        token = stdout.splitlines()[-1].strip()

        # parsable form: "<jobid>[;...]"
        cand = token.split(";", 1)[0].strip()
        if cand.isdigit():
            return cand

        # classic form: "... 12345"
        parts = token.split()
        if parts and parts[-1].isdigit():
            return parts[-1]

        return None

    def _squeue_state(self, job_id: str) -> Optional[str]:
        """
        Returns job state string (e.g., PENDING/RUNNING/...) or None if not in queue.
        """
        try:
            r = subprocess.run(
                ["squeue", "-j", job_id, "--noheader", "--format=%T"],
                capture_output=True,
                text=True,
                check=True,
            )
            out = (r.stdout or "").strip()
            if not out:
                return None
            return out.splitlines()[0].strip()
        except subprocess.CalledProcessError as e:
            # treat failure as "not visible in queue" (best effort)
            self.logger.debug("squeue failed for %s: %s", job_id, (e.stderr or str(e)).strip())
            return None

    def _scontrol_info(self, job_id: str) -> Dict[str, Optional[str]]:
        """
        Best-effort final status without sacct.

        Returns:
          {"state": "...", "exitcode": "..."} when available,
          otherwise None values.
        """
        try:
            r = subprocess.run(
                ["scontrol", "show", "job", job_id],
                capture_output=True,
                text=True,
                check=True,
            )
            txt = (r.stdout or "").strip()
            if not txt:
                return {"state": None, "exitcode": None}

            state = None
            exitcode = None

            # Key=Value tokens separated by spaces/newlines
            for tok in txt.replace("\n", " ").split():
                if tok.startswith("JobState="):
                    state = tok.split("=", 1)[1].strip()
                elif tok.startswith("ExitCode="):
                    exitcode = tok.split("=", 1)[1].strip()

            return {"state": state, "exitcode": exitcode}

        except subprocess.CalledProcessError as e:
            # common if job aged out: "Invalid job id specified"
            self.logger.debug("scontrol show job %s failed: %s", job_id, (e.stderr or str(e)).strip())
            return {"state": None, "exitcode": None}

    def _map_final_status(self, state: Optional[str], exitcode: Optional[str]) -> str:
        """
        Map SLURM controller state + exit code into BaseExecutor status.
        """
        if state is None:
            return self.STATUS_UNKNOWN

        s = state.strip().upper()
        base = s.split()[0].split("+")[0]

        if base in self.SLURM_ACTIVE_STATES:
            if base == "PENDING":
                return self.STATUS_PENDING
            return self.STATUS_RUNNING

        if base == "COMPLETED":
            # ExitCode is usually "0:0" for success
            if exitcode is None or exitcode.strip() in {"", "0:0"}:
                return self.STATUS_SUCCEEDED
            return self.STATUS_FAILED

        if base in self.SLURM_FAIL_STATES:
            return self.STATUS_FAILED

        return self.STATUS_UNKNOWN

    def _try_parse_metrics(self, test, metrics: Dict[str, Any]) -> bool:
        """
        Parser-based success heuristic:
          - if parser.file exists AND parse_metrics_from_execution succeeds => True
          - else => False, and sets test.metadata["__error"].
        """
        parser = test.parser
        if parser is None:
            return False

        try:
            fpath = Path(parser.file)
        except Exception:
            fpath = None

        if fpath is None or not fpath.exists():
            test.metadata["__error"] = f"Parser file does not exist: {parser.file}"
            return False

        try:
            results = parse_metrics_from_execution(test) or {}
            parsed = results.get("metrics", {}) if isinstance(results, dict) else {}

            for name, value in parsed.items():
                if name in metrics:
                    metrics[name] = value
            return True

        except Exception as e:
            test.metadata["__error"] = f"Parsing failed: {e}"
            return False
