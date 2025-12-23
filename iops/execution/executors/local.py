from __future__ import annotations

from pathlib import Path
import subprocess
import time

from iops.execution.matrix import ExecutionInstance
from iops.results.parser import parse_metrics_from_execution
from iops.execution.executors.base import BaseExecutor


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
        self.logger.debug(
            f"  [LocalExec] Submit: exec_id={test.execution_id} "
            f"script={test.script_file.name if test.script_file else 'N/A'}"
        )

        if test.script_file is None or not isinstance(test.script_file, Path) or not self._safe_is_file(test.script_file):
            msg = "test.script_file is not set or invalid."
            self.logger.error(f"  [LocalExec] ERROR: {msg}")
            test.metadata["__executor_status"] = self.STATUS_ERROR
            test.metadata["__error"] = msg
            return

        # check test.execution_dir
        if test.execution_dir is None or not isinstance(test.execution_dir, Path):
            msg = "test.execution_dir is not set or invalid."
            self.logger.error(f"  [LocalExec] ERROR: {msg}")
            test.metadata["__executor_status"] = self.STATUS_ERROR
            test.metadata["__error"] = msg
            return

        script_path: Path = test.script_file

        stdout_path = test.execution_dir / f"stdout"
        stderr_path = test.execution_dir / f"stderr"

        test.metadata["__stdout_path"] = str(stdout_path)
        test.metadata["__stderr_path"] = str(stderr_path)

        # Prefer not using shell=True to avoid masking return codes
        # Equivalent of: bash /path/to/script.sh
        cmd = ["bash", str(script_path)]

        self.logger.debug(f"  [LocalExec] Executing: bash {script_path.name}")

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

            # Log completion
            stdout_lines = len(result.stdout.splitlines()) if result.stdout else 0
            stderr_lines = len(result.stderr.splitlines()) if result.stderr else 0
            self.logger.debug(
                f"  [LocalExec] Completed: returncode={result.returncode} "
                f"stdout={stdout_lines} lines, stderr={stderr_lines} lines"
            )

            if result.returncode != 0:
                msg = (
                    f"Local script failed with code {result.returncode}. \n"
                    f"stdout: {stdout_path} ; \n"
                    f"stderr: {stderr_path}"
                )
                self.logger.error(f"  [LocalExec] FAILED: {msg}")

                # Show first/last lines of stderr for debugging
                if result.stderr:
                    stderr_preview = self._truncate_output(result.stderr, max_lines=10)
                    self.logger.debug(f"  [LocalExec] stderr preview:\n{stderr_preview}")

                test.metadata["__executor_status"] = self.STATUS_FAILED
                test.metadata["__error"] = msg
                return

            test.metadata["__executor_status"] = self.STATUS_SUCCEEDED

            # Execute post-processing script if present
            if self._safe_is_file(test.post_script_file):
                self.logger.debug(f"  [LocalExec] Running post-processing script")
                post_success = self._run_post_script(test)
                if not post_success:
                    # Post script failed, mark entire test as failed
                    test.metadata["__executor_status"] = self.STATUS_FAILED

        except Exception as e:
            msg = f"Error running script {test.script_file}: {e}"
            self.logger.error(msg)
            test.metadata["__executor_status"] = self.STATUS_FAILED
            test.metadata["__error"] = msg

    def wait_and_collect(self, test: ExecutionInstance) -> None:
        # Always create a full metrics dict first (all keys, None values)
        metrics = {m.name: None for m in test.parser.metrics if test.parser}
        test.metadata["metrics"] = metrics  # <-- guarantee presence early

        # Only parse if succeeded
        if test.metadata.get("__executor_status") == self.STATUS_SUCCEEDED:
            self.logger.debug(f"  [LocalExec] Parsing metrics from output files")
            results = parse_metrics_from_execution(test) or {}
            parsed = results.get("metrics", {}) if isinstance(results, dict) else {}

            for name, value in parsed.items():
                if name in metrics:
                    metrics[name] = value

        metric_count = len([v for v in metrics.values() if v is not None])
        self.logger.debug(
            f"  [LocalExec] Collected {metric_count}/{len(metrics)} metrics: "
            f"{list(metrics.keys())[:3]}{'...' if len(metrics) > 3 else ''}"
        )

    def _run_post_script(self, test: ExecutionInstance) -> bool:
        """
        Execute post-processing script after main script succeeds.

        Returns:
            True if post script succeeded or doesn't exist, False if it failed
        """
        if not self._safe_is_file(test.post_script_file):
            return True  # No post script, that's okay

        if not test.execution_dir:
            self.logger.error("  [LocalExec] execution_dir not set, cannot run post script")
            return False

        stdout_path = test.execution_dir / "post_stdout"
        stderr_path = test.execution_dir / "post_stderr"

        test.metadata["__post_stdout_path"] = str(stdout_path)
        test.metadata["__post_stderr_path"] = str(stderr_path)

        cmd = ["bash", str(test.post_script_file)]

        try:
            self.logger.debug(f"  [LocalExec] Executing post-script: {test.post_script_file.name}")

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
                f"  [LocalExec] Post-script completed: returncode={result.returncode} "
                f"stdout={stdout_lines} lines, stderr={stderr_lines} lines"
            )

            if result.returncode != 0:
                msg = (
                    f"Post-processing script failed with code {result.returncode}.\n"
                    f"stdout: {stdout_path} ;\n"
                    f"stderr: {stderr_path}"
                )
                self.logger.error(f"  [LocalExec] Post-script FAILED: {msg}")

                # Show stderr preview
                if result.stderr:
                    stderr_preview = self._truncate_output(result.stderr, max_lines=10)
                    self.logger.debug(f"  [LocalExec] Post-script stderr preview:\n{stderr_preview}")

                test.metadata["__error"] = msg
                return False

            return True

        except Exception as e:
            msg = f"Error running post-processing script: {e}"
            self.logger.error(f"  [LocalExec] Post-script ERROR: {msg}")
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
