"""Tests for IOPS partial archive functionality."""

import json
import tarfile
import pytest
from pathlib import Path

import pandas as pd

from iops.archive import create_archive, ArchiveWriter, ArchiveReader
from iops.archive.filter import (
    filter_executions,
    filter_result_file,
    create_filtered_index,
    get_result_file_paths,
    _count_completed_repetitions,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def run_with_mixed_status(tmp_path):
    """Create a run directory with executions in different statuses."""
    run_dir = tmp_path / "run_001"
    run_dir.mkdir()

    # Create index with 4 executions
    index_data = {
        "benchmark": "Test Benchmark",
        "total_expected": 4,
        "repetitions": 1,
        "executions": {
            "exec_0001": {
                "path": "exec_0001",
                "params": {"nodes": 1, "operation": "read"},
                "command": "echo test1",
            },
            "exec_0002": {
                "path": "exec_0002",
                "params": {"nodes": 2, "operation": "write"},
                "command": "echo test2",
            },
            "exec_0003": {
                "path": "exec_0003",
                "params": {"nodes": 1, "operation": "write"},
                "command": "echo test3",
            },
            "exec_0004": {
                "path": "exec_0004",
                "params": {"nodes": 2, "operation": "read"},
                "command": "echo test4",
            },
        },
    }
    with open(run_dir / "__iops_index.json", "w") as f:
        json.dump(index_data, f)

    # Create __iops_run_metadata.json
    metadata = {
        "benchmark": {"name": "Test Benchmark"},
        "iops_version": "3.0.0",
    }
    with open(run_dir / "__iops_run_metadata.json", "w") as f:
        json.dump(metadata, f)

    # Create execution directories with different statuses
    statuses = {
        "exec_0001": {"status": "SUCCEEDED", "cached": False},
        "exec_0002": {"status": "SUCCEEDED", "cached": True},
        "exec_0003": {"status": "FAILED", "cached": False, "error": "Timeout"},
        "exec_0004": {"status": "RUNNING", "cached": False},
    }

    for exec_id, status_data in statuses.items():
        exec_dir = run_dir / exec_id
        exec_dir.mkdir()

        # Create repetition folder with status
        rep_dir = exec_dir / "repetition_001"
        rep_dir.mkdir()

        with open(rep_dir / "__iops_status.json", "w") as f:
            json.dump(status_data, f)

        with open(exec_dir / "__iops_params.json", "w") as f:
            params = index_data["executions"][exec_id]["params"]
            json.dump(params, f)

        with open(exec_dir / "output.txt", "w") as f:
            f.write(f"output for {exec_id}\n")

    # Create a results CSV file
    results_data = {
        "execution.execution_id": [1, 2, 3, 4],
        "execution.repetition": [0, 0, 0, 0],
        "vars.nodes": [1, 2, 1, 2],
        "vars.operation": ["read", "write", "write", "read"],
        "metrics.throughput": [100.0, 200.0, None, None],
    }
    df = pd.DataFrame(results_data)
    df.to_csv(run_dir / "results.csv", index=False)

    return run_dir


@pytest.fixture
def workdir_with_mixed_status(tmp_path, run_with_mixed_status):
    """Create a workdir with a run containing mixed status executions."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    import shutil
    shutil.move(str(run_with_mixed_status), str(workdir / "run_001"))

    return workdir


@pytest.fixture
def run_with_multiple_reps(tmp_path):
    """Create a run directory with executions having multiple repetitions in various states."""
    run_dir = tmp_path / "run_multi_rep"
    run_dir.mkdir()

    # Create index with 3 executions, each with 3 repetitions
    index_data = {
        "benchmark": "Multi-Rep Test",
        "total_expected": 3,
        "repetitions": 3,
        "executions": {
            "exec_0001": {
                "path": "exec_0001",
                "params": {"nodes": 1},
                "command": "echo test1",
            },
            "exec_0002": {
                "path": "exec_0002",
                "params": {"nodes": 2},
                "command": "echo test2",
            },
            "exec_0003": {
                "path": "exec_0003",
                "params": {"nodes": 4},
                "command": "echo test3",
            },
        },
    }
    with open(run_dir / "__iops_index.json", "w") as f:
        json.dump(index_data, f)

    with open(run_dir / "__iops_run_metadata.json", "w") as f:
        json.dump({"benchmark": {"name": "Multi-Rep Test"}}, f)

    # exec_0001: 3/3 completed (all SUCCEEDED)
    exec_dir = run_dir / "exec_0001"
    exec_dir.mkdir()
    for i in range(1, 4):
        rep_dir = exec_dir / f"repetition_{i:03d}"
        rep_dir.mkdir()
        with open(rep_dir / "__iops_status.json", "w") as f:
            json.dump({"status": "SUCCEEDED"}, f)

    # exec_0002: 2/3 completed (2 SUCCEEDED, 1 RUNNING)
    exec_dir = run_dir / "exec_0002"
    exec_dir.mkdir()
    for i in range(1, 4):
        rep_dir = exec_dir / f"repetition_{i:03d}"
        rep_dir.mkdir()
        status = "SUCCEEDED" if i <= 2 else "RUNNING"
        with open(rep_dir / "__iops_status.json", "w") as f:
            json.dump({"status": status}, f)

    # exec_0003: 1/3 completed (1 SUCCEEDED, 2 PENDING - no status file)
    exec_dir = run_dir / "exec_0003"
    exec_dir.mkdir()
    for i in range(1, 4):
        rep_dir = exec_dir / f"repetition_{i:03d}"
        rep_dir.mkdir()
        if i == 1:
            with open(rep_dir / "__iops_status.json", "w") as f:
                json.dump({"status": "SUCCEEDED"}, f)

    # Create results CSV with rows for each completed repetition
    results_data = {
        "execution.execution_id": [1, 1, 1, 2, 2, 3],
        "execution.repetition": [0, 1, 2, 0, 1, 0],
        "vars.nodes": [1, 1, 1, 2, 2, 4],
        "metrics.throughput": [100, 110, 105, 200, 210, 400],
    }
    df = pd.DataFrame(results_data)
    df.to_csv(run_dir / "results.csv", index=False)

    return run_dir


# ============================================================================
# Filter Module Tests
# ============================================================================


class TestFilterExecutions:
    """Tests for filter_executions function."""

    def test_filter_by_status_succeeded(self, run_with_mixed_status):
        """Test filtering by SUCCEEDED status."""
        matching, total, reps_map = filter_executions(
            run_with_mixed_status,
            status_filter="SUCCEEDED",
        )

        assert total == 4
        assert len(matching) == 2
        assert "exec_0001" in matching
        assert "exec_0002" in matching

    def test_filter_by_status_failed(self, run_with_mixed_status):
        """Test filtering by FAILED status."""
        matching, total, reps_map = filter_executions(
            run_with_mixed_status,
            status_filter="FAILED",
        )

        assert total == 4
        assert len(matching) == 1
        assert "exec_0003" in matching

    def test_filter_by_cached_true(self, run_with_mixed_status):
        """Test filtering by cached=True."""
        matching, total, reps_map = filter_executions(
            run_with_mixed_status,
            cached_filter=True,
        )

        assert len(matching) == 1
        assert "exec_0002" in matching

    def test_filter_by_cached_false(self, run_with_mixed_status):
        """Test filtering by cached=False."""
        matching, total, reps_map = filter_executions(
            run_with_mixed_status,
            cached_filter=False,
        )

        assert len(matching) == 3
        assert "exec_0001" in matching
        assert "exec_0003" in matching
        assert "exec_0004" in matching

    def test_filter_by_params(self, run_with_mixed_status):
        """Test filtering by parameter values."""
        matching, total, reps_map = filter_executions(
            run_with_mixed_status,
            param_filters={"nodes": "1"},
        )

        assert len(matching) == 2
        assert "exec_0001" in matching
        assert "exec_0003" in matching

    def test_filter_by_multiple_params(self, run_with_mixed_status):
        """Test filtering by multiple parameters."""
        matching, total, reps_map = filter_executions(
            run_with_mixed_status,
            param_filters={"nodes": "1", "operation": "read"},
        )

        assert len(matching) == 1
        assert "exec_0001" in matching

    def test_filter_combined(self, run_with_mixed_status):
        """Test combining status and parameter filters."""
        matching, total, reps_map = filter_executions(
            run_with_mixed_status,
            status_filter="SUCCEEDED",
            param_filters={"nodes": "1"},
        )

        assert len(matching) == 1
        assert "exec_0001" in matching

    def test_filter_no_matches(self, run_with_mixed_status):
        """Test that empty result is returned when no matches."""
        matching, total, reps_map = filter_executions(
            run_with_mixed_status,
            status_filter="SKIPPED",
        )

        assert len(matching) == 0
        assert total == 4


class TestFilterResultFile:
    """Tests for filter_result_file function."""

    def test_filter_csv(self, run_with_mixed_status, tmp_path):
        """Test filtering a CSV result file."""
        source = run_with_mixed_status / "results.csv"
        output = tmp_path / "filtered.csv"

        result = filter_result_file(source, output, {1, 2})

        assert result is True
        assert output.exists()

        df = pd.read_csv(output)
        assert len(df) == 2
        assert set(df["execution.execution_id"]) == {1, 2}

    def test_filter_csv_empty_result(self, run_with_mixed_status, tmp_path):
        """Test filtering CSV with no matching rows."""
        source = run_with_mixed_status / "results.csv"
        output = tmp_path / "filtered.csv"

        result = filter_result_file(source, output, {999})

        assert result is False
        assert not output.exists()

    def test_filter_nonexistent_file(self, tmp_path):
        """Test filtering a file that doesn't exist."""
        source = tmp_path / "nonexistent.csv"
        output = tmp_path / "filtered.csv"

        result = filter_result_file(source, output, {1})

        assert result is False


class TestCreateFilteredIndex:
    """Tests for create_filtered_index function."""

    def test_filter_index(self):
        """Test creating a filtered index."""
        original = {
            "benchmark": "Test",
            "executions": {
                "exec_0001": {"path": "exec_0001", "params": {"a": 1}},
                "exec_0002": {"path": "exec_0002", "params": {"a": 2}},
                "exec_0003": {"path": "exec_0003", "params": {"a": 3}},
            },
        }

        filtered = create_filtered_index(original, {"exec_0001", "exec_0003"})

        assert filtered["benchmark"] == "Test"
        assert len(filtered["executions"]) == 2
        assert "exec_0001" in filtered["executions"]
        assert "exec_0003" in filtered["executions"]
        assert "exec_0002" not in filtered["executions"]


class TestGetResultFilePaths:
    """Tests for get_result_file_paths function."""

    def test_finds_csv(self, run_with_mixed_status):
        """Test finding CSV result files."""
        paths = get_result_file_paths(run_with_mixed_status)

        assert len(paths) == 1
        assert paths[0].name == "results.csv"

    def test_ignores_iops_files(self, tmp_path):
        """Test that __iops_ files are not included."""
        (tmp_path / "__iops_index.json").write_text("{}")
        (tmp_path / "results.csv").write_text("a,b\n1,2")

        paths = get_result_file_paths(tmp_path)

        assert len(paths) == 1
        assert paths[0].name == "results.csv"


# ============================================================================
# Partial Archive Tests
# ============================================================================


class TestPartialArchiveCreation:
    """Tests for creating partial archives."""

    def test_create_partial_archive_by_status(self, run_with_mixed_status, tmp_path):
        """Test creating a partial archive filtered by status."""
        output = tmp_path / "partial.tar.gz"

        archive_path = create_archive(
            run_with_mixed_status,
            output,
            partial=True,
            status_filter="SUCCEEDED",
        )

        assert archive_path.exists()

        # Verify archive contents
        reader = ArchiveReader(archive_path)
        manifest = reader.get_manifest()

        assert manifest.partial is True
        assert manifest.original_execution_count == 4
        assert manifest.total_executions == 2
        assert manifest.filters_applied == {"status": "SUCCEEDED"}

    def test_create_partial_archive_by_params(self, run_with_mixed_status, tmp_path):
        """Test creating a partial archive filtered by parameters."""
        output = tmp_path / "partial.tar.gz"

        archive_path = create_archive(
            run_with_mixed_status,
            output,
            partial=True,
            param_filters={"nodes": "1"},
        )

        assert archive_path.exists()

        reader = ArchiveReader(archive_path)
        manifest = reader.get_manifest()

        assert manifest.partial is True
        assert manifest.total_executions == 2
        assert "params" in manifest.filters_applied
        assert manifest.filters_applied["params"]["nodes"] == "1"

    def test_create_partial_archive_combined_filters(self, run_with_mixed_status, tmp_path):
        """Test creating a partial archive with combined filters."""
        output = tmp_path / "partial.tar.gz"

        archive_path = create_archive(
            run_with_mixed_status,
            output,
            partial=True,
            status_filter="SUCCEEDED",
            param_filters={"nodes": "1"},
        )

        assert archive_path.exists()

        reader = ArchiveReader(archive_path)
        manifest = reader.get_manifest()

        assert manifest.partial is True
        assert manifest.total_executions == 1

    def test_partial_archive_no_matches_raises(self, run_with_mixed_status, tmp_path):
        """Test that creating a partial archive with no matches raises error."""
        output = tmp_path / "partial.tar.gz"

        with pytest.raises(ValueError, match="No executions match"):
            create_archive(
                run_with_mixed_status,
                output,
                partial=True,
                status_filter="SKIPPED",
            )

    def test_partial_archive_contains_only_filtered_executions(
        self, run_with_mixed_status, tmp_path
    ):
        """Test that partial archive only contains filtered execution directories."""
        output = tmp_path / "partial.tar.gz"

        create_archive(
            run_with_mixed_status,
            output,
            partial=True,
            status_filter="SUCCEEDED",
        )

        # Extract and verify
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()

        with tarfile.open(output, "r:gz") as tar:
            tar.extractall(extract_dir, filter="data")

        # Check that only exec_0001 and exec_0002 directories exist
        exec_dirs = list(extract_dir.glob("exec_*"))
        exec_names = {d.name for d in exec_dirs}

        assert exec_names == {"exec_0001", "exec_0002"}

    def test_partial_archive_filtered_index(self, run_with_mixed_status, tmp_path):
        """Test that partial archive has filtered index file."""
        output = tmp_path / "partial.tar.gz"

        create_archive(
            run_with_mixed_status,
            output,
            partial=True,
            status_filter="SUCCEEDED",
        )

        # Read index from archive
        reader = ArchiveReader(output)
        index = reader.get_index(".")

        assert len(index["executions"]) == 2
        assert "exec_0001" in index["executions"]
        assert "exec_0002" in index["executions"]
        assert "exec_0003" not in index["executions"]
        assert "exec_0004" not in index["executions"]

    def test_partial_archive_filtered_results(self, run_with_mixed_status, tmp_path):
        """Test that partial archive has filtered results file."""
        output = tmp_path / "partial.tar.gz"

        create_archive(
            run_with_mixed_status,
            output,
            partial=True,
            status_filter="SUCCEEDED",
        )

        # Extract and check results file
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()

        with tarfile.open(output, "r:gz") as tar:
            tar.extractall(extract_dir, filter="data")

        results_file = extract_dir / "results.csv"
        assert results_file.exists()

        df = pd.read_csv(results_file)
        assert len(df) == 2
        assert set(df["execution.execution_id"]) == {1, 2}

    def test_full_archive_unchanged(self, run_with_mixed_status, tmp_path):
        """Test that non-partial archive works as before."""
        output = tmp_path / "full.tar.gz"

        archive_path = create_archive(
            run_with_mixed_status,
            output,
            partial=False,
        )

        reader = ArchiveReader(archive_path)
        manifest = reader.get_manifest()

        assert manifest.partial is False
        assert manifest.original_execution_count is None
        assert manifest.filters_applied is None
        assert manifest.total_executions == 4


class TestPartialArchiveWorkdir:
    """Tests for partial archives from workdirs."""

    def test_partial_archive_workdir(self, workdir_with_mixed_status, tmp_path):
        """Test creating partial archive from a workdir."""
        output = tmp_path / "partial.tar.gz"

        archive_path = create_archive(
            workdir_with_mixed_status,
            output,
            partial=True,
            status_filter="SUCCEEDED",
        )

        assert archive_path.exists()

        reader = ArchiveReader(archive_path)
        manifest = reader.get_manifest()

        assert manifest.partial is True
        assert manifest.archive_type == "workdir"


# ============================================================================
# Manifest Partial Fields Tests
# ============================================================================


class TestManifestPartialFields:
    """Tests for partial archive manifest fields."""

    def test_manifest_to_dict_partial(self):
        """Test that partial fields are included in to_dict for partial archives."""
        from iops.archive.manifest import ArchiveManifest, RunInfo

        manifest = ArchiveManifest(
            iops_version="3.0.0",
            created_at="2024-01-01T00:00:00",
            source_hostname="test",
            archive_type="run",
            original_path="/test",
            runs=[RunInfo("run_001", "Test", 2, ".")],
            checksums={},
            partial=True,
            original_execution_count=10,
            filters_applied={"status": "SUCCEEDED"},
        )

        d = manifest.to_dict()

        assert d["partial"] is True
        assert d["original_execution_count"] == 10
        assert d["filters_applied"] == {"status": "SUCCEEDED"}

    def test_manifest_to_dict_non_partial(self):
        """Test that partial fields are not included for non-partial archives."""
        from iops.archive.manifest import ArchiveManifest, RunInfo

        manifest = ArchiveManifest(
            iops_version="3.0.0",
            created_at="2024-01-01T00:00:00",
            source_hostname="test",
            archive_type="run",
            original_path="/test",
            runs=[RunInfo("run_001", "Test", 10, ".")],
            checksums={},
            partial=False,
        )

        d = manifest.to_dict()

        assert "partial" not in d
        assert "original_execution_count" not in d
        assert "filters_applied" not in d

    def test_manifest_from_dict_partial(self):
        """Test that partial fields are parsed from dict."""
        from iops.archive.manifest import ArchiveManifest

        data = {
            "iops_version": "3.0.0",
            "created_at": "2024-01-01T00:00:00",
            "source_hostname": "test",
            "archive_type": "run",
            "original_path": "/test",
            "runs": [{"name": "run_001", "benchmark_name": "Test", "execution_count": 2, "path": "."}],
            "checksums": {},
            "partial": True,
            "original_execution_count": 10,
            "filters_applied": {"status": "SUCCEEDED"},
        }

        manifest = ArchiveManifest.from_dict(data)

        assert manifest.partial is True
        assert manifest.original_execution_count == 10
        assert manifest.filters_applied == {"status": "SUCCEEDED"}


# ============================================================================
# Min Completed Reps Tests
# ============================================================================


class TestMinCompletedReps:
    """Tests for min_completed_reps filtering."""

    def test_filter_by_min_reps_one(self, run_with_multiple_reps):
        """Test filtering with min_completed_reps=1."""
        from iops.archive.filter import _count_completed_repetitions

        matching, total, reps_map = filter_executions(
            run_with_multiple_reps,
            min_completed_reps=1,
        )

        # All 3 executions have at least 1 completed rep
        assert len(matching) == 3
        assert "exec_0001" in matching
        assert "exec_0002" in matching
        assert "exec_0003" in matching

    def test_filter_by_min_reps_two(self, run_with_multiple_reps):
        """Test filtering with min_completed_reps=2."""
        matching, total, reps_map = filter_executions(
            run_with_multiple_reps,
            min_completed_reps=2,
        )

        # exec_0001 has 3, exec_0002 has 2, exec_0003 has 1
        assert len(matching) == 2
        assert "exec_0001" in matching
        assert "exec_0002" in matching
        assert "exec_0003" not in matching

    def test_filter_by_min_reps_three(self, run_with_multiple_reps):
        """Test filtering with min_completed_reps=3."""
        matching, total, reps_map = filter_executions(
            run_with_multiple_reps,
            min_completed_reps=3,
        )

        # Only exec_0001 has all 3 completed
        assert len(matching) == 1
        assert "exec_0001" in matching

    def test_reps_map_contains_completed_indices(self, run_with_multiple_reps):
        """Test that reps_map contains correct completed repetition indices."""
        matching, total, reps_map = filter_executions(
            run_with_multiple_reps,
            min_completed_reps=1,
        )

        # exec_0001: reps 0, 1, 2 completed
        assert reps_map["exec_0001"] == {0, 1, 2}
        # exec_0002: reps 0, 1 completed (rep 2 is RUNNING)
        assert reps_map["exec_0002"] == {0, 1}
        # exec_0003: only rep 0 completed
        assert reps_map["exec_0003"] == {0}


class TestMinRepsArchiveCreation:
    """Tests for creating archives with min_completed_reps."""

    def test_create_archive_min_reps(self, run_with_multiple_reps, tmp_path):
        """Test creating archive with min_completed_reps."""
        output = tmp_path / "partial.tar.gz"

        archive_path = create_archive(
            run_with_multiple_reps,
            output,
            partial=True,
            min_completed_reps=2,
        )

        assert archive_path.exists()

        reader = ArchiveReader(archive_path)
        manifest = reader.get_manifest()

        assert manifest.partial is True
        assert manifest.total_executions == 2  # exec_0001 and exec_0002
        assert manifest.filters_applied["min_completed_reps"] == 2

    def test_archive_filters_results_by_repetition(self, run_with_multiple_reps, tmp_path):
        """Test that result file is filtered by completed repetitions."""
        output = tmp_path / "partial.tar.gz"

        create_archive(
            run_with_multiple_reps,
            output,
            partial=True,
            min_completed_reps=2,
        )

        # Extract and check results
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()

        with tarfile.open(output, "r:gz") as tar:
            tar.extractall(extract_dir, filter="data")

        results_file = extract_dir / "results.csv"
        assert results_file.exists()

        df = pd.read_csv(results_file)

        # Should have:
        # - exec_0001 (id=1): reps 0, 1, 2 (3 rows)
        # - exec_0002 (id=2): reps 0, 1 (2 rows)
        # Total: 5 rows
        assert len(df) == 5
        assert set(df["execution.execution_id"]) == {1, 2}

        # Check exec_0001 has all 3 reps
        exec1_reps = set(df[df["execution.execution_id"] == 1]["execution.repetition"])
        assert exec1_reps == {0, 1, 2}

        # Check exec_0002 has only 2 completed reps
        exec2_reps = set(df[df["execution.execution_id"] == 2]["execution.repetition"])
        assert exec2_reps == {0, 1}

    def test_min_reps_implies_partial(self, run_with_multiple_reps, tmp_path):
        """Test that min_completed_reps implies partial=True in API."""
        output = tmp_path / "partial.tar.gz"

        # Don't explicitly set partial=True
        archive_path = create_archive(
            run_with_multiple_reps,
            output,
            min_completed_reps=1,
        )

        reader = ArchiveReader(archive_path)
        manifest = reader.get_manifest()

        assert manifest.partial is True
