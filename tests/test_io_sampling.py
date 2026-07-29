"""Tests for the I/O sampling probe.

The probe reads two independent counter sources, block devices from
/proc/diskstats and NFS mounts from /proc/self/mountstats, because neither one
alone describes both a local disk and a network filesystem. These tests exercise
the parsing against fixture counter files, the aggregation of the resulting
traces, and the configuration plumbing.
"""

import csv
import subprocess
from unittest.mock import MagicMock

import pytest
import yaml

from conftest import load_config


DISKSTATS_BASE = """\
   8       0 sda 100 0 1000 50 200 0 2000 80 0 0 0
   7       0 loop0 5 0 50 1 5 0 50 1 0 0 0
 253       0 dm-0 80 0 800 40 180 0 1800 70 0 0 0
"""

# sda: +50 reads, +2000 sectors read, +60 writes, +3000 sectors written
DISKSTATS_AFTER = """\
   8       0 sda 150 0 3000 60 260 0 5000 90 0 0 0
   7       0 loop0 5 0 50 1 5 0 50 1 0 0 0
 253       0 dm-0 130 0 2800 50 240 0 4800 80 0 0 0
"""

MOUNTSTATS_BASE = (
    "device server:/export mounted on /mnt/data with fstype nfs4 statvers=1.1\n"
    "\topts:\trw,vers=4.2\n"
    "\tbytes:\t10 20 0 0 1000 2000 0 0\n"
    "\tper-op statistics\n"
    "\t        NULL: 1 1 0 44 24 0 0 0 0\n"
    "\t        READ: 5 5 0 100 200 0 0 0 0\n"
    "\t     READDIR: 3 3 0 10 20 0 0 0 0\n"
    "\t       WRITE: 7 7 0 100 200 0 0 0 0\n"
    "device /dev/sda1 mounted on / with fstype ext4\n"
    "\tbytes:\t99 99 99 99 99999 99999 0 0\n"
)

# server-read +3000, server-write +7000, READ ops +10, WRITE ops +20
MOUNTSTATS_AFTER = MOUNTSTATS_BASE.replace(
    "\tbytes:\t10 20 0 0 1000 2000 0 0", "\tbytes:\t10 20 0 0 4000 9000 0 0"
).replace(
    "\t        READ: 5 5", "\t        READ: 15 15"
).replace(
    "\t       WRITE: 7 7", "\t       WRITE: 27 27"
)


def _render_sampler(tmp_path, interval=0.05):
    from iops.execution.planner import (
        IO_SAMPLER_TEMPLATE, IO_TRACE_FILENAME_PREFIX, IO_SAMPLER_SENTINEL_FILENAME,
    )

    script = tmp_path / "io_sampler.sh"
    script.write_text(IO_SAMPLER_TEMPLATE.format(
        execution_dir=str(tmp_path),
        io_trace_prefix=IO_TRACE_FILENAME_PREFIX,
        io_trace_interval=interval,
        io_sentinel_filename=IO_SAMPLER_SENTINEL_FILENAME,
    ))
    script.chmod(0o755)
    return script


def _sample_twice(tmp_path, diskstats_pair, mountstats_pair, sysblock_entries=("sda",)):
    """
    Drive two samples against fixture counters and return the emitted CSV rows.

    The sampler is sourced with both counter sources pointing at absent files so
    the launch block does nothing, then the fixtures are swapped in and
    _iops_io_sample is called by hand.
    """
    sampler = _render_sampler(tmp_path)

    sysblock = tmp_path / "sysblock"
    for entry in sysblock_entries:
        (sysblock / entry).mkdir(parents=True)

    files = {}
    for name, content in (
        ("diskstats.1", diskstats_pair[0]), ("diskstats.2", diskstats_pair[1]),
        ("mountstats.1", mountstats_pair[0]), ("mountstats.2", mountstats_pair[1]),
    ):
        path = tmp_path / name
        path.write_text(content)
        files[name] = path

    driver = tmp_path / "driver.sh"
    driver.write_text(f'''#!/bin/bash
export IOPS_IO_DISKSTATS="{tmp_path}/absent"
export IOPS_IO_MOUNTSTATS="{tmp_path}/absent"
export IOPS_IO_SYSBLOCK="{sysblock}"
source "{sampler}"

_IOPS_IO_DISKSTATS="{files['diskstats.1']}"
_IOPS_IO_MOUNTSTATS="{files['mountstats.1']}"
_iops_io_sample

sleep 0.2
_IOPS_IO_DISKSTATS="{files['diskstats.2']}"
_IOPS_IO_MOUNTSTATS="{files['mountstats.2']}"
_iops_io_sample
''')
    driver.chmod(0o755)

    result = subprocess.run(
        ["bash", str(driver)], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr

    rows = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        ts, host, source, device, interval_s, rb, wb, ro, wo = line.split(",")
        rows.append({
            "hostname": host, "source": source, "device": device,
            "interval_s": float(interval_s), "read_bytes": int(rb),
            "write_bytes": int(wb), "read_ops": int(ro), "write_ops": int(wo),
        })
    return rows


# ============================================================================ #
# Counter Parsing
# ============================================================================ #

class TestIoSamplerParsing:
    """Tests for the sampler's counter parsing and delta arithmetic."""

    def test_template_is_valid_bash(self, tmp_path):
        sampler = _render_sampler(tmp_path)
        result = subprocess.run(["bash", "-n", str(sampler)], capture_output=True)
        assert result.returncode == 0

    def test_first_sample_emits_no_rows(self, tmp_path):
        """The first sample only establishes the baseline for the deltas."""
        sampler = _render_sampler(tmp_path)
        sysblock = tmp_path / "sysblock"
        (sysblock / "sda").mkdir(parents=True)
        diskstats = tmp_path / "diskstats"
        diskstats.write_text(DISKSTATS_BASE)

        driver = tmp_path / "driver.sh"
        driver.write_text(f'''#!/bin/bash
export IOPS_IO_DISKSTATS="{tmp_path}/absent"
export IOPS_IO_MOUNTSTATS="{tmp_path}/absent"
export IOPS_IO_SYSBLOCK="{sysblock}"
source "{sampler}"
_IOPS_IO_DISKSTATS="{diskstats}"
_iops_io_sample
''')
        result = subprocess.run(["bash", str(driver)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_block_deltas_are_bytes(self, tmp_path):
        """Sectors are converted at the kernel's fixed 512 bytes per sector."""
        rows = _sample_twice(
            tmp_path, (DISKSTATS_BASE, DISKSTATS_AFTER), (MOUNTSTATS_BASE, MOUNTSTATS_BASE)
        )
        block = [r for r in rows if r["source"] == "block"]
        assert len(block) == 1
        assert block[0]["device"] == "sda"
        assert block[0]["read_bytes"] == 2000 * 512
        assert block[0]["write_bytes"] == 3000 * 512
        assert block[0]["read_ops"] == 50
        assert block[0]["write_ops"] == 60

    def test_virtual_devices_are_excluded(self, tmp_path):
        """loop and dm devices would double count the disks underneath them."""
        rows = _sample_twice(
            tmp_path, (DISKSTATS_BASE, DISKSTATS_AFTER), (MOUNTSTATS_BASE, MOUNTSTATS_BASE),
            sysblock_entries=("sda", "loop0", "dm-0"),
        )
        devices = {r["device"] for r in rows if r["source"] == "block"}
        assert devices == {"sda"}

    def test_partitions_are_excluded(self, tmp_path):
        """A partition's traffic is already counted in its parent device."""
        sampler = _render_sampler(tmp_path)
        sysblock = tmp_path / "sysblock"
        (sysblock / "sda").mkdir(parents=True)
        (sysblock / "sda1").mkdir(parents=True)
        (sysblock / "sda1" / "partition").write_text("1\n")

        driver = tmp_path / "driver.sh"
        driver.write_text(f'''#!/bin/bash
export IOPS_IO_DISKSTATS="{tmp_path}/absent"
export IOPS_IO_MOUNTSTATS="{tmp_path}/absent"
export IOPS_IO_SYSBLOCK="{sysblock}"
source "{sampler}"
echo "$_IOPS_IO_DEVICES"
''')
        result = subprocess.run(["bash", str(driver)], capture_output=True, text=True, timeout=30)
        devices = result.stdout.split()
        assert devices == ["sda"]

    def test_nfs_deltas_use_server_byte_counters(self, tmp_path):
        """
        Fields 5 and 6 of the bytes line are the bytes that crossed the wire.
        The first two would include reads the page cache satisfied locally.
        """
        rows = _sample_twice(
            tmp_path, (DISKSTATS_BASE, DISKSTATS_BASE), (MOUNTSTATS_BASE, MOUNTSTATS_AFTER)
        )
        nfs = [r for r in rows if r["source"] == "nfs"]
        assert len(nfs) == 1
        assert nfs[0]["device"] == "server:/export"
        assert nfs[0]["read_bytes"] == 3000
        assert nfs[0]["write_bytes"] == 7000

    def test_nfs_ops_ignore_similarly_named_operations(self, tmp_path):
        """READDIR must not be mistaken for READ."""
        rows = _sample_twice(
            tmp_path, (DISKSTATS_BASE, DISKSTATS_BASE), (MOUNTSTATS_BASE, MOUNTSTATS_AFTER)
        )
        nfs = [r for r in rows if r["source"] == "nfs"][0]
        assert nfs["read_ops"] == 10
        assert nfs["write_ops"] == 20

    def test_non_nfs_mounts_are_ignored(self, tmp_path):
        """The ext4 mount in the fixture also has a bytes line."""
        rows = _sample_twice(
            tmp_path, (DISKSTATS_BASE, DISKSTATS_BASE), (MOUNTSTATS_BASE, MOUNTSTATS_AFTER)
        )
        assert {r["device"] for r in rows if r["source"] == "nfs"} == {"server:/export"}

    def test_counter_reset_clamps_to_zero(self, tmp_path):
        """A counter that goes backwards must not emit a negative burst."""
        rewound = DISKSTATS_BASE.replace(
            "sda 100 0 1000 50 200 0 2000 80", "sda 1 0 10 5 2 0 20 8"
        )
        rows = _sample_twice(
            tmp_path, (DISKSTATS_BASE, rewound), (MOUNTSTATS_BASE, MOUNTSTATS_BASE)
        )
        block = [r for r in rows if r["source"] == "block"][0]
        assert block["read_bytes"] == 0
        assert block["write_bytes"] == 0
        assert block["read_ops"] == 0
        assert block["write_ops"] == 0

    def test_rows_carry_the_measured_interval(self, tmp_path):
        """Rates come from the measured elapsed time, not the configured one."""
        rows = _sample_twice(
            tmp_path, (DISKSTATS_BASE, DISKSTATS_AFTER), (MOUNTSTATS_BASE, MOUNTSTATS_AFTER)
        )
        assert rows
        for row in rows:
            assert row["interval_s"] >= 0.19


# ============================================================================ #
# Sampler Lifecycle
# ============================================================================ #

class TestIoSamplerLifecycle:
    """Tests for sentinel handling and multi-node fan-out."""

    def test_sampler_delegates_multinode_launch(self):
        from iops.execution.planner import IO_SAMPLER_TEMPLATE, NODE_LAUNCHER_TEMPLATE

        assert "_iops_launch_on_nodes" in IO_SAMPLER_TEMPLATE
        assert "srun --overlap" in NODE_LAUNCHER_TEMPLATE

    def test_sampler_uses_shared_attempt_id(self):
        from iops.execution.planner import IO_SAMPLER_TEMPLATE

        assert "IOPS_ATTEMPT_ID" in IO_SAMPLER_TEMPLATE
        assert "OAR_JOB_ID" in IO_SAMPLER_TEMPLATE

    def test_sampler_terminates_when_sentinel_removed(self, tmp_path):
        from iops.execution.planner import (
            EXIT_HANDLER_TEMPLATE, IO_TRACE_FILENAME_PREFIX, IO_SAMPLER_SENTINEL_FILENAME,
        )

        sampler = _render_sampler(tmp_path)
        handler = tmp_path / "handler.sh"
        handler.write_text(EXIT_HANDLER_TEMPLATE)

        job = tmp_path / "job.sh"
        job.write_text(f'''#!/bin/bash
source "{handler}"
source "{sampler}"
sleep 0.3
''')
        result = subprocess.run(
            ["bash", str(job)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
        )
        assert result.returncode == 0

        assert not list(tmp_path.glob(f"{IO_SAMPLER_SENTINEL_FILENAME}*")), \
            "sentinel must be removed by the exit handler"
        traces = list(tmp_path.glob(f"{IO_TRACE_FILENAME_PREFIX}*.csv"))
        assert traces, "sampler must produce a trace file"
        assert traces[0].read_text().startswith(
            "timestamp,hostname,source,device,interval_s,read_bytes,write_bytes,read_ops,write_ops"
        )

    def test_sampler_skips_when_no_counter_source(self, tmp_path):
        """Neither source readable means no sentinel and no empty trace file."""
        from iops.execution.planner import (
            EXIT_HANDLER_TEMPLATE, IO_TRACE_FILENAME_PREFIX, IO_SAMPLER_SENTINEL_FILENAME,
        )

        sampler = _render_sampler(tmp_path)
        handler = tmp_path / "handler.sh"
        handler.write_text(EXIT_HANDLER_TEMPLATE)

        job = tmp_path / "job.sh"
        job.write_text(f'''#!/bin/bash
export IOPS_IO_DISKSTATS="{tmp_path}/absent"
export IOPS_IO_MOUNTSTATS="{tmp_path}/absent"
source "{handler}"
source "{sampler}"
sleep 0.2
''')
        result = subprocess.run(
            ["bash", str(job)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
        )
        assert result.returncode == 0
        assert not list(tmp_path.glob(f"{IO_TRACE_FILENAME_PREFIX}*.csv"))
        assert not list(tmp_path.glob(f"{IO_SAMPLER_SENTINEL_FILENAME}*"))


# ============================================================================ #
# Configuration
# ============================================================================ #

class TestIoSamplingConfig:
    """Tests for the probes.io_sampling option."""

    def _load(self, sample_config_dict, tmp_path, probes=None, **script_overrides):
        if probes is not None:
            sample_config_dict["benchmark"]["probes"] = probes
        for key, value in script_overrides.items():
            sample_config_dict["scripts"][0][key] = value
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)
        return load_config(config_file)

    def test_io_sampling_defaults_to_false(self, sample_config_dict, tmp_path):
        config = self._load(sample_config_dict, tmp_path, probes={})
        assert config.benchmark.probes.io_sampling is False

    def test_io_sampling_can_be_enabled(self, sample_config_dict, tmp_path):
        config = self._load(sample_config_dict, tmp_path, probes={"io_sampling": True})
        assert config.benchmark.probes.io_sampling is True

    def test_unknown_probe_key_still_rejected(self, sample_config_dict, tmp_path):
        from iops.config.loader import ConfigValidationError

        with pytest.raises(ConfigValidationError):
            self._load(sample_config_dict, tmp_path, probes={"io_samplingg": True})

    def test_io_sampling_disabled_for_non_bash_script(self, sample_config_dict, tmp_path):
        """The sampler needs bash features, so a sh script must turn it off."""
        from iops.config.loader import check_resource_sampler_compatibility

        config = self._load(
            sample_config_dict, tmp_path,
            probes={"io_sampling": True, "resource_sampling": False},
            submit="sbatch", script_template="#!/bin/sh\necho hello\n",
        )
        assert config.benchmark.probes.io_sampling is True

        check_resource_sampler_compatibility(config, logger=None)
        assert config.benchmark.probes.io_sampling is False

    def test_io_sampling_kept_for_bash_script(self, sample_config_dict, tmp_path):
        from iops.config.loader import check_resource_sampler_compatibility

        config = self._load(
            sample_config_dict, tmp_path,
            probes={"io_sampling": True},
            script_template="#!/bin/bash\necho hello\n",
        )
        check_resource_sampler_compatibility(config, logger=None)
        assert config.benchmark.probes.io_sampling is True


# ============================================================================ #
# Injection
# ============================================================================ #

class TestIoSamplerInjection:
    """Tests for I/O sampler injection into generated scripts."""

    def _planner(self, sample_config_dict, tmp_path, probes):
        sample_config_dict["benchmark"]["probes"] = probes
        config_file = tmp_path / "test_config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(sample_config_dict, f)

        from iops.execution.planner import BasePlanner
        return BasePlanner.build(load_config(config_file))

    def test_sampler_written_when_enabled(self, sample_config_dict, tmp_path):
        from iops.execution.planner import RUNTIME_IO_SAMPLER_FILENAME, NODE_LAUNCHER_FILENAME

        planner = self._planner(
            sample_config_dict, tmp_path, {"io_sampling": True, "system_snapshot": False}
        )
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        script = planner._inject_iops_scripts("#!/bin/bash\necho hi", exec_dir)

        sampler_file = exec_dir / RUNTIME_IO_SAMPLER_FILENAME
        assert sampler_file.exists()
        assert f'source "{sampler_file}"' in script
        # The I/O sampler needs the launcher to reach other nodes
        assert (exec_dir / NODE_LAUNCHER_FILENAME).exists()

    def test_sampler_not_written_when_disabled(self, sample_config_dict, tmp_path):
        from iops.execution.planner import RUNTIME_IO_SAMPLER_FILENAME

        planner = self._planner(
            sample_config_dict, tmp_path, {"io_sampling": False, "system_snapshot": True}
        )
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        planner._inject_iops_scripts("#!/bin/bash\necho hi", exec_dir)
        assert not (exec_dir / RUNTIME_IO_SAMPLER_FILENAME).exists()

    def test_sampler_uses_config_interval(self, sample_config_dict, tmp_path):
        from iops.execution.planner import RUNTIME_IO_SAMPLER_FILENAME

        planner = self._planner(
            sample_config_dict, tmp_path,
            {"io_sampling": True, "sampling_interval": 2.5, "system_snapshot": False},
        )
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        planner._inject_iops_scripts("#!/bin/bash\necho hi", exec_dir)
        content = (exec_dir / RUNTIME_IO_SAMPLER_FILENAME).read_text()
        assert "_IOPS_IO_INTERVAL=2.5" in content


# ============================================================================ #
# Aggregation
# ============================================================================ #

def _write_io_trace(path, rows):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "hostname", "source", "device", "interval_s",
            "read_bytes", "write_bytes", "read_ops", "write_ops",
        ])
        writer.writerows(rows)


class TestIoTraceAggregation:
    """Tests for _compute_io_trace_metrics."""

    def _metrics(self, trace_files):
        from iops.execution.runner import IOPSRunner

        runner = MagicMock(spec=IOPSRunner)
        runner.logger = MagicMock()
        return IOPSRunner._compute_io_trace_metrics(runner, trace_files)

    def test_empty_trace_reports_zero_counters(self, tmp_path):
        trace = tmp_path / "__iops_io_trace_node01_1.csv"
        _write_io_trace(trace, [])

        metrics = self._metrics([trace])
        assert metrics["io_nodes_traced"] == 0
        assert metrics["io_samples_collected"] == 0
        assert "io_read_gb" not in metrics

    def test_sources_are_reported_separately_and_summed(self, tmp_path):
        """
        The reason the probe reads two sources: an NFS-backed run shows nothing
        on block devices, and a local-disk run shows nothing on NFS.
        """
        mib = 1024 ** 2
        trace = tmp_path / "__iops_io_trace_node01_1.csv"
        _write_io_trace(trace, [
            [100.0, "node01", "block", "sda", 1.0, 100 * mib, 200 * mib, 10, 20],
            [100.0, "node01", "nfs", "srv:/exp", 1.0, 300 * mib, 400 * mib, 30, 40],
        ])

        metrics = self._metrics([trace])
        assert metrics["io_disk_read_gb"] == pytest.approx(100 / 1024, abs=1e-3)
        assert metrics["io_disk_write_gb"] == pytest.approx(200 / 1024, abs=1e-3)
        assert metrics["io_nfs_read_gb"] == pytest.approx(300 / 1024, abs=1e-3)
        assert metrics["io_nfs_write_gb"] == pytest.approx(400 / 1024, abs=1e-3)
        assert metrics["io_read_gb"] == pytest.approx(400 / 1024, abs=1e-3)
        assert metrics["io_write_gb"] == pytest.approx(600 / 1024, abs=1e-3)

    def test_absent_source_reports_zero_not_missing(self, tmp_path):
        """A local-disk run must still emit the NFS columns, holding zero."""
        trace = tmp_path / "__iops_io_trace_node01_1.csv"
        _write_io_trace(trace, [[100.0, "node01", "block", "sda", 1.0, 1024, 2048, 1, 2]])

        metrics = self._metrics([trace])
        assert metrics["io_nfs_read_gb"] == 0.0
        assert metrics["io_nfs_write_gb"] == 0.0

    def test_throughput_uses_measured_intervals(self, tmp_path):
        mib = 1024 ** 2
        trace = tmp_path / "__iops_io_trace_node01_1.csv"
        # Two samples covering 2s in total, 300 MiB written
        _write_io_trace(trace, [
            [100.0, "node01", "block", "sda", 1.0, 0, 100 * mib, 0, 10],
            [101.0, "node01", "block", "sda", 1.0, 0, 200 * mib, 0, 20],
        ])

        metrics = self._metrics([trace])
        assert metrics["io_trace_duration_s"] == 2.0
        assert metrics["io_write_mbs_avg"] == pytest.approx(150.0, abs=0.1)
        # Peak is the busiest single sample, not the average
        assert metrics["io_write_mbs_peak_per_node"] == pytest.approx(200.0, abs=0.1)
        assert metrics["io_write_iops_avg"] == pytest.approx(15.0, abs=0.1)

    def test_devices_in_the_same_sample_are_summed(self, tmp_path):
        mib = 1024 ** 2
        trace = tmp_path / "__iops_io_trace_node01_1.csv"
        _write_io_trace(trace, [
            [100.0, "node01", "block", "sda", 1.0, 0, 100 * mib, 0, 0],
            [100.0, "node01", "block", "nvme0n1", 1.0, 0, 100 * mib, 0, 0],
        ])

        metrics = self._metrics([trace])
        # One sampling instant, so the interval is counted once, not per device
        assert metrics["io_trace_duration_s"] == 1.0
        assert metrics["io_write_mbs_peak_per_node"] == pytest.approx(200.0, abs=0.1)

    def test_multiple_nodes_are_combined(self, tmp_path):
        mib = 1024 ** 2
        trace_a = tmp_path / "__iops_io_trace_node01_1.csv"
        trace_b = tmp_path / "__iops_io_trace_node02_1.csv"
        _write_io_trace(trace_a, [[100.0, "node01", "block", "sda", 1.0, 0, 100 * mib, 0, 0]])
        _write_io_trace(trace_b, [[100.0, "node02", "block", "sda", 1.0, 0, 300 * mib, 0, 0]])

        metrics = self._metrics([trace_a, trace_b])
        assert metrics["io_nodes_traced"] == 2
        # Aggregate throughput sums the nodes, the peak stays per node
        assert metrics["io_write_mbs_avg"] == pytest.approx(400.0, abs=0.1)
        assert metrics["io_write_mbs_peak_per_node"] == pytest.approx(300.0, abs=0.1)

    def test_zero_interval_rows_are_skipped(self, tmp_path):
        """A row with no measurable elapsed time yields no rate."""
        trace = tmp_path / "__iops_io_trace_node01_1.csv"
        _write_io_trace(trace, [[100.0, "node01", "block", "sda", 0.0, 1024, 1024, 1, 1]])

        metrics = self._metrics([trace])
        assert metrics["io_samples_collected"] == 0

    def test_malformed_rows_are_skipped(self, tmp_path):
        mib = 1024 ** 2
        trace = tmp_path / "__iops_io_trace_node01_1.csv"
        _write_io_trace(trace, [
            [100.0, "node01", "block", "sda", 1.0, "garbage", 0, 0, 0],
            [101.0, "node01", "block", "sda", 1.0, 0, 100 * mib, 0, 0],
        ])

        metrics = self._metrics([trace])
        assert metrics["io_samples_collected"] == 1
        assert metrics["io_write_gb"] == pytest.approx(100 / 1024, abs=1e-3)


# ============================================================================ #
# Summary CSV
# ============================================================================ #

class TestResourceSummaryColumns:
    """Tests for how the summary CSV handles rows with differing metrics."""

    def test_summary_columns_are_the_union_across_executions(self, tmp_path):
        """
        An execution short enough that its sampler collected nothing reports
        only the counters. Taking the first row's keys as the header would drop
        every later column and lose the whole summary.
        """
        from iops.execution.runner import IOPSRunner, RESOURCE_SUMMARY_FILENAME

        workdir = tmp_path / "wd"
        workdir.mkdir()

        runner = MagicMock(spec=IOPSRunner)
        runner.logger = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.benchmark.probes.resource_sampling = False
        mock_cfg.benchmark.probes.gpu_sampling = False
        mock_cfg.benchmark.probes.io_sampling = True
        mock_cfg.benchmark.workdir = workdir
        runner.cfg = mock_cfg
        runner._compute_io_trace_metrics = IOPSRunner._compute_io_trace_metrics.__get__(runner)
        runner._register_resource_metrics = MagicMock()

        tests = []
        populated = [[100.0, "node01", "block", "sda", 1.0, 0, 512 * 1024 ** 2, 0, 1]]
        for idx, rows in enumerate([[], populated], start=1):
            exec_dir = workdir / f"exec_{idx:04d}"
            exec_dir.mkdir()
            _write_io_trace(exec_dir / f"__iops_io_trace_node01_{idx}.csv", rows)

            test = MagicMock()
            test.execution_id = idx
            test.repetition = 1
            test.execution_dir = exec_dir
            test.vars = {"nodes": idx}
            tests.append(test)

        IOPSRunner._aggregate_resource_traces(runner, tests)

        summary = workdir / RESOURCE_SUMMARY_FILENAME
        assert summary.exists(), "summary must be written even when the first row is sparse"
        with open(summary) as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            written = list(reader)

        assert "io_write_gb" in header, "columns from later rows must survive"
        assert written[0]["io_write_gb"] == "", "missing values fill in as empty"
        assert float(written[1]["io_write_gb"]) > 0
