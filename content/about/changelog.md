---
title: "Changelog"
---

All notable changes to IOPS are documented here.

## [3.5.0] - Unreleased

### Added
- Resource tracing for CPU and memory monitoring (`trace_resources`, `trace_interval`)
- Single-allocation mode for batch SLURM execution (`slurm_options.allocation`) [experimental]
- `iops cache rebuild` command to exclude variables retroactively
- Parser script context injection (`vars`, `env`, `execution_id`, `repetition` globals)
- `--partial` and `--min-reps` flags for partial archive creation
- Unknown key validation with "did you mean?" suggestions for YAML config
- Core-hours tracking for cache hits in dry-run estimates

### Changed
- Renamed `executor_options` to `slurm_options` (old name deprecated, remove in 3.7.0)
- Removed `scripts[].submit` field 
- Removed `output.sink.include` option
- `iops generate` now defaults to SLURM executor (use `--local` for local)
- Separate user labels from IOPS internal metadata in output
- Default output path when `output.sink.path` not specified

### Fixed
- Dry-run cache lookup using wrong repetition values
- Constraint evaluation order (swept vars before derived expressions)

## [3.4.0] - 2026-01-13

### Added
- Archive module for workdir portability (`iops archive create/extract`)
- Progress bars for archive operations
- Conditional variables with `when`/`default` fields
- Watch mode for real-time execution monitoring (`iops watch`)
- Metrics display and filtering in watch mode
- Cache indicator and `--cached` filter for find/watch commands
- `fallback_to_exhaustive` option for Bayesian planner
- `create_folders_upfront` benchmark option
- Client-side search for documentation site

### Changed
- Centralized validation logic in loader.py
- Restructured documentation for v3.0
- Reorganized code structure to align with CLI commands

### Fixed
- Archive progress bar performance with compression level tuning
- Metrics not showing when using `--hide` in watch mode
- Duration tracking to use cached sysinfo
- Bayesian planner edge case bugs
- Search index to include full page content
- File permission test when running as root

## [3.3.0] - 2026-01-09

- Subcommand-based CLI structure (`run`, `check`, `generate`, `report`, `find`)
- `find` command to explore execution folders with parameter filtering
- Execution status tracking with `--status` filter (SUCCEEDED, FAILED, ERROR)
- `--show-command` and `--full` flags for find output
- YAML file shorthand: `iops config.yaml` works as `iops run config.yaml`
- `dryrun_` prefix for dry-run folders
- Renamed `sqlite_db` to `cache_file`
- Portable workdir metadata with relative paths
- System info collection and config validation

## [3.2.0] - 2026-01-08

- Enhanced Bayesian optimization with `base_estimator`, `xi`, `kappa`, `n_iterations`
- Search space efficiency statistics in Bayesian reports
- Variable values shown on hover in Bayesian evolution plot
- Renamed `target_metric` to `objective_metric`
- Removed rounds feature and simplified planner architecture
- Made pyarrow an optional dependency

## [3.1.0] - 2025-12-23

- User-configurable reporting system with 8 plot types
- `reporting` configuration section for plot customization
- `--report-config` CLI option to regenerate reports with different settings
- Auto-generated `report_config.yaml` templates after execution
- Theme configuration (colors, fonts, plotly styles)
- Spack package support

## [3.0.0] - 2025-12-20

Major overhaul transforming IOPS into a generic benchmark orchestration framework.

- Generic framework supporting any parametric experiment
- `iops generate` to create configuration templates
- Interactive setup wizard for guided configuration
- Bayesian optimization for intelligent parameter search
- Random sampling planner for parameter space exploration
- Core-hours budget tracking for HPC clusters
- Dry-run mode to preview executions with resource estimates
- HTML report generation with interactive Plotly charts
- Result caching with `--use-cache` flag
- SLURM cluster support with automatic job management
- Parameter constraints to filter invalid configurations
- Configurable SLURM commands via `slurm_options`
- `exhaustive_vars` for hybrid search strategies
- PyPI packaging as `iops-benchmark`

## [2.0.0] - 2024

Internal development version that introduced architectural changes leading to 3.0.0.

- Database-backed storage for results
- Improved executor architecture with better SLURM support
- Enhanced test coverage and validation
- Refactored planner with greedy strategy and caching

## [1.0.0] - 2023-10-19

Initial release of IOPS as an IOR-specific benchmark orchestration tool.

- IOR benchmark automation with parametric sweeps
- SLURM and local execution support
- Multi-round optimization with binary search heuristics
- HTML report generation with bandwidth graphs
- Configuration via INI files
- Stripe folder management for parallel filesystems
- Test repetitions for statistical validity
- Progress tracking and interruption handling
