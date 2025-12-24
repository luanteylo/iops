"""
Test case for bug: Reporting fails when metrics in metadata don't exist in results.

This test reproduces the issue where run_metadata.json contains metrics that
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
                "metadata": {},
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

        metadata_path = workdir / "run_metadata.json"
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
        # Default report name is analysis_report.html
        assert report_path.name == "analysis_report.html"

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


class TestRealWorldScenario:
    """
    Test using actual data from the bug discovery.

    This uses files from /home/luan/workdir/mdtest/run_004 if available.
    """

    @pytest.fixture
    def real_workdir(self):
        """Check if real bug data is available."""
        real_path = Path("/home/luan/workdir/mdtest/run_004")
        if not real_path.exists():
            pytest.skip("Real workdir not available")
        return real_path

    def test_real_bug_scenario(self, real_workdir):
        """
        Test the actual bug scenario that was discovered.

        This test uses the real data from the mdtest run where the bug occurred.
        Note: This test may pass if the metadata has been manually fixed.
        """
        metadata_path = real_workdir / "run_metadata.json"
        results_path = real_workdir / "results.csv"

        # Load real data
        with open(metadata_path) as f:
            metadata = json.load(f)

        df = pd.read_csv(results_path)

        # Verify the bug scenario
        declared_metrics = set([m["name"] for m in metadata["metrics"]])
        available_metrics = set(
            [
                col.replace("metrics.", "")
                for col in df.columns
                if col.startswith("metrics.")
            ]
        )

        missing = declared_metrics - available_metrics

        # In the real scenario, file_read_rate should be missing
        # If the metadata was already fixed, skip this test
        if len(missing) == 0:
            pytest.skip("Metadata was already fixed - no missing metrics to test")

        # Otherwise verify we can detect the missing metrics
        assert len(missing) > 0


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
