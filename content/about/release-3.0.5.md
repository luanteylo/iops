---
title: "Release 3.0.5 - SLURM Command Customization"
date: 2025-12-21
weight: 2
---

# IOPS 3.0.5 Release Notes

**Release Date:** December 21, 2025

We're excited to announce IOPS 3.0.5, which introduces comprehensive SLURM command customization and enhanced documentation.

## What's New

### Configurable SLURM Commands (`executor_options`)

The headline feature of this release is the new `executor_options` configuration block, which allows you to customize all SLURM commands used by the executor. This is especially useful for HPC systems that use command wrappers or custom SLURM installations.

**Key Features:**
- Customize `submit`, `status`, `info`, and `cancel` commands
- Support for command wrappers (e.g., `lrms-wrapper`, `flux`)
- Per-script submit command override capability
- Backward compatible with existing configurations

**Example Configuration:**

```yaml
benchmark:
  executor: "slurm"
  executor_options:
    commands:
      submit: "lrms-wrapper sbatch"   # Default for all scripts
      status: "lrms-wrapper squeue"   # Job status query
      info: "lrms-wrapper scontrol"   # Job information
      cancel: "lrms-wrapper scancel"  # Job cancellation

scripts:
  - name: "benchmark"
    # Uses default submit from executor_options
    script_template: ...

  - name: "custom"
    submit: "sbatch --parsable"  # Override for this script only
    script_template: ...
```

**Benefits:**
- ✅ Works with any SLURM wrapper system
- ✅ Centralized command configuration
- ✅ Flexible per-script overrides when needed
- ✅ No code changes required for different clusters

### Documentation Improvements

- Migrated documentation to Hugo static site generator
- Added comprehensive executor_options documentation
- Updated all examples and templates
- Improved YAML schema reference with executor_options details

### Enhanced Testing

- Added 7 new tests for executor_options functionality
- Full test coverage for command customization and fallback behavior
- All 19 executor tests passing

## Upgrade Guide

### From 3.0.4 to 3.0.5

This is a **backward-compatible** release. No configuration changes are required.

**Optional: Enable executor_options**

If you want to use command wrappers, add the `executor_options` block to your configuration:

```yaml
benchmark:
  executor: "slurm"
  executor_options:
    commands:
      submit: "your-wrapper sbatch"
      status: "your-wrapper squeue"
      info: "your-wrapper scontrol"
      cancel: "your-wrapper scancel"
```

### Installation

```bash
# Install from PyPI
pip install --upgrade iops-benchmark

# Or install from source
git clone https://github.com/your-org/iops.git
cd iops
git checkout v3.0.5
pip install -e .
```

## Full Changelog

### Added
- Configurable SLURM commands via `executor_options.commands`
- Support for customizing `submit`, `status`, `info`, and `cancel` commands
- Default submit command with per-script override capability
- Comprehensive documentation in YAML schema reference
- Test coverage for executor_options (7 new tests)

### Documentation
- Migrated from MkDocs to Hugo
- Updated execution backends guide
- Enhanced YAML schema reference
- Updated all examples and templates

### Internal
- Improved executor architecture for command customization
- Enhanced signal handler for Ctrl+C cleanup with custom commands

## Migration Path

Since 3.0.4 was the first major release with the new architecture, 3.0.5 builds on that foundation with enhanced HPC compatibility.

**Key compatibility notes:**
- All 3.0.x configurations work unchanged
- executor_options is entirely optional
- Existing scripts[].submit configurations continue to work
- Default behavior unchanged (uses standard SLURM commands)

## What's Next

We're continuing to enhance IOPS with:
- Additional executor backends (Kubernetes, PBS/Torque)
- Enhanced Bayesian optimization algorithms
- Real-time monitoring dashboard
- Cloud platform integration

## Resources

- **Documentation:** [IOPS Documentation](https://your-docs-site.com)
- **PyPI Package:** [iops-benchmark](https://pypi.org/project/iops-benchmark/)
- **Issue Tracker:** [GitHub Issues](https://github.com/your-org/iops/issues)
- **Changelog:** [Full Changelog](changelog.md)

## Contributors

Thank you to everyone who contributed to this release!

---

**Download:** `pip install iops-benchmark==3.0.5`

**Git Tag:** `v3.0.5`
