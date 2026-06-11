"""
Regression tests for bugs found in the 3.5.x code audit.

Covers:
- Bayesian objective default and best-value tracking for minimize
- Cache parameter normalization (false hits from string-to-float coercion)
- CSV-built caches (status key, negative integer params)
- Result sink writers (CSV dtype corruption, empty CSV, SQLite schema evolution,
  Parquet integer upcast)
- SLURM job id parsing and transient squeue failure handling
- Partial archive integrity verification and tar extraction safety
"""

import io
import json
import logging
import sqlite3
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import pytest
import yaml

from iops.cache.execution_cache import ExecutionCache, _normalize_value
from iops.execution.executors import SlurmExecutor
from iops.results.writer import _write_csv, _write_parquet, _write_sqlite


def _load_config(config_path):
    from iops.config.loader import load_generic_config

    logger = logging.getLogger("test")
    return load_generic_config(Path(config_path), logger)


def _bayesian_config_dict(workdir: Path, objective=None):
    bayesian_config = {
        "objective_metric": "metric",
        "n_initial_points": 2,
        "n_iterations": 5,
    }
    if objective is not None:
        bayesian_config["objective"] = objective

    return {
        "benchmark": {
            "name": "Audit Regression Bayesian",
            "workdir": str(workdir),
            "executor": "local",
            "search_method": "bayesian",
            "repetitions": 1,
            "random_seed": 42,
            "bayesian_config": bayesian_config,
        },
        "vars": {
            "param1": {
                "type": "int",
                "sweep": {"mode": "list", "values": [1, 10, 100]},
            },
            "param2": {
                "type": "int",
                "sweep": {"mode": "list", "values": [1, 2, 3]},
            },
        },
        "command": {
            "template": "echo 'param1={{ param1 }} param2={{ param2 }}'",
        },
        "scripts": [
            {
                "name": "test_script",
                "script_template": "#!/bin/bash\necho 'metric: 100' > {{ execution_dir }}/output.txt",
                "parser": {
                    "file": "{{ execution_dir }}/output.txt",
                    "metrics": [{"name": "metric", "type": "float"}],
                    "parser_script": (
                        "def parse(file_path):\n"
                        "    with open(file_path) as f:\n"
                        "        line = f.read().strip()\n"
                        "    return {'metric': float(line.split(':')[1])}"
                    ),
                },
            }
        ],
        "output": {
            "sink": {
                "type": "csv",
                "path": "{{ workdir }}/results.csv",
            }
        },
    }


def _write_bayesian_config(tmp_path: Path, objective=None) -> Path:
    workdir = tmp_path / "workdir"
    workdir.mkdir(parents=True, exist_ok=True)
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(_bayesian_config_dict(workdir, objective=objective), f)
    return config_file


class TestBayesianObjective:
    """The loader defaulted objective to 'maximize' while model and docs say
    'minimize', and best-value tracking reported the last point instead of the
    best for minimize studies."""

    def test_objective_defaults_to_minimize(self, tmp_path):
        config_file = _write_bayesian_config(tmp_path)
        cfg = _load_config(config_file)
        assert cfg.benchmark.bayesian_config.objective == "minimize"

    def test_minimize_tracks_best_not_last(self, tmp_path):
        pytest.importorskip("skopt")
        from iops.execution.planner import BayesianPlanner

        config_file = _write_bayesian_config(tmp_path, objective="minimize")
        cfg = _load_config(config_file)
        planner = BayesianPlanner(cfg)

        for value in (50.0, 10.0, 30.0):
            test = planner.next_test()
            assert test is not None
            test.metadata["metrics"] = {"metric": value}
            planner.record_completed_test(test)

        assert planner.best_value == 10.0

    def test_maximize_tracks_best_not_last(self, tmp_path):
        pytest.importorskip("skopt")
        from iops.execution.planner import BayesianPlanner

        config_file = _write_bayesian_config(tmp_path, objective="maximize")
        cfg = _load_config(config_file)
        planner = BayesianPlanner(cfg)

        for value in (50.0, 90.0, 30.0):
            test = planner.next_test()
            assert test is not None
            test.metadata["metrics"] = {"metric": value}
            planner.record_completed_test(test)

        assert planner.best_value == 90.0


class TestCacheNormalization:
    """String-to-float coercion collapsed distinct string parameters (e.g.
    version strings "1.1" and "1.10") into the same hash, producing false
    cache hits."""

    def test_unambiguous_numeric_strings_coerced(self):
        assert _normalize_value("8") == 8
        assert _normalize_value("-8") == -8
        assert _normalize_value("4.0") == 4.0
        assert _normalize_value("1.1") == 1.1

    def test_ambiguous_strings_stay_strings(self):
        for text in ("1.10", "1e3", "08", "nan", "inf", "1_000", "+5", "abc"):
            assert _normalize_value(text) == text

    def test_distinct_version_strings_do_not_collide(self, tmp_path):
        cache = ExecutionCache(db_path=tmp_path / "cache.db")
        cache.store_result(
            params={"version": "1.1"},
            repetition=1,
            metrics={"bw": 100.0},
            metadata={"__executor_status": "SUCCEEDED"},
        )
        assert cache.get_cached_result({"version": "1.1"}, 1) is not None
        assert cache.get_cached_result({"version": "1.10"}, 1) is None

    def test_string_and_native_int_share_hash(self, tmp_path):
        cache = ExecutionCache(db_path=tmp_path / "cache.db")
        cache.store_result(
            params={"nodes": "8"},
            repetition=1,
            metrics={"bw": 100.0},
            metadata={"__executor_status": "SUCCEEDED"},
        )
        assert cache.get_cached_result({"nodes": 8}, 1) is not None


class TestCacheFromCsv:
    """CSV-built caches stored the wrong status key (hits reported UNKNOWN)
    and disagreed with runtime normalization on negative integers."""

    def test_csv_cache_hit_reports_succeeded(self, tmp_path):
        from iops.cache.from_csv import create_cache_from_csv

        csv_file = tmp_path / "results.csv"
        csv_file.write_text("nodes,offset,bw\n8,-4,100.0\n")
        db = tmp_path / "cache.db"
        create_cache_from_csv(
            csv_file,
            db,
            param_columns=["nodes", "offset"],
            metric_columns=["bw"],
            show_progress=False,
        )

        cache = ExecutionCache(db_path=db)
        # Lookup with native types, as a real run produces them
        result = cache.get_cached_result({"nodes": 8, "offset": -4}, 1)
        assert result is not None
        assert result["metadata"]["__executor_status"] == "SUCCEEDED"
        assert result["metrics"]["bw"] == 100.0


class TestCsvWriter:
    """Extending the CSV schema re-read the whole file with pandas type
    inference and rewrote it, silently mutating stored values."""

    def test_schema_extension_preserves_string_values(self, tmp_path):
        path = tmp_path / "results.csv"
        _write_csv(path, pd.DataFrame([{"vars.tag": "0010", "metrics.bw": 1.0}]))
        _write_csv(
            path,
            pd.DataFrame([{"vars.tag": "0020", "metrics.bw": 2.0, "metrics.lat": 5.0}]),
        )
        content = path.read_text()
        assert "0010" in content
        df = pd.read_csv(path, dtype=str)
        assert list(df["vars.tag"]) == ["0010", "0020"]

    def test_existing_empty_file_recovers(self, tmp_path):
        path = tmp_path / "results.csv"
        path.touch()
        _write_csv(path, pd.DataFrame([{"a": 1}]))
        df = pd.read_csv(path)
        assert len(df) == 1


class TestSqliteWriter:
    """A row introducing a new column crashed the whole run with
    OperationalError; the schema is now extended via ALTER TABLE."""

    def test_new_column_appends(self, tmp_path):
        db = tmp_path / "results.db"
        _write_sqlite(db, "results", pd.DataFrame([{"a": 1}]))
        _write_sqlite(db, "results", pd.DataFrame([{"a": 2, "b": "x"}]))
        con = sqlite3.connect(db)
        try:
            rows = con.execute("SELECT a, b FROM results ORDER BY a").fetchall()
        finally:
            con.close()
        assert rows == [(1, None), (2, "x")]


class TestParquetWriter:
    """Appending a row missing an integer column upcast the whole column to
    float64 permanently."""

    def test_integer_column_preserved_across_appends(self, tmp_path):
        pytest.importorskip("pyarrow")
        path = tmp_path / "results.parquet"
        _write_parquet(path, pd.DataFrame([{"n": 1, "m": 10}]))
        _write_parquet(path, pd.DataFrame([{"n": 2, "extra": "x"}]))
        df = pd.read_parquet(path)
        assert str(df["m"].dtype) == "Int64"
        assert df["m"].dropna().tolist() == [10]


def _mock_slurm_executor():
    config = Mock()
    config.benchmark = Mock()
    config.benchmark.slurm_options = None
    config.execution = Mock()
    config.execution.status_check_delay = 1
    return SlurmExecutor(config)


class TestSlurmRobustness:
    """Transient squeue failures were treated as 'job left the queue',
    abandoning live jobs; multi-cluster sbatch output was unparseable."""

    def test_parse_jobid_multicluster(self):
        executor = _mock_slurm_executor()
        jobid = executor._parse_jobid("Submitted batch job 12345 on cluster c2")
        assert jobid == "12345"

    def test_squeue_transient_failure_is_not_job_gone(self):
        executor = _mock_slurm_executor()
        err = subprocess.CalledProcessError(
            1,
            ["squeue"],
            stderr="slurm_load_jobs error: Socket timed out on send/recv operation",
        )
        with patch("subprocess.run", side_effect=err):
            state = executor._squeue_state("12345")
        assert state is executor.SQUEUE_UNAVAILABLE

    def test_squeue_invalid_job_id_means_gone(self):
        executor = _mock_slurm_executor()
        err = subprocess.CalledProcessError(
            1,
            ["squeue"],
            stderr="slurm_load_jobs error: Invalid job id specified",
        )
        with patch("subprocess.run", side_effect=err):
            state = executor._squeue_state("12345")
        assert state is None

    def test_deadline_is_terminal_failure(self):
        executor = _mock_slurm_executor()
        assert executor._map_final_status("DEADLINE", "0:0") == executor.STATUS_FAILED


def _make_run_dir(base: Path) -> Path:
    run = base / "run_001"
    run.mkdir()
    index = {"benchmark": "T", "executions": {}}
    for i in (1, 2, 3):
        eid = f"exec_{i:04d}"
        exec_dir = run / eid
        exec_dir.mkdir()
        (exec_dir / "__iops_params.json").write_text(json.dumps({"nodes": i}))
        rep = exec_dir / "repetition_001"
        rep.mkdir()
        status = "SUCCEEDED" if i < 3 else "FAILED"
        (rep / "__iops_status.json").write_text(json.dumps({"status": status}))
        index["executions"][eid] = {"path": eid, "params": {"nodes": i}, "command": "x"}
    (run / "__iops_index.json").write_text(json.dumps(index))
    (run / "__iops_run_metadata.json").write_text(json.dumps({"benchmark": {"name": "T"}}))
    pd.DataFrame(
        {
            "execution.execution_id": [1, 2, 3],
            "execution.repetition": [1, 1, 1],
            "metrics.bw": [1.0, 2.0, 3.0],
        }
    ).to_csv(run / "results.csv", index=False)
    return run


class TestArchiveIntegrity:
    """Partial archives recorded checksums of the unfiltered source tree, so
    any archive that excluded something failed its own verification."""

    def test_partial_archive_extracts_with_verification(self, tmp_path):
        from iops.archive.core import ArchiveReader, ArchiveWriter

        run = _make_run_dir(tmp_path)
        writer = ArchiveWriter(run, status_filter="SUCCEEDED", partial=True)
        archive = writer.write(tmp_path / "study.tar.gz", show_progress=False)

        dest = tmp_path / "extracted"
        reader = ArchiveReader(archive)
        reader.extract(dest, verify=True, show_progress=False)

        df = pd.read_csv(dest / "results.csv")
        assert set(df["execution.execution_id"]) == {1, 2}
        assert not (dest / "exec_0003").exists()


class TestArchiveExtractionSafety:
    """The custom extraction filter replaced the stdlib 'data' filter without
    checking link targets, allowing symlink-based path traversal."""

    def test_symlink_escape_blocked(self, tmp_path):
        from iops.archive.core import ArchiveReader

        evil = tmp_path / "evil.tar.gz"
        outside = tmp_path / "outside"
        outside.mkdir()
        with tarfile.open(evil, "w:gz") as tar:
            link = tarfile.TarInfo("link")
            link.type = tarfile.SYMTYPE
            link.linkname = str(outside)
            tar.addfile(link)
            payload = b"pwned"
            member = tarfile.TarInfo("link/owned.txt")
            member.size = len(payload)
            tar.addfile(member, io.BytesIO(payload))

        reader = ArchiveReader(evil)
        try:
            reader.extract(tmp_path / "dest", verify=False, show_progress=False)
        except Exception:
            pass  # rejecting the whole archive is also acceptable

        assert not (outside / "owned.txt").exists()

    def test_double_dot_in_filename_is_extracted(self, tmp_path):
        from iops.archive.core import ArchiveReader

        archive = tmp_path / "ok.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            payload = b"data"
            member = tarfile.TarInfo("results..csv")
            member.size = len(payload)
            tar.addfile(member, io.BytesIO(payload))

        dest = tmp_path / "dest"
        reader = ArchiveReader(archive)
        reader.extract(dest, verify=False, show_progress=False)
        assert (dest / "results..csv").read_text() == "data"
