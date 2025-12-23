---
title: "Changelog"
---


All notable changes to IOPS (I/O Performance Suite) are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- **Template Generation**: `--generate_setup` flag to create fully-commented configuration templates
- **Interactive Setup Wizard**: Step-by-step guided configuration creation
- **Pip Packaging**: Full PyPI package support with `iops-benchmark` name
- **Bayesian Optimization**: Gaussian Process-based intelligent parameter search
- **Random Sampling**: Configurable random parameter space sampling
- **Core-Hours Budget Tracking**: Prevent exceeding compute allocations on HPC clusters
- **Dry-Run Mode**: Preview executions with resource estimates before running
- **HTML Report Generation**: Interactive analysis reports with plots and statistics
- **Result Caching**: SQLite-based execution caching with `--use_cache` flag
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

- Try `iops --generate_setup` to create a template
- Enable caching with `--use_cache` for faster iterations
- Use Bayesian optimization for large parameter spaces
- Generate reports with `iops analyze <workdir/run_001>`

---

## Contributing

See [CONTRIBUTING.md](contributing.md) for how to contribute to IOPS.

## Links

- **Repository**: [GitLab](https://gitlab.inria.fr/lgouveia/iops)
- **Issues**: [Issue Tracker](https://gitlab.inria.fr/lgouveia/iops/-/issues)
- **PyPI**: [iops-benchmark](https://pypi.org/project/iops-benchmark/)
