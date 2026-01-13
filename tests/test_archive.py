"""Tests for IOPS archive functionality."""

import json
import tarfile
import pytest
from pathlib import Path

from iops.archive import create_archive, extract_archive, ArchiveWriter, ArchiveReader
from iops.archive.manifest import ArchiveManifest, RunInfo


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_run_dir(tmp_path):
    """Create a sample IOPS run directory structure."""
    run_dir = tmp_path / "run_001"
    run_dir.mkdir()

    # Create __iops_index.json
    index_data = {
        "benchmark": "Test Benchmark",
        "total_expected": 2,
        "repetitions": 1,
        "executions": {
            "exec_0001": {
                "path": "exec_0001",
                "params": {"nodes": 1, "ppn": 4},
                "command": "echo test",
            },
            "exec_0002": {
                "path": "exec_0002",
                "params": {"nodes": 2, "ppn": 4},
                "command": "echo test2",
            },
        },
    }
    with open(run_dir / "__iops_index.json", "w") as f:
        json.dump(index_data, f)

    # Create __iops_run_metadata.json
    metadata = {
        "benchmark": {
            "name": "Test Benchmark",
            "description": "A test benchmark",
        },
        "iops_version": "3.0.0",
    }
    with open(run_dir / "__iops_run_metadata.json", "w") as f:
        json.dump(metadata, f)

    # Create execution directories
    for exec_id in ["exec_0001", "exec_0002"]:
        exec_dir = run_dir / exec_id
        exec_dir.mkdir()

        # Create __iops_params.json
        params = {"nodes": 1 if exec_id == "exec_0001" else 2, "ppn": 4}
        with open(exec_dir / "__iops_params.json", "w") as f:
            json.dump(params, f)

        # Create __iops_status.json
        status = {"status": "SUCCEEDED"}
        with open(exec_dir / "__iops_status.json", "w") as f:
            json.dump(status, f)

        # Create some output files
        with open(exec_dir / "output.txt", "w") as f:
            f.write("result: 100\n")

    return run_dir


@pytest.fixture
def sample_workdir(tmp_path, sample_run_dir):
    """Create a sample IOPS workdir with multiple runs."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    # Move the sample run into the workdir
    import shutil
    shutil.move(str(sample_run_dir), str(workdir / "run_001"))

    # Create a second run
    run2_dir = workdir / "run_002"
    run2_dir.mkdir()

    index_data = {
        "benchmark": "Another Benchmark",
        "total_expected": 1,
        "repetitions": 1,
        "executions": {
            "exec_0001": {
                "path": "exec_0001",
                "params": {"size": 1024},
                "command": "echo size test",
            },
        },
    }
    with open(run2_dir / "__iops_index.json", "w") as f:
        json.dump(index_data, f)

    exec_dir = run2_dir / "exec_0001"
    exec_dir.mkdir()
    with open(exec_dir / "__iops_params.json", "w") as f:
        json.dump({"size": 1024}, f)

    return workdir


# ============================================================================
# Manifest Tests
# ============================================================================


class TestRunInfo:
    """Tests for RunInfo dataclass."""

    def test_to_dict(self):
        """Test RunInfo serialization to dict."""
        run_info = RunInfo(
            name="run_001",
            benchmark_name="Test Benchmark",
            execution_count=5,
            path="run_001",
        )

        d = run_info.to_dict()

        assert d["name"] == "run_001"
        assert d["benchmark_name"] == "Test Benchmark"
        assert d["execution_count"] == 5
        assert d["path"] == "run_001"

    def test_from_dict(self):
        """Test RunInfo deserialization from dict."""
        data = {
            "name": "run_001",
            "benchmark_name": "Test Benchmark",
            "execution_count": 5,
            "path": "run_001",
        }

        run_info = RunInfo.from_dict(data)

        assert run_info.name == "run_001"
        assert run_info.benchmark_name == "Test Benchmark"
        assert run_info.execution_count == 5
        assert run_info.path == "run_001"


class TestArchiveManifest:
    """Tests for ArchiveManifest dataclass."""

    def test_to_dict(self):
        """Test ArchiveManifest serialization."""
        manifest = ArchiveManifest(
            iops_version="3.0.0",
            created_at="2024-01-15T10:30:00",
            source_hostname="testhost",
            archive_type="run",
            original_path="/path/to/run",
            runs=[RunInfo("run_001", "Test", 5, ".")],
            checksums={"__iops_index.json": "abc123"},
        )

        d = manifest.to_dict()

        assert d["iops_version"] == "3.0.0"
        assert d["archive_type"] == "run"
        assert len(d["runs"]) == 1
        assert d["checksums"]["__iops_index.json"] == "abc123"

    def test_from_dict(self):
        """Test ArchiveManifest deserialization."""
        data = {
            "iops_version": "3.0.0",
            "created_at": "2024-01-15T10:30:00",
            "source_hostname": "testhost",
            "archive_type": "run",
            "original_path": "/path/to/run",
            "runs": [{"name": "run_001", "benchmark_name": "Test", "execution_count": 5, "path": "."}],
            "checksums": {"__iops_index.json": "abc123"},
        }

        manifest = ArchiveManifest.from_dict(data)

        assert manifest.iops_version == "3.0.0"
        assert manifest.archive_type == "run"
        assert len(manifest.runs) == 1
        assert manifest.runs[0].name == "run_001"

    def test_validate_valid(self):
        """Test validation of a valid manifest."""
        manifest = ArchiveManifest(
            iops_version="3.0.0",
            created_at="2024-01-15T10:30:00",
            source_hostname="testhost",
            archive_type="run",
            original_path="/path/to/run",
            runs=[RunInfo("run_001", "Test", 5, ".")],
        )

        errors = manifest.validate()
        assert errors == []

    def test_validate_invalid_archive_type(self):
        """Test validation catches invalid archive type."""
        manifest = ArchiveManifest(
            iops_version="3.0.0",
            created_at="2024-01-15T10:30:00",
            source_hostname="testhost",
            archive_type="invalid",
            original_path="/path/to/run",
            runs=[RunInfo("run_001", "Test", 5, ".")],
        )

        errors = manifest.validate()
        assert any("archive_type" in e for e in errors)

    def test_validate_no_runs(self):
        """Test validation catches missing runs."""
        manifest = ArchiveManifest(
            iops_version="3.0.0",
            created_at="2024-01-15T10:30:00",
            source_hostname="testhost",
            archive_type="run",
            original_path="/path/to/run",
            runs=[],
        )

        errors = manifest.validate()
        assert any("No runs" in e for e in errors)

    def test_total_executions(self):
        """Test total_executions property."""
        manifest = ArchiveManifest(
            iops_version="3.0.0",
            created_at="2024-01-15T10:30:00",
            source_hostname="testhost",
            archive_type="workdir",
            original_path="/path",
            runs=[
                RunInfo("run_001", "Test1", 5, "run_001"),
                RunInfo("run_002", "Test2", 3, "run_002"),
            ],
        )

        assert manifest.total_executions == 8

    def test_run_names(self):
        """Test run_names property."""
        manifest = ArchiveManifest(
            iops_version="3.0.0",
            created_at="2024-01-15T10:30:00",
            source_hostname="testhost",
            archive_type="workdir",
            original_path="/path",
            runs=[
                RunInfo("run_001", "Test1", 5, "run_001"),
                RunInfo("run_002", "Test2", 3, "run_002"),
            ],
        )

        assert manifest.run_names == ["run_001", "run_002"]


# ============================================================================
# ArchiveWriter Tests
# ============================================================================


class TestArchiveWriter:
    """Tests for ArchiveWriter class."""

    def test_detect_type_run(self, sample_run_dir):
        """Test detection of run directory."""
        writer = ArchiveWriter(sample_run_dir)
        assert writer.archive_type == "run"

    def test_detect_type_workdir(self, sample_workdir):
        """Test detection of workdir with multiple runs."""
        writer = ArchiveWriter(sample_workdir)
        assert writer.archive_type == "workdir"

    def test_detect_type_invalid(self, tmp_path):
        """Test detection fails for invalid directory."""
        invalid_dir = tmp_path / "invalid"
        invalid_dir.mkdir()

        with pytest.raises(ValueError, match="not a valid IOPS directory"):
            ArchiveWriter(invalid_dir)

    def test_source_not_found(self, tmp_path):
        """Test error when source doesn't exist."""
        with pytest.raises(FileNotFoundError):
            ArchiveWriter(tmp_path / "nonexistent")

    def test_source_not_directory(self, tmp_path):
        """Test error when source is a file."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")

        with pytest.raises(ValueError, match="not a directory"):
            ArchiveWriter(file_path)

    def test_write_run_archive(self, sample_run_dir, tmp_path):
        """Test creating archive from a run directory."""
        output_path = tmp_path / "test.tar.gz"

        writer = ArchiveWriter(sample_run_dir)
        result = writer.write(output_path)

        assert result.exists()
        assert tarfile.is_tarfile(result)

        # Verify archive contents
        with tarfile.open(result, "r:gz") as tar:
            names = tar.getnames()
            assert "__iops_archive_manifest.json" in names
            assert "__iops_index.json" in names
            assert "__iops_run_metadata.json" in names
            assert "exec_0001/__iops_params.json" in names

    def test_write_workdir_archive(self, sample_workdir, tmp_path):
        """Test creating archive from a workdir."""
        output_path = tmp_path / "workdir.tar.gz"

        writer = ArchiveWriter(sample_workdir)
        result = writer.write(output_path)

        assert result.exists()

        # Verify archive contents
        with tarfile.open(result, "r:gz") as tar:
            names = tar.getnames()
            assert "__iops_archive_manifest.json" in names
            assert "run_001/__iops_index.json" in names
            assert "run_002/__iops_index.json" in names

    def test_write_different_compressions(self, sample_run_dir, tmp_path):
        """Test different compression formats."""
        writer = ArchiveWriter(sample_run_dir)

        # Test gz
        gz_path = writer.write(tmp_path / "test", "gz")
        assert gz_path.suffix == ".gz"
        assert tarfile.is_tarfile(gz_path)

        # Test bz2
        bz2_path = writer.write(tmp_path / "test", "bz2")
        assert str(bz2_path).endswith(".tar.bz2")
        assert tarfile.is_tarfile(bz2_path)

        # Test xz
        xz_path = writer.write(tmp_path / "test", "xz")
        assert str(xz_path).endswith(".tar.xz")
        assert tarfile.is_tarfile(xz_path)

        # Test none (uncompressed)
        tar_path = writer.write(tmp_path / "test", "none")
        assert tar_path.suffix == ".tar"
        assert tarfile.is_tarfile(tar_path)

    def test_write_invalid_compression(self, sample_run_dir, tmp_path):
        """Test error for invalid compression type."""
        writer = ArchiveWriter(sample_run_dir)

        with pytest.raises(ValueError, match="Invalid compression type"):
            writer.write(tmp_path / "test.tar.gz", "invalid")

    def test_manifest_contains_checksums(self, sample_run_dir, tmp_path):
        """Test that manifest includes checksums for critical files."""
        output_path = tmp_path / "test.tar.gz"

        writer = ArchiveWriter(sample_run_dir)
        writer.write(output_path)

        # Read manifest from archive
        with tarfile.open(output_path, "r:gz") as tar:
            manifest_file = tar.extractfile("__iops_archive_manifest.json")
            manifest_data = json.load(manifest_file)

        assert "checksums" in manifest_data
        assert "__iops_index.json" in manifest_data["checksums"]


# ============================================================================
# ArchiveReader Tests
# ============================================================================


class TestArchiveReader:
    """Tests for ArchiveReader class."""

    def test_archive_not_found(self, tmp_path):
        """Test error when archive doesn't exist."""
        with pytest.raises(FileNotFoundError):
            ArchiveReader(tmp_path / "nonexistent.tar.gz")

    def test_invalid_archive(self, tmp_path):
        """Test error for invalid tar file."""
        invalid_file = tmp_path / "invalid.tar.gz"
        invalid_file.write_text("not a tar file")

        with pytest.raises(ValueError, match="Not a valid tar archive"):
            ArchiveReader(invalid_file)

    def test_get_manifest(self, sample_run_dir, tmp_path):
        """Test reading manifest without full extraction."""
        archive_path = tmp_path / "test.tar.gz"
        create_archive(sample_run_dir, archive_path)

        reader = ArchiveReader(archive_path)
        manifest = reader.get_manifest()

        assert manifest is not None
        assert manifest.archive_type == "run"
        assert len(manifest.runs) == 1
        assert manifest.runs[0].benchmark_name == "Test Benchmark"

    def test_extract(self, sample_run_dir, tmp_path):
        """Test extracting archive."""
        archive_path = tmp_path / "test.tar.gz"
        create_archive(sample_run_dir, archive_path)

        extract_dir = tmp_path / "extracted"
        reader = ArchiveReader(archive_path)
        result = reader.extract(extract_dir)

        assert result == extract_dir
        assert (extract_dir / "__iops_index.json").exists()
        assert (extract_dir / "__iops_run_metadata.json").exists()
        assert (extract_dir / "exec_0001" / "__iops_params.json").exists()

    def test_extract_with_verification(self, sample_run_dir, tmp_path):
        """Test extraction with integrity verification."""
        archive_path = tmp_path / "test.tar.gz"
        create_archive(sample_run_dir, archive_path)

        extract_dir = tmp_path / "extracted"
        reader = ArchiveReader(archive_path)
        result = reader.extract(extract_dir, verify=True)

        assert result == extract_dir

    def test_extract_without_verification(self, sample_run_dir, tmp_path):
        """Test extraction without verification."""
        archive_path = tmp_path / "test.tar.gz"
        create_archive(sample_run_dir, archive_path)

        extract_dir = tmp_path / "extracted"
        reader = ArchiveReader(archive_path)
        result = reader.extract(extract_dir, verify=False)

        assert result == extract_dir

    def test_validate_integrity_valid(self, sample_run_dir, tmp_path):
        """Test integrity validation passes for valid archive."""
        archive_path = tmp_path / "test.tar.gz"
        create_archive(sample_run_dir, archive_path)

        reader = ArchiveReader(archive_path)
        errors = reader.validate_integrity()

        assert errors == []

    def test_validate_integrity_from_archive(self, sample_run_dir, tmp_path):
        """Test integrity validation directly from archive (without extraction)."""
        archive_path = tmp_path / "test.tar.gz"
        create_archive(sample_run_dir, archive_path)

        reader = ArchiveReader(archive_path)
        # Validate without extraction (extracted_path=None)
        errors = reader.validate_integrity(extracted_path=None)

        assert errors == []


# ============================================================================
# Convenience Function Tests
# ============================================================================


class TestConvenienceFunctions:
    """Tests for the public convenience functions."""

    def test_create_archive(self, sample_run_dir, tmp_path):
        """Test create_archive convenience function."""
        output_path = tmp_path / "test.tar.gz"
        result = create_archive(sample_run_dir, output_path)

        assert result.exists()
        assert tarfile.is_tarfile(result)

    def test_extract_archive(self, sample_run_dir, tmp_path):
        """Test extract_archive convenience function."""
        archive_path = tmp_path / "test.tar.gz"
        create_archive(sample_run_dir, archive_path)

        extract_dir = tmp_path / "extracted"
        result = extract_archive(archive_path, extract_dir)

        assert result == extract_dir
        assert (extract_dir / "__iops_index.json").exists()

    def test_round_trip(self, sample_run_dir, tmp_path):
        """Test complete round-trip: archive then extract."""
        archive_path = tmp_path / "test.tar.gz"
        create_archive(sample_run_dir, archive_path)

        extract_dir = tmp_path / "extracted"
        extract_archive(archive_path, extract_dir)

        # Verify key files match
        original_index = json.loads((sample_run_dir / "__iops_index.json").read_text())
        extracted_index = json.loads((extract_dir / "__iops_index.json").read_text())

        assert original_index == extracted_index

    def test_workdir_round_trip(self, sample_workdir, tmp_path):
        """Test round-trip for workdir with multiple runs."""
        archive_path = tmp_path / "workdir.tar.gz"
        create_archive(sample_workdir, archive_path)

        extract_dir = tmp_path / "extracted"
        extract_archive(archive_path, extract_dir)

        # Verify both runs exist
        assert (extract_dir / "run_001" / "__iops_index.json").exists()
        assert (extract_dir / "run_002" / "__iops_index.json").exists()


# ============================================================================
# Archive Inspection Tests
# ============================================================================


class TestArchiveInspection:
    """Tests for archive inspection methods (reading without extraction)."""

    def test_get_index_run(self, sample_run_dir, tmp_path):
        """Test reading index from a run archive."""
        archive_path = tmp_path / "test.tar.gz"
        create_archive(sample_run_dir, archive_path)

        reader = ArchiveReader(archive_path)
        index = reader.get_index()

        assert index is not None
        assert index["benchmark"] == "Test Benchmark"
        assert "exec_0001" in index["executions"]
        assert "exec_0002" in index["executions"]

    def test_get_index_workdir(self, sample_workdir, tmp_path):
        """Test reading index from a workdir archive."""
        archive_path = tmp_path / "workdir.tar.gz"
        create_archive(sample_workdir, archive_path)

        reader = ArchiveReader(archive_path)

        # Read run_001 index
        index1 = reader.get_index("run_001")
        assert index1 is not None
        assert index1["benchmark"] == "Test Benchmark"

        # Read run_002 index
        index2 = reader.get_index("run_002")
        assert index2 is not None
        assert index2["benchmark"] == "Another Benchmark"

    def test_get_run_metadata(self, sample_run_dir, tmp_path):
        """Test reading run metadata from archive."""
        archive_path = tmp_path / "test.tar.gz"
        create_archive(sample_run_dir, archive_path)

        reader = ArchiveReader(archive_path)
        metadata = reader.get_run_metadata()

        assert metadata is not None
        assert metadata["benchmark"]["name"] == "Test Benchmark"
        assert metadata["benchmark"]["description"] == "A test benchmark"

    def test_get_execution_status(self, sample_run_dir, tmp_path):
        """Test reading execution status from archive."""
        archive_path = tmp_path / "test.tar.gz"
        create_archive(sample_run_dir, archive_path)

        reader = ArchiveReader(archive_path)

        # Both executions should be SUCCEEDED
        status1 = reader.get_execution_status(".", "exec_0001")
        assert status1["status"] == "SUCCEEDED"

        status2 = reader.get_execution_status(".", "exec_0002")
        assert status2["status"] == "SUCCEEDED"

    def test_get_execution_status_mixed(self, tmp_path):
        """Test reading execution status with different statuses."""
        # Create a run with different statuses
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        # Create index
        index = {
            "benchmark": "Test",
            "executions": {
                "exec_0001": {"path": "exec_0001", "params": {"n": 1}},
                "exec_0002": {"path": "exec_0002", "params": {"n": 2}},
                "exec_0003": {"path": "exec_0003", "params": {"n": 3}},
            }
        }
        (run_dir / "__iops_index.json").write_text(json.dumps(index))

        # Create executions with different statuses
        exec1 = run_dir / "exec_0001"
        exec1.mkdir()
        (exec1 / "__iops_params.json").write_text(json.dumps({"n": 1}))
        (exec1 / "__iops_status.json").write_text(json.dumps({"status": "SUCCEEDED"}))

        exec2 = run_dir / "exec_0002"
        exec2.mkdir()
        (exec2 / "__iops_params.json").write_text(json.dumps({"n": 2}))
        (exec2 / "__iops_status.json").write_text(json.dumps({"status": "FAILED", "error": "test error"}))

        exec3 = run_dir / "exec_0003"
        exec3.mkdir()
        (exec3 / "__iops_params.json").write_text(json.dumps({"n": 3}))
        (exec3 / "__iops_status.json").write_text(json.dumps({"status": "SKIPPED", "reason": "constraint"}))

        # Create archive
        archive_path = tmp_path / "test.tar.gz"
        create_archive(run_dir, archive_path)

        reader = ArchiveReader(archive_path)

        # Check each status
        status1 = reader.get_execution_status(".", "exec_0001")
        assert status1["status"] == "SUCCEEDED"

        status2 = reader.get_execution_status(".", "exec_0002")
        assert status2["status"] == "FAILED"
        assert status2["error"] == "test error"

        status3 = reader.get_execution_status(".", "exec_0003")
        assert status3["status"] == "SKIPPED"
        assert status3["reason"] == "constraint"

    def test_list_executions(self, sample_run_dir, tmp_path):
        """Test listing executions from archive."""
        archive_path = tmp_path / "test.tar.gz"
        create_archive(sample_run_dir, archive_path)

        reader = ArchiveReader(archive_path)
        executions = reader.list_executions()

        assert len(executions) == 2
        exec_ids = {e["exec_id"] for e in executions}
        assert exec_ids == {"exec_0001", "exec_0002"}

    def test_list_executions_with_filter(self, sample_run_dir, tmp_path):
        """Test listing executions with parameter filter."""
        archive_path = tmp_path / "test.tar.gz"
        create_archive(sample_run_dir, archive_path)

        reader = ArchiveReader(archive_path)
        executions = reader.list_executions(filters={"nodes": "1"})

        assert len(executions) == 1
        assert executions[0]["params"]["nodes"] == 1

    def test_list_executions_with_status_filter(self, tmp_path):
        """Test listing executions filtered by status."""
        # Create a run with different statuses
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        index = {
            "benchmark": "Test",
            "executions": {
                "exec_0001": {"path": "exec_0001", "params": {"n": 1}},
                "exec_0002": {"path": "exec_0002", "params": {"n": 2}},
            }
        }
        (run_dir / "__iops_index.json").write_text(json.dumps(index))

        exec1 = run_dir / "exec_0001"
        exec1.mkdir()
        (exec1 / "__iops_params.json").write_text(json.dumps({"n": 1}))
        (exec1 / "__iops_status.json").write_text(json.dumps({"status": "SUCCEEDED"}))

        exec2 = run_dir / "exec_0002"
        exec2.mkdir()
        (exec2 / "__iops_params.json").write_text(json.dumps({"n": 2}))
        (exec2 / "__iops_status.json").write_text(json.dumps({"status": "FAILED"}))

        archive_path = tmp_path / "test.tar.gz"
        create_archive(run_dir, archive_path)

        reader = ArchiveReader(archive_path)

        # Filter by SUCCEEDED
        succeeded = reader.list_executions(status_filter="SUCCEEDED")
        assert len(succeeded) == 1
        assert succeeded[0]["exec_id"] == "exec_0001"

        # Filter by FAILED
        failed = reader.list_executions(status_filter="FAILED")
        assert len(failed) == 1
        assert failed[0]["exec_id"] == "exec_0002"

    def test_list_executions_workdir(self, sample_workdir, tmp_path):
        """Test listing executions from workdir archive."""
        archive_path = tmp_path / "workdir.tar.gz"
        create_archive(sample_workdir, archive_path)

        reader = ArchiveReader(archive_path)
        executions = reader.list_executions()

        # Should have 2 from run_001 and 1 from run_002
        assert len(executions) == 3

        # Check runs are identified
        runs = {e["run"] for e in executions}
        assert "run_001" in runs
        assert "run_002" in runs


# ============================================================================
# Find Command with Archive Tests
# ============================================================================


class TestFindWithArchive:
    """Tests for iops find command with tar archives."""

    def test_find_archive_basic(self, sample_run_dir, tmp_path, capsys):
        """Test basic find on an archive."""
        from iops.results.find import find_executions

        archive_path = tmp_path / "test.tar.gz"
        create_archive(sample_run_dir, archive_path)

        find_executions(archive_path)

        captured = capsys.readouterr()
        assert "Archive: test.tar.gz" in captured.out
        assert "Test Benchmark" in captured.out
        assert "exec_0001" in captured.out
        assert "exec_0002" in captured.out

    def test_find_archive_with_filter(self, sample_run_dir, tmp_path, capsys):
        """Test find on archive with parameter filter."""
        from iops.results.find import find_executions

        archive_path = tmp_path / "test.tar.gz"
        create_archive(sample_run_dir, archive_path)

        find_executions(archive_path, filters=["nodes=1"])

        captured = capsys.readouterr()
        assert "exec_0001" in captured.out
        assert "exec_0002" not in captured.out
        assert "Found 1 execution(s)" in captured.out

    def test_find_archive_with_status_filter(self, tmp_path, capsys):
        """Test find on archive with status filter."""
        from iops.results.find import find_executions

        # Create a run with different statuses
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        index = {
            "benchmark": "Test",
            "executions": {
                "exec_0001": {"path": "exec_0001", "params": {"n": 1}},
                "exec_0002": {"path": "exec_0002", "params": {"n": 2}},
            }
        }
        (run_dir / "__iops_index.json").write_text(json.dumps(index))

        exec1 = run_dir / "exec_0001"
        exec1.mkdir()
        (exec1 / "__iops_params.json").write_text(json.dumps({"n": 1}))
        (exec1 / "__iops_status.json").write_text(json.dumps({"status": "SUCCEEDED"}))

        exec2 = run_dir / "exec_0002"
        exec2.mkdir()
        (exec2 / "__iops_params.json").write_text(json.dumps({"n": 2}))
        (exec2 / "__iops_status.json").write_text(json.dumps({"status": "FAILED"}))

        archive_path = tmp_path / "test.tar.gz"
        create_archive(run_dir, archive_path)

        find_executions(archive_path, status_filter="FAILED")

        captured = capsys.readouterr()
        assert "exec_0002" in captured.out
        assert "FAILED" in captured.out
        assert "Found 1 execution(s)" in captured.out

    def test_find_archive_workdir(self, sample_workdir, tmp_path, capsys):
        """Test find on workdir archive shows multiple runs."""
        from iops.results.find import find_executions

        archive_path = tmp_path / "workdir.tar.gz"
        create_archive(sample_workdir, archive_path)

        find_executions(archive_path)

        captured = capsys.readouterr()
        assert "Archive: workdir.tar.gz" in captured.out
        assert "workdir" in captured.out  # archive type
        assert "run_001" in captured.out
        assert "run_002" in captured.out
        assert "Found 3 execution(s)" in captured.out

    def test_find_archive_no_manifest(self, tmp_path, capsys):
        """Test find on archive without IOPS manifest."""
        from iops.results.find import find_executions

        # Create a simple tar without manifest
        archive_path = tmp_path / "simple.tar.gz"
        import tarfile
        with tarfile.open(archive_path, "w:gz") as tar:
            # Add a dummy file
            import io
            info = tarfile.TarInfo(name="dummy.txt")
            info.size = 4
            tar.addfile(info, io.BytesIO(b"test"))

        find_executions(archive_path)

        captured = capsys.readouterr()
        assert "No IOPS manifest found" in captured.out

    def test_is_archive_detection(self, tmp_path):
        """Test archive detection utility."""
        from iops.results.find import _is_archive

        # Create valid tar archive
        archive_path = tmp_path / "test.tar.gz"
        import tarfile
        with tarfile.open(archive_path, "w:gz") as tar:
            import io
            info = tarfile.TarInfo(name="dummy.txt")
            info.size = 4
            tar.addfile(info, io.BytesIO(b"test"))

        assert _is_archive(archive_path) is True

        # Non-archive file
        text_file = tmp_path / "text.txt"
        text_file.write_text("not a tar")
        assert _is_archive(text_file) is False

        # Non-existent file
        assert _is_archive(tmp_path / "nonexistent.tar.gz") is False

        # Directory (not a file)
        assert _is_archive(tmp_path) is False
