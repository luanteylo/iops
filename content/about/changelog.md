---
title: "Changelog"
---

All notable changes to IOPS are documented here.

## [Unreleased]

### Added
- GPU sampling probe (`probes.gpu_sampling`) for monitoring GPU metrics during benchmark execution
  - Collects utilization, memory usage, temperature, power draw, and clock speeds
  - Supports NVIDIA GPUs via `nvidia-smi`, designed for future AMD/Intel extension
  - Gracefully skips when no supported GPU is detected
  - Per-node GPU sample files (`__iops_gpu_trace_<hostname>.csv`)
  - Energy consumption calculation via trapezoidal integration of power over time (`gpu_energy_j`)
  - GPU metrics aggregated into `__iops_resource_summary.csv` alongside CPU/memory metrics
- GPU hardware detection in system snapshot probe (`gpu_count`, `gpu_model`, `gpu_driver`, `gpu_memory_mib` in `__iops_sysinfo.json`)
- `iops convert` command for translating JUBE XML benchmarks to IOPS YAML format [experimental]
- Jinja2 templating support in `benchmark.cache_file`
- `examples/gpu_stress/` synthetic CUDA workload for testing GPU probes

## [3.5.2] - 2026-03-02

### Added
- Adaptive variable probing (`search_method: "adaptive"`) for finding threshold values automatically
  - Supports multiplicative (`factor`), additive (`increment`), and custom (`step_expr`) progression
  - Configurable stop conditions via `stop_when` expressions (exit code, metrics, execution time)
  - Independent probes per swept variable combination
  - Probe results stored in `__iops_run_metadata.json` under `adaptive_results`
- `list` variable type for indexed access to correlated parameter arrays
- `--add VAR[:TYPE]=VALUE` option for `iops cache rebuild` to add typed variables to all cache entries
- `machines` section for per-machine config overrides with deep-merge semantics
- `--machine NAME` flag (and `IOPS_MACHINE` env var) for `iops run` and `iops check`
- `iops check --resolve [FILE]` to output the fully merged config as YAML
- `iops generate --machines` to scaffold a config with machine override examples
- `metrics` global variable in parser scripts (list of expected metric names for selective computation)
- Copy input YAML config to run folder for reproducibility
- Reports section on the website with interactive Plotly report viewer

### Changed
- Made scikit-optimize an optional dependency, installed via `pip install iops-benchmark[bayesian]`

### Fixed
- `--resolve` now renders multi-line strings (parser scripts, script templates) with YAML literal block style (`|`) instead of escaped single-line format
- Watch mode progress display for adaptive planner
- Parser script now accepts directory paths
- Bayesian test failures when scikit-optimize is not installed

## [3.5.0] - 2026-02-01

### Added
- Resource tracing for CPU and memory monitoring (`trace_resources`, `trace_interval`)
- Single-allocation mode for batch SLURM execution (`slurm_options.allocation`) [experimental]
- MPI block for automatic MPI launching in single-allocation mode (`scripts[].mpi`)
- `iops cache rebuild` command to exclude variables retroactively
- Parser script context injection (`vars`, `env`, `os_env`, `execution_id`, `repetition` globals)
- `os_env` context variable exposing system environment variables to Jinja2 templates
- `--partial` and `--min-reps` flags for partial archive creation
- Unknown key validation with "did you mean?" suggestions for YAML config
- Core-hours tracking for cache hits in dry-run estimates
- Boolean variables now included in report generation by default (treated as 0/1)
- Plot export to image files (`--export-plots`, `--plot-format`) with pdf, png, svg, jpg, webp support
- Random search evolution section in HTML reports
- NFS auto-detection with lock-free SQLite mode for cache
- Real-time execution status tracking with executor-specific updates
- `early_stop_on_convergence` option for Bayesian optimization to stop when optimizer converges
- `convergence_patience` option to control early stopping sensitivity (default: 3)
- `xi_boost_factor` option to dynamically increase exploration when stuck (default: 5.0)
- `--cache-only` CLI option for cache-only execution (skip tests not in cache)
- Keyboard navigation for watch mode (pause, page scroll, search by test ID)

### Changed
- Renamed `executor_options` to `slurm_options` (old name deprecated, remove in 3.7.0)
- Refactored probe configuration to nested `probes:` section with clearer field names:
  - `collect_system_info` → `probes.system_snapshot`
  - `track_executions` → `probes.execution_index`
  - `trace_resources` → `probes.resource_sampling`
  - `trace_interval` → `probes.sampling_interval`
  (old names deprecated, remove in 3.7.0)
- Renamed `[pdf]` optional dependency to `[plots]` (supports pdf, png, svg, jpg, webp)
- Removed `scripts[].submit` field
- Removed `output.sink.include` option
- Removed Pareto Frontier analysis from reports
- `iops generate` now defaults to SLURM executor (use `--local` for local)
- Separate user labels from IOPS internal metadata in output
- Default output path when `output.sink.path` not specified
- Bayesian optimization now uses MAX/MIN aggregation for repetitions (matching objective) instead of MEAN

### Fixed
- `sections.parallel_coordinates` and `sections.variable_impact` settings being ignored in reports
- Dry-run cache lookup using wrong repetition values
- Constraint evaluation order (swept vars before derived expressions)
- Refactored BayesianPlanner to use pre-built execution matrix (consistent with other planners)
- SQLite cache locking errors on NFS filesystems
- Bayesian optimization nearest-neighbor tie-breaking now deterministic (prefers higher parameter values)

## [3.4.0] - 2026-01-13

### Added
- Subcommand-based CLI structure (`run`, `check`, `generate`, `report`, `find`)
- `find` command to explore execution folders with parameter filtering
- Execution status tracking with `--status` filter (SUCCEEDED, FAILED, ERROR)
- Archive module for workdir portability (`iops archive create/extract`)
- Watch mode for real-time execution monitoring (`iops watch`)
- Conditional variables with `when`/`default` fields
- Enhanced Bayesian optimization with `base_estimator`, `xi`, `kappa`, `n_iterations`
- Search space efficiency statistics in Bayesian reports
- `fallback_to_exhaustive` option for Bayesian planner
- `create_folders_upfront` benchmark option
- System info collection and config validation
- Client-side search for documentation site

### Changed
- YAML file shorthand: `iops config.yaml` works as `iops run config.yaml`
- Renamed `sqlite_db` to `cache_file`
- Renamed `target_metric` to `objective_metric`
- Removed rounds feature and simplified planner architecture
- Made pyarrow an optional dependency
- Portable workdir metadata with relative paths
- Centralized validation logic in loader.py
- Restructured documentation for v3

### Fixed
- Bayesian planner edge case bugs
- Archive progress bar performance with compression level tuning
- Metrics not showing when using `--hide` in watch mode
- Duration tracking to use cached sysinfo
- Search index to include full page content

## [3.2.0] - 2025-12

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
- User-configurable reporting system with 8 plot types
- `reporting` configuration section for plot customization
- `--report-config` CLI option to regenerate reports
- Theme configuration (colors, fonts, plotly styles)
- PyPI packaging as `iops-benchmark`
- Spack package support

## [2.0.0] - 2024

Internal development version that introduced architectural changes leading to 3.2.0.

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
