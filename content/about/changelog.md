---
title: "Changelog"
---


All notable changes to IOPS are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.3.0] - 2026-01-09

### Added
- Subcommand-based CLI structure (`run`, `check`, `generate`, `analyze`, `find`) with context-sensitive help
- `find` command to explore execution folders with parameter filtering (`iops find ./workdir nodes=4`)
- `--show-command` flag to display rendered commands in find output
- Auto-detection of `report_config.yaml` in analyze mode
- Bash compatibility check for system probe
- Accurate execution duration tracking for core-hours calculation
- System info collection and comprehensive config validation
- Portable workdir metadata with relative paths in `__iops_run_metadata.json`

### Changed
- CLI syntax changed from flags to subcommands (e.g., `iops run config.yaml` instead of `iops config.yaml`)
- System probe moved to separate file for cleaner user scripts
- System probe moved to end of script to preserve SLURM directives

### Fixed
- Exclude NFS from parallel filesystem detection
- Improved filesystem detection and benchmark config logging

## [3.2.2] - 2026-01-08

### Fixed
- `command.metadata` values not appearing in output results (CSV, Parquet, SQLite)

## [3.2.1] - 2026-01-08

### Fixed
- KeyError: 'round' in dry-run mode caused by leftover references to removed rounds feature

## [3.2.0] - 2026-01-08

### Added
- BayesianConfig dataclass with typed validation for all Bayesian optimization parameters
- New Bayesian config options: `base_estimator`, `xi`, `kappa` for fine-tuned optimization control
- Search space efficiency statistics in Bayesian reports (total space, iterations, tests saved)
- Variable values shown on hover in Bayesian metric evolution plot
- JSON serialization tests for dataclasses and numpy types

### Changed
- Renamed `target_metric` to `objective_metric` in Bayesian config (backward compatible)
- Simplified CLI arguments into logical groups
- Removed rounds feature and simplified planner architecture
- Made pyarrow an optional dependency for parquet support

### Fixed
- Bayesian optimization plots not rendering in reports
- Pareto point detection in report generator
- Dataclass JSON serialization for runtime metadata

### Documentation
- Updated yaml-schema.md with complete Bayesian config documentation
- Updated all example YAML files with new `objective_metric` field name

## [3.1.3] - 2026-01-05

### Fixed
- Fixed blank plots in HTML reports with Plotly 6.x by converting numpy arrays to native Python lists before passing to Plotly (Plotly 6.x uses binary encoding which caused rendering issues in some browsers)

## [3.1.0] - 2025-12-23

### Added
- Comprehensive user-configurable reporting system
- 8 plot types: bar, line, scatter, heatmap, box, violin, surface_3d, parallel_coordinates
- `reporting` configuration section for complete plot customization
- Per-metric plot configuration via YAML
- Auto-generated `report_config.yaml` templates in workdir after each execution
- `--report-config` CLI option to regenerate reports with different settings
- Enhanced test summary with execution metadata (timestamps, success rate, cache stats, core-hours)
- Theme configuration (colors, fonts, plotly styles)
- Section control to enable/disable report components
- Reference comments in generated configs showing available variables, metrics, and plot types
- Plot factory system with registry pattern for extensibility
- 113 new tests for reporting features (259 total tests passing)
- Runnable example: examples/example_with_reporting.yaml

### Documentation
- New comprehensive reporting user guide (content/user-guide/reporting.md)
- Updated YAML schema reference with reporting section (lines 1459-1952)
- Example configuration with reporting (content/examples/example_with_reporting.yaml)
- Updated template_full.yaml with concise reporting section
- Release notes: content/about/release-3.1.0.md

### Fixed
- Added plotly, pyarrow, and fastparquet to pyproject.toml dependencies for CI/CD compatibility

### Internal
- Created iops/reporting/plots.py with plot factory implementation (550 lines)
- Enhanced iops/reporting/report_generator.py with custom plot support
- Extended iops/config/models.py with 7 new reporting dataclasses
- Enhanced iops/config/loader.py with reporting configuration parsers
- Updated iops/execution/runner.py for auto-generation and clean config saving

## [3.0.8] - 2025-12-23

### Added
- Parameter constraint validation to filter invalid configurations before execution
- `constraints` section in YAML configuration for defining validation rules
- Support for three violation policies: skip (filter), error (fail), warn (log)
- Python expression-based constraint rules with access to all variables
- Automatic filtering during execution matrix generation
- Constraint reporting in dry-run mode
- Test coverage with 16 new constraint validation tests

## [3.0.5] - 2025-12-21

### Added
- Configurable SLURM commands via `executor_options.commands` for systems with command wrappers
- Support for customizing `submit`, `status`, `info`, and `cancel` commands in SLURM executor
- Default submit command can be specified in executor_options (scripts can still override per-script)
- Comprehensive documentation for executor_options in YAML schema reference and execution backends guide
- Test coverage for executor_options functionality (7 new tests)

## [3.0.4] - 2025-12-20

### Added
- Random sampling planner for efficient parameter space exploration
- Support for `n_samples` and `percentage` configuration options in random search
- `random_config` section in benchmark configuration

### Fixed
- PyProject configuration issues
- Report time tracking accuracy

## [3.0.0] - 2025-12-20

Major overhaul transforming IOPS into a generic benchmark orchestration framework.

### Added
- **Generic Framework**: No longer limited to I/O benchmarks - supports any parametric experiment
- **Template Generation**: `--generate` flag to create fully-commented configuration templates
- **Interactive Setup Wizard**: Step-by-step guided configuration creation
- **Pip Packaging**: Full PyPI package support with `iops-benchmark` name
- **Bayesian Optimization**: Gaussian Process-based intelligent parameter search
- **Random Sampling**: Configurable random parameter space sampling
- **Core-Hours Budget Tracking**: Prevent exceeding compute allocations on HPC clusters
- **Dry-Run Mode**: Preview executions with resource estimates before running
- **HTML Report Generation**: Interactive analysis reports with plots and statistics
- **Result Caching**: SQLite-based execution caching with `--use-cache` flag
- **Multi-Round Optimization**: Progressive parameter refinement across rounds
- **SLURM Support**: Native HPC cluster integration with automatic job management

### Changed
- **Configuration Format**: Complete YAML format redesign for genericity
- **Module Organization**: Refactored into domain-based structure (`execution/`, `config/`, `results/`)
- **Lazy Rendering**: All templates rendered on-access for maximum flexibility
- **License**: Adopted BSD-3-Clause license
- **Documentation**: Comprehensive YAML format documentation and usage guides

### Removed
- Legacy IOR-specific configuration format
- Hardcoded I/O benchmark assumptions

## [2.0.x] - 2025-12

### Added
- SLURM executor with job submission and monitoring
- Multi-node allocation support
- SLURM job cleanup on interruption (Ctrl+C)
- Debug logging for SLURM execution

### Fixed
- SLURM multi-node allocation by removing conflicting `--ntasks` directive
- JSON serialization for numpy int64 types in metadata

## Earlier Versions

### Features Introduced
- Rounds-based optimization workflows
- Lazy execution rendering with Jinja2
- Repetition support with `{{ repetition }}` context variable
- CSV and Parquet output formats
- Local executor for subprocess-based execution
- Variable sweeping with list and range modes
- Derived variables with expressions
- Parser scripts for metric extraction
- Metadata and environment variable support

---

## Upgrade Guide

### From 2.x to 3.x

IOPS 3.0 is a major rewrite with breaking changes to the configuration format.

**Configuration Migration:**

1. **Benchmark Section**:
   ```yaml
   # Old (2.x)
   name: "My Benchmark"
   workdir: "/path/to/workdir"

   # New (3.x)
   benchmark:
     name: "My Benchmark"
     workdir: "/path/to/workdir"
     executor: "local"  # or "slurm"
     search_method: "exhaustive"
   ```

2. **Variables**:
   ```yaml
   # Old (2.x)
   vars:
     nodes: [2, 4, 8]

   # New (3.x)
   vars:
     nodes:
       type: int
       sweep:
         mode: list
         values: [2, 4, 8]
   ```

3. **Scripts**:
   ```yaml
   # Old (2.x)
   scripts:
     - name: "test"
       template: "#!/bin/bash\n{{ command }}"

   # New (3.x)
   scripts:
     - name: "test"
       submit: "bash"
       script_template: |
         #!/bin/bash
         {{ command.template }}
   ```

**New Features to Explore:**

- Try `iops generate` to create a template
- Enable caching with `iops run config.yaml --use-cache` for faster iterations
- Use Bayesian optimization for large parameter spaces
- Generate reports with `iops analyze ./workdir/run_001`
- Explore executions with `iops find ./workdir nodes=4`

---

## Contributing

See [CONTRIBUTING.md](contributing.md) for how to contribute to IOPS.

## Links

- **Repository**: [GitLab](https://gitlab.inria.fr/lgouveia/iops)
- **Issues**: [Issue Tracker](https://gitlab.inria.fr/lgouveia/iops/-/issues)
- **PyPI**: [iops-benchmark](https://pypi.org/project/iops-benchmark/)
