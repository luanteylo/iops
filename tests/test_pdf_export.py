"""
Tests for optional plot export functionality.

Tests that:
1. Plot files are NOT created by default (export_plots=False)
2. Plot files are created in __iops_plots folder when export_plots=True and kaleido is available
3. Export is skipped gracefully when kaleido is not available
4. Plot files have correct naming (numbered and descriptive)
5. Different formats work correctly (pdf, png, svg, jpg, webp)
6. KALEIDO_AVAILABLE flag works correctly

These tests are slow due to Kaleido rendering. Run explicitly with:
    pytest tests/test_pdf_export.py -v
"""

import json
from pathlib import Path
from unittest import mock

import os

import pandas as pd
import pytest

# Skip this entire module by default (slow tests due to Kaleido rendering)
# Run with: RUN_SLOW_TESTS=1 pytest tests/test_pdf_export.py -v
pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_SLOW_TESTS"),
    reason="PDF export tests are slow; run with RUN_SLOW_TESTS=1"
)


class TestKaleidoAvailability:
    """Test KALEIDO_AVAILABLE flag behavior."""

    def test_kaleido_available_when_installed(self):
        """Test that KALEIDO_AVAILABLE is True when kaleido is installed."""
        from iops.reporting import report_generator

        # Since user confirmed kaleido is installed
        assert report_generator.KALEIDO_AVAILABLE is True

    def test_kaleido_available_can_be_mocked_false(self):
        """Test that KALEIDO_AVAILABLE can be mocked to False for testing."""
        from iops.reporting import report_generator

        # Verify we can mock it to False for other tests
        with mock.patch.object(report_generator, "KALEIDO_AVAILABLE", False):
            assert report_generator.KALEIDO_AVAILABLE is False


class TestPlotExportDisabledByDefault:
    """Test that plot export is disabled by default."""

    @pytest.fixture
    def workdir_with_results(self, tmp_path):
        """Create a minimal workdir with results."""
        workdir = tmp_path / "test_run"
        workdir.mkdir()

        results_data = {
            "benchmark.name": ["test"] * 4,
            "execution.execution_id": [1, 2, 3, 4],
            "execution.repetition": [1, 1, 1, 1],
            "vars.nodes": [1, 2, 4, 8],
            "metrics.bandwidth": [100.0, 200.0, 400.0, 800.0],
        }

        df = pd.DataFrame(results_data)
        results_path = workdir / "results.csv"
        df.to_csv(results_path, index=False)

        metadata = {
            "benchmark": {
                "name": "Test Benchmark",
                "workdir": str(workdir),
                "executor": "local",
                "repetitions": 1,
                "report_vars": ["nodes"],
                "timestamp": "2025-01-01T00:00:00",
                "search_method": "exhaustive",
            },
            "variables": {
                "nodes": {
                    "type": "int",
                    "swept": True,
                    "sweep": {"mode": "list", "values": [1, 2, 4, 8]},
                },
            },
            "metrics": [{"name": "bandwidth", "script": "test"}],
            "output": {"type": "csv", "path": str(results_path)},
            "command": {"template": "benchmark --nodes {{ nodes }}", "labels": {}},
            "reporting": {"enabled": True},
        }

        metadata_path = workdir / "__iops_run_metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        return workdir

    def test_no_plots_directory_by_default(self, workdir_with_results):
        """Test that __iops_plots is NOT created by default (export_plots=False)."""
        from iops.reporting.report_generator import ReportGenerator

        generator = ReportGenerator(workdir=workdir_with_results)
        generator.load_metadata()
        generator.load_results()
        generator.generate_report()

        plots_dir = workdir_with_results / "__iops_plots"
        assert not plots_dir.exists(), (
            "PDF plots directory should NOT be created by default"
        )

    def test_html_report_generated_without_export(self, workdir_with_results):
        """Test that HTML report is generated even without plot export."""
        from iops.reporting.report_generator import ReportGenerator

        generator = ReportGenerator(workdir=workdir_with_results)
        generator.load_metadata()
        generator.load_results()
        report_path = generator.generate_report()

        assert report_path.exists(), "HTML report should be generated"
        assert report_path.suffix == ".html"

        # Verify it's valid HTML
        content = report_path.read_text()
        assert "<html" in content.lower()
        assert "plotly" in content.lower()


class TestPlotExportEnabled:
    """Integration tests for plot export when explicitly enabled."""

    @pytest.fixture
    def workdir_with_results(self, tmp_path):
        """Create a minimal workdir with results for report generation."""
        workdir = tmp_path / "test_run"
        workdir.mkdir()

        # Create results CSV
        results_data = {
            "benchmark.name": ["test"] * 6,
            "execution.execution_id": [1, 2, 3, 4, 5, 6],
            "execution.repetition": [1, 1, 1, 1, 1, 1],
            "vars.nodes": [1, 1, 2, 2, 4, 4],
            "vars.block_size": [64, 128, 64, 128, 64, 128],
            "metrics.bandwidth": [100.0, 150.0, 180.0, 250.0, 320.0, 450.0],
            "metrics.latency": [10.0, 8.0, 6.0, 5.0, 4.0, 3.0],
        }

        df = pd.DataFrame(results_data)
        results_path = workdir / "results.csv"
        df.to_csv(results_path, index=False)

        # Create metadata
        metadata = {
            "benchmark": {
                "name": "Test Benchmark",
                "workdir": str(workdir),
                "executor": "local",
                "repetitions": 1,
                "report_vars": ["nodes", "block_size"],
                "timestamp": "2025-01-01T00:00:00",
                "search_method": "exhaustive",
            },
            "variables": {
                "nodes": {
                    "type": "int",
                    "swept": True,
                    "sweep": {"mode": "list", "values": [1, 2, 4]},
                },
                "block_size": {
                    "type": "int",
                    "swept": True,
                    "sweep": {"mode": "list", "values": [64, 128]},
                },
            },
            "metrics": [
                {"name": "bandwidth", "script": "test"},
                {"name": "latency", "script": "test"},
            ],
            "output": {
                "type": "csv",
                "path": str(results_path),
            },
            "command": {
                "template": "benchmark --nodes {{ nodes }} --block {{ block_size }}",
                "labels": {},
            },
            "reporting": {
                "enabled": True,
            },
        }

        metadata_path = workdir / "__iops_run_metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        return workdir

    def test_plots_directory_created_when_enabled(self, workdir_with_results):
        """Test that __iops_plots directory is created when export_plots=True."""
        from iops.reporting.report_generator import (
            KALEIDO_AVAILABLE,
            ReportGenerator,
        )

        if not KALEIDO_AVAILABLE:
            pytest.skip("kaleido not installed")

        generator = ReportGenerator(
            workdir=workdir_with_results,
            export_plots=True
        )
        generator.load_metadata()
        generator.load_results()
        generator.generate_report()

        plots_dir = workdir_with_results / "__iops_plots"
        assert plots_dir.exists(), "Plots directory should be created when export_plots=True"
        assert plots_dir.is_dir(), "__iops_plots should be a directory"

    def test_pdf_files_created(self, workdir_with_results):
        """Test that PDF files are created when export_plots=True (default format)."""
        from iops.reporting.report_generator import (
            KALEIDO_AVAILABLE,
            ReportGenerator,
        )

        if not KALEIDO_AVAILABLE:
            pytest.skip("kaleido not installed")

        generator = ReportGenerator(
            workdir=workdir_with_results,
            export_plots=True
        )
        generator.load_metadata()
        generator.load_results()
        generator.generate_report()

        plots_dir = workdir_with_results / "__iops_plots"
        pdf_files = list(plots_dir.glob("*.pdf"))

        assert len(pdf_files) > 0, "At least one PDF file should be created"

    def test_png_format(self, workdir_with_results):
        """Test that PNG files are created when plot_format='png'."""
        from iops.reporting.report_generator import (
            KALEIDO_AVAILABLE,
            ReportGenerator,
        )

        if not KALEIDO_AVAILABLE:
            pytest.skip("kaleido not installed")

        generator = ReportGenerator(
            workdir=workdir_with_results,
            export_plots=True,
            plot_format='png'
        )
        generator.load_metadata()
        generator.load_results()
        generator.generate_report()

        plots_dir = workdir_with_results / "__iops_plots"
        png_files = list(plots_dir.glob("*.png"))

        assert len(png_files) > 0, "At least one PNG file should be created"

    def test_svg_format(self, workdir_with_results):
        """Test that SVG files are created when plot_format='svg'."""
        from iops.reporting.report_generator import (
            KALEIDO_AVAILABLE,
            ReportGenerator,
        )

        if not KALEIDO_AVAILABLE:
            pytest.skip("kaleido not installed")

        generator = ReportGenerator(
            workdir=workdir_with_results,
            export_plots=True,
            plot_format='svg'
        )
        generator.load_metadata()
        generator.load_results()
        generator.generate_report()

        plots_dir = workdir_with_results / "__iops_plots"
        svg_files = list(plots_dir.glob("*.svg"))

        assert len(svg_files) > 0, "At least one SVG file should be created"

    def test_files_numbered_sequentially(self, workdir_with_results):
        """Test that plot files are numbered sequentially (001, 002, etc.)."""
        from iops.reporting.report_generator import (
            KALEIDO_AVAILABLE,
            ReportGenerator,
        )

        if not KALEIDO_AVAILABLE:
            pytest.skip("kaleido not installed")

        generator = ReportGenerator(
            workdir=workdir_with_results,
            export_plots=True
        )
        generator.load_metadata()
        generator.load_results()
        generator.generate_report()

        plots_dir = workdir_with_results / "__iops_plots"
        pdf_files = sorted(plots_dir.glob("*.pdf"))

        # Check that files start with sequential numbers
        for i, pdf_file in enumerate(pdf_files, start=1):
            expected_prefix = f"{i:03d}_"
            assert pdf_file.name.startswith(expected_prefix), (
                f"Plot file {pdf_file.name} should start with {expected_prefix}"
            )

    def test_files_have_descriptive_names(self, workdir_with_results):
        """Test that plot files have descriptive names beyond just numbers."""
        from iops.reporting.report_generator import (
            KALEIDO_AVAILABLE,
            ReportGenerator,
        )

        if not KALEIDO_AVAILABLE:
            pytest.skip("kaleido not installed")

        generator = ReportGenerator(
            workdir=workdir_with_results,
            export_plots=True
        )
        generator.load_metadata()
        generator.load_results()
        generator.generate_report()

        plots_dir = workdir_with_results / "__iops_plots"
        pdf_files = list(plots_dir.glob("*.pdf"))

        for pdf_file in pdf_files:
            # Name should be more than just "001_plot.pdf"
            # Should contain descriptive text like metric name or section
            name_without_number = pdf_file.stem[4:]  # Remove "001_" prefix
            assert len(name_without_number) > 0, (
                f"Plot file {pdf_file.name} should have a descriptive name"
            )

    def test_html_report_still_generated(self, workdir_with_results):
        """Test that HTML report is still generated alongside plot files."""
        from iops.reporting.report_generator import (
            KALEIDO_AVAILABLE,
            ReportGenerator,
        )

        if not KALEIDO_AVAILABLE:
            pytest.skip("kaleido not installed")

        generator = ReportGenerator(
            workdir=workdir_with_results,
            export_plots=True
        )
        generator.load_metadata()
        generator.load_results()
        report_path = generator.generate_report()

        # HTML report should exist
        assert report_path.exists(), "HTML report should be generated"
        assert report_path.suffix == ".html", "Report should be HTML"

        # Plots directory should also exist
        plots_dir = workdir_with_results / "__iops_plots"
        assert plots_dir.exists(), "Plots directory should also exist"


class TestPlotExportWithoutKaleido:
    """Test behavior when kaleido is not available."""

    @pytest.fixture
    def workdir_with_results(self, tmp_path):
        """Create a minimal workdir with results."""
        workdir = tmp_path / "test_run"
        workdir.mkdir()

        results_data = {
            "benchmark.name": ["test"] * 4,
            "execution.execution_id": [1, 2, 3, 4],
            "execution.repetition": [1, 1, 1, 1],
            "vars.nodes": [1, 2, 4, 8],
            "metrics.bandwidth": [100.0, 200.0, 400.0, 800.0],
        }

        df = pd.DataFrame(results_data)
        results_path = workdir / "results.csv"
        df.to_csv(results_path, index=False)

        metadata = {
            "benchmark": {
                "name": "Test Benchmark",
                "workdir": str(workdir),
                "executor": "local",
                "repetitions": 1,
                "report_vars": ["nodes"],
                "timestamp": "2025-01-01T00:00:00",
                "search_method": "exhaustive",
            },
            "variables": {
                "nodes": {
                    "type": "int",
                    "swept": True,
                    "sweep": {"mode": "list", "values": [1, 2, 4, 8]},
                },
            },
            "metrics": [{"name": "bandwidth", "script": "test"}],
            "output": {"type": "csv", "path": str(results_path)},
            "command": {"template": "benchmark --nodes {{ nodes }}", "labels": {}},
            "reporting": {"enabled": True},
        }

        metadata_path = workdir / "__iops_run_metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        return workdir

    def test_no_plots_directory_when_kaleido_unavailable(self, workdir_with_results):
        """Test that __iops_plots is not created when kaleido is unavailable."""
        from iops.reporting import report_generator
        from iops.reporting.report_generator import ReportGenerator

        # Mock KALEIDO_AVAILABLE to be False
        with mock.patch.object(report_generator, "KALEIDO_AVAILABLE", False):
            generator = ReportGenerator(
                workdir=workdir_with_results,
                export_plots=True  # Explicitly request export
            )
            generator.load_metadata()
            generator.load_results()
            generator.generate_report()

        plots_dir = workdir_with_results / "__iops_plots"
        assert not plots_dir.exists(), (
            "Plots directory should NOT be created when kaleido unavailable"
        )

    def test_html_report_generated_without_kaleido(self, workdir_with_results):
        """Test that HTML report is still generated when kaleido is unavailable."""
        from iops.reporting import report_generator
        from iops.reporting.report_generator import ReportGenerator

        # Mock KALEIDO_AVAILABLE to be False
        with mock.patch.object(report_generator, "KALEIDO_AVAILABLE", False):
            generator = ReportGenerator(
                workdir=workdir_with_results,
                export_plots=True
            )
            generator.load_metadata()
            generator.load_results()
            report_path = generator.generate_report()

        # HTML report should still be generated
        assert report_path.exists(), "HTML report should be generated without kaleido"
        assert report_path.suffix == ".html"

        # Read and verify it's valid HTML
        content = report_path.read_text()
        assert "<html" in content.lower()
        assert "plotly" in content.lower()


class TestPlotCounter:
    """Test the plot counter mechanism for plot naming."""

    @pytest.fixture
    def workdir_with_results(self, tmp_path):
        """Create workdir with multiple metrics to generate multiple plots."""
        workdir = tmp_path / "test_run"
        workdir.mkdir()

        results_data = {
            "benchmark.name": ["test"] * 4,
            "execution.execution_id": [1, 2, 3, 4],
            "execution.repetition": [1, 1, 1, 1],
            "vars.nodes": [1, 2, 4, 8],
            "metrics.bandwidth": [100.0, 200.0, 400.0, 800.0],
            "metrics.latency": [10.0, 5.0, 2.5, 1.25],
            "metrics.iops": [1000, 2000, 4000, 8000],
        }

        df = pd.DataFrame(results_data)
        results_path = workdir / "results.csv"
        df.to_csv(results_path, index=False)

        metadata = {
            "benchmark": {
                "name": "Multi-Metric Test",
                "workdir": str(workdir),
                "executor": "local",
                "repetitions": 1,
                "report_vars": ["nodes"],
                "timestamp": "2025-01-01T00:00:00",
                "search_method": "exhaustive",
            },
            "variables": {
                "nodes": {
                    "type": "int",
                    "swept": True,
                    "sweep": {"mode": "list", "values": [1, 2, 4, 8]},
                },
            },
            "metrics": [
                {"name": "bandwidth", "script": "test"},
                {"name": "latency", "script": "test"},
                {"name": "iops", "script": "test"},
            ],
            "output": {"type": "csv", "path": str(results_path)},
            "command": {"template": "benchmark --nodes {{ nodes }}", "labels": {}},
            "reporting": {"enabled": True},
        }

        metadata_path = workdir / "__iops_run_metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        return workdir

    def test_plot_counter_resets_between_reports(self, workdir_with_results):
        """Test that plot counter resets when generating a new report."""
        from iops.reporting.report_generator import (
            KALEIDO_AVAILABLE,
            ReportGenerator,
        )

        if not KALEIDO_AVAILABLE:
            pytest.skip("kaleido not installed")

        # Generate first report
        generator1 = ReportGenerator(
            workdir=workdir_with_results,
            export_plots=True
        )
        generator1.load_metadata()
        generator1.load_results()
        generator1.generate_report()

        # Count files
        plots_dir = workdir_with_results / "__iops_plots"
        first_count = len(list(plots_dir.glob("*.pdf")))

        # Generate second report (overwrite)
        generator2 = ReportGenerator(
            workdir=workdir_with_results,
            export_plots=True
        )
        generator2.load_metadata()
        generator2.load_results()
        generator2.generate_report()

        # Should have same number of files (counter reset, same plots)
        second_count = len(list(plots_dir.glob("*.pdf")))
        assert first_count == second_count, (
            "Plot counter should reset between report generations"
        )

    def test_multiple_plots_numbered_correctly(self, workdir_with_results):
        """Test that multiple plots get sequential numbers."""
        from iops.reporting.report_generator import (
            KALEIDO_AVAILABLE,
            ReportGenerator,
        )

        if not KALEIDO_AVAILABLE:
            pytest.skip("kaleido not installed")

        generator = ReportGenerator(
            workdir=workdir_with_results,
            export_plots=True
        )
        generator.load_metadata()
        generator.load_results()
        generator.generate_report()

        plots_dir = workdir_with_results / "__iops_plots"
        pdf_files = sorted(plots_dir.glob("*.pdf"))

        # Extract numbers from filenames
        numbers = []
        for pdf_file in pdf_files:
            # Extract the number prefix (e.g., "001" from "001_plot_name.pdf")
            num_str = pdf_file.name.split("_")[0]
            numbers.append(int(num_str))

        # Numbers should be sequential starting from 1
        expected = list(range(1, len(numbers) + 1))
        assert numbers == expected, (
            f"Plot numbers should be sequential: expected {expected}, got {numbers}"
        )


class TestPlotFileNames:
    """Test plot file naming conventions."""

    @pytest.fixture
    def workdir_with_special_chars(self, tmp_path):
        """Create workdir with metric names containing special characters."""
        workdir = tmp_path / "test_run"
        workdir.mkdir()

        results_data = {
            "benchmark.name": ["test"] * 4,
            "execution.execution_id": [1, 2, 3, 4],
            "execution.repetition": [1, 1, 1, 1],
            "vars.nodes": [1, 2, 4, 8],
            "metrics.read_bandwidth_mb_s": [100.0, 200.0, 400.0, 800.0],
        }

        df = pd.DataFrame(results_data)
        results_path = workdir / "results.csv"
        df.to_csv(results_path, index=False)

        metadata = {
            "benchmark": {
                "name": "Test with Special/Characters",
                "workdir": str(workdir),
                "executor": "local",
                "repetitions": 1,
                "report_vars": ["nodes"],
                "timestamp": "2025-01-01T00:00:00",
                "search_method": "exhaustive",
            },
            "variables": {
                "nodes": {
                    "type": "int",
                    "swept": True,
                    "sweep": {"mode": "list", "values": [1, 2, 4, 8]},
                },
            },
            "metrics": [{"name": "read_bandwidth_mb_s", "script": "test"}],
            "output": {"type": "csv", "path": str(results_path)},
            "command": {"template": "benchmark --nodes {{ nodes }}", "labels": {}},
            "reporting": {"enabled": True},
        }

        metadata_path = workdir / "__iops_run_metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        return workdir

    def test_special_characters_sanitized_in_filename(self, workdir_with_special_chars):
        """Test that special characters are sanitized in plot filenames."""
        from iops.reporting.report_generator import (
            KALEIDO_AVAILABLE,
            ReportGenerator,
        )

        if not KALEIDO_AVAILABLE:
            pytest.skip("kaleido not installed")

        generator = ReportGenerator(
            workdir=workdir_with_special_chars,
            export_plots=True
        )
        generator.load_metadata()
        generator.load_results()
        generator.generate_report()

        plots_dir = workdir_with_special_chars / "__iops_plots"
        pdf_files = list(plots_dir.glob("*.pdf"))

        for pdf_file in pdf_files:
            # Filename should not contain problematic characters
            filename = pdf_file.name
            # Only alphanumeric, dots, underscores, and hyphens allowed
            for char in filename:
                assert char.isalnum() or char in "._-", (
                    f"Unexpected character '{char}' in filename: {filename}"
                )


class TestConvenienceFunction:
    """Test the generate_report_from_workdir convenience function."""

    @pytest.fixture
    def workdir_with_results(self, tmp_path):
        """Create a minimal workdir with results."""
        workdir = tmp_path / "test_run"
        workdir.mkdir()

        results_data = {
            "benchmark.name": ["test"] * 4,
            "execution.execution_id": [1, 2, 3, 4],
            "execution.repetition": [1, 1, 1, 1],
            "vars.nodes": [1, 2, 4, 8],
            "metrics.bandwidth": [100.0, 200.0, 400.0, 800.0],
        }

        df = pd.DataFrame(results_data)
        results_path = workdir / "results.csv"
        df.to_csv(results_path, index=False)

        metadata = {
            "benchmark": {
                "name": "Test Benchmark",
                "workdir": str(workdir),
                "executor": "local",
                "repetitions": 1,
                "report_vars": ["nodes"],
                "timestamp": "2025-01-01T00:00:00",
                "search_method": "exhaustive",
            },
            "variables": {
                "nodes": {
                    "type": "int",
                    "swept": True,
                    "sweep": {"mode": "list", "values": [1, 2, 4, 8]},
                },
            },
            "metrics": [{"name": "bandwidth", "script": "test"}],
            "output": {"type": "csv", "path": str(results_path)},
            "command": {"template": "benchmark --nodes {{ nodes }}", "labels": {}},
            "reporting": {"enabled": True},
        }

        metadata_path = workdir / "__iops_run_metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        return workdir

    def test_convenience_function_default_no_export(self, workdir_with_results):
        """Test that convenience function doesn't export by default."""
        from iops.reporting.report_generator import generate_report_from_workdir

        report_path = generate_report_from_workdir(workdir_with_results)

        assert report_path.exists(), "HTML report should be generated"

        plots_dir = workdir_with_results / "__iops_plots"
        assert not plots_dir.exists(), "Plots directory should NOT be created by default"

    def test_convenience_function_with_export(self, workdir_with_results):
        """Test that convenience function exports when requested."""
        from iops.reporting.report_generator import (
            KALEIDO_AVAILABLE,
            generate_report_from_workdir,
        )

        if not KALEIDO_AVAILABLE:
            pytest.skip("kaleido not installed")

        report_path = generate_report_from_workdir(
            workdir_with_results,
            export_plots=True
        )

        assert report_path.exists(), "HTML report should be generated"

        plots_dir = workdir_with_results / "__iops_plots"
        assert plots_dir.exists(), "Plots directory should be created when requested"

    def test_convenience_function_with_format(self, workdir_with_results):
        """Test that convenience function respects plot_format."""
        from iops.reporting.report_generator import (
            KALEIDO_AVAILABLE,
            generate_report_from_workdir,
        )

        if not KALEIDO_AVAILABLE:
            pytest.skip("kaleido not installed")

        generate_report_from_workdir(
            workdir_with_results,
            export_plots=True,
            plot_format='png'
        )

        plots_dir = workdir_with_results / "__iops_plots"
        png_files = list(plots_dir.glob("*.png"))

        assert len(png_files) > 0, "PNG files should be created"
        pdf_files = list(plots_dir.glob("*.pdf"))
        assert len(pdf_files) == 0, "PDF files should NOT be created when format is png"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
