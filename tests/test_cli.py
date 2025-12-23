"""Unit tests for IOPS CLI (Command Line Interface)."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call
import argparse
import sys
import yaml

from iops.main import (
    parse_arguments,
    load_version,
    initialize_logger,
    log_execution_context,
    main,
)
from iops.config.models import ConfigValidationError


class TestLoadVersion:
    """Test version loading from VERSION file."""

    def test_load_version_success(self):
        """Test loading version from VERSION file."""
        version = load_version()
        assert version is not None
        assert isinstance(version, str)
        # Version should be in format X.Y.Z
        parts = version.split('.')
        assert len(parts) == 3
        assert all(part.isdigit() for part in parts)

    def test_load_version_missing_file(self):
        """Test error when VERSION file is missing."""
        with patch('iops.main.Path') as mock_path:
            mock_version_file = MagicMock()
            mock_version_file.exists.return_value = False
            mock_path.return_value.parent.__truediv__.return_value = mock_version_file

            with pytest.raises(FileNotFoundError, match="Version file not found"):
                load_version()


class TestParseArguments:
    """Test command-line argument parsing."""

    def test_parse_minimal_args(self):
        """Test parsing with just setup file."""
        test_args = ['test_config.yaml']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.setup_file == Path('test_config.yaml')
            assert not args.check_setup
            assert not args.dry_run
            assert not args.use_cache
            assert args.log_level == 'INFO'

    def test_parse_check_setup(self):
        """Test --check_setup flag."""
        test_args = ['config.yaml', '--check_setup']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.check_setup is True

    def test_parse_dry_run(self):
        """Test --dry-run flag."""
        test_args = ['config.yaml', '--dry-run']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.dry_run is True

    def test_parse_use_cache(self):
        """Test --use_cache flag."""
        test_args = ['config.yaml', '--use_cache']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.use_cache is True

    def test_parse_max_core_hours(self):
        """Test --max-core-hours argument."""
        test_args = ['config.yaml', '--max-core-hours', '1000']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.max_core_hours == 1000.0

    def test_parse_log_level(self):
        """Test --log_level argument."""
        test_args = ['config.yaml', '--log_level', 'DEBUG']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.log_level == 'DEBUG'

    def test_parse_log_file(self):
        """Test --log_file argument."""
        test_args = ['config.yaml', '--log_file', 'custom.log']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.log_file == Path('custom.log')

    def test_parse_no_log_terminal(self):
        """Test --no-log-terminal flag."""
        test_args = ['config.yaml', '--no-log-terminal']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.no_log_terminal is True

    def test_parse_verbose(self):
        """Test --verbose flag."""
        test_args = ['config.yaml', '--verbose']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.verbose is True

    def test_parse_estimated_time(self):
        """Test --estimated-time argument."""
        test_args = ['config.yaml', '--estimated-time', '120']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.estimated_time == '120'

    def test_parse_analyze(self):
        """Test --analyze argument."""
        test_args = ['--analyze', '/path/to/workdir']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.analyze == Path('/path/to/workdir')

    def test_parse_report_config(self):
        """Test --report-config argument."""
        test_args = ['--analyze', '/path/to/workdir', '--report-config', 'report.yaml']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.report_config == Path('report.yaml')

    def test_parse_generate_setup_default(self):
        """Test --generate_setup with default filename."""
        test_args = ['--generate_setup']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.generate_setup == Path('iops_config.yaml')

    def test_parse_generate_setup_custom(self):
        """Test --generate_setup with custom filename."""
        test_args = ['--generate_setup', 'my_config.yaml']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.generate_setup == Path('my_config.yaml')

    def test_parse_version(self):
        """Test --version flag exits with version info."""
        test_args = ['--version']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            with pytest.raises(SystemExit):
                parse_arguments()


class TestInitializeLogger:
    """Test logger initialization."""

    def test_initialize_logger_defaults(self):
        """Test logger initialization with default arguments."""
        args = Mock()
        args.log_file = Path('test.log')
        args.no_log_terminal = False
        args.log_level = 'INFO'

        with patch('iops.main.setup_logger') as mock_setup:
            initialize_logger(args)
            mock_setup.assert_called_once_with(
                name='iops',
                log_file=Path('test.log'),
                to_stdout=True,
                to_file=True,
                level=20  # logging.INFO
            )

    def test_initialize_logger_no_terminal(self):
        """Test logger initialization with terminal logging disabled."""
        args = Mock()
        args.log_file = Path('test.log')
        args.no_log_terminal = True
        args.log_level = 'DEBUG'

        with patch('iops.main.setup_logger') as mock_setup:
            initialize_logger(args)
            mock_setup.assert_called_once()
            assert mock_setup.call_args[1]['to_stdout'] is False

    def test_initialize_logger_debug_level(self):
        """Test logger initialization with DEBUG level."""
        args = Mock()
        args.log_file = Path('test.log')
        args.no_log_terminal = False
        args.log_level = 'DEBUG'

        with patch('iops.main.setup_logger') as mock_setup:
            initialize_logger(args)
            assert mock_setup.call_args[1]['level'] == 10  # logging.DEBUG


class TestLogExecutionContext:
    """Test execution context logging."""

    def test_log_execution_context(self, sample_config_file):
        """Test that execution context is logged without errors."""
        from conftest import load_config

        cfg = load_config(sample_config_file)

        args = Mock()
        args.setup_file = sample_config_file
        args.use_cache = False
        args.max_core_hours = None

        logger = Mock()

        # Should not raise any exceptions
        log_execution_context(cfg, args, logger)

        # Verify logger was called with banner and info
        assert logger.info.called
        assert logger.debug.called


class TestGenerateSetup:
    """Test --generate_setup mode (template generation)."""

    def test_generate_setup_success(self):
        """Test successful template generation."""
        # Mock the import inside main()
        with patch('iops.setup.BenchmarkWizard') as mock_wizard_class:
            mock_wizard = MagicMock()
            mock_wizard.run.return_value = 'iops_config.yaml'
            mock_wizard_class.return_value = mock_wizard

            test_args = ['--generate_setup']
            with patch.object(sys, 'argv', ['iops'] + test_args):
                with patch('iops.main.initialize_logger'):
                    main()

            # Verify wizard was instantiated and run
            mock_wizard_class.assert_called_once()
            mock_wizard.run.assert_called_once()

    def test_generate_setup_custom_path(self):
        """Test template generation with custom output path."""
        with patch('iops.setup.BenchmarkWizard') as mock_wizard_class:
            mock_wizard = MagicMock()
            mock_wizard.run.return_value = 'custom.yaml'
            mock_wizard_class.return_value = mock_wizard

            test_args = ['--generate_setup', 'custom.yaml']
            with patch.object(sys, 'argv', ['iops'] + test_args):
                with patch('iops.main.initialize_logger'):
                    main()

            # Verify custom path was passed
            mock_wizard.run.assert_called_once_with(output_path='custom.yaml')

    def test_generate_setup_cancelled(self):
        """Test template generation when user cancels."""
        with patch('iops.setup.BenchmarkWizard') as mock_wizard_class:
            mock_wizard = MagicMock()
            mock_wizard.run.return_value = None
            mock_wizard_class.return_value = mock_wizard

            test_args = ['--generate_setup']
            with patch.object(sys, 'argv', ['iops'] + test_args):
                with patch('iops.main.initialize_logger'):
                    main()

            # Should handle None return gracefully
            mock_wizard.run.assert_called_once()

    def test_generate_setup_keyboard_interrupt(self):
        """Test template generation handles KeyboardInterrupt."""
        with patch('iops.setup.BenchmarkWizard') as mock_wizard_class:
            mock_wizard = MagicMock()
            mock_wizard.run.side_effect = KeyboardInterrupt()
            mock_wizard_class.return_value = mock_wizard

            test_args = ['--generate_setup']
            with patch.object(sys, 'argv', ['iops'] + test_args):
                with patch('iops.main.initialize_logger'):
                    # Should not raise, just log
                    main()

    def test_generate_setup_error_verbose(self):
        """Test template generation error with --verbose shows traceback."""
        with patch('iops.setup.BenchmarkWizard') as mock_wizard_class:
            mock_wizard = MagicMock()
            mock_wizard.run.side_effect = ValueError("Test error")
            mock_wizard_class.return_value = mock_wizard

            test_args = ['--generate_setup', '--verbose']
            with patch.object(sys, 'argv', ['iops'] + test_args):
                with patch('iops.main.initialize_logger'):
                    with pytest.raises(ValueError, match="Test error"):
                        main()

    def test_generate_setup_error_no_verbose(self):
        """Test template generation error without --verbose logs and returns."""
        with patch('iops.setup.BenchmarkWizard') as mock_wizard_class:
            mock_wizard = MagicMock()
            mock_wizard.run.side_effect = ValueError("Test error")
            mock_wizard_class.return_value = mock_wizard

            test_args = ['--generate_setup']
            with patch.object(sys, 'argv', ['iops'] + test_args):
                with patch('iops.main.initialize_logger'):
                    # Should not raise, just log
                    main()


class TestCheckSetup:
    """Test --check_setup mode (validation only)."""

    def test_check_setup_valid_config(self, sample_config_file):
        """Test validation with valid config file."""
        test_args = [str(sample_config_file), '--check_setup']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                # Should complete without errors
                main()

    def test_check_setup_invalid_config(self, tmp_path):
        """Test validation with invalid config file."""
        # Create invalid config (missing required fields)
        invalid_config = tmp_path / 'invalid.yaml'
        with open(invalid_config, 'w') as f:
            yaml.dump({'benchmark': {'name': 'Test'}}, f)  # Missing vars, command, etc.

        test_args = [str(invalid_config), '--check_setup']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                # Should log errors but not crash
                main()

    def test_check_setup_missing_file(self, tmp_path):
        """Test validation with missing config file."""
        missing_file = tmp_path / 'nonexistent.yaml'

        test_args = [str(missing_file), '--check_setup']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                # Should log error about missing file
                main()

    @patch('iops.config.loader.validate_yaml_config')
    def test_check_setup_multiple_errors(self, mock_validate, sample_config_file):
        """Test validation reports multiple errors."""
        mock_validate.return_value = [
            "Error 1: Missing required field",
            "Error 2: Invalid value type"
        ]

        test_args = [str(sample_config_file), '--check_setup']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        mock_validate.assert_called_once()


class TestAnalyze:
    """Test --analyze mode (report generation from workdir)."""

    @patch('iops.reporting.report_generator.generate_report_from_workdir')
    def test_analyze_success(self, mock_generate):
        """Test successful report generation."""
        mock_generate.return_value = Path('/workdir/report.html')

        test_args = ['--analyze', '/path/to/workdir']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        mock_generate.assert_called_once_with(
            Path('/path/to/workdir'),
            report_config=None
        )

    @patch('iops.reporting.report_generator.generate_report_from_workdir')
    @patch('iops.config.loader.load_report_config')
    def test_analyze_with_custom_report_config(self, mock_load_config, mock_generate):
        """Test report generation with custom report config."""
        mock_report_config = Mock()
        mock_load_config.return_value = mock_report_config
        mock_generate.return_value = Path('/workdir/report.html')

        test_args = ['--analyze', '/path/to/workdir', '--report-config', 'report.yaml']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        mock_load_config.assert_called_once_with(Path('report.yaml'))
        mock_generate.assert_called_once_with(
            Path('/path/to/workdir'),
            report_config=mock_report_config
        )

    @patch('iops.config.loader.load_report_config')
    def test_analyze_invalid_report_config(self, mock_load_config):
        """Test analyze with invalid report config file."""
        mock_load_config.side_effect = ConfigValidationError("Invalid config")

        test_args = ['--analyze', '/path/to/workdir', '--report-config', 'bad.yaml']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                # Should log error and return, not crash
                main()

    @patch('iops.config.loader.load_report_config')
    def test_analyze_invalid_report_config_verbose(self, mock_load_config):
        """Test analyze with invalid report config and --verbose."""
        mock_load_config.side_effect = ConfigValidationError("Invalid config")

        test_args = ['--analyze', '/path/to/workdir', '--report-config', 'bad.yaml', '--verbose']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                with pytest.raises(ConfigValidationError):
                    main()

    @patch('iops.reporting.report_generator.generate_report_from_workdir')
    def test_analyze_generation_error(self, mock_generate):
        """Test analyze when report generation fails."""
        mock_generate.side_effect = FileNotFoundError("Missing metadata")

        test_args = ['--analyze', '/path/to/workdir']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                # Should log error and return
                main()

    @patch('iops.reporting.report_generator.generate_report_from_workdir')
    def test_analyze_generation_error_verbose(self, mock_generate):
        """Test analyze error with --verbose shows traceback."""
        mock_generate.side_effect = FileNotFoundError("Missing metadata")

        test_args = ['--analyze', '/path/to/workdir', '--verbose']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                with pytest.raises(FileNotFoundError):
                    main()


class TestDryRun:
    """Test --dry-run mode."""

    @patch('iops.main.IOPSRunner')
    def test_dry_run_mode(self, mock_runner_class, sample_config_file):
        """Test dry-run mode calls runner.run_dry()."""
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner

        test_args = [str(sample_config_file), '--dry-run']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        # Verify run_dry was called instead of run
        mock_runner.run_dry.assert_called_once()
        mock_runner.run.assert_not_called()

    @patch('iops.main.IOPSRunner')
    def test_normal_run_mode(self, mock_runner_class, sample_config_file):
        """Test normal mode (no --dry-run) calls runner.run()."""
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner

        test_args = [str(sample_config_file)]

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        # Verify run was called
        mock_runner.run.assert_called_once()
        mock_runner.run_dry.assert_not_called()


class TestErrorHandling:
    """Test CLI error handling."""

    def test_no_setup_file_provided(self):
        """Test error when no setup file is provided for execution."""
        test_args = []

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                # Should log error and return
                main()

    def test_missing_setup_file(self, tmp_path):
        """Test error when setup file doesn't exist."""
        missing_file = tmp_path / 'missing.yaml'

        test_args = [str(missing_file)]

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                # load_generic_config will raise error
                with pytest.raises(FileNotFoundError):
                    main()

    def test_invalid_yaml_syntax(self, tmp_path):
        """Test error with invalid YAML syntax."""
        bad_yaml = tmp_path / 'bad.yaml'
        with open(bad_yaml, 'w') as f:
            f.write("invalid: yaml: syntax:\n  - bad\n  indentation")

        test_args = [str(bad_yaml)]

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                with pytest.raises(Exception):  # YAML parsing error
                    main()


class TestCommandCombinations:
    """Test various command-line argument combinations."""

    @patch('iops.main.IOPSRunner')
    def test_use_cache_with_max_core_hours(self, mock_runner_class, sample_config_file):
        """Test combining --use_cache and --max-core-hours."""
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner

        test_args = [
            str(sample_config_file),
            '--use_cache',
            '--max-core-hours', '500'
        ]

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        # Verify runner received correct args
        args = mock_runner_class.call_args[1]['args']
        assert args.use_cache is True
        assert args.max_core_hours == 500.0

    @patch('iops.main.IOPSRunner')
    def test_dry_run_with_cache(self, mock_runner_class, sample_config_file):
        """Test combining --dry-run with --use_cache."""
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner

        test_args = [
            str(sample_config_file),
            '--dry-run',
            '--use_cache'
        ]

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        # Verify both flags are respected
        args = mock_runner_class.call_args[1]['args']
        assert args.dry_run is True
        assert args.use_cache is True
        mock_runner.run_dry.assert_called_once()

    @patch('iops.main.IOPSRunner')
    def test_all_logging_options(self, mock_runner_class, sample_config_file):
        """Test all logging-related options together."""
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner

        test_args = [
            str(sample_config_file),
            '--log_level', 'DEBUG',
            '--log_file', 'custom.log',
            '--no-log-terminal',
            '--verbose'
        ]

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger') as mock_init_logger:
                main()

        # Verify logger initialization
        args = mock_init_logger.call_args[0][0]
        assert args.log_level == 'DEBUG'
        assert args.log_file == Path('custom.log')
        assert args.no_log_terminal is True
        assert args.verbose is True


class TestIntegrationWithRunner:
    """Test CLI integration with IOPSRunner."""

    @patch('iops.main.IOPSRunner')
    def test_runner_receives_correct_config(self, mock_runner_class, sample_config_file):
        """Test that runner receives correctly loaded config."""
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner

        test_args = [str(sample_config_file)]

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        # Verify runner was instantiated with config
        assert mock_runner_class.called
        cfg = mock_runner_class.call_args[1]['cfg']
        assert cfg.benchmark.name == 'Test Benchmark'

    @patch('iops.main.IOPSRunner')
    def test_runner_receives_args(self, mock_runner_class, sample_config_file):
        """Test that runner receives command-line args."""
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner

        test_args = [
            str(sample_config_file),
            '--use_cache',
            '--max-core-hours', '1000'
        ]

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        # Verify args object passed to runner
        args = mock_runner_class.call_args[1]['args']
        assert args.use_cache is True
        assert args.max_core_hours == 1000.0


class TestEstimatedTime:
    """Test --estimated-time argument handling."""

    @patch('iops.main.IOPSRunner')
    def test_estimated_time_single_value(self, mock_runner_class, sample_config_file):
        """Test --estimated-time with single value."""
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner

        test_args = [str(sample_config_file), '--estimated-time', '120']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        args = mock_runner_class.call_args[1]['args']
        assert args.estimated_time == '120'

    @patch('iops.main.IOPSRunner')
    def test_estimated_time_multiple_values(self, mock_runner_class, sample_config_file):
        """Test --estimated-time with comma-separated values."""
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner

        test_args = [str(sample_config_file), '--estimated-time', '60,120,300']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        args = mock_runner_class.call_args[1]['args']
        assert args.estimated_time == '60,120,300'


class TestSpecialModes:
    """Test special CLI modes that exit early."""

    def test_generate_setup_exits_early(self):
        """Test that --generate_setup doesn't require setup_file."""
        test_args = ['--generate_setup']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                with patch('iops.setup.BenchmarkWizard') as mock_wizard:
                    mock_wizard.return_value.run.return_value = 'config.yaml'
                    main()

        # Should complete without error about missing setup_file

    def test_analyze_exits_early(self):
        """Test that --analyze doesn't require setup_file."""
        test_args = ['--analyze', '/workdir']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                with patch('iops.reporting.report_generator.generate_report_from_workdir') as mock_gen:
                    mock_gen.return_value = Path('/workdir/report.html')
                    main()

        # Should complete without error about missing setup_file

    def test_check_setup_requires_setup_file(self):
        """Test that --check_setup still requires setup_file."""
        test_args = ['--check_setup']

        # This should work but not crash (will log error about missing file)
        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()
