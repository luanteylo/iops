"""Tests for resource tracing functionality.

This module tests the resource tracing feature which enables
collection of CPU and memory utilization during benchmark execution.
"""

import pytest
import yaml
import csv
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from conftest import load_config


# ============================================================================ #
# Configuration Tests
# ============================================================================ #

class TestResourceTracingConfig:
    """Tests for resource tracing configuration options."""

    def test_trace_resources_default_false(self, sample_config_dict, tmp_path):
        """Test that trace_resources defaults to False."""
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        assert config.benchmark.trace_resources is False

    def test_trace_resources_can_be_enabled(self, sample_config_dict, tmp_path):
        """Test that trace_resources can be enabled."""
        sample_config_dict["benchmark"]["trace_resources"] = True
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        assert config.benchmark.trace_resources is True

    def test_trace_interval_default(self, sample_config_dict, tmp_path):
        """Test that trace_interval defaults to 1.0."""
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        assert config.benchmark.trace_interval == 1.0

    def test_trace_interval_custom(self, sample_config_dict, tmp_path):
        """Test that trace_interval can be customized."""
        sample_config_dict["benchmark"]["trace_interval"] = 0.5
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        assert config.benchmark.trace_interval == 0.5

    def test_trace_interval_validation_rejects_zero(self, sample_config_dict, tmp_path):
        """Test that trace_interval/sampling_interval must be positive."""
        from iops.config.models import ConfigValidationError

        sample_config_dict["benchmark"]["trace_interval"] = 0
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        with pytest.raises(ConfigValidationError) as exc_info:
            load_config(config_file)
        # Accept either old or new field name in error message
        assert "trace_interval" in str(exc_info.value) or "sampling_interval" in str(exc_info.value)
        assert "positive" in str(exc_info.value)

    def test_trace_interval_validation_rejects_negative(self, sample_config_dict, tmp_path):
        """Test that negative trace_interval/sampling_interval is rejected."""
        from iops.config.models import ConfigValidationError

        sample_config_dict["benchmark"]["trace_interval"] = -1.0
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        with pytest.raises(ConfigValidationError) as exc_info:
            load_config(config_file)
        # Accept either old or new field name in error message
        assert "trace_interval" in str(exc_info.value) or "sampling_interval" in str(exc_info.value)


# ============================================================================ #
# Sampler Template Tests
# ============================================================================ #

class TestResourceSamplerTemplate:
    """Tests for the resource sampler template."""

    def test_sampler_template_exists(self):
        """Test that RESOURCE_SAMPLER_TEMPLATE is defined."""
        from iops.execution.planner import RESOURCE_SAMPLER_TEMPLATE
        assert RESOURCE_SAMPLER_TEMPLATE is not None
        assert len(RESOURCE_SAMPLER_TEMPLATE) > 0

    def test_sampler_template_has_shebang(self):
        """Test that sampler template starts with bash shebang."""
        from iops.execution.planner import RESOURCE_SAMPLER_TEMPLATE
        assert RESOURCE_SAMPLER_TEMPLATE.startswith("#!/bin/bash")

    def test_sampler_template_uses_renice(self):
        """Test that sampler runs with low priority (renice)."""
        from iops.execution.planner import RESOURCE_SAMPLER_TEMPLATE
        assert "renice -n 19" in RESOURCE_SAMPLER_TEMPLATE

    def test_sampler_template_has_csv_header(self):
        """Test that sampler outputs CSV with header."""
        from iops.execution.planner import RESOURCE_SAMPLER_TEMPLATE
        assert "timestamp,hostname,core" in RESOURCE_SAMPLER_TEMPLATE

    def test_sampler_template_reads_proc_stat(self):
        """Test that sampler reads CPU stats from /proc/stat."""
        from iops.execution.planner import RESOURCE_SAMPLER_TEMPLATE
        assert "/proc/stat" in RESOURCE_SAMPLER_TEMPLATE

    def test_sampler_template_reads_proc_meminfo(self):
        """Test that sampler reads memory stats from /proc/meminfo."""
        from iops.execution.planner import RESOURCE_SAMPLER_TEMPLATE
        assert "/proc/meminfo" in RESOURCE_SAMPLER_TEMPLATE

    def test_sampler_template_self_terminates_on_sentinel_removal(self):
        """Test that sampler self-terminates when sentinel file is removed."""
        from iops.execution.planner import RESOURCE_SAMPLER_TEMPLATE
        # Sampler uses sentinel file for termination (supports SLURM multi-node)
        assert "_IOPS_SENTINEL=" in RESOURCE_SAMPLER_TEMPLATE
        assert '[[ -f "$_IOPS_SENTINEL" ]]' in RESOURCE_SAMPLER_TEMPLATE
        # Sampler registers cleanup with exit handler
        assert '_iops_register_exit "_iops_stop_samplers"' in RESOURCE_SAMPLER_TEMPLATE

    def test_sampler_actually_terminates_when_sentinel_removed(self, tmp_path):
        """Behavioral test: sampler process terminates when sentinel file is removed."""
        import subprocess
        import time
        import os
        from iops.execution.planner import (
            RESOURCE_SAMPLER_TEMPLATE, EXIT_HANDLER_TEMPLATE,
            TRACE_FILENAME_PREFIX, SAMPLER_SENTINEL_FILENAME,
            RUNTIME_SAMPLER_FILENAME
        )

        # Create exit handler script
        exit_handler_file = tmp_path / "__iops_exit_handler.sh"
        exit_handler_file.write_text(EXIT_HANDLER_TEMPLATE)

        # Create sampler script
        sampler_script = RESOURCE_SAMPLER_TEMPLATE.format(
            execution_dir=str(tmp_path),
            trace_prefix=TRACE_FILENAME_PREFIX,
            trace_interval=0.1,
            sentinel_filename=SAMPLER_SENTINEL_FILENAME
        )
        sampler_file = tmp_path / "__iops_sampler.sh"
        sampler_file.write_text(sampler_script)

        parent_pid_file = tmp_path / "parent_pid"

        # Create a parent script that sources exit handler then sampler, and exits
        # The exit handler's trap will remove the sentinel file, causing sampler to stop
        parent_script = tmp_path / "parent.sh"
        parent_script.write_text(f'''#!/bin/bash
echo $$ > "{parent_pid_file}"
source "{exit_handler_file}"
source "{sampler_file}"
sleep 0.3
# Parent exits here - exit handler removes sentinel, sampler should terminate
''')
        parent_script.chmod(0o755)

        # Run the parent script with stdout/stderr redirected to /dev/null
        # This prevents subprocess.run from blocking on background job's pipes
        result = subprocess.run(
            ["bash", str(parent_script)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5
        )
        assert result.returncode == 0

        # Get the parent PID to find background jobs
        parent_pid = int(parent_pid_file.read_text().strip())

        # Wait for sampler to detect sentinel removal and exit
        # The sampler checks every trace_interval (0.1s), so wait a bit longer
        time.sleep(0.5)

        # Check that no process with parent as PPID is still running
        # Use pgrep to find any children of the parent process
        try:
            result = subprocess.run(
                ["pgrep", "-P", str(parent_pid)],
                capture_output=True,
                timeout=1
            )
            # If pgrep finds processes, they're still running - that's a bug
            if result.returncode == 0 and result.stdout.strip():
                child_pids = result.stdout.decode().strip().split('\n')
                pytest.fail(f"Background processes still running after parent exited: {child_pids}")
        except subprocess.TimeoutExpired:
            pytest.fail("pgrep timed out - background processes may be stuck")

        # Verify sentinel file was removed by exit handler. The sampler now
        # suffixes the sentinel with an attempt id (SLURM_JOB_ID or $$), so
        # match the base name with a glob.
        remaining = list(tmp_path.glob(f"{SAMPLER_SENTINEL_FILENAME}*"))
        assert not remaining, (
            f"Sentinel file should be removed by exit handler, found: {remaining}"
        )

    def test_concurrent_attempts_do_not_kill_each_others_samplers(self, tmp_path):
        """
        Reproduces the bug where a second SLURM attempt on the same exec_dir
        would delete the shared sentinel on its own exit and stop the first
        attempt's still-running sampler. With per-attempt sentinel/trace paths,
        the second attempt's exit must only affect its own sampler.
        """
        import subprocess
        import time
        from iops.execution.planner import (
            RESOURCE_SAMPLER_TEMPLATE, EXIT_HANDLER_TEMPLATE,
            TRACE_FILENAME_PREFIX, SAMPLER_SENTINEL_FILENAME,
        )

        exit_handler = tmp_path / "__iops_exit_handler.sh"
        exit_handler.write_text(EXIT_HANDLER_TEMPLATE)

        sampler_script = RESOURCE_SAMPLER_TEMPLATE.format(
            execution_dir=str(tmp_path),
            trace_prefix=TRACE_FILENAME_PREFIX,
            trace_interval=0.05,
            sentinel_filename=SAMPLER_SENTINEL_FILENAME,
        )
        sampler_file = tmp_path / "__iops_runtime_sampler.sh"
        sampler_file.write_text(sampler_script)

        # "Attempt A" starts and keeps running while "attempt B" comes and goes.
        # Both source the sampler and exit handler. A stays alive for longer.
        attempt_a = tmp_path / "attempt_a.sh"
        attempt_a.write_text(f'''#!/bin/bash
export SLURM_JOB_ID=11111
source "{exit_handler}"
source "{sampler_file}"
sleep 1.0
''')
        attempt_a.chmod(0o755)

        attempt_b = tmp_path / "attempt_b.sh"
        attempt_b.write_text(f'''#!/bin/bash
export SLURM_JOB_ID=22222
source "{exit_handler}"
source "{sampler_file}"
sleep 0.2
''')
        attempt_b.chmod(0o755)

        proc_a = subprocess.Popen(
            ["bash", str(attempt_a)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(0.1)
        proc_b = subprocess.Popen(
            ["bash", str(attempt_b)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        proc_b.wait(timeout=5)
        # A's sentinel must still exist right after B's exit, proving B did
        # not remove A's sentinel.
        sentinel_a = tmp_path / f"{SAMPLER_SENTINEL_FILENAME}.11111"
        sentinel_b = tmp_path / f"{SAMPLER_SENTINEL_FILENAME}.22222"
        assert sentinel_a.exists(), "Attempt A's sentinel must survive attempt B exiting"
        assert not sentinel_b.exists(), "Attempt B's own sentinel should have been cleaned up"

        # Let A finish and verify both traces exist and are independent files.
        proc_a.wait(timeout=5)
        trace_a_matches = list(tmp_path.glob(f"{TRACE_FILENAME_PREFIX}*_11111.csv"))
        trace_b_matches = list(tmp_path.glob(f"{TRACE_FILENAME_PREFIX}*_22222.csv"))
        assert trace_a_matches, "Attempt A trace should exist"
        assert trace_b_matches, "Attempt B trace should exist"
        assert trace_a_matches[0] != trace_b_matches[0], "Traces must be separate files"


# ============================================================================ #
# Sampler Injection Tests
# ============================================================================ #

class TestResourceSamplerInjection:
    """Tests for resource sampler injection into scripts."""

    def test_inject_iops_scripts_creates_sampler_file(self, sample_config_dict, tmp_path):
        """Test that _inject_iops_scripts creates a sampler file when trace_resources is enabled."""
        from iops.execution.planner import BasePlanner, RUNTIME_SAMPLER_FILENAME

        sample_config_dict["benchmark"]["trace_resources"] = True
        sample_config_dict["benchmark"]["collect_system_info"] = False  # Disable to test sampler only
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        planner = BasePlanner.build(config)

        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        script_text = "#!/bin/bash\necho hello"
        modified_script = planner._inject_iops_scripts(script_text, exec_dir)

        # Check sampler file was created
        sampler_file = exec_dir / RUNTIME_SAMPLER_FILENAME
        assert sampler_file.exists()

        # Check source line was added
        assert f'source "{sampler_file}"' in modified_script

    def test_inject_iops_scripts_preserves_shebang(self, sample_config_dict, tmp_path):
        """Test that IOPS script injection preserves the original shebang."""
        from iops.execution.planner import BasePlanner

        sample_config_dict["benchmark"]["trace_resources"] = True
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        planner = BasePlanner.build(config)

        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        script_text = "#!/bin/bash\necho hello"
        modified_script = planner._inject_iops_scripts(script_text, exec_dir)

        # Shebang should be first line
        assert modified_script.startswith("#!/bin/bash")

    def test_inject_iops_scripts_uses_config_interval(self, sample_config_dict, tmp_path):
        """Test that sampler uses the configured interval."""
        from iops.execution.planner import BasePlanner, RUNTIME_SAMPLER_FILENAME

        sample_config_dict["benchmark"]["trace_resources"] = True
        sample_config_dict["benchmark"]["trace_interval"] = 2.5
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        planner = BasePlanner.build(config)

        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        script_text = "#!/bin/bash\necho hello"
        planner._inject_iops_scripts(script_text, exec_dir)

        # Check interval in sampler script
        sampler_file = exec_dir / RUNTIME_SAMPLER_FILENAME
        content = sampler_file.read_text()
        assert "_IOPS_INTERVAL=2.5" in content

    def test_prepare_artifacts_injects_sampler_when_enabled(self, sample_config_dict, tmp_path):
        """Test that _prepare_execution_artifacts injects sampler when enabled."""
        from iops.execution.planner import BasePlanner, RUNTIME_SAMPLER_FILENAME

        sample_config_dict["benchmark"]["trace_resources"] = True
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        planner = BasePlanner.build(config)

        # Get first test
        test = planner.next_test()

        # Check sampler file was created
        sampler_file = test.execution_dir / RUNTIME_SAMPLER_FILENAME
        assert sampler_file.exists()

        # Check source line in script
        script_content = test.script_file.read_text()
        assert "source" in script_content
        assert RUNTIME_SAMPLER_FILENAME in script_content

    def test_prepare_artifacts_skips_sampler_when_disabled(self, sample_config_dict, tmp_path):
        """Test that _prepare_execution_artifacts skips sampler when disabled."""
        from iops.execution.planner import BasePlanner, RUNTIME_SAMPLER_FILENAME

        sample_config_dict["benchmark"]["trace_resources"] = False
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        planner = BasePlanner.build(config)

        # Get first test
        test = planner.next_test()

        # Check sampler file was NOT created
        sampler_file = test.execution_dir / RUNTIME_SAMPLER_FILENAME
        assert not sampler_file.exists()

    def test_inject_iops_scripts_preserves_slurm_directives(self, sample_config_dict, tmp_path):
        """Test that IOPS script injection preserves SLURM #SBATCH directives at top."""
        from iops.execution.planner import BasePlanner, RUNTIME_SAMPLER_FILENAME

        sample_config_dict["benchmark"]["trace_resources"] = True
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        planner = BasePlanner.build(config)

        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        # Script with SLURM directives
        script_text = """#!/bin/bash
#SBATCH --job-name=test
#SBATCH --nodes=4
#SBATCH --time=01:00:00

echo "Running benchmark"
"""
        modified_script = planner._inject_iops_scripts(script_text, exec_dir)

        lines = modified_script.split('\n')

        # Shebang must be first
        assert lines[0] == "#!/bin/bash"

        # #SBATCH lines must come immediately after shebang
        assert lines[1] == "#SBATCH --job-name=test"
        assert lines[2] == "#SBATCH --nodes=4"
        assert lines[3] == "#SBATCH --time=01:00:00"

        # Source lines should come after #SBATCH directives
        first_source_idx = next(i for i, line in enumerate(lines) if line.startswith("source"))
        assert first_source_idx > 3  # After all SBATCH lines


# ============================================================================ #
# Compatibility Check Tests
# ============================================================================ #

class TestResourceSamplerCompatibility:
    """Tests for resource sampler compatibility checks."""

    def test_sampler_disabled_for_sh_script(self, sample_config_dict, tmp_path):
        """Test that sampler is disabled for non-bash scripts with sbatch."""
        from iops.config.loader import check_resource_sampler_compatibility

        sample_config_dict["benchmark"]["trace_resources"] = True
        # Use sbatch + sh shebang to trigger incompatibility
        sample_config_dict["scripts"][0]["submit"] = "sbatch"
        sample_config_dict["scripts"][0]["script_template"] = "#!/bin/sh\necho hello\n"
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        assert config.benchmark.trace_resources is True

        # Check compatibility - should disable and warn
        check_resource_sampler_compatibility(config, logger=None)

        assert config.benchmark.trace_resources is False

    def test_sampler_kept_for_bash_script(self, sample_config_dict, tmp_path):
        """Test that sampler is kept for bash scripts."""
        from iops.config.loader import check_resource_sampler_compatibility

        sample_config_dict["benchmark"]["trace_resources"] = True
        sample_config_dict["scripts"][0]["script_template"] = "#!/bin/bash\necho hello\n"
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        check_resource_sampler_compatibility(config, logger=None)

        assert config.benchmark.trace_resources is True


# ============================================================================ #
# Sampler Parsing Tests
# ============================================================================ #

def _proc_stat(cores):
    """Render a /proc/stat with one line per core.

    ``cores`` holds (user, nice, system, idle, iowait, irq, softirq) per core.
    The aggregate line and the trailing non-cpu lines are included because the
    sampler has to skip them.
    """
    lines = ["cpu  1 2 3 4 5 6 7 0 0 0"]
    for i, c in enumerate(cores):
        lines.append(f"cpu{i} " + " ".join(str(v) for v in c) + " 0 0 0")
    lines += ["intr 12345 1 2 3", "ctxt 999", "btime 1700000000", "procs_running 2"]
    return "\n".join(lines) + "\n"


MEMINFO = "MemTotal:       195979760 kB\nMemFree:          100000 kB\nMemAvailable:   193273960 kB\n"


def _drive_cpu_sampler(tmp_path, stats, env="", pre=""):
    """Source the CPU sampler and call _iops_sample once per /proc/stat fixture.

    Returns the emitted CSV rows as lists of fields. Launching is stubbed out so
    sourcing the sampler only defines its functions.
    """
    from iops.execution.planner import (
        RESOURCE_SAMPLER_TEMPLATE, TRACE_FILENAME_PREFIX, SAMPLER_SENTINEL_FILENAME,
    )

    sampler = tmp_path / "sampler.sh"
    sampler.write_text(RESOURCE_SAMPLER_TEMPLATE.format(
        execution_dir=str(tmp_path), trace_prefix=TRACE_FILENAME_PREFIX,
        trace_interval=0.05, sentinel_filename=SAMPLER_SENTINEL_FILENAME,
    ))
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(MEMINFO)

    calls = []
    for i, content in enumerate(stats):
        f = tmp_path / f"stat.{i}"
        f.write_text(content)
        calls.append(f'_IOPS_PROC_STAT="{f}"\n_iops_sample')

    driver = tmp_path / "driver.sh"
    driver.write_text(f'''#!/bin/bash
{env}export IOPS_PROC_MEMINFO="{meminfo}"
_iops_register_exit() {{ :; }}
_iops_launch_on_nodes() {{ :; }}
source "{sampler}"
{pre}
''' + "\n".join(calls) + "\n")

    import subprocess
    result = subprocess.run(["bash", str(driver)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return [line.split(",") for line in result.stdout.strip().split("\n") if line]


class TestResourceSamplerParsing:
    """Behavioral tests for the CPU sampler's counter parsing."""

    BASE = [(100, 0, 50, 850, 0, 0, 0), (0, 0, 0, 1000, 0, 0, 0)]
    # cpu0: user+nice +40, system+irq+softirq +15, idle+iowait +25 (total 80)
    # cpu1: unchanged, so no time elapsed on it and no row
    AFTER = [(130, 10, 60, 870, 5, 3, 2), (0, 0, 0, 1000, 0, 0, 0)]

    def test_first_sample_emits_no_rows(self, tmp_path):
        """The first sample only establishes the baseline for the deltas."""
        assert _drive_cpu_sampler(tmp_path, [_proc_stat(self.BASE)]) == []

    def test_percentages_from_counter_deltas(self, tmp_path):
        rows = _drive_cpu_sampler(tmp_path, [_proc_stat(self.BASE), _proc_stat(self.AFTER)])
        assert len(rows) == 1, rows
        ts, host, core, user, system, idle, mem_total, mem_avail = rows[0]
        assert core == "0"
        assert (user, system, idle) == ("50.00", "18.75", "31.25")
        assert (mem_total, mem_avail) == ("195979760", "193273960")

    def test_percentages_are_rounded_to_two_decimals(self, tmp_path):
        """1/3 and 2/3 of the elapsed ticks."""
        base = [(0, 0, 0, 0, 0, 0, 0)]
        after = [(1, 0, 0, 2, 0, 0, 0)]
        rows = _drive_cpu_sampler(tmp_path, [_proc_stat(base), _proc_stat(after)])
        assert rows[0][3:6] == ["33.33", "0.00", "66.67"]

    def test_every_core_gets_a_row(self, tmp_path):
        n = 64
        base = [(10 * i, 0, 0, 1000, 0, 0, 0) for i in range(n)]
        after = [(10 * i + 5, 0, 0, 1005, 0, 0, 0) for i in range(n)]
        rows = _drive_cpu_sampler(tmp_path, [_proc_stat(base), _proc_stat(after)])
        assert [r[2] for r in rows] == [str(i) for i in range(n)]
        assert all(r[3] == "50.00" for r in rows)

    def test_counter_reset_clamps_to_zero(self, tmp_path):
        """A counter that goes backwards must not produce a negative share."""
        base = [(100, 0, 100, 800, 0, 0, 0)]
        after = [(50, 0, 110, 890, 0, 0, 0)]
        rows = _drive_cpu_sampler(tmp_path, [_proc_stat(base), _proc_stat(after)])
        user, system, idle = rows[0][3:6]
        assert user == "0.00"
        assert float(system) + float(idle) == pytest.approx(100.0, abs=0.02)

    def test_malformed_line_is_skipped_not_fatal(self, tmp_path):
        """
        A non-numeric field in bash arithmetic aborts the whole script, which
        would silently end sampling for the rest of the job.
        """
        good = _proc_stat(self.AFTER)
        bad = good.replace("cpu1 0 0 0 1000", "cpu1 0 x 0 1000")
        rows = _drive_cpu_sampler(tmp_path, [_proc_stat(self.BASE), bad])
        assert [r[2] for r in rows] == ["0"]

    def test_timestamp_uses_a_dot_under_a_comma_locale(self, tmp_path):
        """
        bash 5's EPOCHREALTIME follows the locale's decimal separator, so on a
        French system it reads "1700000000,123456". Older shells treat the
        variable as an ordinary one, so the comma form is injected directly.
        """
        env = 'export EPOCHREALTIME="1700000000,123456"\nexport LC_ALL=fr_FR.UTF-8 2>/dev/null\n'
        rows = _drive_cpu_sampler(tmp_path, [_proc_stat(self.BASE), _proc_stat(self.AFTER)], env=env)
        ts = rows[0][0]
        assert "," not in ts
        seconds, micros = ts.split(".")
        assert seconds.isdigit() and len(micros) == 6
        # Percentages are integer-formatted, so they never pick up the comma either
        assert rows[0][3] == "50.00"

    def test_sample_starts_no_counter_parsing_processes(self, tmp_path):
        """
        Regression: each sample split every /proc/stat field with
        `$(echo ... | awk ...)`, about 650 process launches on a 36-core node.
        That stretched a 0.05 s interval to about 2 s. Parsing tools are
        replaced by logging stubs here: none may run, and `date` (the clock
        fallback on bash older than 5) at most once per sample, whatever the
        core count.
        """
        bindir = tmp_path / "bin"
        bindir.mkdir()
        log = tmp_path / "calls.log"
        import shutil
        for tool in ("awk", "gawk", "mawk", "grep", "sed", "cut", "tr", "hostname", "date", "cat"):
            real = shutil.which(tool)
            stub = bindir / tool
            target = f'exec "{real}" "$@"' if real else "exit 0"
            stub.write_text(f'#!/bin/sh\necho {tool} >> "{log}"\n{target}\n')
            stub.chmod(0o755)

        n_cores, n_samples = 48, 4
        stats = [
            _proc_stat([(10 * k + i, 0, 0, 1000 + k, 0, 0, 0) for i in range(n_cores)])
            for k in range(n_samples)
        ]
        # PATH is switched after sourcing, so the one-time hostname lookup is not counted
        rows = _drive_cpu_sampler(tmp_path, stats, pre=f'export PATH="{bindir}:$PATH"')
        assert len(rows) == n_cores * (n_samples - 1)

        calls = log.read_text().split() if log.exists() else []
        assert [c for c in calls if c != "date"] == [], f"per-sample processes: {calls}"
        assert calls.count("date") <= n_samples


# ============================================================================ #
# Trace Aggregation Tests
# ============================================================================ #

class TestTraceAggregation:
    """Tests for trace file aggregation."""

    def test_compute_trace_metrics_empty_files(self, tmp_path):
        """Test _compute_trace_metrics with empty trace files."""
        from iops.execution.runner import IOPSRunner

        # Create mock runner
        runner = MagicMock(spec=IOPSRunner)
        runner.logger = MagicMock()

        # Create empty trace file (just header)
        trace_file = tmp_path / "__iops_trace_node1.csv"
        trace_file.write_text("timestamp,hostname,core,cpu_user_pct,cpu_system_pct,cpu_idle_pct,mem_total_kb,mem_available_kb\n")

        # Call method
        metrics = IOPSRunner._compute_trace_metrics(runner, [trace_file])

        assert metrics["nodes_traced"] == 0
        assert metrics["samples_collected"] == 0

    def test_compute_trace_metrics_single_sample(self, tmp_path):
        """Test _compute_trace_metrics with a single sample."""
        from iops.execution.runner import IOPSRunner

        runner = MagicMock(spec=IOPSRunner)
        runner.logger = MagicMock()

        trace_file = tmp_path / "__iops_trace_node1.csv"
        trace_file.write_text(
            "timestamp,hostname,core,cpu_user_pct,cpu_system_pct,cpu_idle_pct,mem_total_kb,mem_available_kb\n"
            "1705123456.123,node01,0,50.0,10.0,40.0,16000000,8000000\n"
        )

        metrics = IOPSRunner._compute_trace_metrics(runner, [trace_file])

        assert metrics["nodes_traced"] == 1
        assert metrics["samples_collected"] == 1
        # Memory: used = 16000000 - 8000000 = 8000000 KB = 7.63 GB
        assert "mem_peak_gb" in metrics
        assert "cpu_avg_pct" in metrics

    def test_compute_trace_metrics_multiple_samples(self, tmp_path):
        """Test _compute_trace_metrics with multiple samples."""
        from iops.execution.runner import IOPSRunner

        runner = MagicMock(spec=IOPSRunner)
        runner.logger = MagicMock()

        trace_file = tmp_path / "__iops_trace_node1.csv"
        trace_file.write_text(
            "timestamp,hostname,core,cpu_user_pct,cpu_system_pct,cpu_idle_pct,mem_total_kb,mem_available_kb\n"
            "1705123456.0,node01,0,40.0,10.0,50.0,16000000,10000000\n"
            "1705123457.0,node01,0,60.0,15.0,25.0,16000000,6000000\n"
            "1705123458.0,node01,0,50.0,10.0,40.0,16000000,8000000\n"
        )

        metrics = IOPSRunner._compute_trace_metrics(runner, [trace_file])

        assert metrics["nodes_traced"] == 1
        assert metrics["samples_collected"] == 3
        assert metrics["trace_duration_s"] == 2.0  # 1705123458 - 1705123456

    def test_compute_trace_metrics_multiple_nodes(self, tmp_path):
        """Test _compute_trace_metrics with multiple nodes."""
        from iops.execution.runner import IOPSRunner

        runner = MagicMock(spec=IOPSRunner)
        runner.logger = MagicMock()

        trace_file1 = tmp_path / "__iops_trace_node01.csv"
        trace_file1.write_text(
            "timestamp,hostname,core,cpu_user_pct,cpu_system_pct,cpu_idle_pct,mem_total_kb,mem_available_kb\n"
            "1705123456.0,node01,0,50.0,10.0,40.0,16000000,8000000\n"
        )

        trace_file2 = tmp_path / "__iops_trace_node02.csv"
        trace_file2.write_text(
            "timestamp,hostname,core,cpu_user_pct,cpu_system_pct,cpu_idle_pct,mem_total_kb,mem_available_kb\n"
            "1705123456.0,node02,0,60.0,15.0,25.0,32000000,16000000\n"
        )

        metrics = IOPSRunner._compute_trace_metrics(runner, [trace_file1, trace_file2])

        assert metrics["nodes_traced"] == 2
        assert metrics["samples_collected"] == 2

    def test_compute_trace_metrics_cpu_imbalance(self, tmp_path):
        """Test _compute_trace_metrics computes CPU imbalance correctly."""
        from iops.execution.runner import IOPSRunner

        runner = MagicMock(spec=IOPSRunner)
        runner.logger = MagicMock()

        # Two cores with different utilization
        trace_file = tmp_path / "__iops_trace_node1.csv"
        trace_file.write_text(
            "timestamp,hostname,core,cpu_user_pct,cpu_system_pct,cpu_idle_pct,mem_total_kb,mem_available_kb\n"
            "1705123456.0,node01,0,80.0,10.0,10.0,16000000,8000000\n"
            "1705123456.0,node01,1,40.0,10.0,50.0,16000000,8000000\n"
        )

        metrics = IOPSRunner._compute_trace_metrics(runner, [trace_file])

        # Core 0: 80+10 = 90%, Core 1: 40+10 = 50%, Imbalance: 90-50 = 40%
        assert "cpu_imbalance_pct" in metrics
        assert metrics["cpu_imbalance_pct"] == 40.0

    def test_compute_trace_metrics_handles_malformed_rows(self, tmp_path):
        """Test _compute_trace_metrics handles malformed rows gracefully."""
        from iops.execution.runner import IOPSRunner

        runner = MagicMock(spec=IOPSRunner)
        runner.logger = MagicMock()

        # Test with rows that have invalid numeric values (not missing columns)
        trace_file = tmp_path / "__iops_trace_node1.csv"
        trace_file.write_text(
            "timestamp,hostname,core,cpu_user_pct,cpu_system_pct,cpu_idle_pct,mem_total_kb,mem_available_kb\n"
            "1705123456.0,node01,0,50.0,10.0,40.0,16000000,8000000\n"
            "not_a_number,node01,0,invalid,data,here,bad,values\n"  # Malformed numeric values
            "1705123457.0,node01,0,60.0,15.0,25.0,16000000,6000000\n"
        )

        metrics = IOPSRunner._compute_trace_metrics(runner, [trace_file])

        # Should skip malformed row and process valid ones
        assert metrics["nodes_traced"] == 1
        # Only 2 valid rows should be processed (malformed one skipped)
        assert metrics["samples_collected"] == 2

    def test_aggregate_resource_traces_no_trace_files(self, sample_config_dict, tmp_path):
        """Test _aggregate_resource_traces when no trace files exist."""
        from iops.execution.runner import IOPSRunner

        sample_config_dict["benchmark"]["trace_resources"] = True
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)

        # Create mock runner
        runner = MagicMock(spec=IOPSRunner)
        runner.cfg = config
        runner.logger = MagicMock()

        # Create mock test without trace files
        mock_test = MagicMock()
        mock_test.execution_id = 1
        mock_test.repetition = 1
        mock_test.execution_dir = tmp_path / "exec_0001"
        mock_test.execution_dir.mkdir(parents=True)
        mock_test.vars = {"nodes": 1, "ppn": 4}

        IOPSRunner._aggregate_resource_traces(runner, [mock_test])

        # Should log that no trace files found
        runner.logger.debug.assert_called()


TRACE_HEADER = "timestamp,hostname,core,cpu_user_pct,cpu_system_pct,cpu_idle_pct,mem_total_kb,mem_available_kb\n"


def _trace(path, stamps, cores=2):
    """Write a CPU trace with one row per core at each timestamp."""
    rows = "".join(
        f"{ts},node01,{c},10.0,5.0,85.0,16000000,8000000\n" for ts in stamps for c in range(cores)
    )
    path.write_text(TRACE_HEADER + rows)
    return path


class TestSamplingIntervalWarning:
    """
    A sampler sleeps for the interval, then samples, so a slow sample stretches
    the real interval. That used to go unnoticed: a 0.05 s configuration ran at
    about 2 s on 36-core nodes and produced no message at all.
    """

    def test_gaps_are_between_distinct_timestamps_per_file(self, tmp_path):
        from iops.execution.runner import IOPSRunner

        a = _trace(tmp_path / "__iops_trace_a.csv", [10.0, 12.0, 14.5], cores=36)
        b = _trace(tmp_path / "__iops_trace_b.csv", [100.0, 101.0], cores=36)
        gaps = IOPSRunner._sample_intervals([a, b])
        assert sorted(gaps) == [1.0, 2.0, 2.5]

    def test_single_sample_and_unreadable_rows_yield_no_gaps(self, tmp_path):
        from iops.execution.runner import IOPSRunner

        one = _trace(tmp_path / "__iops_trace_one.csv", [10.0])
        bad = tmp_path / "__iops_trace_bad.csv"
        bad.write_text(TRACE_HEADER + "not-a-time,node01,0,1,1,98,1,1\n")
        assert IOPSRunner._sample_intervals([one, bad, tmp_path / "missing.csv"]) == []

    @pytest.mark.parametrize("gaps, configured", [
        ([2.05, 2.1, 1.98], 0.05),   # the case seen on a 36-core cluster node
        ([3.0, 3.1], 1.0),
    ])
    def test_warns_when_much_slower_than_configured(self, gaps, configured):
        from iops.execution.runner import IOPSRunner

        runner = MagicMock(spec=IOPSRunner)
        runner.logger = MagicMock()
        IOPSRunner._warn_on_slow_sampling(runner, gaps, configured)
        runner.logger.warning.assert_called_once()
        message = runner.logger.warning.call_args[0][0]
        assert "sampling_interval" in message
        assert f"{configured:g} s" in message

    @pytest.mark.parametrize("gaps, configured", [
        ([0.06, 0.07, 0.06], 0.05),  # sleep plus a fast sample
        ([1.2, 1.3], 1.0),           # under the 0.5 s slack for long intervals
        ([], 0.05),                  # nothing to judge
    ])
    def test_silent_when_on_pace(self, gaps, configured):
        from iops.execution.runner import IOPSRunner

        runner = MagicMock(spec=IOPSRunner)
        runner.logger = MagicMock()
        IOPSRunner._warn_on_slow_sampling(runner, gaps, configured)
        runner.logger.warning.assert_not_called()

    def test_aggregation_warns_once_across_executions(self, sample_config_dict, tmp_path):
        from iops.execution.runner import IOPSRunner

        sample_config_dict["benchmark"]["probes"] = {
            "resource_sampling": True, "sampling_interval": 0.05,
        }
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)
        config = load_config(config_file)

        runner = MagicMock(spec=IOPSRunner)
        runner.cfg = config
        runner.logger = MagicMock()
        runner._compute_trace_metrics = lambda files: IOPSRunner._compute_trace_metrics(runner, files)
        runner._sample_intervals = IOPSRunner._sample_intervals
        runner._warn_on_slow_sampling = lambda g, c: IOPSRunner._warn_on_slow_sampling(runner, g, c)

        tests = []
        for exec_id in (1, 2, 3):
            exec_dir = tmp_path / f"exec_{exec_id:04d}"
            exec_dir.mkdir()
            _trace(exec_dir / "__iops_trace_node01_1.csv", [0.0, 2.05, 4.1, 6.15])
            test = MagicMock()
            test.execution_id, test.repetition = exec_id, 1
            test.execution_dir = exec_dir
            test.vars = {"nodes": 1}
            tests.append(test)

        IOPSRunner._aggregate_resource_traces(runner, tests)

        slow = [c for c in runner.logger.warning.call_args_list if "sampling_interval" in c[0][0]]
        assert len(slow) == 1
        assert "2.05 s" in slow[0][0][0]


# ============================================================================ #
# Summary File Tests
# ============================================================================ #

class TestResourceSummaryFile:
    """Tests for the resource summary CSV file."""

    def test_summary_file_created(self, tmp_path):
        """Test that summary file is created with correct structure."""
        from iops.execution.runner import IOPSRunner, RESOURCE_SUMMARY_FILENAME

        # Create trace file
        exec_dir = tmp_path / "runs" / "exec_0001" / "repetition_001"
        exec_dir.mkdir(parents=True)
        trace_file = exec_dir / "__iops_trace_node01.csv"
        trace_file.write_text(
            "timestamp,hostname,core,cpu_user_pct,cpu_system_pct,cpu_idle_pct,mem_total_kb,mem_available_kb\n"
            "1705123456.0,node01,0,50.0,10.0,40.0,16000000,8000000\n"
        )

        # Create mock runner and config
        runner = MagicMock(spec=IOPSRunner)
        runner.logger = MagicMock()

        mock_cfg = MagicMock()
        mock_cfg.benchmark.trace_resources = True
        mock_cfg.benchmark.workdir = tmp_path
        runner.cfg = mock_cfg

        # Bind method
        runner._compute_trace_metrics = IOPSRunner._compute_trace_metrics.__get__(runner)

        # Create mock test
        mock_test = MagicMock()
        mock_test.execution_id = 1
        mock_test.repetition = 1
        mock_test.execution_dir = exec_dir
        mock_test.vars = {"nodes": 1, "ppn": 4, "__internal": "skip"}

        # Call aggregation
        IOPSRunner._aggregate_resource_traces(runner, [mock_test])

        # Check summary file
        summary_file = tmp_path / RESOURCE_SUMMARY_FILENAME
        assert summary_file.exists()

        # Read and verify content
        with open(summary_file, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["execution_id"] == "exec_0001"
        assert rows[0]["repetition"] == "1"
        assert rows[0]["nodes"] == "1"
        assert rows[0]["ppn"] == "4"
        assert "__internal" not in rows[0]  # Internal vars filtered
        assert "mem_peak_gb" in rows[0]
        assert "cpu_avg_pct" in rows[0]

    def test_summary_file_multiple_executions(self, tmp_path):
        """Test summary file with multiple executions."""
        from iops.execution.runner import IOPSRunner, RESOURCE_SUMMARY_FILENAME

        # Create trace files for two executions
        for exec_id in [1, 2]:
            for rep in [1, 2]:
                exec_dir = tmp_path / "runs" / f"exec_{exec_id:04d}" / f"repetition_{rep:03d}"
                exec_dir.mkdir(parents=True)
                trace_file = exec_dir / "__iops_trace_node01.csv"
                trace_file.write_text(
                    "timestamp,hostname,core,cpu_user_pct,cpu_system_pct,cpu_idle_pct,mem_total_kb,mem_available_kb\n"
                    f"1705123456.0,node01,0,{50 + exec_id * 10}.0,10.0,40.0,16000000,8000000\n"
                )

        # Create mock runner
        runner = MagicMock(spec=IOPSRunner)
        runner.logger = MagicMock()

        mock_cfg = MagicMock()
        mock_cfg.benchmark.trace_resources = True
        mock_cfg.benchmark.workdir = tmp_path
        runner.cfg = mock_cfg

        runner._compute_trace_metrics = IOPSRunner._compute_trace_metrics.__get__(runner)

        # Create mock tests
        tests = []
        for exec_id in [1, 2]:
            for rep in [1, 2]:
                mock_test = MagicMock()
                mock_test.execution_id = exec_id
                mock_test.repetition = rep
                mock_test.execution_dir = tmp_path / "runs" / f"exec_{exec_id:04d}" / f"repetition_{rep:03d}"
                mock_test.vars = {"nodes": exec_id, "ppn": 4}
                tests.append(mock_test)

        IOPSRunner._aggregate_resource_traces(runner, tests)

        # Check summary file
        summary_file = tmp_path / RESOURCE_SUMMARY_FILENAME
        with open(summary_file, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 4  # 2 executions x 2 repetitions

    def test_summary_not_created_when_disabled(self, tmp_path):
        """Test that summary file is not created when trace_resources is False."""
        from iops.execution.runner import IOPSRunner, RESOURCE_SUMMARY_FILENAME

        runner = MagicMock(spec=IOPSRunner)
        runner.logger = MagicMock()

        mock_cfg = MagicMock()
        mock_cfg.benchmark.trace_resources = False
        mock_cfg.benchmark.workdir = tmp_path
        runner.cfg = mock_cfg

        IOPSRunner._aggregate_resource_traces(runner, [])

        summary_file = tmp_path / RESOURCE_SUMMARY_FILENAME
        assert not summary_file.exists()


class TestAutoReportIncludesResourceMetrics:
    """The report generated at the end of a run must see the resource summary."""

    def test_auto_report_includes_gpu_metrics(self, sample_config_dict, tmp_path):
        """Custom plots on resource metrics render in the automatic report.

        Regression: the report used to be generated before the resource trace
        summary was written, so it reported "Metric ... not found in results"
        until regenerated with `iops report`.
        """
        from iops.execution.planner import GPU_TRACE_FILENAME_PREFIX
        from iops.execution.runner import IOPSRunner

        # The script writes the GPU trace itself, so the test needs neither a
        # GPU nor nvidia-smi and does not depend on sampler timing.
        trace_file = f"{{{{ execution_dir }}}}/{GPU_TRACE_FILENAME_PREFIX}node01_1.csv"
        sample_config_dict["benchmark"]["repetitions"] = 1
        sample_config_dict["benchmark"]["probes"] = {"gpu_sampling": True}
        sample_config_dict["scripts"][0]["script_template"] = (
            "#!/bin/bash\n"
            "echo 'result: 100' > {{ execution_dir }}/output.txt\n"
            f"cat > {trace_file} <<'TRACE'\n"
            "timestamp,hostname,gpu_index,gpu_name,utilization_gpu_pct,utilization_mem_pct,"
            "memory_used_mib,memory_total_mib,temperature_c,power_draw_w,clock_sm_mhz,clock_mem_mhz\n"
            "1705123456.0,node01,0,Tesla V100,40,10,1024,32768,45,150.0,1500,877\n"
            "1705123457.0,node01,0,Tesla V100,60,10,1024,32768,45,150.0,1500,877\n"
            "TRACE\n"
        )
        sample_config_dict["reporting"] = {
            "enabled": True,
            "metrics": {
                "gpu_avg_utilization_pct": {
                    "plots": [{"type": "bar", "x_var": "nodes"}],
                },
            },
        }

        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)
        config = load_config(config_file)

        args = MagicMock()
        args.use_cache = False
        args.cache_only = False
        args.log_level = "INFO"
        args.max_core_hours = None
        IOPSRunner(config, args).run()

        report = (Path(config.benchmark.workdir) / config.reporting.output_filename).read_text()
        assert "Metric 'gpu_avg_utilization_pct' not found in results" not in report
        assert "<h3>gpu_avg_utilization_pct</h3>" in report
        assert "Resource Metrics Summary" in report
        assert "Total Runtime" in report
