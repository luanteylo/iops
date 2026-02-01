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

        # Verify sentinel file was removed by exit handler
        sentinel_file = tmp_path / SAMPLER_SENTINEL_FILENAME
        assert not sentinel_file.exists(), "Sentinel file should be removed by exit handler"


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
