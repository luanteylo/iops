"""
Test case for bug: Reporting fails when metrics in metadata don't exist in results.

This test reproduces the issue where __iops_run_metadata.json contains metrics that
don't have corresponding columns in the results CSV, causing report generation
to fail with "Columns not found" error.

Bug report: BUG_REPORT_missing_metrics.md
"""

import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from iops.reporting.report_generator import ReportGenerator


class TestMissingMetricsHandling:
    """Test cases for graceful handling of missing metrics in results."""

    @pytest.fixture
    def workdir_with_missing_metrics(self, tmp_path):
        """
        Create a test workdir that mimics the bug scenario:
        - metadata lists metrics: [A, B, C, D, E, F]
        - results CSV only has: [A, B, D, E]
        - Missing metrics: [C, F]
        """
        workdir = tmp_path / "test_run"
        workdir.mkdir()

        # Create results CSV with subset of metrics
        results_data = {
            "benchmark.name": ["mdtest"] * 4,
            "execution.execution_id": [1, 2, 3, 4],
            "execution.repetition": [1, 1, 1, 1],
            "vars.mpi_processes": [1, 2, 4, 1],
            "vars.files_per_task": [100, 100, 100, 1000],
            "metrics.file_creation_rate": [1000.0, 2000.0, 4000.0, 1500.0],
            "metrics.file_stat_rate": [5000.0, 10000.0, 20000.0, 7500.0],
            # NOTE: file_read_rate is MISSING (this is the bug scenario)
            "metrics.file_removal_rate": [800.0, 1600.0, 3200.0, 1200.0],
            "metrics.tree_creation_rate": [500.0, 1000.0, 2000.0, 750.0],
            # NOTE: tree_removal_rate is MISSING (another missing metric)
        }

        df = pd.DataFrame(results_data)
        results_path = workdir / "results.csv"
        df.to_csv(results_path, index=False)

        # Create metadata that includes the missing metrics
        metadata = {
            "benchmark": {
                "name": "mdtest Benchmark",
                "workdir": str(workdir),
                "executor": "local",
                "repetitions": 1,
                "report_vars": ["mpi_processes", "files_per_task"],
                "timestamp": "2025-12-24T00:00:00",
                "description": "Test benchmark with missing metrics",
            },
            "variables": {
                "mpi_processes": {
                    "type": "int",
                    "swept": True,
                    "sweep": {"mode": "list", "values": [1, 2, 4]},
                },
                "files_per_task": {
                    "type": "int",
                    "swept": True,
                    "sweep": {"mode": "list", "values": [100, 1000]},
                },
            },
            "metrics": [
                {"name": "file_creation_rate", "script": "mdtest"},
                {"name": "file_stat_rate", "script": "mdtest"},
                {"name": "file_read_rate", "script": "mdtest"},  # MISSING in CSV!
                {"name": "file_removal_rate", "script": "mdtest"},
                {"name": "tree_creation_rate", "script": "mdtest"},
                {"name": "tree_removal_rate", "script": "mdtest"},  # MISSING in CSV!
            ],
            "output": {
                "type": "csv",
                "path": str(results_path),
            },
            "command": {
                "template": "mdtest -n {{ files_per_task }} -p {{ mpi_processes }}",
                "labels": {},
            },
            "reporting": {
                "enabled": True,
                "output_filename": "test_report.html",
                "metrics": {
                    "file_creation_rate": {
                        "plots": [
                            {
                                "type": "line",
                                "x_var": "files_per_task",
                                "group_by": "mpi_processes",
                            }
                        ]
                    },
                    "file_read_rate": {  # This references a MISSING metric!
                        "plots": [
                            {
                                "type": "bar",
                                "x_var": "mpi_processes",
                            }
                        ]
                    },
                },
                "default_plots": [],
            },
        }

        metadata_path = workdir / "__iops_run_metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        return {
            "workdir": workdir,
            "results_path": results_path,
            "metadata_path": metadata_path,
            "metadata": metadata,
            "missing_metrics": ["file_read_rate", "tree_removal_rate"],
            "available_metrics": [
                "file_creation_rate",
                "file_stat_rate",
                "file_removal_rate",
                "tree_creation_rate",
            ],
        }

    def test_report_generation_fails_with_missing_metrics(
        self, workdir_with_missing_metrics
    ):
        """
        Test that USED TO reproduce the bug: Report generation fails when metadata
        lists metrics that don't exist in results CSV.

        This test now validates that the bug is FIXED - report generation should
        succeed with appropriate warnings instead of failing.
        """
        workdir = workdir_with_missing_metrics["workdir"]

        # This should now SUCCEED (bug is fixed)
        generator = ReportGenerator(workdir=workdir)
        generator.load_metadata()
        generator.load_results()

        # Verify that metadata was filtered to only available metrics
        available = set(workdir_with_missing_metrics["available_metrics"])
        actual_metrics = set([m["name"] for m in generator.metadata["metrics"]])
        assert actual_metrics == available

        # Report generation should now succeed
        report_path = generator.generate_report()
        assert report_path.exists()

    def test_report_generation_handles_missing_metrics_gracefully(
        self, workdir_with_missing_metrics, caplog
    ):
        """
        Test that report generation succeeds with warnings when some metrics are missing.

        Expected behavior:
        1. Detect missing metrics (file_read_rate, tree_removal_rate)
        2. Log warnings about missing metrics
        3. Filter out plots that reference missing metrics
        4. Successfully generate report with available metrics only
        """
        import logging

        workdir = workdir_with_missing_metrics["workdir"]
        missing = set(workdir_with_missing_metrics["missing_metrics"])
        available = set(workdir_with_missing_metrics["available_metrics"])

        # Configure logging to capture warnings
        with caplog.at_level(logging.WARNING):
            # This should NOT raise an exception after the fix
            generator = ReportGenerator(workdir=workdir)
            generator.load_metadata()
            generator.load_results()

            # Generate report - should succeed
            report_path = generator.generate_report()

        # Verify report was created
        assert report_path.exists()
        # generate_report() honors the reporting config's output_filename
        # (set to "test_report.html" in the fixture metadata) when no explicit
        # output_path is passed.
        assert report_path.name == "test_report.html"

        # Verify warnings were logged
        warnings = [
            record for record in caplog.records if record.levelname == "WARNING"
        ]
        assert len(warnings) >= 1, "Expected at least one warning about missing metrics"

        # Verify warning messages mention the missing metrics
        warning_text = " ".join([w.message for w in warnings])
        for metric in missing:
            assert metric in warning_text, f"Expected warning to mention {metric}"

        # Verify the generator only used available metrics
        actual_metrics = set([m["name"] for m in generator.metadata["metrics"]])
        assert actual_metrics == available, f"Expected {available}, got {actual_metrics}"

        # Verify reporting config was also filtered
        if generator.report_config and generator.report_config.metrics:
            reporting_metrics = set(generator.report_config.metrics.keys())
            # Reporting metrics should be a subset of available metrics
            assert reporting_metrics.issubset(available)

    def test_identify_missing_metrics(self, workdir_with_missing_metrics):
        """
        Test helper function to identify missing metrics.

        This tests the utility function that should be added to identify
        which metrics are in metadata but not in results.
        """
        results_path = workdir_with_missing_metrics["results_path"]
        metadata = workdir_with_missing_metrics["metadata"]
        expected_missing = set(workdir_with_missing_metrics["missing_metrics"])

        # Load results
        df = pd.read_csv(results_path)

        # Get available metrics from CSV columns
        available_metrics = set(
            [
                col.replace("metrics.", "")
                for col in df.columns
                if col.startswith("metrics.")
            ]
        )

        # Get declared metrics from metadata
        declared_metrics = set([m["name"] for m in metadata["metrics"]])

        # Identify missing metrics
        missing_metrics = declared_metrics - available_metrics

        # Verify we correctly identified the missing metrics
        assert missing_metrics == expected_missing
        assert "file_read_rate" in missing_metrics
        assert "tree_removal_rate" in missing_metrics
        assert "file_creation_rate" not in missing_metrics

    def test_filter_metadata_to_available_metrics(self, workdir_with_missing_metrics):
        """
        Test the proposed fix: Filter metadata to only include available metrics.

        This tests the logic that should be added to the report generator.
        """
        results_path = workdir_with_missing_metrics["results_path"]
        metadata = workdir_with_missing_metrics["metadata"].copy()

        # Load results
        df = pd.read_csv(results_path)

        # Proposed fix implementation
        available_metrics = set(
            [
                col.replace("metrics.", "")
                for col in df.columns
                if col.startswith("metrics.")
            ]
        )

        # Filter metadata metrics
        original_count = len(metadata["metrics"])
        metadata["metrics"] = [
            m for m in metadata["metrics"] if m["name"] in available_metrics
        ]
        filtered_count = len(metadata["metrics"])

        # Filter reporting metric configurations
        if "reporting" in metadata and "metrics" in metadata["reporting"]:
            metadata["reporting"]["metrics"] = {
                k: v
                for k, v in metadata["reporting"]["metrics"].items()
                if k in available_metrics
            }

        # Verify filtering worked correctly
        assert filtered_count < original_count
        assert filtered_count == 4  # Only 4 metrics available
        assert original_count == 6  # Originally 6 metrics declared

        # Verify only available metrics remain
        remaining_metrics = set([m["name"] for m in metadata["metrics"]])
        assert remaining_metrics == available_metrics

        # Verify reporting config also filtered
        reporting_metrics = set(metadata["reporting"]["metrics"].keys())
        assert "file_creation_rate" in reporting_metrics
        assert "file_read_rate" not in reporting_metrics  # Filtered out


class TestReportOutputPath:
    """generate_report() output-path resolution.

    Regression coverage for the bug where output_dir/output_filename from the
    reporting config were ignored and the report was always written to
    workdir/analysis_report.html.
    """

    @pytest.fixture
    def minimal_run(self, tmp_path):
        """A minimal valid run directory with a single metric and plot."""
        workdir = tmp_path / "run"
        workdir.mkdir()

        results_path = workdir / "results.csv"
        pd.DataFrame(
            {
                "benchmark.name": ["b"] * 3,
                "execution.execution_id": [1, 2, 3],
                "execution.repetition": [1, 1, 1],
                "vars.nodes": [1, 2, 4],
                "metrics.throughput": [100.0, 200.0, 400.0],
            }
        ).to_csv(results_path, index=False)

        metadata = {
            "benchmark": {
                "name": "b",
                "workdir": str(workdir),
                "executor": "local",
                "repetitions": 1,
                "report_vars": ["nodes"],
                "timestamp": "2025-12-24T00:00:00",
            },
            "variables": {
                "nodes": {
                    "type": "int",
                    "swept": True,
                    "sweep": {"mode": "list", "values": [1, 2, 4]},
                },
            },
            "metrics": [{"name": "throughput", "script": "b"}],
            "output": {"type": "csv", "path": str(results_path)},
            "command": {"template": "run --nodes {{ nodes }}", "labels": {}},
            "reporting": {
                "enabled": True,
                "metrics": {
                    "throughput": {
                        "plots": [{"type": "line", "x_var": "nodes"}]
                    }
                },
                "default_plots": [],
            },
        }
        with open(workdir / "__iops_run_metadata.json", "w") as f:
            json.dump(metadata, f)
        return {"workdir": workdir, "metadata": metadata}

    def _build(self, workdir):
        generator = ReportGenerator(workdir=workdir)
        generator.load_metadata()
        generator.load_results()
        return generator

    def test_default_output_path(self, minimal_run):
        """No output_dir/output_filename set -> workdir/analysis_report.html."""
        report_path = self._build(minimal_run["workdir"]).generate_report()
        assert report_path == minimal_run["workdir"] / "analysis_report.html"
        assert report_path.exists()

    def test_config_output_dir_and_filename_honored(self, minimal_run, tmp_path):
        """output_dir + output_filename from the config drive the output path."""
        out_dir = tmp_path / "reports"
        out_dir.mkdir()
        minimal_run["metadata"]["reporting"]["output_dir"] = str(out_dir)
        minimal_run["metadata"]["reporting"]["output_filename"] = "custom.html"
        with open(minimal_run["workdir"] / "__iops_run_metadata.json", "w") as f:
            json.dump(minimal_run["metadata"], f)

        report_path = self._build(minimal_run["workdir"]).generate_report()
        assert report_path == out_dir / "custom.html"
        assert report_path.exists()

    def test_explicit_output_path_overrides_config(self, minimal_run, tmp_path):
        """An explicit output_path wins over config output_dir/output_filename."""
        minimal_run["metadata"]["reporting"]["output_dir"] = str(tmp_path / "ignored")
        minimal_run["metadata"]["reporting"]["output_filename"] = "ignored.html"
        with open(minimal_run["workdir"] / "__iops_run_metadata.json", "w") as f:
            json.dump(minimal_run["metadata"], f)

        forced = tmp_path / "forced" / "report.html"
        forced.parent.mkdir()
        report_path = self._build(minimal_run["workdir"]).generate_report(output_path=forced)
        assert report_path == forced
        assert report_path.exists()


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
