"""Tests for the I/O sampling probe.

The probe reads two independent counter sources, block devices from
/proc/diskstats and NFS mounts from /proc/self/mountstats, because neither one
alone describes both a local disk and a network filesystem. These tests exercise
the parsing against fixture counter files, the aggregation of the resulting
traces, and the configuration plumbing.
"""

import csv
import pathlib
import subprocess
from unittest.mock import MagicMock

import pytest
import yaml

from conftest import load_config


# The sampler keeps its per-target labels in an associative array, so running it
# needs bash 4+. macOS still ships bash 3.2, where `declare -A` is a syntax
# error. Tests that only check the template's syntax or its target resolution
# stay platform independent and are deliberately not marked.
_BASH_HAS_ASSOC_ARRAYS = subprocess.run(
    ["bash", "-c", "declare -A _probe"], capture_output=True
).returncode == 0

requires_bash_assoc_arrays = pytest.mark.skipif(
    not _BASH_HAS_ASSOC_ARRAYS,
    reason="sampler needs bash 4+ for `declare -A`; this system's bash is older",
)


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


def _render_sampler(tmp_path, interval=0.05, io_paths=""):
    from iops.execution.planner import (
        IO_SAMPLER_TEMPLATE, IO_TRACE_FILENAME_PREFIX, IO_TARGETS_FILENAME_PREFIX,
        IO_SAMPLER_SENTINEL_FILENAME,
    )

    script = tmp_path / "io_sampler.sh"
    script.write_text(IO_SAMPLER_TEMPLATE.format(
        execution_dir=str(tmp_path),
        io_trace_prefix=IO_TRACE_FILENAME_PREFIX,
        io_targets_prefix=IO_TARGETS_FILENAME_PREFIX,
        io_trace_interval=interval,
        io_sentinel_filename=IO_SAMPLER_SENTINEL_FILENAME,
        io_paths=io_paths,
    ))
    script.chmod(0o755)
    return script


def _fake_df(tmp_path, table, default=("overlay", "overlay")):
    """Write a ``df`` stub answering from ``table`` and return the PATH export.

    ``_iops_io_resolve`` shells out to ``df -PT``, so what a path resolves to is
    a property of the machine running the test: a workstation has a block-backed
    root, a CI container has an overlay one that legitimately resolves to
    "none". Pinning df's answers keeps these tests about the resolution logic
    instead of about where they happen to run.

    ``table`` maps a path to ``(source, fstype)``; anything else gets ``default``.
    """
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    branches = "\n".join(
        f'    {path}) _src="{src}"; _type="{fstype}"; _mount="{path}" ;;'
        for path, (src, fstype) in table.items()
    )
    stub = bindir / "df"
    stub.write_text(f'''#!/bin/bash
_p="${{@: -1}}"
_src="{default[0]}"; _type="{default[1]}"; _mount="/"
case "$_p" in
{branches}
esac
echo "Filesystem Type 1024-blocks Used Available Capacity Mounted on"
echo "$_src $_type 1024 0 1024 0% $_mount"
''')
    stub.chmod(0o755)
    return f'export PATH="{bindir}:$PATH"\n'


def _fake_sysclass(tmp_path, disk="nvme0n1", partition="nvme0n1p1"):
    """Build a sysfs tree where ``partition`` lives under its whole ``disk``."""
    sysclass = tmp_path / "sysclassblock"
    (sysclass / disk / partition).mkdir(parents=True)
    (sysclass / disk / partition / "partition").write_text("1\n")
    (sysclass / partition).symlink_to(sysclass / disk / partition)
    return sysclass


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
_iops_io_resolve_targets

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
        ts, host, source, device, path, interval_s, rb, wb, ro, wo = line.split(",")
        rows.append({
            "hostname": host, "source": source, "device": device, "path": path,
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
_iops_io_resolve_targets
_IOPS_IO_DISKSTATS="{diskstats}"
_iops_io_sample
''')
        result = subprocess.run(["bash", str(driver)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    @requires_bash_assoc_arrays
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

    @requires_bash_assoc_arrays
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
_iops_io_resolve_targets
echo "$_IOPS_IO_DEVICES"
''')
        result = subprocess.run(["bash", str(driver)], capture_output=True, text=True, timeout=30)
        devices = result.stdout.split()
        assert devices == ["sda"]

    @requires_bash_assoc_arrays
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

    @requires_bash_assoc_arrays
    def test_nfs_ops_ignore_similarly_named_operations(self, tmp_path):
        """READDIR must not be mistaken for READ."""
        rows = _sample_twice(
            tmp_path, (DISKSTATS_BASE, DISKSTATS_BASE), (MOUNTSTATS_BASE, MOUNTSTATS_AFTER)
        )
        nfs = [r for r in rows if r["source"] == "nfs"][0]
        assert nfs["read_ops"] == 10
        assert nfs["write_ops"] == 20

    @requires_bash_assoc_arrays
    def test_non_nfs_mounts_are_ignored(self, tmp_path):
        """The ext4 mount in the fixture also has a bytes line."""
        rows = _sample_twice(
            tmp_path, (DISKSTATS_BASE, DISKSTATS_BASE), (MOUNTSTATS_BASE, MOUNTSTATS_AFTER)
        )
        assert {r["device"] for r in rows if r["source"] == "nfs"} == {"server:/export"}

    @requires_bash_assoc_arrays
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

    @requires_bash_assoc_arrays
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

class TestIoPathScoping:
    """
    Tests for probes.io_paths.

    Without it the sampler counts every device on the node, so a benchmark
    writing to /tmp on a machine that also mounts NFS reports both. Scoping to a
    path restricts the counters to the filesystem actually holding it.
    """

    def _resolve(self, tmp_path, path, sysclassblock=None, df_table=None):
        """Call _iops_io_resolve for one path and return its raw result."""
        sampler = _render_sampler(tmp_path)
        env = ""
        if sysclassblock is not None:
            env = f'export IOPS_IO_SYSCLASSBLOCK="{sysclassblock}"\n'
        if df_table is not None:
            env += _fake_df(tmp_path, df_table)

        driver = tmp_path / "resolve.sh"
        driver.write_text(f'''#!/bin/bash
export IOPS_IO_DISKSTATS="{tmp_path}/absent"
export IOPS_IO_MOUNTSTATS="{tmp_path}/absent"
{env}source "{sampler}"
_iops_io_resolve "{path}"
''')
        result = subprocess.run(
            ["bash", str(driver)], capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def test_partition_resolves_to_its_whole_device(self, tmp_path):
        """
        /proc/diskstats counts whole devices, so a path on /dev/sda1 has to be
        attributed to sda. Modelled on real sysfs, where a partition lives under
        its parent disk.
        """
        sysclass = tmp_path / "sysclassblock"
        (sysclass / "sda").mkdir(parents=True)
        (sysclass / "sda" / "sda1").mkdir()
        (sysclass / "sda" / "sda1" / "partition").write_text("1\n")
        (sysclass / "sda1").symlink_to(sysclass / "sda" / "sda1")

        sampler = _render_sampler(tmp_path)
        driver = tmp_path / "walk.sh"
        driver.write_text(f'''#!/bin/bash
export IOPS_IO_DISKSTATS="{tmp_path}/absent"
export IOPS_IO_MOUNTSTATS="{tmp_path}/absent"
export IOPS_IO_SYSCLASSBLOCK="{sysclass}"
source "{sampler}"
_iops_io_whole_device sda1
''')
        result = subprocess.run(
            ["bash", str(driver)], capture_output=True, text=True, timeout=30,
        )
        assert result.stdout.strip() == "sda"

    def test_device_mapper_resolves_to_underlying_devices(self, tmp_path):
        """An LVM volume's traffic lands on the disks underneath it."""
        sysclass = tmp_path / "sysclassblock"
        (sysclass / "dm-0" / "slaves").mkdir(parents=True)
        for disk in ("sda", "sdb"):
            (sysclass / disk).mkdir()
            (sysclass / "dm-0" / "slaves" / disk).symlink_to(sysclass / disk)

        sampler = _render_sampler(tmp_path)
        driver = tmp_path / "walk.sh"
        driver.write_text(f'''#!/bin/bash
export IOPS_IO_DISKSTATS="{tmp_path}/absent"
export IOPS_IO_MOUNTSTATS="{tmp_path}/absent"
export IOPS_IO_SYSCLASSBLOCK="{sysclass}"
source "{sampler}"
_iops_io_whole_device dm-0
''')
        result = subprocess.run(
            ["bash", str(driver)], capture_output=True, text=True, timeout=30,
        )
        assert sorted(result.stdout.split()) == ["sda", "sdb"]

    def test_local_path_resolves_to_a_block_device(self, tmp_path):
        """A path on a real disk is attributed to the whole device beneath it."""
        sysclass = _fake_sysclass(tmp_path)
        resolved = self._resolve(
            tmp_path, "/", sysclassblock=str(sysclass),
            df_table={"/": ("/dev/nvme0n1p1", "ext4")},
        )
        kind, target, _mount, fstype = resolved.split("|", 3)
        assert kind == "block"
        assert target == "nvme0n1"
        assert fstype == "ext4"

    def test_path_that_does_not_exist_yet_uses_its_nearest_ancestor(self, tmp_path):
        """The benchmark usually creates its output directory itself."""
        sysclass = _fake_sysclass(tmp_path)
        resolved = self._resolve(
            tmp_path, str(tmp_path / "not" / "created" / "yet"),
            sysclassblock=str(sysclass),
            # Only the existing ancestor is ever handed to df; if the walk did
            # not back off to it, the lookup would miss and report the default.
            df_table={str(tmp_path): ("/dev/nvme0n1p1", "ext4")},
        )
        kind, target, _mount, _fstype = resolved.split("|", 3)
        assert kind == "block"
        assert target == "nvme0n1"

    def test_tmpfs_path_resolves_to_nothing_countable(self, tmp_path):
        """
        Writes to tmpfs never reach storage, so there is no counter to read.
        Reporting this as 'none' is what lets the runner warn instead of
        silently returning zero.
        """
        if not pathlib.Path("/dev/shm").is_dir():
            pytest.skip("no tmpfs mount available")

        resolved = self._resolve(tmp_path, "/dev/shm")
        kind, target, _mount, fstype = resolved.split("|", 3)
        assert kind == "none"
        assert target == ""
        assert fstype == "tmpfs"

    def test_configured_paths_restrict_the_block_filter(self, tmp_path):
        """Only devices behind a configured path are sampled."""
        sysblock = tmp_path / "sysblock"
        for entry in ("sda", "sdb"):
            (sysblock / entry).mkdir(parents=True)

        sysclass = _fake_sysclass(tmp_path)
        path_env = _fake_df(tmp_path, {"/": ("/dev/nvme0n1p1", "ext4")})

        sampler = _render_sampler(tmp_path, io_paths="'/'")
        driver = tmp_path / "targets.sh"
        driver.write_text(f'''#!/bin/bash
export IOPS_IO_DISKSTATS="{tmp_path}/absent"
export IOPS_IO_MOUNTSTATS="{tmp_path}/absent"
export IOPS_IO_SYSBLOCK="{sysblock}"
export IOPS_IO_SYSCLASSBLOCK="{sysclass}"
{path_env}source "{sampler}"
_iops_io_resolve_targets
echo "DEVICES:$_IOPS_IO_DEVICES"
''')
        result = subprocess.run(
            ["bash", str(driver)], capture_output=True, text=True, timeout=30,
        )
        devices = result.stdout.split("DEVICES:")[1].split()
        # The devices present on the node are never picked up wholesale: only
        # what the one configured path resolved to.
        assert "sda" not in devices and "sdb" not in devices
        assert devices == ["nvme0n1"]

    def test_no_configured_paths_monitors_every_device(self, tmp_path):
        """The default stays 'monitor everything' for backwards compatibility."""
        sysblock = tmp_path / "sysblock"
        for entry in ("sda", "sdb"):
            (sysblock / entry).mkdir(parents=True)

        sampler = _render_sampler(tmp_path)
        driver = tmp_path / "targets.sh"
        driver.write_text(f'''#!/bin/bash
export IOPS_IO_DISKSTATS="{tmp_path}/absent"
export IOPS_IO_MOUNTSTATS="{tmp_path}/absent"
export IOPS_IO_SYSBLOCK="{sysblock}"
source "{sampler}"
_iops_io_resolve_targets
echo "DEVICES:$_IOPS_IO_DEVICES"
''')
        result = subprocess.run(
            ["bash", str(driver)], capture_output=True, text=True, timeout=30,
        )
        devices = result.stdout.split("DEVICES:")[1].split()
        assert sorted(devices) == ["sda", "sdb"]

    @requires_bash_assoc_arrays
    def test_nfs_filter_selects_only_the_configured_export(self, tmp_path):
        """Rows for other NFS mounts on the node must not be emitted."""
        sysblock = tmp_path / "sysblock"
        (sysblock / "sda").mkdir(parents=True)

        two_mounts = MOUNTSTATS_AFTER.replace(
            "device /dev/sda1 mounted on / with fstype ext4\n\tbytes:\t99 99 99 99 99999 99999 0 0\n",
            "device other:/vol mounted on /mnt/other with fstype nfs4 statvers=1.1\n"
            "\tbytes:\t0 0 0 0 5000 6000 0 0\n",
        )
        base_two_mounts = MOUNTSTATS_BASE.replace(
            "device /dev/sda1 mounted on / with fstype ext4\n\tbytes:\t99 99 99 99 99999 99999 0 0\n",
            "device other:/vol mounted on /mnt/other with fstype nfs4 statvers=1.1\n"
            "\tbytes:\t0 0 0 0 1000 1000 0 0\n",
        )

        sampler = _render_sampler(tmp_path)
        (tmp_path / "ms.1").write_text(base_two_mounts)
        (tmp_path / "ms.2").write_text(two_mounts)

        driver = tmp_path / "driver.sh"
        driver.write_text(f'''#!/bin/bash
export IOPS_IO_DISKSTATS="{tmp_path}/absent"
export IOPS_IO_MOUNTSTATS="{tmp_path}/absent"
export IOPS_IO_SYSBLOCK="{sysblock}"
source "{sampler}"
_IOPS_IO_FILTERED=1
_IOPS_IO_DEVICES=" "
_IOPS_IO_NFS_MOUNTS=" server:/export "
_iops_io_labels["nfs|server:/export"]="/mnt/data"
_IOPS_IO_MOUNTSTATS="{tmp_path}/ms.1"
_iops_io_sample > /dev/null
sleep 0.2
_IOPS_IO_MOUNTSTATS="{tmp_path}/ms.2"
_iops_io_sample
''')
        result = subprocess.run(
            ["bash", str(driver)], capture_output=True, text=True, timeout=30,
        )
        lines = [ln for ln in result.stdout.strip().split("\n") if ln]
        assert len(lines) == 1, f"expected only the configured export, got {lines}"
        assert "server:/export" in lines[0]
        assert "other:/vol" not in lines[0]
        # The row is labelled with the path it was resolved from
        assert lines[0].split(",")[4] == "/mnt/data"

    def test_local_only_paths_exclude_every_nfs_mount(self, tmp_path):
        """
        Regression: a run scoped to a local path reported every NFS mount on the
        node. The NFS filter treated "empty" as "no filtering", but once paths
        are configured an empty filter means the paths resolved to no NFS mount,
        so nothing from that source should be counted.

        Observed on a cluster where io_paths was ["/tmp"] and the reported reads
        were almost entirely the package store and home directory mounts, which
        the benchmark only touched while loading modules.
        """
        sysblock = tmp_path / "sysblock"
        (sysblock / "sda").mkdir(parents=True)

        sampler = _render_sampler(tmp_path, io_paths="'/'")
        (tmp_path / "ms.1").write_text(MOUNTSTATS_BASE)
        (tmp_path / "ms.2").write_text(MOUNTSTATS_AFTER)
        (tmp_path / "ds.1").write_text(DISKSTATS_BASE)
        (tmp_path / "ds.2").write_text(DISKSTATS_AFTER)

        driver = tmp_path / "driver.sh"
        driver.write_text(f'''#!/bin/bash
export IOPS_IO_DISKSTATS="{tmp_path}/absent"
export IOPS_IO_MOUNTSTATS="{tmp_path}/absent"
export IOPS_IO_SYSBLOCK="{sysblock}"
source "{sampler}"
_iops_io_resolve_targets
_IOPS_IO_DISKSTATS="{tmp_path}/ds.1"
_IOPS_IO_MOUNTSTATS="{tmp_path}/ms.1"
_iops_io_sample > /dev/null
sleep 0.2
_IOPS_IO_DISKSTATS="{tmp_path}/ds.2"
_IOPS_IO_MOUNTSTATS="{tmp_path}/ms.2"
_iops_io_sample
''')
        result = subprocess.run(
            ["bash", str(driver)], capture_output=True, text=True, timeout=30,
        )
        sources = {ln.split(",")[2] for ln in result.stdout.strip().split("\n") if ln}
        assert "nfs" not in sources, (
            f"a run scoped to a local path must not report NFS mounts, got {result.stdout}"
        )

    @requires_bash_assoc_arrays
    def test_paths_sharing_a_device_are_counted_once(self, tmp_path):
        """
        Two directories on the same disk resolve to the same device. The device
        must be registered once, otherwise its traffic would be added twice, and
        the label must name both paths rather than crediting whichever was
        resolved last. The kernel has no per-directory counters, so this is the
        limit of what path scoping can separate.
        """
        (tmp_path / "sub").mkdir()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        sysclass = _fake_sysclass(tmp_path)
        _fake_sysclass(tmp_path, disk="sda", partition="sda1")
        # The first two paths share one device; the third is on another, so the
        # grouping cannot be an artefact of every path resolving alike.
        path_env = _fake_df(tmp_path, {
            str(tmp_path): ("/dev/nvme0n1p1", "ext4"),
            f"{tmp_path}/sub": ("/dev/nvme0n1p1", "ext4"),
            str(elsewhere): ("/dev/sda1", "ext4"),
        })

        sampler = _render_sampler(
            tmp_path, io_paths=f"'{tmp_path}' '{tmp_path}/sub' '{elsewhere}'")
        driver = tmp_path / "shared.sh"
        driver.write_text(f'''#!/bin/bash
export IOPS_IO_DISKSTATS="{tmp_path}/absent"
export IOPS_IO_MOUNTSTATS="{tmp_path}/absent"
export IOPS_IO_SYSCLASSBLOCK="{sysclass}"
{path_env}source "{sampler}"
_iops_io_resolve_targets
echo "DEVICES:$_IOPS_IO_DEVICES"
for k in "${{!_iops_io_labels[@]}}"; do echo "LABEL:$k=${{_iops_io_labels[$k]}}"; done
''')
        result = subprocess.run(
            ["bash", str(driver)], capture_output=True, text=True, timeout=30,
        )

        devices = result.stdout.split("DEVICES:")[1].split("\n")[0].split()
        assert len(devices) == len(set(devices)), f"device registered more than once: {devices}"
        assert sorted(devices) == ["nvme0n1", "sda"]

        labels = [ln for ln in result.stdout.split("\n") if ln.startswith("LABEL:")]
        shared = [ln for ln in labels if ";" in ln]
        assert shared, f"paths sharing a device must be listed together, got {labels}"
        # The shared label names both paths, not just whichever resolved last.
        assert str(tmp_path) in shared[0] and f"{tmp_path}/sub" in shared[0]

    def test_targets_file_records_each_resolution(self, tmp_path):
        """
        The targets file is what makes a zero result explainable: it says what
        each configured path turned out to be backed by.
        """
        import json

        from iops.execution.planner import IO_TARGETS_FILENAME_PREFIX

        # One path on a disk and one in RAM, so the file has to record both a
        # countable and an uncountable resolution.
        on_disk = tmp_path / "ondisk"
        in_ram = tmp_path / "inram"
        on_disk.mkdir()
        in_ram.mkdir()
        sysclass = _fake_sysclass(tmp_path)
        path_env = _fake_df(tmp_path, {
            str(on_disk): ("/dev/nvme0n1p1", "ext4"),
            str(in_ram): ("tmpfs", "tmpfs"),
        })

        sampler = _render_sampler(tmp_path, io_paths=f"'{on_disk}' '{in_ram}'")
        driver = tmp_path / "targets.sh"
        driver.write_text(f'''#!/bin/bash
export IOPS_IO_DISKSTATS="{tmp_path}/absent"
export IOPS_IO_MOUNTSTATS="{tmp_path}/absent"
export IOPS_IO_SYSCLASSBLOCK="{sysclass}"
{path_env}source "{sampler}"
_iops_io_resolve_targets
''')
        subprocess.run(["bash", str(driver)], capture_output=True, timeout=30)

        files = list(tmp_path.glob(f"{IO_TARGETS_FILENAME_PREFIX}*.json"))
        assert files, "the sampler must record what its paths resolved to"

        data = json.loads(files[0].read_text())
        by_path = {entry["path"]: entry for entry in data["paths"]}
        assert set(by_path) == {str(on_disk), str(in_ram)}
        assert by_path[str(on_disk)]["kind"] == "block"
        assert by_path[str(in_ram)]["kind"] == "none"


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

    @requires_bash_assoc_arrays
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
            "timestamp,hostname,source,device,path,interval_s,read_bytes,write_bytes,read_ops,write_ops"
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
        config = self._load(sample_config_dict, tmp_path, probes={"io_sampling": True, "io_paths": ["/tmp"]})
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
            probes={"io_sampling": True, "io_paths": ["/tmp"], "resource_sampling": False},
            submit="sbatch", script_template="#!/bin/sh\necho hello\n",
        )
        assert config.benchmark.probes.io_sampling is True

        check_resource_sampler_compatibility(config, logger=None)
        assert config.benchmark.probes.io_sampling is False

    def test_io_sampling_kept_for_bash_script(self, sample_config_dict, tmp_path):
        from iops.config.loader import check_resource_sampler_compatibility

        config = self._load(
            sample_config_dict, tmp_path,
            probes={"io_sampling": True, "io_paths": ["/tmp"]},
            script_template="#!/bin/bash\necho hello\n",
        )
        check_resource_sampler_compatibility(config, logger=None)
        assert config.benchmark.probes.io_sampling is True

    def test_io_sampling_requires_io_paths(self, sample_config_dict, tmp_path):
        """
        Without paths the probe would count every disk and mount on the node,
        including storage the benchmark never touches, so the numbers would not
        describe the run. Better to refuse than to report something misleading.
        """
        from iops.config.loader import ConfigValidationError

        with pytest.raises(ConfigValidationError, match="requires benchmark.probes.io_paths"):
            self._load(sample_config_dict, tmp_path, probes={"io_sampling": True})

    def test_io_paths_accepted(self, sample_config_dict, tmp_path):
        config = self._load(
            sample_config_dict, tmp_path,
            probes={"io_sampling": True, "io_paths": ["/scratch", "{{ execution_dir }}"]},
        )
        assert config.benchmark.probes.io_paths == ["/scratch", "{{ execution_dir }}"]

    def test_io_paths_rejects_empty_list(self, sample_config_dict, tmp_path):
        """An empty list is the same as not naming any path."""
        from iops.config.loader import ConfigValidationError

        with pytest.raises(ConfigValidationError, match="requires benchmark.probes.io_paths"):
            self._load(
                sample_config_dict, tmp_path,
                probes={"io_sampling": True, "io_paths": []},
            )

    def test_io_paths_rejects_non_list(self, sample_config_dict, tmp_path):
        from iops.config.loader import ConfigValidationError

        with pytest.raises(ConfigValidationError, match="non-empty list"):
            self._load(
                sample_config_dict, tmp_path,
                probes={"io_sampling": True, "io_paths": "/scratch"},
            )

    def test_io_paths_rejects_blank_entry(self, sample_config_dict, tmp_path):
        from iops.config.loader import ConfigValidationError

        with pytest.raises(ConfigValidationError, match="non-empty strings"):
            self._load(
                sample_config_dict, tmp_path,
                probes={"io_sampling": True, "io_paths": ["/scratch", "  "]},
            )

    def test_io_paths_requires_io_sampling(self, sample_config_dict, tmp_path):
        """Paths with the probe off would silently do nothing."""
        from iops.config.loader import ConfigValidationError

        with pytest.raises(ConfigValidationError, match="requires benchmark.probes.io_sampling"):
            self._load(
                sample_config_dict, tmp_path,
                probes={"io_sampling": False, "io_paths": ["/scratch"]},
            )


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
            sample_config_dict, tmp_path, {"io_sampling": True, "io_paths": ["/tmp"], "system_snapshot": False}
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

    def test_io_paths_are_rendered_per_execution(self, sample_config_dict, tmp_path):
        """
        Paths are Jinja templates so they can name a directory the execution
        creates. Writing the raw template into the script would leave the
        sampler resolving a literal "{{ execution_dir }}".
        """
        from iops.execution.planner import RUNTIME_IO_SAMPLER_FILENAME

        planner = self._planner(
            sample_config_dict, tmp_path,
            {
                "io_sampling": True,
                "system_snapshot": False,
                "io_paths": ["{{ execution_dir }}/scratch"],
            },
        )
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        test = planner.next_tests(1)[0]
        test.execution_dir = exec_dir
        planner._inject_iops_scripts("#!/bin/bash\necho hi", exec_dir, test)

        content = (exec_dir / RUNTIME_IO_SAMPLER_FILENAME).read_text()
        assert f"{exec_dir}/scratch" in content
        assert "{{ execution_dir }}" not in content

    def test_paths_with_spaces_are_quoted(self, sample_config_dict, tmp_path):
        """A path is dropped into a bash array, so it has to survive quoting."""
        from iops.execution.planner import RUNTIME_IO_SAMPLER_FILENAME

        planner = self._planner(
            sample_config_dict, tmp_path,
            {"io_sampling": True, "io_paths": ["/mnt/my data"], "system_snapshot": False},
        )
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        planner._inject_iops_scripts("#!/bin/bash\necho hi", exec_dir)

        content = (exec_dir / RUNTIME_IO_SAMPLER_FILENAME).read_text()
        assert "'/mnt/my data'" in content

    def test_configured_paths_reach_the_script(self, sample_config_dict, tmp_path):
        from iops.execution.planner import RUNTIME_IO_SAMPLER_FILENAME

        planner = self._planner(
            sample_config_dict, tmp_path,
            {"io_sampling": True, "io_paths": ["/scratch", "/data"], "system_snapshot": False},
        )
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir(parents=True)

        planner._inject_iops_scripts("#!/bin/bash\necho hi", exec_dir)

        content = (exec_dir / RUNTIME_IO_SAMPLER_FILENAME).read_text()
        assert "_IOPS_IO_PATHS=(/scratch /data)" in content

    def test_sampler_uses_config_interval(self, sample_config_dict, tmp_path):
        from iops.execution.planner import RUNTIME_IO_SAMPLER_FILENAME

        planner = self._planner(
            sample_config_dict, tmp_path,
            {"io_sampling": True, "io_paths": ["/tmp"], "sampling_interval": 2.5, "system_snapshot": False},
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
            "timestamp", "hostname", "source", "device", "path", "interval_s",
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
            [100.0, "node01", "block", "sda", "", 1.0, 100 * mib, 200 * mib, 10, 20],
            [100.0, "node01", "nfs", "srv:/exp", "", 1.0, 300 * mib, 400 * mib, 30, 40],
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
        _write_io_trace(trace, [[100.0, "node01", "block", "sda", "", 1.0, 1024, 2048, 1, 2]])

        metrics = self._metrics([trace])
        assert metrics["io_nfs_read_gb"] == 0.0
        assert metrics["io_nfs_write_gb"] == 0.0

    def test_throughput_uses_measured_intervals(self, tmp_path):
        mib = 1024 ** 2
        trace = tmp_path / "__iops_io_trace_node01_1.csv"
        # Two samples covering 2s in total, 300 MiB written
        _write_io_trace(trace, [
            [100.0, "node01", "block", "sda", "", 1.0, 0, 100 * mib, 0, 10],
            [101.0, "node01", "block", "sda", "", 1.0, 0, 200 * mib, 0, 20],
        ])

        metrics = self._metrics([trace])
        assert metrics["io_trace_duration_s"] == 2.0
        assert metrics["io_write_mbs_avg"] == pytest.approx(150.0, abs=0.1)
        # Peak is the busiest single sample, not the average
        assert metrics["io_write_mbs_peak_per_node"] == pytest.approx(200.0, abs=0.1)
        assert metrics["io_write_iops_avg"] == pytest.approx(15.0, abs=0.1)

    def test_idle_samples_dilute_the_average_but_not_the_active_rate(self, tmp_path):
        """
        Sampling covers the whole script, most of which is usually not I/O.
        The window average answers "per second of runtime", the active average
        answers "how fast was the storage while in use". Totals and peaks are
        unaffected by idle samples either way.
        """
        mib = 1024 ** 2
        trace = tmp_path / "__iops_io_trace_node01_1.csv"
        # 200 MiB written in the first of four one-second samples
        _write_io_trace(trace, [
            [100.0, "node01", "block", "sda", "", 1.0, 0, 200 * mib, 0, 10],
            [101.0, "node01", "block", "sda", "", 1.0, 0, 0, 0, 0],
            [102.0, "node01", "block", "sda", "", 1.0, 0, 0, 0, 0],
            [103.0, "node01", "block", "sda", "", 1.0, 0, 0, 0, 0],
        ])

        metrics = self._metrics([trace])
        assert metrics["io_trace_duration_s"] == 4.0
        assert metrics["io_write_active_s"] == 1.0
        # Diluted four ways by the idle samples
        assert metrics["io_write_mbs_avg"] == pytest.approx(50.0, abs=0.1)
        # The rate while the storage was actually working
        assert metrics["io_write_mbs_active"] == pytest.approx(200.0, abs=0.1)
        # Totals and peaks do not care about idle samples
        assert metrics["io_write_gb"] == pytest.approx(200 / 1024, abs=1e-3)
        assert metrics["io_write_mbs_peak_per_node"] == pytest.approx(200.0, abs=0.1)

    def test_active_seconds_are_zero_when_nothing_moved(self, tmp_path):
        trace = tmp_path / "__iops_io_trace_node01_1.csv"
        _write_io_trace(trace, [[100.0, "node01", "block", "sda", "", 1.0, 0, 0, 0, 0]])

        metrics = self._metrics([trace])
        assert metrics["io_write_active_s"] == 0.0
        assert metrics["io_write_mbs_active"] == 0.0

    def test_devices_in_the_same_sample_are_summed(self, tmp_path):
        mib = 1024 ** 2
        trace = tmp_path / "__iops_io_trace_node01_1.csv"
        _write_io_trace(trace, [
            [100.0, "node01", "block", "sda", "", 1.0, 0, 100 * mib, 0, 0],
            [100.0, "node01", "block", "nvme0n1", "", 1.0, 0, 100 * mib, 0, 0],
        ])

        metrics = self._metrics([trace])
        # One sampling instant, so the interval is counted once, not per device
        assert metrics["io_trace_duration_s"] == 1.0
        assert metrics["io_write_mbs_peak_per_node"] == pytest.approx(200.0, abs=0.1)

    def test_multiple_nodes_are_combined(self, tmp_path):
        mib = 1024 ** 2
        trace_a = tmp_path / "__iops_io_trace_node01_1.csv"
        trace_b = tmp_path / "__iops_io_trace_node02_1.csv"
        _write_io_trace(trace_a, [[100.0, "node01", "block", "sda", "", 1.0, 0, 100 * mib, 0, 0]])
        _write_io_trace(trace_b, [[100.0, "node02", "block", "sda", "", 1.0, 0, 300 * mib, 0, 0]])

        metrics = self._metrics([trace_a, trace_b])
        assert metrics["io_nodes_traced"] == 2
        # Aggregate throughput sums the nodes, the peak stays per node
        assert metrics["io_write_mbs_avg"] == pytest.approx(400.0, abs=0.1)
        assert metrics["io_write_mbs_peak_per_node"] == pytest.approx(300.0, abs=0.1)

    def test_zero_interval_rows_are_skipped(self, tmp_path):
        """A row with no measurable elapsed time yields no rate."""
        trace = tmp_path / "__iops_io_trace_node01_1.csv"
        _write_io_trace(trace, [[100.0, "node01", "block", "sda", "", 0.0, 1024, 1024, 1, 1]])

        metrics = self._metrics([trace])
        assert metrics["io_samples_collected"] == 0

    def test_malformed_rows_are_skipped(self, tmp_path):
        mib = 1024 ** 2
        trace = tmp_path / "__iops_io_trace_node01_1.csv"
        _write_io_trace(trace, [
            [100.0, "node01", "block", "sda", "", 1.0, "garbage", 0, 0, 0],
            [101.0, "node01", "block", "sda", "", 1.0, 0, 100 * mib, 0, 0],
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
        populated = [[100.0, "node01", "block", "sda", "", 1.0, 0, 512 * 1024 ** 2, 0, 1]]
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
