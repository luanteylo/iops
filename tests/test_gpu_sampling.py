"""Tests for GPU sampling probe functionality.

This module tests the GPU sampling feature which enables
collection of GPU metrics (utilization, memory, temperature,
power, clocks) during benchmark execution.
"""

import pytest
import yaml
import csv
from pathlib import Path
from unittest.mock import MagicMock

from conftest import load_config


# ============================================================================ #
# Configuration Tests
# ============================================================================ #

class TestGpuSamplingConfig:
    """Tests for GPU sampling configuration options."""

    def test_gpu_sampling_default_false(self, sample_config_dict, tmp_path):
        """Test that gpu_sampling defaults to False."""
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        assert config.benchmark.probes.gpu_sampling is False

    def test_gpu_sampling_can_be_enabled_via_probes(self, sample_config_dict, tmp_path):
        """Test that gpu_sampling can be enabled via probes section."""
        sample_config_dict["benchmark"]["probes"] = {"gpu_sampling": True}
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        assert config.benchmark.probes.gpu_sampling is True

    def test_gpu_sampling_uses_sampling_interval(self, sample_config_dict, tmp_path):
        """Test that gpu_sampling shares the sampling_interval setting."""
        sample_config_dict["benchmark"]["probes"] = {
            "gpu_sampling": True,
            "sampling_interval": 2.5
        }
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        assert config.benchmark.probes.gpu_sampling is True
        assert config.benchmark.probes.sampling_interval == 2.5

    def test_gpu_sampling_invalid_key_rejected(self, sample_config_dict, tmp_path):
        """Test that invalid keys under probes are rejected."""
        from iops.config.models import ConfigValidationError

        sample_config_dict["benchmark"]["probes"] = {"gpu_sampling_invalid": True}
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        with pytest.raises(ConfigValidationError):
            load_config(config_file)


# ============================================================================ #
# GPU Sampler Template Tests
# ============================================================================ #

class TestGpuSamplerTemplate:
    """Tests for the GPU sampler template."""

    def test_gpu_sampler_template_exists(self):
        """Test that GPU_SAMPLER_TEMPLATE is defined."""
        from iops.execution.planner import GPU_SAMPLER_TEMPLATE
        assert GPU_SAMPLER_TEMPLATE is not None
        assert len(GPU_SAMPLER_TEMPLATE) > 0

    def test_gpu_sampler_template_has_shebang(self):
        """Test that GPU sampler template starts with bash shebang."""
        from iops.execution.planner import GPU_SAMPLER_TEMPLATE
        assert GPU_SAMPLER_TEMPLATE.startswith("#!/bin/bash")

    def test_gpu_sampler_template_uses_renice(self):
        """Test that GPU sampler runs with low priority."""
        from iops.execution.planner import GPU_SAMPLER_TEMPLATE
        assert "renice -n 19" in GPU_SAMPLER_TEMPLATE

    def test_gpu_sampler_template_has_csv_header(self):
        """Test that GPU sampler outputs CSV with vendor-neutral header."""
        from iops.execution.planner import GPU_SAMPLER_TEMPLATE
        expected_columns = (
            "timestamp,hostname,gpu_index,gpu_name,"
            "utilization_gpu_pct,utilization_mem_pct,"
            "memory_used_mib,memory_total_mib,"
            "temperature_c,power_draw_w,"
            "clock_sm_mhz,clock_mem_mhz"
        )
        assert expected_columns in GPU_SAMPLER_TEMPLATE

    def test_gpu_sampler_template_uses_nvidia_smi(self):
        """Test that GPU sampler uses nvidia-smi for NVIDIA GPUs."""
        from iops.execution.planner import GPU_SAMPLER_TEMPLATE
        assert "nvidia-smi" in GPU_SAMPLER_TEMPLATE
        assert "--query-gpu=" in GPU_SAMPLER_TEMPLATE

    def test_gpu_sampler_template_detects_vendor(self):
        """Test that GPU sampler detects GPU vendor dynamically."""
        from iops.execution.planner import GPU_SAMPLER_TEMPLATE
        assert "command -v nvidia-smi" in GPU_SAMPLER_TEMPLATE
        assert '_IOPS_GPU_VENDOR=""' in GPU_SAMPLER_TEMPLATE
        assert '_IOPS_GPU_VENDOR="nvidia"' in GPU_SAMPLER_TEMPLATE

    def test_gpu_sampler_template_skips_when_no_gpu(self):
        """Test that GPU sampler gracefully skips when no GPU vendor detected."""
        from iops.execution.planner import GPU_SAMPLER_TEMPLATE
        # When sourced and no vendor detected, should not create sentinel or launch
        assert 'if [[ -n "$_IOPS_GPU_VENDOR" ]]' in GPU_SAMPLER_TEMPLATE
        # When running standalone loop with no vendor, should return early
        assert 'if [[ -z "$_IOPS_GPU_VENDOR" ]]' in GPU_SAMPLER_TEMPLATE

    def test_gpu_sampler_template_uses_sentinel_file(self):
        """Test that GPU sampler uses sentinel file for termination."""
        from iops.execution.planner import GPU_SAMPLER_TEMPLATE
        assert "_IOPS_GPU_SENTINEL=" in GPU_SAMPLER_TEMPLATE
        assert '[[ -f "$_IOPS_GPU_SENTINEL" ]]' in GPU_SAMPLER_TEMPLATE
        assert '_iops_register_exit "_iops_stop_gpu_samplers"' in GPU_SAMPLER_TEMPLATE

    def test_gpu_sampler_template_supports_slurm_multinode(self):
        """Test that GPU sampler supports SLURM multi-node via srun."""
        from iops.execution.planner import GPU_SAMPLER_TEMPLATE
        assert "SLURM_JOB_ID" in GPU_SAMPLER_TEMPLATE
        assert "srun --overlap" in GPU_SAMPLER_TEMPLATE
        assert "--ntasks-per-node=1" in GPU_SAMPLER_TEMPLATE

    def test_gpu_sampler_template_can_be_formatted(self):
        """Test that GPU sampler template can be formatted with expected placeholders."""
        from iops.execution.planner import (
            GPU_SAMPLER_TEMPLATE, GPU_TRACE_FILENAME_PREFIX,
            GPU_SAMPLER_SENTINEL_FILENAME
        )
        # Should not raise
        formatted = GPU_SAMPLER_TEMPLATE.format(
            execution_dir="/tmp/test_exec",
            gpu_trace_prefix=GPU_TRACE_FILENAME_PREFIX,
            gpu_trace_interval=1.0,
            gpu_sentinel_filename=GPU_SAMPLER_SENTINEL_FILENAME
        )
        assert "/tmp/test_exec" in formatted
        assert GPU_TRACE_FILENAME_PREFIX in formatted

    def test_gpu_sampler_queries_power_draw(self):
        """Test that GPU sampler queries power.draw for energy monitoring."""
        from iops.execution.planner import GPU_SAMPLER_TEMPLATE
        assert "power.draw" in GPU_SAMPLER_TEMPLATE

    def test_gpu_sampler_queries_temperature(self):
        """Test that GPU sampler queries GPU temperature."""
        from iops.execution.planner import GPU_SAMPLER_TEMPLATE
        assert "temperature.gpu" in GPU_SAMPLER_TEMPLATE

    def test_gpu_sampler_queries_utilization(self):
        """Test that GPU sampler queries GPU and memory utilization."""
        from iops.execution.planner import GPU_SAMPLER_TEMPLATE
        assert "utilization.gpu" in GPU_SAMPLER_TEMPLATE
        assert "utilization.memory" in GPU_SAMPLER_TEMPLATE

    def test_gpu_sampler_queries_clocks(self):
        """Test that GPU sampler queries clock speeds."""
        from iops.execution.planner import GPU_SAMPLER_TEMPLATE
        assert "clocks.current.sm" in GPU_SAMPLER_TEMPLATE
        assert "clocks.current.memory" in GPU_SAMPLER_TEMPLATE


# ============================================================================ #
# GPU Sampler Injection Tests
# ============================================================================ #

class TestGpuSamplerInjection:
    """Tests for GPU sampler injection into scripts."""

    def test_inject_creates_gpu_sampler_file(self, sample_config_dict, tmp_path):
        """Test that _inject_iops_scripts creates a GPU sampler file when gpu_sampling is enabled."""
        from iops.execution.planner import BasePlanner, RUNTIME_GPU_SAMPLER_FILENAME

        sample_config_dict["benchmark"]["probes"] = {
            "gpu_sampling": True,
            "system_snapshot": False,
        }
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        planner = BasePlanner.build(config)

        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        script_text = "#!/bin/bash\necho hello"
        modified_script = planner._inject_iops_scripts(script_text, exec_dir)

        # Check GPU sampler file was created
        gpu_sampler_file = exec_dir / RUNTIME_GPU_SAMPLER_FILENAME
        assert gpu_sampler_file.exists()

        # Check source line was added
        assert f'source "{gpu_sampler_file}"' in modified_script

    def test_inject_preserves_shebang_with_gpu_sampling(self, sample_config_dict, tmp_path):
        """Test that IOPS script injection preserves the original shebang."""
        from iops.execution.planner import BasePlanner

        sample_config_dict["benchmark"]["probes"] = {"gpu_sampling": True}
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        planner = BasePlanner.build(config)

        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        script_text = "#!/bin/bash\necho hello"
        modified_script = planner._inject_iops_scripts(script_text, exec_dir)

        assert modified_script.startswith("#!/bin/bash")

    def test_inject_uses_config_interval_for_gpu(self, sample_config_dict, tmp_path):
        """Test that GPU sampler uses the configured sampling interval."""
        from iops.execution.planner import BasePlanner, RUNTIME_GPU_SAMPLER_FILENAME

        sample_config_dict["benchmark"]["probes"] = {
            "gpu_sampling": True,
            "sampling_interval": 2.5,
            "system_snapshot": False,
        }
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        planner = BasePlanner.build(config)

        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        script_text = "#!/bin/bash\necho hello"
        planner._inject_iops_scripts(script_text, exec_dir)

        # Read GPU sampler file and check interval
        gpu_sampler_file = exec_dir / RUNTIME_GPU_SAMPLER_FILENAME
        content = gpu_sampler_file.read_text()
        assert "_IOPS_GPU_INTERVAL=2.5" in content

    def test_no_gpu_sampler_when_disabled(self, sample_config_dict, tmp_path):
        """Test that GPU sampler is not injected when gpu_sampling is False."""
        from iops.execution.planner import BasePlanner, RUNTIME_GPU_SAMPLER_FILENAME

        sample_config_dict["benchmark"]["probes"] = {
            "gpu_sampling": False,
            "system_snapshot": True,
        }
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        planner = BasePlanner.build(config)

        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        script_text = "#!/bin/bash\necho hello"
        modified_script = planner._inject_iops_scripts(script_text, exec_dir)

        # GPU sampler file should NOT be created
        gpu_sampler_file = exec_dir / RUNTIME_GPU_SAMPLER_FILENAME
        assert not gpu_sampler_file.exists()

        # No GPU sampler source line
        assert RUNTIME_GPU_SAMPLER_FILENAME not in modified_script

    def test_gpu_sampler_and_resource_sampler_coexist(self, sample_config_dict, tmp_path):
        """Test that GPU sampler and resource sampler can both be enabled."""
        from iops.execution.planner import (
            BasePlanner, RUNTIME_SAMPLER_FILENAME, RUNTIME_GPU_SAMPLER_FILENAME
        )

        sample_config_dict["benchmark"]["probes"] = {
            "resource_sampling": True,
            "gpu_sampling": True,
            "system_snapshot": False,
        }
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        planner = BasePlanner.build(config)

        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        script_text = "#!/bin/bash\necho hello"
        modified_script = planner._inject_iops_scripts(script_text, exec_dir)

        # Both sampler files should exist
        assert (exec_dir / RUNTIME_SAMPLER_FILENAME).exists()
        assert (exec_dir / RUNTIME_GPU_SAMPLER_FILENAME).exists()

        # Both should be sourced in the script
        assert RUNTIME_SAMPLER_FILENAME in modified_script
        assert RUNTIME_GPU_SAMPLER_FILENAME in modified_script

    def test_gpu_sampler_injection_after_sbatch(self, sample_config_dict, tmp_path):
        """Test that GPU sampler is injected after #SBATCH directives."""
        from iops.execution.planner import BasePlanner, RUNTIME_GPU_SAMPLER_FILENAME

        sample_config_dict["benchmark"]["probes"] = {
            "gpu_sampling": True,
            "system_snapshot": False,
        }
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        config = load_config(config_file)
        planner = BasePlanner.build(config)

        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        script_text = "#!/bin/bash\n#SBATCH --nodes=2\n#SBATCH --ntasks=8\necho hello"
        modified_script = planner._inject_iops_scripts(script_text, exec_dir)

        lines = modified_script.split('\n')
        # Find the GPU sampler source line
        gpu_source_idx = None
        sbatch_last_idx = None
        for i, line in enumerate(lines):
            if RUNTIME_GPU_SAMPLER_FILENAME in line:
                gpu_source_idx = i
            if line.strip().startswith("#SBATCH"):
                sbatch_last_idx = i

        assert gpu_source_idx is not None, "GPU sampler source line not found"
        assert sbatch_last_idx is not None, "SBATCH directives not found"
        assert gpu_source_idx > sbatch_last_idx, "GPU sampler should be after #SBATCH directives"


# ============================================================================ #
# System Probe GPU Info Tests
# ============================================================================ #

class TestSystemProbeGpuInfo:
    """Tests for GPU information in the system probe template."""

    def test_system_probe_detects_nvidia(self):
        """Test that system probe detects NVIDIA GPUs via nvidia-smi."""
        from iops.execution.planner import SYSTEM_PROBE_TEMPLATE
        assert "nvidia-smi" in SYSTEM_PROBE_TEMPLATE

    def test_system_probe_collects_gpu_count(self):
        """Test that system probe collects GPU count."""
        from iops.execution.planner import SYSTEM_PROBE_TEMPLATE
        assert "gpu_count" in SYSTEM_PROBE_TEMPLATE

    def test_system_probe_collects_gpu_model(self):
        """Test that system probe collects GPU model name."""
        from iops.execution.planner import SYSTEM_PROBE_TEMPLATE
        assert "gpu_model" in SYSTEM_PROBE_TEMPLATE

    def test_system_probe_collects_gpu_driver(self):
        """Test that system probe collects GPU driver version."""
        from iops.execution.planner import SYSTEM_PROBE_TEMPLATE
        assert "gpu_driver" in SYSTEM_PROBE_TEMPLATE

    def test_system_probe_collects_gpu_memory(self):
        """Test that system probe collects GPU memory."""
        from iops.execution.planner import SYSTEM_PROBE_TEMPLATE
        assert "gpu_memory_mib" in SYSTEM_PROBE_TEMPLATE

    def test_system_probe_gpu_defaults_to_zero(self):
        """Test that GPU fields default to 0/empty when no GPU detected."""
        from iops.execution.planner import SYSTEM_PROBE_TEMPLATE
        # Check that defaults are set before nvidia-smi detection
        assert '_gpu_count=0' in SYSTEM_PROBE_TEMPLATE
        assert '_gpu_model=""' in SYSTEM_PROBE_TEMPLATE
        assert '_gpu_driver=""' in SYSTEM_PROBE_TEMPLATE
        assert '_gpu_memory_mib=0' in SYSTEM_PROBE_TEMPLATE


# ============================================================================ #
# Constants Tests
# ============================================================================ #

class TestGpuSamplerConstants:
    """Tests for GPU sampler constants."""

    def test_gpu_sampler_filename_follows_convention(self):
        """Test that GPU sampler filename follows __iops_runtime_* convention."""
        from iops.execution.planner import RUNTIME_GPU_SAMPLER_FILENAME
        assert RUNTIME_GPU_SAMPLER_FILENAME.startswith("__iops_runtime_")

    def test_gpu_trace_prefix_follows_convention(self):
        """Test that GPU trace prefix follows __iops_ convention."""
        from iops.execution.planner import GPU_TRACE_FILENAME_PREFIX
        assert GPU_TRACE_FILENAME_PREFIX.startswith("__iops_")

    def test_gpu_sentinel_follows_convention(self):
        """Test that GPU sentinel filename follows __iops_ convention."""
        from iops.execution.planner import GPU_SAMPLER_SENTINEL_FILENAME
        assert GPU_SAMPLER_SENTINEL_FILENAME.startswith("__iops_")

    def test_gpu_constants_differ_from_cpu_constants(self):
        """Test that GPU constants don't conflict with CPU resource sampler constants."""
        from iops.execution.planner import (
            RUNTIME_SAMPLER_FILENAME, RUNTIME_GPU_SAMPLER_FILENAME,
            TRACE_FILENAME_PREFIX, GPU_TRACE_FILENAME_PREFIX,
            SAMPLER_SENTINEL_FILENAME, GPU_SAMPLER_SENTINEL_FILENAME
        )
        assert RUNTIME_SAMPLER_FILENAME != RUNTIME_GPU_SAMPLER_FILENAME
        assert TRACE_FILENAME_PREFIX != GPU_TRACE_FILENAME_PREFIX
        assert SAMPLER_SENTINEL_FILENAME != GPU_SAMPLER_SENTINEL_FILENAME


# ============================================================================ #
# GPU Trace Aggregation Tests
# ============================================================================ #

GPU_TRACE_HEADER = (
    "timestamp,hostname,gpu_index,gpu_name,"
    "utilization_gpu_pct,utilization_mem_pct,"
    "memory_used_mib,memory_total_mib,"
    "temperature_c,power_draw_w,"
    "clock_sm_mhz,clock_mem_mhz\n"
)


class TestGpuTraceMetrics:
    """Tests for _compute_gpu_trace_metrics."""

    def _make_runner(self):
        from iops.execution.runner import IOPSRunner
        runner = MagicMock(spec=IOPSRunner)
        runner.logger = MagicMock()
        return runner

    def test_empty_trace_file(self, tmp_path):
        """Test with a GPU trace file containing only the header."""
        from iops.execution.runner import IOPSRunner

        runner = self._make_runner()
        trace_file = tmp_path / "__iops_gpu_trace_node1.csv"
        trace_file.write_text(GPU_TRACE_HEADER)

        metrics = IOPSRunner._compute_gpu_trace_metrics(runner, [trace_file])

        assert metrics["gpu_count"] == 0
        assert metrics["gpu_samples_collected"] == 0

    def test_single_gpu_single_sample(self, tmp_path):
        """Test with one GPU and one sample."""
        from iops.execution.runner import IOPSRunner

        runner = self._make_runner()
        trace_file = tmp_path / "__iops_gpu_trace_node1.csv"
        trace_file.write_text(
            GPU_TRACE_HEADER
            + "1705123456.0,node01,0,NVIDIA A100,85.0,40.0,30000,81920,62,250.5,1410,1215\n"
        )

        metrics = IOPSRunner._compute_gpu_trace_metrics(runner, [trace_file])

        assert metrics["gpu_count"] == 1
        assert metrics["gpu_samples_collected"] == 1
        # Aggregate metrics
        assert metrics["gpu_avg_utilization_pct"] == 85.0
        assert metrics["gpu_max_utilization_pct"] == 85.0
        assert metrics["gpu_avg_mem_utilization_pct"] == 40.0
        assert metrics["gpu_mem_peak_mib"] == 30000.0
        assert metrics["gpu_avg_temperature_c"] == 62.0
        assert metrics["gpu_max_temperature_c"] == 62.0
        assert metrics["gpu_avg_power_w"] == 250.5
        assert metrics["gpu_max_power_w"] == 250.5
        assert metrics["gpu_trace_duration_s"] == 0  # single sample
        # Per-GPU columns
        assert metrics["gpu0_avg_utilization_pct"] == 85.0
        assert metrics["gpu0_avg_power_w"] == 250.5
        assert metrics["gpu0_energy_j"] == 0.0  # single sample, no interval
        assert metrics["gpu0_avg_temperature_c"] == 62.0
        assert metrics["gpu0_mem_peak_mib"] == 30000.0

    def test_multiple_samples_metrics(self, tmp_path):
        """Test aggregated metrics across multiple samples."""
        from iops.execution.runner import IOPSRunner

        runner = self._make_runner()
        trace_file = tmp_path / "__iops_gpu_trace_node1.csv"
        trace_file.write_text(
            GPU_TRACE_HEADER
            + "1705123456.0,node01,0,NVIDIA A100,60.0,30.0,20000,81920,55,200.0,1410,1215\n"
            + "1705123457.0,node01,0,NVIDIA A100,80.0,50.0,40000,81920,70,300.0,1410,1215\n"
            + "1705123458.0,node01,0,NVIDIA A100,70.0,40.0,30000,81920,65,250.0,1410,1215\n"
        )

        metrics = IOPSRunner._compute_gpu_trace_metrics(runner, [trace_file])

        assert metrics["gpu_count"] == 1
        assert metrics["gpu_samples_collected"] == 3
        assert metrics["gpu_avg_utilization_pct"] == pytest.approx(70.0, abs=0.01)
        assert metrics["gpu_max_utilization_pct"] == 80.0
        assert metrics["gpu_mem_peak_mib"] == 40000.0
        assert metrics["gpu_avg_temperature_c"] == pytest.approx(63.33, abs=0.01)
        assert metrics["gpu_max_temperature_c"] == 70.0
        assert metrics["gpu_avg_power_w"] == 250.0
        assert metrics["gpu_max_power_w"] == 300.0
        assert metrics["gpu_trace_duration_s"] == 2.0

    def test_energy_calculation(self, tmp_path):
        """Test energy calculation via trapezoidal integration."""
        from iops.execution.runner import IOPSRunner

        runner = self._make_runner()
        trace_file = tmp_path / "__iops_gpu_trace_node1.csv"
        # Constant 200W for 2 seconds = 400 Joules
        trace_file.write_text(
            GPU_TRACE_HEADER
            + "1000.0,node01,0,GPU,50.0,30.0,10000,81920,60,200.0,1410,1215\n"
            + "1001.0,node01,0,GPU,50.0,30.0,10000,81920,60,200.0,1410,1215\n"
            + "1002.0,node01,0,GPU,50.0,30.0,10000,81920,60,200.0,1410,1215\n"
        )

        metrics = IOPSRunner._compute_gpu_trace_metrics(runner, [trace_file])

        # 200W * 2s = 400J (trapezoidal with constant power)
        assert metrics["gpu_energy_j"] == 400.0

    def test_energy_calculation_varying_power(self, tmp_path):
        """Test energy calculation with varying power draw."""
        from iops.execution.runner import IOPSRunner

        runner = self._make_runner()
        trace_file = tmp_path / "__iops_gpu_trace_node1.csv"
        # Power ramps from 100W to 300W over 2 seconds
        trace_file.write_text(
            GPU_TRACE_HEADER
            + "1000.0,node01,0,GPU,50.0,30.0,10000,81920,60,100.0,1410,1215\n"
            + "1001.0,node01,0,GPU,50.0,30.0,10000,81920,60,200.0,1410,1215\n"
            + "1002.0,node01,0,GPU,50.0,30.0,10000,81920,60,300.0,1410,1215\n"
        )

        metrics = IOPSRunner._compute_gpu_trace_metrics(runner, [trace_file])

        # Trapezoidal: (100+200)/2 * 1 + (200+300)/2 * 1 = 150 + 250 = 400J
        assert metrics["gpu_energy_j"] == 400.0

    def test_energy_multiple_gpus(self, tmp_path):
        """Test energy sums across multiple GPUs."""
        from iops.execution.runner import IOPSRunner

        runner = self._make_runner()
        trace_file = tmp_path / "__iops_gpu_trace_node1.csv"
        # Two GPUs, each drawing 200W for 1 second = 400J total
        trace_file.write_text(
            GPU_TRACE_HEADER
            + "1000.0,node01,0,GPU-A,50.0,30.0,10000,81920,60,200.0,1410,1215\n"
            + "1000.0,node01,1,GPU-B,50.0,30.0,10000,81920,60,200.0,1410,1215\n"
            + "1001.0,node01,0,GPU-A,50.0,30.0,10000,81920,60,200.0,1410,1215\n"
            + "1001.0,node01,1,GPU-B,50.0,30.0,10000,81920,60,200.0,1410,1215\n"
        )

        metrics = IOPSRunner._compute_gpu_trace_metrics(runner, [trace_file])

        assert metrics["gpu_count"] == 2
        # GPU-A: 200W * 1s = 200J, GPU-B: 200W * 1s = 200J, Total = 400J
        assert metrics["gpu_energy_j"] == 400.0
        # Per-GPU energy
        assert metrics["gpu0_energy_j"] == 200.0
        assert metrics["gpu1_energy_j"] == 200.0

    def test_idle_gpu_does_not_pollute_averages(self, tmp_path):
        """Test that an idle GPU does not drag down active GPU averages."""
        from iops.execution.runner import IOPSRunner

        runner = self._make_runner()
        trace_file = tmp_path / "__iops_gpu_trace_node1.csv"
        # GPU 0: active at 90% util, 250W, 65C
        # GPU 1: idle at 0% util, 25W, 35C
        trace_file.write_text(
            GPU_TRACE_HEADER
            + "1000.0,node01,0,GPU,90.0,40.0,30000,81920,65,250.0,1410,1215\n"
            + "1000.0,node01,1,GPU,0.0,0.0,0,81920,35,25.0,135,877\n"
            + "1001.0,node01,0,GPU,90.0,40.0,30000,81920,65,250.0,1410,1215\n"
            + "1001.0,node01,1,GPU,0.0,0.0,0,81920,35,25.0,135,877\n"
        )

        metrics = IOPSRunner._compute_gpu_trace_metrics(runner, [trace_file])

        assert metrics["gpu_count"] == 2
        # Aggregate uses max-of-per-gpu-averages, so idle GPU doesn't drag down
        assert metrics["gpu_avg_utilization_pct"] == 90.0  # max(90, 0) = 90
        assert metrics["gpu_avg_power_w"] == 250.0          # max(250, 25) = 250
        assert metrics["gpu_avg_temperature_c"] == 65.0     # max(65, 35) = 65
        # Per-GPU columns show the difference clearly
        assert metrics["gpu0_avg_utilization_pct"] == 90.0
        assert metrics["gpu1_avg_utilization_pct"] == 0.0
        assert metrics["gpu0_avg_power_w"] == 250.0
        assert metrics["gpu1_avg_power_w"] == 25.0
        # Energy: active GPU contributes, idle contributes its own idle power
        assert metrics["gpu0_energy_j"] == 250.0  # 250W * 1s
        assert metrics["gpu1_energy_j"] == 25.0    # 25W * 1s
        assert metrics["gpu_energy_j"] == 275.0    # sum of both

    def test_multiple_nodes(self, tmp_path):
        """Test metrics from multiple nodes."""
        from iops.execution.runner import IOPSRunner

        runner = self._make_runner()
        trace1 = tmp_path / "__iops_gpu_trace_node01.csv"
        trace1.write_text(
            GPU_TRACE_HEADER
            + "1000.0,node01,0,GPU,80.0,40.0,30000,81920,60,250.0,1410,1215\n"
        )
        trace2 = tmp_path / "__iops_gpu_trace_node02.csv"
        trace2.write_text(
            GPU_TRACE_HEADER
            + "1000.0,node02,0,GPU,90.0,50.0,40000,81920,70,300.0,1410,1215\n"
        )

        metrics = IOPSRunner._compute_gpu_trace_metrics(runner, [trace1, trace2])

        assert metrics["gpu_count"] == 2
        assert metrics["gpu_samples_collected"] == 2
        assert metrics["gpu_max_utilization_pct"] == 90.0
        assert metrics["gpu_mem_peak_mib"] == 40000.0
        assert metrics["gpu_max_temperature_c"] == 70.0
        assert metrics["gpu_max_power_w"] == 300.0
        # Per-GPU columns are disambiguated by hostname so same-indexed GPUs
        # on different hosts don't overwrite each other.
        assert metrics["node01_gpu0_avg_utilization_pct"] == 80.0
        assert metrics["node02_gpu0_avg_utilization_pct"] == 90.0
        assert "gpu0_avg_utilization_pct" not in metrics

    def test_multiple_nodes_same_gpu_index_preserved(self, tmp_path):
        """Multi-node traces must not collapse same-indexed GPUs into one column."""
        from iops.execution.runner import IOPSRunner

        runner = self._make_runner()
        trace1 = tmp_path / "__iops_gpu_trace_sirocco22.foo.bar.csv"
        trace1.write_text(
            GPU_TRACE_HEADER
            + "1000.0,sirocco22.foo.bar,0,GPU,95.0,40.0,30000,81920,65,240.0,1410,1215\n"
            + "1001.0,sirocco22.foo.bar,0,GPU,95.0,40.0,30000,81920,65,240.0,1410,1215\n"
        )
        trace2 = tmp_path / "__iops_gpu_trace_sirocco25.foo.bar.csv"
        trace2.write_text(
            GPU_TRACE_HEADER
            + "1000.0,sirocco25.foo.bar,0,GPU,5.0,1.0,100,81920,35,45.0,210,1215\n"
            + "1001.0,sirocco25.foo.bar,0,GPU,5.0,1.0,100,81920,35,45.0,210,1215\n"
        )

        metrics = IOPSRunner._compute_gpu_trace_metrics(runner, [trace1, trace2])

        assert metrics["gpu_count"] == 2
        assert metrics["sirocco22_gpu0_avg_utilization_pct"] == 95.0
        assert metrics["sirocco25_gpu0_avg_utilization_pct"] == 5.0
        assert metrics["sirocco22_gpu0_avg_power_w"] == 240.0
        assert metrics["sirocco25_gpu0_avg_power_w"] == 45.0

    def test_malformed_rows_skipped(self, tmp_path):
        """Test that malformed rows are skipped gracefully."""
        from iops.execution.runner import IOPSRunner

        runner = self._make_runner()
        trace_file = tmp_path / "__iops_gpu_trace_node1.csv"
        trace_file.write_text(
            GPU_TRACE_HEADER
            + "1000.0,node01,0,GPU,80.0,40.0,30000,81920,60,250.0,1410,1215\n"
            + "bad_ts,node01,0,GPU,invalid,bad,data,here,bad,vals,x,y\n"
            + "1001.0,node01,0,GPU,90.0,50.0,40000,81920,70,300.0,1410,1215\n"
        )

        metrics = IOPSRunner._compute_gpu_trace_metrics(runner, [trace_file])

        assert metrics["gpu_samples_collected"] == 2
