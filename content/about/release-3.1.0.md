---
title: "Release 3.1.0 - Comprehensive Reporting System"
date: 2025-12-23
weight: 1
---

# IOPS 3.1.0 Release Notes

**Release Date:** December 23, 2025

We're excited to announce IOPS 3.1.0, which introduces a comprehensive user-configurable reporting system with interactive visualizations and extensive plot customization capabilities.

## What's New

### User-Configurable Reporting System

The headline feature of this release is the new `reporting` configuration section, which gives users complete control over report generation and visualization.

**Key Features:**
- 8 plot types: bar, line, scatter, heatmap, box, violin, surface_3d, parallel_coordinates
- Per-metric plot customization via YAML configuration
- Auto-generated `report_config.yaml` templates for easy report regeneration
- CLI `--report-config` option to regenerate reports with different settings
- Enhanced test summary with execution metadata (timestamps, cache stats, core-hours)
- Theme configuration (colors, fonts, plotly styles)
- Section control (enable/disable specific report sections)
- Backward compatible with existing workdirs

**Example Configuration:**

```yaml
reporting:
  enabled: true
  output_filename: "analysis_report.html"

  theme:
    style: "plotly_white"
    colors: ["#3498db", "#e74c3c", "#2ecc71"]

  sections:
    test_summary: true
    best_results: true
    variable_impact: true
    custom_plots: true

  metrics:
    bandwidth:
      plots:
        - type: "line"
          x_var: "block_size"
          group_by: "nodes"
          title: "Bandwidth vs Block Size"

        - type: "heatmap"
          x_var: "nodes"
          y_var: "block_size"
          colorscale: "Viridis"

  default_plots:
    - type: "bar"
      per_variable: true
      show_error_bars: true
```

**Benefits:**
- ✅ Complete control over plot types and configurations
- ✅ Easy report regeneration with different visualization settings
- ✅ Reference comments in generated configs showing available variables and metrics
- ✅ No code changes needed for custom visualizations
- ✅ Opt-in by default (enabled: false)

### Auto-Generated Report Templates

After each execution, IOPS now automatically generates a `report_config.yaml` file in the workdir with:
- Clean, expandable version of user's configuration (if provided)
- Smart template based on execution results (if no config provided)
- Reference comments listing all swept variables (with types)
- Reference comments listing all detected metrics
- Reference comments showing available plot types

This makes it trivial to regenerate reports with different visualizations:

```bash
# Edit the generated template
vim workdir/run_001/report_config.yaml

# Regenerate report with new settings
iops --analyze workdir/run_001 --report-config workdir/run_001/report_config.yaml
```

### Enhanced Test Summary

The test summary section now includes comprehensive execution metadata:
- Benchmark name and executor type
- Search method used
- Timestamp information (benchmark start, report generation)
- Total parameter combinations tested
- Success rate (succeeded/total tests)
- Cache hit rate
- Average test duration
- Core-hours consumed (SLURM only)
- Parameter space coverage

### Plot Factory Architecture

Implemented an extensible plot factory system with:
- Registry pattern for easy plot type extension
- Base class abstraction for consistent plot behavior
- Comprehensive error handling and graceful degradation
- Support for per-variable plot generation
- Theme support across all plot types

### Documentation

- New comprehensive reporting user guide
- Updated YAML schema reference with reporting section
- Example configuration with reporting
- Updated template_full.yaml with reporting section
- All documentation includes plot type references and examples

## Upgrade Guide

### From 3.0.x to 3.1.0

This is a **backward-compatible** release. No configuration changes are required.

**Optional: Enable Reporting**

To use the new reporting features, add the `reporting` block to your configuration:

```yaml
reporting:
  enabled: true

  metrics:
    your_metric_name:
      plots:
        - type: "line"
          x_var: "parameter1"
          group_by: "parameter2"
```

### Installation

```bash
# Install from PyPI
pip install --upgrade iops-benchmark

# Or install from source
git clone https://gitlab.inria.fr/lgouveia/iops.git
cd iops
git checkout v3.1.0
pip install -e .
```

## Full Changelog

### Added
- `reporting` configuration section with full plot customization
- 8 plot types: bar, line, scatter, heatmap, box, violin, surface_3d, parallel_coordinates
- Auto-generated `report_config.yaml` templates in workdir
- `--report-config` CLI option for report regeneration
- Enhanced test summary with execution metadata
- Theme configuration (style, colors, fonts)
- Section control for report components
- Per-metric and default plot configurations
- Reference comments in generated configs
- Plot factory system with registry pattern
- 113 new tests for reporting features (259 total tests)

### Documentation
- New user guide: content/user-guide/reporting.md
- Updated YAML schema reference
- Example configuration: content/examples/example_with_reporting.yaml
- Updated template_full.yaml with reporting section

### Internal
- Created iops/reporting/plots.py (550 lines)
- Enhanced iops/reporting/report_generator.py
- Extended iops/config/models.py with 7 new dataclasses
- Enhanced iops/config/loader.py with reporting parsers
- Updated iops/execution/runner.py for auto-generation

## Migration Path

Since 3.1.0 is backward compatible, existing configurations work unchanged:
- Old workdirs without reporting metadata use legacy defaults
- Reports can be regenerated for old workdirs using `--analyze`
- Reporting is opt-in (enabled: false by default)
- No breaking changes to existing functionality

## What's Next

We're continuing to enhance IOPS with:
- Additional plot types (3D scatter, violin plots enhancements)
- Interactive report features (filtering, zooming, data tables)
- Export capabilities (PDF, static images)
- Real-time monitoring dashboard
- Advanced statistical analysis sections

## Resources

- **Documentation:** https://lgouveia.gitlabpages.inria.fr/iops/
- **PyPI Package:** https://pypi.org/project/iops-benchmark/
- **Issue Tracker:** https://gitlab.inria.fr/lgouveia/iops/-/issues
- **Changelog:** [Full Changelog](changelog.md)

## Contributors

Thank you to everyone who contributed to this release!

---

**Download:** `pip install iops-benchmark==3.1.0`

**Git Tag:** `v3.1.0`
