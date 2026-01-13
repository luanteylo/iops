"""Unit tests for IOPS CLI (Command Line Interface)."""

import json
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
from iops.results.find import (
    find_executions,
    INDEX_FILENAME,
    PARAMS_FILENAME,
)
from iops.config.models import ConfigValidationError


class TestLoadVersion:
    """Test version loading from VERSION file."""

    def test_load_version_success(self):
        """Test loading version from VERSION file."""
        version = load_version()
        assert version is not None
        assert isinstance(version, str)
        # Version should be in format X.Y.Z or X.Y.Z.devN (PEP 440)
        parts = version.split('.')
        assert len(parts) >= 3
        # First three parts should be numeric (major.minor.patch)
        assert all(part.isdigit() for part in parts[:3])

    def test_load_version_missing_file(self):
        """Test error when VERSION file is missing."""
        with patch('iops.main.Path') as mock_path:
            mock_version_file = MagicMock()
            mock_version_file.exists.return_value = False
            mock_path.return_value.parent.__truediv__.return_value = mock_version_file

            with pytest.raises(FileNotFoundError, match="Version file not found"):
                load_version()


class TestModuleExecution:
    """Test that iops can be run as a module (python -m iops)."""

    def test_module_execution_version(self):
        """Test running 'python -m iops --version' works."""
        import subprocess
        result = subprocess.run(
            [sys.executable, '-m', 'iops', '--version'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'IOPS Tool v' in result.stdout

    def test_module_execution_help(self):
        """Test running 'python -m iops --help' works."""
        import subprocess
        result = subprocess.run(
            [sys.executable, '-m', 'iops', '--help'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'iops' in result.stdout.lower()

    def test_module_execution_run_help(self):
        """Test running 'python -m iops run --help' works."""
        import subprocess
        result = subprocess.run(
            [sys.executable, '-m', 'iops', 'run', '--help'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert '--dry-run' in result.stdout


class TestParseArguments:
    """Test command-line argument parsing with subcommands."""

    def test_parse_run_minimal(self):
        """Test parsing 'run' command with just config file."""
        test_args = ['run', 'test_config.yaml']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.command == 'run'
            assert args.config_file == Path('test_config.yaml')
            assert not args.dry_run
            assert not args.use_cache
            assert args.log_level == 'INFO'

    def test_parse_check(self):
        """Test 'check' command."""
        test_args = ['check', 'config.yaml']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.command == 'check'
            assert args.config_file == Path('config.yaml')

    def test_parse_dry_run(self):
        """Test --dry-run flag with run command."""
        test_args = ['run', 'config.yaml', '--dry-run']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.command == 'run'
            assert args.dry_run is True

    def test_parse_use_cache(self):
        """Test --use-cache flag with run command."""
        test_args = ['run', 'config.yaml', '--use-cache']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.use_cache is True

    def test_parse_max_core_hours(self):
        """Test --max-core-hours argument with run command."""
        test_args = ['run', 'config.yaml', '--max-core-hours', '1000']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.max_core_hours == 1000.0

    def test_parse_log_level(self):
        """Test --log-level argument."""
        test_args = ['run', 'config.yaml', '--log-level', 'DEBUG']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.log_level == 'DEBUG'

    def test_parse_log_file(self):
        """Test --log-file argument."""
        test_args = ['run', 'config.yaml', '--log-file', 'custom.log']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.log_file == Path('custom.log')

    def test_parse_no_log_terminal(self):
        """Test --no-log-terminal flag."""
        test_args = ['run', 'config.yaml', '--no-log-terminal']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.no_log_terminal is True

    def test_parse_verbose(self):
        """Test --verbose flag."""
        test_args = ['run', 'config.yaml', '--verbose']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.verbose is True

    def test_parse_time_estimate(self):
        """Test --time-estimate argument."""
        test_args = ['run', 'config.yaml', '--time-estimate', '120']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.time_estimate == '120'

    def test_parse_report(self):
        """Test 'report' command."""
        test_args = ['report', '/path/to/workdir']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.command == 'report'
            assert args.path == Path('/path/to/workdir')

    def test_parse_report_config(self):
        """Test --report-config argument with report command."""
        test_args = ['report', '/path/to/workdir', '--report-config', 'report.yaml']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.report_config == Path('report.yaml')

    def test_parse_generate_default(self):
        """Test 'generate' command with default filename."""
        test_args = ['generate']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.command == 'generate'
            assert args.output == Path('iops_config.yaml')

    def test_parse_generate_custom(self):
        """Test 'generate' command with custom filename."""
        test_args = ['generate', 'my_config.yaml']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.output == Path('my_config.yaml')

    def test_parse_version(self):
        """Test --version flag exits with version info."""
        test_args = ['--version']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            with pytest.raises(SystemExit):
                parse_arguments()

    def test_parse_no_command_shows_help(self):
        """Test that running without command shows help and exits."""
        test_args = []
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
        args.config_file = sample_config_file
        args.use_cache = False
        args.max_core_hours = None

        logger = Mock()

        # Should not raise any exceptions
        log_execution_context(cfg, args, logger)

        # Verify logger was called with banner and info
        assert logger.info.called
        assert logger.debug.called


class TestGenerate:
    """Test 'generate' command (template generation)."""

    def test_generate_success(self):
        """Test successful template generation."""
        # Mock the import inside main()
        with patch('iops.setup.BenchmarkWizard') as mock_wizard_class:
            mock_wizard = MagicMock()
            mock_wizard.run.return_value = 'iops_config.yaml'
            mock_wizard_class.return_value = mock_wizard

            test_args = ['generate']
            with patch.object(sys, 'argv', ['iops'] + test_args):
                with patch('iops.main.initialize_logger'):
                    main()

            # Verify wizard was instantiated and run
            mock_wizard_class.assert_called_once()
            mock_wizard.run.assert_called_once()

    def test_generate_custom_path(self):
        """Test template generation with custom output path."""
        with patch('iops.setup.BenchmarkWizard') as mock_wizard_class:
            mock_wizard = MagicMock()
            mock_wizard.run.return_value = 'custom.yaml'
            mock_wizard_class.return_value = mock_wizard

            test_args = ['generate', 'custom.yaml']
            with patch.object(sys, 'argv', ['iops'] + test_args):
                with patch('iops.main.initialize_logger'):
                    main()

            # Verify custom path was passed with default options
            mock_wizard.run.assert_called_once_with(
                output_path='custom.yaml',
                executor='local',
                benchmark='ior',
                full_template=False,
                copy_examples=False
            )

    def test_generate_cancelled(self):
        """Test template generation when user cancels."""
        with patch('iops.setup.BenchmarkWizard') as mock_wizard_class:
            mock_wizard = MagicMock()
            mock_wizard.run.return_value = None
            mock_wizard_class.return_value = mock_wizard

            test_args = ['generate']
            with patch.object(sys, 'argv', ['iops'] + test_args):
                with patch('iops.main.initialize_logger'):
                    main()

            # Should handle None return gracefully
            mock_wizard.run.assert_called_once()

    def test_generate_keyboard_interrupt(self):
        """Test template generation handles KeyboardInterrupt."""
        with patch('iops.setup.BenchmarkWizard') as mock_wizard_class:
            mock_wizard = MagicMock()
            mock_wizard.run.side_effect = KeyboardInterrupt()
            mock_wizard_class.return_value = mock_wizard

            test_args = ['generate']
            with patch.object(sys, 'argv', ['iops'] + test_args):
                with patch('iops.main.initialize_logger'):
                    # Should not raise, just log
                    main()

    def test_generate_error_verbose(self):
        """Test template generation error with --verbose shows traceback."""
        with patch('iops.setup.BenchmarkWizard') as mock_wizard_class:
            mock_wizard = MagicMock()
            mock_wizard.run.side_effect = ValueError("Test error")
            mock_wizard_class.return_value = mock_wizard

            test_args = ['generate', '--verbose']
            with patch.object(sys, 'argv', ['iops'] + test_args):
                with patch('iops.main.initialize_logger'):
                    with pytest.raises(ValueError, match="Test error"):
                        main()

    def test_generate_error_no_verbose(self):
        """Test template generation error without --verbose logs and returns."""
        with patch('iops.setup.BenchmarkWizard') as mock_wizard_class:
            mock_wizard = MagicMock()
            mock_wizard.run.side_effect = ValueError("Test error")
            mock_wizard_class.return_value = mock_wizard

            test_args = ['generate']
            with patch.object(sys, 'argv', ['iops'] + test_args):
                with patch('iops.main.initialize_logger'):
                    # Should not raise, just log
                    main()


class TestCheck:
    """Test 'check' command (validation only)."""

    def test_check_valid_config(self, sample_config_file):
        """Test validation with valid config file."""
        test_args = ['check', str(sample_config_file)]

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                # Should complete without errors
                main()

    def test_check_invalid_config(self, tmp_path):
        """Test validation with invalid config file."""
        # Create invalid config (missing required fields)
        invalid_config = tmp_path / 'invalid.yaml'
        with open(invalid_config, 'w') as f:
            yaml.dump({'benchmark': {'name': 'Test'}}, f)  # Missing vars, command, etc.

        test_args = ['check', str(invalid_config)]

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                # Should log errors but not crash
                main()

    def test_check_missing_file(self, tmp_path):
        """Test validation with missing config file."""
        missing_file = tmp_path / 'nonexistent.yaml'

        test_args = ['check', str(missing_file)]

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                # Should log error about missing file
                main()

    @patch('iops.config.loader.validate_yaml_config')
    def test_check_multiple_errors(self, mock_validate, sample_config_file):
        """Test validation reports multiple errors."""
        mock_validate.return_value = [
            "Error 1: Missing required field",
            "Error 2: Invalid value type"
        ]

        test_args = ['check', str(sample_config_file)]

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        mock_validate.assert_called_once()


class TestReport:
    """Test 'report' command (report generation from workdir)."""

    @patch('iops.reporting.report_generator.generate_report_from_workdir')
    def test_report_success(self, mock_generate):
        """Test successful report generation."""
        mock_generate.return_value = Path('/workdir/report.html')

        test_args = ['report', '/path/to/workdir']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        mock_generate.assert_called_once_with(
            Path('/path/to/workdir'),
            report_config=None
        )

    @patch('iops.reporting.report_generator.generate_report_from_workdir')
    @patch('iops.config.loader.load_report_config')
    def test_report_with_custom_report_config(self, mock_load_config, mock_generate):
        """Test report generation with custom report config."""
        mock_report_config = Mock()
        mock_load_config.return_value = mock_report_config
        mock_generate.return_value = Path('/workdir/report.html')

        test_args = ['report', '/path/to/workdir', '--report-config', 'report.yaml']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        mock_load_config.assert_called_once_with(Path('report.yaml'))
        mock_generate.assert_called_once_with(
            Path('/path/to/workdir'),
            report_config=mock_report_config
        )

    @patch('iops.config.loader.load_report_config')
    def test_report_invalid_report_config(self, mock_load_config):
        """Test report with invalid report config file."""
        mock_load_config.side_effect = ConfigValidationError("Invalid config")

        test_args = ['report', '/path/to/workdir', '--report-config', 'bad.yaml']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                # Should log error and return, not crash
                main()

    @patch('iops.config.loader.load_report_config')
    def test_report_invalid_report_config_verbose(self, mock_load_config):
        """Test report with invalid report config and --verbose."""
        mock_load_config.side_effect = ConfigValidationError("Invalid config")

        test_args = ['report', '/path/to/workdir', '--report-config', 'bad.yaml', '--verbose']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                with pytest.raises(ConfigValidationError):
                    main()

    @patch('iops.reporting.report_generator.generate_report_from_workdir')
    def test_report_generation_error(self, mock_generate):
        """Test report when report generation fails."""
        mock_generate.side_effect = FileNotFoundError("Missing metadata")

        test_args = ['report', '/path/to/workdir']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                # Should log error and return
                main()

    @patch('iops.reporting.report_generator.generate_report_from_workdir')
    def test_report_generation_error_verbose(self, mock_generate):
        """Test report error with --verbose shows traceback."""
        mock_generate.side_effect = FileNotFoundError("Missing metadata")

        test_args = ['report', '/path/to/workdir', '--verbose']

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

        test_args = ['run', str(sample_config_file), '--dry-run']

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

        test_args = ['run', str(sample_config_file)]

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        # Verify run was called
        mock_runner.run.assert_called_once()
        mock_runner.run_dry.assert_not_called()


class TestErrorHandling:
    """Test CLI error handling."""

    def test_no_command_provided(self):
        """Test error when no command is provided."""
        test_args = []

        with patch.object(sys, 'argv', ['iops'] + test_args):
            # Should exit with error (shows help)
            with pytest.raises(SystemExit):
                parse_arguments()

    def test_missing_setup_file(self, tmp_path):
        """Test error when setup file doesn't exist - should handle gracefully."""
        missing_file = tmp_path / 'missing.yaml'

        test_args = ['run', str(missing_file)]

        with patch.object(sys, 'argv', ['iops'] + test_args):
            mock_logger = MagicMock()
            with patch('iops.main.initialize_logger', return_value=mock_logger):
                # Should handle error gracefully and return (not raise)
                main()
                # Verify error was logged
                assert mock_logger.error.called

    def test_invalid_yaml_syntax(self, tmp_path):
        """Test error with invalid YAML syntax - should handle gracefully."""
        bad_yaml = tmp_path / 'bad.yaml'
        with open(bad_yaml, 'w') as f:
            f.write("invalid: yaml: syntax:\n  - bad\n  indentation")

        test_args = ['run', str(bad_yaml)]

        with patch.object(sys, 'argv', ['iops'] + test_args):
            mock_logger = MagicMock()
            with patch('iops.main.initialize_logger', return_value=mock_logger):
                # Should handle error gracefully and return (not raise)
                main()
                # Verify error was logged
                assert mock_logger.error.called


class TestCommandCombinations:
    """Test various command-line argument combinations."""

    @patch('iops.main.IOPSRunner')
    def test_use_cache_with_max_core_hours(self, mock_runner_class, sample_config_file):
        """Test combining --use-cache and --max-core-hours."""
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner

        test_args = [
            'run', str(sample_config_file),
            '--use-cache',
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
        """Test combining --dry-run with --use-cache."""
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner

        test_args = [
            'run', str(sample_config_file),
            '--dry-run',
            '--use-cache'
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
            'run', str(sample_config_file),
            '--log-level', 'DEBUG',
            '--log-file', 'custom.log',
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

        test_args = ['run', str(sample_config_file)]

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
            'run', str(sample_config_file),
            '--use-cache',
            '--max-core-hours', '1000'
        ]

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        # Verify args object passed to runner
        args = mock_runner_class.call_args[1]['args']
        assert args.use_cache is True
        assert args.max_core_hours == 1000.0


class TestTimeEstimate:
    """Test --time-estimate argument handling."""

    @patch('iops.main.IOPSRunner')
    def test_time_estimate_single_value(self, mock_runner_class, sample_config_file):
        """Test --time-estimate with single value."""
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner

        test_args = ['run', str(sample_config_file), '--time-estimate', '120']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        args = mock_runner_class.call_args[1]['args']
        assert args.time_estimate == '120'

    @patch('iops.main.IOPSRunner')
    def test_time_estimate_multiple_values(self, mock_runner_class, sample_config_file):
        """Test --time-estimate with comma-separated values."""
        mock_runner = MagicMock()
        mock_runner_class.return_value = mock_runner

        test_args = ['run', str(sample_config_file), '--time-estimate', '60,120,300']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                main()

        args = mock_runner_class.call_args[1]['args']
        assert args.time_estimate == '60,120,300'


class TestSpecialModes:
    """Test special CLI modes that exit early."""

    def test_generate_exits_early(self):
        """Test that 'generate' command doesn't require config_file."""
        test_args = ['generate']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                with patch('iops.setup.BenchmarkWizard') as mock_wizard:
                    mock_wizard.return_value.run.return_value = 'config.yaml'
                    main()

        # Should complete without error about missing config_file

    def test_report_exits_early(self):
        """Test that 'report' command doesn't require config_file."""
        test_args = ['report', '/workdir']

        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                with patch('iops.reporting.report_generator.generate_report_from_workdir') as mock_gen:
                    mock_gen.return_value = Path('/workdir/report.html')
                    main()

        # Should complete without error about missing config_file

    def test_check_requires_config_file(self):
        """Test that 'check' requires config_file argument."""
        test_args = ['check']

        # This should fail because check requires config_file argument
        with patch.object(sys, 'argv', ['iops'] + test_args):
            with pytest.raises(SystemExit):
                parse_arguments()


class TestFindCommand:
    """Test 'find' command (execution folder lookup)."""

    def test_parse_find_argument(self):
        """Test 'find' command parsing."""
        test_args = ['find', '/path/to/workdir']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.command == 'find'
            assert args.path == Path('/path/to/workdir')

    def test_parse_find_with_filter(self):
        """Test 'find' with filter arguments."""
        test_args = ['find', '/path/to/workdir', 'nodes=4', 'ppn=8']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.command == 'find'
            assert args.path == Path('/path/to/workdir')
            assert args.filter == ['nodes=4', 'ppn=8']

    def test_find_with_index_file(self, tmp_path):
        """Test find_executions with index file."""
        # Create index file
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1, "ppn": 4}},
                "exec_0002": {"path": "runs/exec_0002", "params": {"nodes": 2, "ppn": 4}},
                "exec_0003": {"path": "runs/exec_0003", "params": {"nodes": 4, "ppn": 8}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Test without filter (shows all)
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'runs/exec_0001' in output
            assert 'runs/exec_0002' in output
            assert 'runs/exec_0003' in output

    def test_find_with_filter(self, tmp_path):
        """Test find_executions with filter."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1, "ppn": 4}},
                "exec_0002": {"path": "runs/exec_0002", "params": {"nodes": 2, "ppn": 4}},
                "exec_0003": {"path": "runs/exec_0003", "params": {"nodes": 4, "ppn": 8}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Filter by nodes=2
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, filters=['nodes=2'])
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'runs/exec_0002' in output
            assert 'exec_0001' not in output
            assert 'exec_0003' not in output

    def test_find_with_params_file(self, tmp_path):
        """Test find_executions with params file (exec folder)."""
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir()

        params = {"nodes": 4, "ppn": 8, "block_size": "1M"}
        params_file = exec_dir / PARAMS_FILENAME
        with open(params_file, 'w') as f:
            json.dump(params, f)

        # Create repetition folders
        (exec_dir / "repetition_001").mkdir()
        (exec_dir / "repetition_002").mkdir()

        with patch('builtins.print') as mock_print:
            find_executions(exec_dir)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'nodes: 4' in output
            assert 'ppn: 8' in output
            assert 'Repetitions: 2' in output

    def test_find_no_data(self, tmp_path):
        """Test find_executions with no IOPS data."""
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'No IOPS execution data found' in output

    def test_find_with_run_dirs(self, tmp_path):
        """Test find_executions in workdir containing run_XXX folders."""
        # Create run_001 with index
        run_dir = tmp_path / "run_001"
        run_dir.mkdir()

        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1}},
            }
        }
        index_file = run_dir / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'run_001' in output

    def test_find_invalid_filter_format(self, tmp_path):
        """Test find_executions with invalid filter format."""
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, filters=['invalid_filter'])
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'Invalid filter format' in output

    def test_find_no_matches(self, tmp_path):
        """Test find_executions when filter matches nothing."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, filters=['nodes=999'])
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'No executions match' in output

    def test_find_main_integration(self, tmp_path):
        """Test 'find' command through main()."""
        index = {
            "benchmark": "Test",
            "executions": {"exec_0001": {"path": "runs/exec_0001", "params": {"x": 1}}}
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        test_args = ['find', str(tmp_path)]
        with patch.object(sys, 'argv', ['iops'] + test_args):
            with patch('iops.main.initialize_logger'):
                # Should complete without error
                main()

    def test_find_multiple_filters(self, tmp_path):
        """Test find_executions with multiple filters (AND logic)."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1, "ppn": 4, "threads": 2}},
                "exec_0002": {"path": "runs/exec_0002", "params": {"nodes": 2, "ppn": 4, "threads": 2}},
                "exec_0003": {"path": "runs/exec_0003", "params": {"nodes": 2, "ppn": 8, "threads": 4}},
                "exec_0004": {"path": "runs/exec_0004", "params": {"nodes": 2, "ppn": 4, "threads": 4}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Filter by nodes=2 AND ppn=4 (should match exec_0002 and exec_0004)
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, filters=['nodes=2', 'ppn=4'])
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'runs/exec_0002' in output
            assert 'runs/exec_0004' in output
            assert 'exec_0001' not in output
            assert 'exec_0003' not in output

    def test_find_filter_type_coercion(self, tmp_path):
        """Test that filters compare values as strings (e.g., '4' matches 4)."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1, "ppn": 4}},
                "exec_0002": {"path": "runs/exec_0002", "params": {"nodes": 2, "ppn": 8}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Filter with string value should match integer in params
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, filters=['ppn=8'])
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'runs/exec_0002' in output
            assert 'exec_0001' not in output

    def test_find_filter_missing_variable(self, tmp_path):
        """Test filter for variable that doesn't exist in some executions."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1, "ppn": 4}},
                "exec_0002": {"path": "runs/exec_0002", "params": {"nodes": 2, "ppn": 8, "threads": 16}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Filter by variable that only exists in exec_0002
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, filters=['threads=16'])
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'runs/exec_0002' in output
            assert 'exec_0001' not in output

    def test_find_empty_executions(self, tmp_path):
        """Test find with index containing no executions."""
        index = {
            "benchmark": "Empty Benchmark",
            "executions": {}
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'No executions found' in output

    def test_find_malformed_index_json(self, tmp_path):
        """Test find handles malformed JSON in index file gracefully."""
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            f.write("{ invalid json }")

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'Error reading' in output

    def test_find_malformed_params_json(self, tmp_path):
        """Test find handles malformed JSON in params file gracefully."""
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir()

        params_file = exec_dir / PARAMS_FILENAME
        with open(params_file, 'w') as f:
            f.write("{ malformed: json }")

        with patch('builtins.print') as mock_print:
            find_executions(exec_dir)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'Error reading' in output

    def test_find_params_file_no_repetitions(self, tmp_path):
        """Test find with params file but no repetition folders."""
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir()

        params = {"nodes": 4, "ppn": 8}
        params_file = exec_dir / PARAMS_FILENAME
        with open(params_file, 'w') as f:
            json.dump(params, f)

        with patch('builtins.print') as mock_print:
            find_executions(exec_dir)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'nodes: 4' in output
            # Should not show repetitions section if none exist
            assert 'Repetitions' not in output

    def test_find_multiple_run_dirs(self, tmp_path):
        """Test find in workdir with multiple run_XXX folders."""
        # Create run_001 with index
        run_dir1 = tmp_path / "run_001"
        run_dir1.mkdir()
        index1 = {
            "benchmark": "Benchmark Run 1",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1}},
            }
        }
        with open(run_dir1 / INDEX_FILENAME, 'w') as f:
            json.dump(index1, f)

        # Create run_002 with index
        run_dir2 = tmp_path / "run_002"
        run_dir2.mkdir()
        index2 = {
            "benchmark": "Benchmark Run 2",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 2}},
            }
        }
        with open(run_dir2 / INDEX_FILENAME, 'w') as f:
            json.dump(index2, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            # Should show both run directories
            assert 'run_001' in output
            assert 'run_002' in output

    def test_find_with_string_and_numeric_params(self, tmp_path):
        """Test find displays string and numeric parameters correctly."""
        index = {
            "benchmark": "Mixed Types Benchmark",
            "executions": {
                "exec_0001": {
                    "path": "runs/exec_0001",
                    "params": {
                        "nodes": 4,
                        "block_size": "1M",
                        "io_pattern": "sequential",
                        "threads": 16
                    }
                },
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            # All parameter names should appear in header or data
            assert 'nodes' in output
            assert 'block_size' in output
            assert 'io_pattern' in output
            assert 'threads' in output

    def test_find_filter_with_equals_in_value(self, tmp_path):
        """Test filter parsing when value contains '=' character."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"equation": "x=y+z"}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Filter with value containing '=' should use split maxsplit=1
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, filters=['equation=x=y+z'])
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            # Should find the execution since split(maxsplit=1) handles this
            assert 'runs/exec_0001' in output

    def test_find_sorted_output(self, tmp_path):
        """Test that executions are displayed in sorted order."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0003": {"path": "runs/exec_0003", "params": {"nodes": 3}},
                "exec_0001": {"path": "runs/exec_0001", "params": {"nodes": 1}},
                "exec_0002": {"path": "runs/exec_0002", "params": {"nodes": 2}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path)
            # Get all print calls as list
            calls = [str(call) for call in mock_print.call_args_list]
            output = '\n'.join(calls)

            # Find positions of executions in output
            pos_1 = output.find('exec_0001')
            pos_2 = output.find('exec_0002')
            pos_3 = output.find('exec_0003')

            # Should appear in sorted order (if they appear)
            if pos_1 != -1 and pos_2 != -1 and pos_3 != -1:
                assert pos_1 < pos_2 < pos_3

    def test_find_params_file_sorted_params(self, tmp_path):
        """Test that parameters are displayed in sorted order for single execution."""
        exec_dir = tmp_path / "exec_0001"
        exec_dir.mkdir()

        params = {
            "z_var": 1,
            "a_var": 2,
            "m_var": 3,
        }
        params_file = exec_dir / PARAMS_FILENAME
        with open(params_file, 'w') as f:
            json.dump(params, f)

        with patch('builtins.print') as mock_print:
            find_executions(exec_dir)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # Parameters should be displayed in sorted order
            pos_a = output.find('a_var')
            pos_m = output.find('m_var')
            pos_z = output.find('z_var')

            assert pos_a < pos_m < pos_z

    def test_find_column_alignment(self, tmp_path):
        """Test that output columns are properly aligned."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {"path": "runs/exec_0001", "params": {"short": 1, "very_long_variable_name": 2}},
                "exec_0002": {"path": "runs/exec_0002", "params": {"short": 99999, "very_long_variable_name": 1}},
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)

            # Should contain header separator (dashes)
            assert '-' in output
            # Should have column headers
            assert 'Path' in output or 'path' in output

    def test_parse_show_command_argument(self):
        """Test --show-command argument parsing."""
        test_args = ['find', '/path/to/workdir', '--show-command']
        with patch.object(sys, 'argv', ['iops'] + test_args):
            args = parse_arguments()
            assert args.command == 'find'
            assert args.path == Path('/path/to/workdir')
            assert args.show_command is True

    def test_find_with_show_command(self, tmp_path):
        """Test find_executions with --show-command displays command column."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {
                    "path": "runs/exec_0001",
                    "params": {"nodes": 1, "ppn": 4},
                    "command": "mpirun -np 4 ./benchmark"
                },
                "exec_0002": {
                    "path": "runs/exec_0002",
                    "params": {"nodes": 2, "ppn": 8},
                    "command": "mpirun -np 16 ./benchmark"
                },
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Without --show-command, command should not appear
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, show_command=False)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'mpirun' not in output

        # With --show-command, command should appear
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, show_command=True)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'Command' in output
            assert 'mpirun -np 4 ./benchmark' in output
            assert 'mpirun -np 16 ./benchmark' in output

    def test_find_show_command_with_filter(self, tmp_path):
        """Test --show-command works with filters."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {
                    "path": "runs/exec_0001",
                    "params": {"nodes": 1},
                    "command": "cmd1"
                },
                "exec_0002": {
                    "path": "runs/exec_0002",
                    "params": {"nodes": 2},
                    "command": "cmd2"
                },
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, filters=['nodes=2'], show_command=True)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'cmd2' in output
            assert 'cmd1' not in output

    def test_find_show_command_missing_command(self, tmp_path):
        """Test --show-command handles missing command field gracefully."""
        index = {
            "benchmark": "Test Benchmark",
            "executions": {
                "exec_0001": {
                    "path": "runs/exec_0001",
                    "params": {"nodes": 1},
                    # No command field
                },
            }
        }
        index_file = tmp_path / INDEX_FILENAME
        with open(index_file, 'w') as f:
            json.dump(index, f)

        # Should not crash
        with patch('builtins.print') as mock_print:
            find_executions(tmp_path, show_command=True)
            output = '\n'.join(str(call) for call in mock_print.call_args_list)
            assert 'runs/exec_0001' in output
