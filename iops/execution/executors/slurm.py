from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Any
import subprocess
import time
import shlex

from iops.execution.matrix import ExecutionInstance
from iops.results.parser import parse_metrics_from_execution
from iops.execution.executors.base import BaseExecutor


@BaseExecutor.register("slurm")
class SlurmExecutor(BaseExecutor):
    """
    YAML-driven SLURM executor.

    Strategy:
      1) Submit using YAML-driven test.submit_cmd (+ append script if missing)
      2) Poll status via squeue while present
      3) When job leaves squeue:
           - try scontrol show job <jobid> to get JobState/ExitCode
           - if scontrol has no record (aged out), finalize by parser outcome:
                * if parser output exists and parsing succeeds -> SUCCEEDED
                * else -> FAILED

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

    Configurable Commands:
      - Commands can be customized via executor_options.commands in YAML
      - Useful for systems with command wrappers or custom SLURM installations
    """

    SLURM_ACTIVE_STATES = {
        "PENDING", "CONFIGURING", "RUNNING", "COMPLETING",
        "SUSPENDED", "REQUEUED", "RESIZING", "SIGNALING", "STAGE_OUT",
    }

    SLURM_FAIL_STATES = {
        "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY",
        "PREEMPTED", "BOOT_FAIL",
    }

    def __init__(self, cfg):
        """Initialize SLURM executor with configurable command templates and polling interval."""
        super().__init__(cfg)

        # Extract command overrides from executor_options
        executor_options = cfg.benchmark.executor_options
        custom_commands = {}
        if executor_options and executor_options.commands:
            custom_commands = executor_options.commands

        # Set command templates with defaults
        # Templates support {job_id} placeholder for runtime substitution
        # Note: submit can be overridden per-script via scripts[].submit
        self.cmd_submit = custom_commands.get("submit", "sbatch")
        self.cmd_status = custom_commands.get("status", "squeue -j {job_id} --noheader --format=%T")
        self.cmd_info = custom_commands.get("info", "scontrol show job {job_id}")
        self.cmd_cancel = custom_commands.get("cancel", "scancel {job_id}")

        # Set polling interval with fallback chain:
        # 1. executor_options.poll_interval
        # 2. execution.status_check_delay
        # 3. default: 30 seconds
        if executor_options and executor_options.poll_interval is not None:
            self.poll_interval = executor_options.poll_interval
        else:
            self.poll_interval = getattr(getattr(cfg, "execution", None), "status_check_delay", 30)

    def submit(self, test) -> None:
        self._init_execution_metadata(test)

        # Validate script_file
        if test.script_file is None or not isinstance(test.script_file, Path) or not self._safe_is_file(test.script_file):
            msg = "test.script_file is not set or invalid."
            self.logger.error(f"  [SlurmExec] ERROR: {msg}")
            test.metadata["__executor_status"] = self.STATUS_ERROR
            test.metadata["__error"] = msg
            return

        # Validate execution_dir
        if test.execution_dir is None or not isinstance(test.execution_dir, Path):
            msg = "test.execution_dir is not set or invalid."
            self.logger.error(f"  [SlurmExec] ERROR: {msg}")
            test.metadata["__executor_status"] = self.STATUS_ERROR
            test.metadata["__error"] = msg
            return

        # Use script-specific submit command, or fall back to executor default
        submit_cmd = (test.submit_cmd or "").strip()
        if not submit_cmd:
            submit_cmd = self.cmd_submit
            self.logger.debug(f"  [SlurmExec] Using default submit command: {submit_cmd}")

        cmd = shlex.split(submit_cmd)

        # Ensure the script path is included (unless user already put it in submit)
        script_str = str(test.script_file)
        if script_str not in cmd:
            cmd.append(script_str)

        # Log detailed execution information at debug level
        self.logger.debug(f"  [SlurmExec] ═══════════════════════════════════════════════════")
        self.logger.debug(f"  [SlurmExec] Execution ID: {test.execution_id}")
        self.logger.debug(f"  [SlurmExec] Repetition: {getattr(test, 'repetition', '?')}/{getattr(test, 'repetitions', '?')}")
        self.logger.debug(f"  [SlurmExec] Working directory: {test.execution_dir}")
        self.logger.debug(f"  [SlurmExec] Script file: {test.script_file}")
        self.logger.debug(f"  [SlurmExec] Submit command: {' '.join(cmd)}")

        # Show key SLURM variables if available
        if hasattr(test, 'vars') and test.vars and isinstance(test.vars, dict):
            slurm_vars = {k: v for k, v in test.vars.items() if k in ['nodes', 'ntasks', 'processes_per_node', 'ntasks_per_node']}
            if slurm_vars:
                vars_str = ", ".join(f"{k}={v}" for k, v in slurm_vars.items())
                self.logger.debug(f"  [SlurmExec] SLURM variables: {vars_str}")

        # Show first few lines of script for verification
        try:
            with open(test.script_file, 'r') as f:
                script_lines = f.readlines()[:10]  # First 10 lines
                sbatch_directives = [line.strip() for line in script_lines if line.strip().startswith('#SBATCH')]
                if sbatch_directives:
                    self.logger.debug(f"  [SlurmExec] SBATCH directives:")
                    for directive in sbatch_directives:
                        self.logger.debug(f"  [SlurmExec]   {directive}")
        except Exception as e:
            self.logger.debug(f"  [SlurmExec] Could not read script preview: {e}")

        self.logger.debug(f"  [SlurmExec] ═══════════════════════════════════════════════════")

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

            # Register job ID with runner for cleanup on interrupt (Ctrl+C)
            if self.runner and hasattr(self.runner, 'register_slurm_job'):
                self.runner.register_slurm_job(job_id)

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

        self.logger.debug(f"  [SlurmExec] Waiting for job {job_id} (poll interval={self.poll_interval}s)")

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
                # Record when job transitions from PENDING to RUNNING (actual job start)
                if last_state == "PENDING" and "__job_start" not in test.metadata:
                    test.metadata["__job_start"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    self.logger.debug(f"  [SlurmExec] Job {job_id} started running at {test.metadata['__job_start']}")

            if state != last_state:
                self.logger.info("SLURM job %s state: %s", job_id, state)
                last_state = state

            time.sleep(self.poll_interval)

        # Job left squeue - unregister from tracking (no longer needs cleanup)
        test.metadata["__end"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        # Unregister job from runner tracking (job completed, no need to cancel)
        if self.runner and hasattr(self.runner, 'submitted_job_ids') and job_id in self.runner.submitted_job_ids:
            self.runner.submitted_job_ids.discard(job_id)
            self.logger.debug(f"  [JobTracker] Unregistered completed job {job_id} (remaining tracked: {len(self.runner.submitted_job_ids)})")

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

        # Run post-processing script locally after SLURM job completes successfully
        if self._safe_is_file(test.post_script_file):
            self.logger.debug(f"  [SlurmExec] Running post-processing script locally")
            post_success = self._run_post_script_local(test)
            if not post_success:
                # Post script failed, mark entire test as failed
                test.metadata["__executor_status"] = self.STATUS_FAILED
                return

        # On success, ensure parsing filled the metrics (if we haven't parsed yet)
        if parser is not None:
            # If we already parsed during fallback, this will be a no-op (still safe)
            self.logger.debug(f"  [SlurmExec] Parsing metrics from output files")
            self._try_parse_metrics(test, metrics)

        metric_count = len([v for v in metrics.values() if v is not None])
        self.logger.debug(
            f"  [SlurmExec] Collected {metric_count}/{len(metrics)} metrics: "
            f"{list(metrics.keys())[:3]}{'...' if len(metrics) > 3 else ''}"
        )

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
        Uses cmd_status template with {job_id} placeholder.
        """
        try:
            # Format the command template with job_id
            cmd_str = self.cmd_status.format(job_id=job_id)
            cmd = shlex.split(cmd_str)

            r = subprocess.run(
                cmd,
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
            self.logger.debug(
                f"  [SlurmExec] Status command failed for job {job_id}: {(e.stderr or str(e)).strip()}"
            )
            return None

    def _scontrol_info(self, job_id: str) -> Dict[str, Optional[str]]:
        """
        Best-effort final status without sacct.
        Uses cmd_info template with {job_id} placeholder.

        Returns:
          {"state": "...", "exitcode": "..."} when available,
          otherwise None values.
        """
        try:
            # Format the command template with job_id
            cmd_str = self.cmd_info.format(job_id=job_id)
            cmd = shlex.split(cmd_str)

            r = subprocess.run(
                cmd,
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
            self.logger.debug(
                f"  [SlurmExec] Info command failed for job {job_id} (likely aged out): "
                f"{(e.stderr or str(e)).strip()}"
            )
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

    def _run_post_script_local(self, test) -> bool:
        """
        Execute post-processing script locally after SLURM job completes.

        Note: This runs on the submission node, not on compute nodes.
        Useful for aggregating results, transferring files, cleanup, etc.

        Returns:
            True if post script succeeded or doesn't exist, False if it failed
        """
        if not self._safe_is_file(test.post_script_file):
            return True  # No post script, that's okay

        stdout_path = test.execution_dir / "post_stdout"
        stderr_path = test.execution_dir / "post_stderr"

        test.metadata["__post_stdout_path"] = str(stdout_path)
        test.metadata["__post_stderr_path"] = str(stderr_path)

        cmd = ["bash", str(test.post_script_file)]

        try:
            self.logger.debug(f"  [SlurmExec] Executing post-script locally: {test.post_script_file.name}")

            result = subprocess.run(
                cmd,
                cwd=test.execution_dir,
                capture_output=True,
                text=True,
            )

            # Save outputs
            stdout_path.write_text(result.stdout or "", encoding="utf-8", errors="replace")
            stderr_path.write_text(result.stderr or "", encoding="utf-8", errors="replace")

            test.metadata["__post_returncode"] = result.returncode

            # Log completion
            stdout_lines = len(result.stdout.splitlines()) if result.stdout else 0
            stderr_lines = len(result.stderr.splitlines()) if result.stderr else 0
            self.logger.debug(
                f"  [SlurmExec] Post-script completed: returncode={result.returncode} "
                f"stdout={stdout_lines} lines, stderr={stderr_lines} lines"
            )

            if result.returncode != 0:
                msg = (
                    f"Post-processing script failed with code {result.returncode}.\n"
                    f"stdout: {stdout_path} ;\n"
                    f"stderr: {stderr_path}"
                )
                self.logger.error(f"  [SlurmExec] Post-script FAILED: {msg}")

                # Show stderr preview
                if result.stderr:
                    stderr_preview = self._truncate_output(result.stderr, max_lines=10)
                    self.logger.debug(f"  [SlurmExec] Post-script stderr preview:\n{stderr_preview}")

                test.metadata["__error"] = msg
                return False

            return True

        except Exception as e:
            msg = f"Error running post-processing script: {e}"
            self.logger.error(f"  [SlurmExec] Post-script ERROR: {msg}")
            test.metadata["__error"] = msg
            return False

    def _truncate_output(self, text: str, max_lines: int = 10) -> str:
        """Truncate output to first and last N/2 lines."""
        if not text:
            return ""

        lines = text.splitlines()
        if len(lines) <= max_lines:
            return text

        half = max_lines // 2
        first_lines = lines[:half]
        last_lines = lines[-half:]

        return (
            "\n".join(first_lines)
            + f"\n... ({len(lines) - max_lines} lines omitted) ...\n"
            + "\n".join(last_lines)
        )

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

        if not self._safe_is_file(fpath):
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
