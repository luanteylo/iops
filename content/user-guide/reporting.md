---
title: "Custom Reports & Visualization"
---

IOPS includes a comprehensive reporting system that generates interactive HTML reports with custom plots and statistical analysis from your benchmark results.

---

## Introduction

The reporting feature allows you to:

- **Auto-generate reports** after benchmark execution
- **Create custom plots** per metric with full control over visualization
- **Customize themes** and styling to match your preferences
- **Control report sections** to include only relevant analyses
- **Regenerate reports** with different configurations without re-running benchmarks

Reports are generated as self-contained HTML files with embedded interactive Plotly visualizations.

---

## Basic Usage

### Enabling Auto-Generation

Add the `reporting` section to your configuration and set `enabled: true`:

```yaml
reporting:
  enabled: true
```

With this minimal configuration, IOPS will automatically generate a report after benchmark execution using default settings.

### Manual Report Generation

Generate a report from an existing run:

```bash
iops --analyze /path/to/workdir/run_001
```

This works with any completed run, regardless of whether `reporting` was configured during execution.

### Custom Report Configuration

Generate a report with custom visualization settings:

```bash
iops --analyze /path/to/workdir/run_001 --report-config custom_report.yaml
```

The `--report-config` file contains only the `reporting` section, allowing you to experiment with different visualizations without re-running benchmarks.

**Example custom_report.yaml**:

```yaml
reporting:
  enabled: true
  theme:
    style: "plotly_dark"
    colors: ["#636EFA", "#EF553B", "#00CC96"]

  metrics:
    bandwidth:
      plots:
        - type: "line"
          x_var: "block_size"
          group_by: "nodes"
          title: "Bandwidth vs Block Size by Node Count"
```

---

## Report Sections

Generated reports include the following sections (all enabled by default):

### Test Summary

Displays execution statistics and parameter space information:

- Total execution time
- Number of tests executed
- Cache hit rate (if caching enabled)
- Core-hours consumed (if budget tracking enabled)
- Success/failure counts
- Parameter space coverage

### Best Results

Shows the top N configurations for each metric:

- Top 5 configurations by default (configurable via `best_results.top_n`)
- Parameter values for each configuration
- Metric values
- Optionally includes the rendered command for reproducibility

**Configuration**:

```yaml
reporting:
  best_results:
    top_n: 10                # Show top 10 configurations
    show_command: true       # Include rendered commands
```

### Variable Impact Analysis

Analyzes which variables have the strongest effect on metrics using variance-based importance:

- Identifies which parameters most affect performance
- Helps focus optimization efforts
- Uses statistical variance decomposition

**When to use**: Large parameter spaces where you need to identify the most influential variables.

### Parallel Coordinates Plot

Multi-dimensional visualization showing relationships between all variables and metrics:

- Visualize high-dimensional parameter spaces
- Identify parameter correlations
- Spot trade-offs between metrics

**When to use**: Understanding complex relationships in multi-variable optimization.

### Pareto Frontier

Multi-objective optimization analysis (shown when 2+ metrics are present):

- Identifies non-dominated configurations
- Visualizes trade-offs between competing metrics
- Highlights optimal configurations for different objectives

**When to use**: Benchmarks with multiple conflicting metrics (e.g., bandwidth vs latency).

### Bayesian Evolution

Shows optimization progress over iterations (Bayesian search only):

- Visualizes convergence behavior
- Shows exploration vs exploitation balance
- Tracks improvement over time

**When to use**: Only relevant when using `search_method: "bayesian"`.

### Custom Plots

User-defined plots specified in the `metrics` section (see below).

---

## Controlling Sections

Enable or disable specific sections:

```yaml
reporting:
  sections:
    test_summary: true           # Execution statistics
    best_results: true           # Top configurations
    variable_impact: true        # Variance analysis
    parallel_coordinates: true   # Multi-dimensional plot
    pareto_frontier: true        # Multi-objective analysis
    bayesian_evolution: false    # Skip (not using Bayesian)
    custom_plots: true           # User-defined plots
```

---

## Custom Plots

Define custom plots per metric for detailed analysis.

### Plot Types

IOPS supports 8 plot types:

#### 1. Bar Charts

Displays metric values with error bars (mean ± standard deviation).

```yaml
metrics:
  bandwidth:
    plots:
      - type: "bar"
        x_var: "block_size"
        show_error_bars: true
        title: "Bandwidth by Block Size"
```

**When to use**: Comparing discrete parameter values, showing statistical variation.

#### 2. Line Plots

Shows trends across continuous or ordered parameters.

```yaml
metrics:
  bandwidth:
    plots:
      - type: "line"
        x_var: "block_size"
        group_by: "nodes"           # Multiple lines for each node count
        title: "Bandwidth Scaling"
        xaxis_label: "Block Size (MB)"
        yaxis_label: "Bandwidth (MB/s)"
```

**When to use**: Visualizing trends, scaling behavior, grouped comparisons.

#### 3. Scatter Plots

Shows individual data points with optional color/size mapping.

```yaml
metrics:
  bandwidth:
    plots:
      - type: "scatter"
        x_var: "nodes"
        y_var: "processes_per_node"
        color_by: "bandwidth"       # Color points by bandwidth value
        size_by: "block_size"       # Size points by block_size
        title: "Parameter Space Exploration"
```

**When to use**: Exploring relationships, identifying patterns, visualizing high-dimensional data.

#### 4. Heatmaps

2D heatmaps showing metric values across two variables.

```yaml
metrics:
  bandwidth:
    plots:
      - type: "heatmap"
        x_var: "nodes"
        y_var: "block_size"
        colorscale: "Viridis"       # Plotly colorscale name
        title: "Bandwidth Heatmap"
```

**When to use**: Visualizing performance across two-dimensional parameter grid.

**Supported colorscales**: `"Viridis"`, `"Plasma"`, `"Inferno"`, `"Magma"`, `"Cividis"`, `"Blues"`, `"Reds"`, `"RdBu"`, etc.

#### 5. Box Plots

Box plots showing distribution statistics (quartiles, median) with optional outliers.

**Required Parameters**:
- `x_var` (string): Variable for categorical grouping (x-axis)

**Optional Parameters**:
- `show_outliers` (boolean): Display outlier points beyond whiskers (default: false)
- `title` (string): Custom plot title
- `xaxis_label` (string): Custom x-axis label
- `yaxis_label` (string): Custom y-axis label
- `height` (integer): Plot height in pixels
- `width` (integer): Plot width in pixels

```yaml
metrics:
  latency:
    plots:
      - type: "box"
        x_var: "concurrency"
        show_outliers: true
        title: "Latency Distribution by Concurrency"
        xaxis_label: "Concurrency Level"
        yaxis_label: "Latency (ms)"
```

**When to use**: Understanding distributions, detecting outliers, comparing variability across parameter values.

#### 6. Violin Plots

Violin plots showing distribution with kernel density estimation and embedded box plot.

**Required Parameters**:
- `x_var` (string): Variable for categorical grouping (x-axis)

**Optional Parameters**:
- `title` (string): Custom plot title
- `xaxis_label` (string): Custom x-axis label
- `yaxis_label` (string): Custom y-axis label
- `height` (integer): Plot height in pixels
- `width` (integer): Plot width in pixels

```yaml
metrics:
  latency:
    plots:
      - type: "violin"
        x_var: "nodes"
        title: "Latency Distribution by Node Count"
        xaxis_label: "Number of Nodes"
        yaxis_label: "Latency (ms)"
```

**When to use**: Detailed distribution analysis, comparing shapes of distributions, visualizing density patterns.

#### 7. 3D Surface Plots

3D surface plots showing metric values across two variables.

**Required Parameters**:
- `x_var` (string): Variable for x-axis
- `y_var` (string): Variable for y-axis

**Optional Parameters**:
- `z_metric` (string): Metric to display as z-axis/surface (default: current metric)
- `colorscale` (string): Plotly colorscale name (default: "Viridis")
- `title` (string): Custom plot title
- `xaxis_label` (string): Custom x-axis label
- `yaxis_label` (string): Custom y-axis label
- `height` (integer): Plot height in pixels
- `width` (integer): Plot width in pixels

```yaml
metrics:
  bandwidth:
    plots:
      - type: "surface_3d"
        x_var: "nodes"
        y_var: "block_size"
        z_metric: "bandwidth"
        colorscale: "Plasma"
        title: "Bandwidth Response Surface"
        xaxis_label: "Number of Nodes"
        yaxis_label: "Block Size (MB)"
```

**When to use**: Visualizing smooth response surfaces, finding optimal regions in 2D parameter space, understanding interactions between two variables.

#### 8. Parallel Coordinates

Multi-dimensional visualization showing all numeric swept variables and the metric as parallel axes.

**Required Parameters**: None (automatically includes all numeric swept variables)

**Optional Parameters**:
- `colorscale` (string): Colorscale for lines colored by metric value (default: "Viridis")
- `title` (string): Custom plot title

```yaml
metrics:
  bandwidth:
    plots:
      - type: "parallel_coordinates"
        colorscale: "Plasma"
        title: "Multi-Dimensional Parameter Analysis"
```

**When to use**: Visualizing relationships across many variables simultaneously, identifying parameter correlations, exploring high-dimensional parameter spaces.

---

## Per-Variable Plots

Generate one plot per swept variable automatically:

```yaml
reporting:
  default_plots:
    - type: "bar"
      per_variable: true          # Create one bar chart per variable
      show_error_bars: true
```

This is useful for quick exploration of all parameters without manually specifying each plot.

---

## Default Plots

Define fallback plots for metrics without specific configurations:

```yaml
reporting:
  default_plots:
    - type: "bar"
      per_variable: true
      show_error_bars: true
    - type: "parallel_coordinates"
```

These plots are used when:
- `custom_plots` section is enabled
- A metric has no specific `metrics.{metric_name}` configuration

---

## Themes and Styling

### Built-in Themes

Choose from Plotly's built-in themes:

```yaml
reporting:
  theme:
    style: "plotly_white"      # Clean white background (default)
    # Other options: "plotly", "plotly_dark", "ggplot2", "seaborn", "simple_white"
```

### Custom Colors

Define a custom color palette:

```yaml
reporting:
  theme:
    style: "plotly_white"
    colors:
      - "#636EFA"               # Blue
      - "#EF553B"               # Red
      - "#00CC96"               # Green
      - "#AB63FA"               # Purple
      - "#FFA15A"               # Orange
```

Colors are used for grouping, categorical variables, and multi-series plots.

### Font Customization

```yaml
reporting:
  theme:
    style: "plotly_white"
    font_family: "Arial, sans-serif"
```

---

## Plot Sizing and Defaults

Control default dimensions for all plots:

```yaml
reporting:
  plot_defaults:
    height: 600                # Default height in pixels
    width: null                # Auto width (responsive)
    margin:
      l: 80                    # Left margin
      r: 80                    # Right margin
      t: 100                   # Top margin
      b: 80                    # Bottom margin
```

Override for individual plots:

```yaml
metrics:
  bandwidth:
    plots:
      - type: "line"
        x_var: "block_size"
        height: 800              # Override default
        width: 1200
```

---

## Output Configuration

### Output Location

By default, reports are saved to the workdir. Customize the location:

```yaml
reporting:
  enabled: true
  output_dir: "/custom/path/to/reports"     # Custom directory
  output_filename: "benchmark_report.html"  # Custom filename
```

**Default behavior**: If `output_dir` is not specified, reports are saved to the run's workdir (e.g., `/workdir/run_001/analysis_report.html`).

---

## Complete Examples

### Minimal Configuration

```yaml
reporting:
  enabled: true
```

This generates a report with all default sections and automatic plots.

### Custom Visualization for IOR Benchmark

```yaml
reporting:
  enabled: true
  output_filename: "ior_performance_report.html"

  theme:
    style: "plotly_white"
    colors: ["#1f77b4", "#ff7f0e", "#2ca02c"]
    font_family: "Segoe UI, sans-serif"

  sections:
    test_summary: true
    best_results: true
    variable_impact: true
    parallel_coordinates: true
    pareto_frontier: true
    bayesian_evolution: false      # Not using Bayesian search
    custom_plots: true

  best_results:
    top_n: 10
    show_command: true

  metrics:
    bandwidth:
      plots:
        - type: "line"
          x_var: "block_size"
          group_by: "nodes"
          title: "Bandwidth vs Block Size"
          xaxis_label: "Block Size (MB)"
          yaxis_label: "Bandwidth (MB/s)"
          show_error_bars: true

        - type: "heatmap"
          x_var: "nodes"
          y_var: "block_size"
          colorscale: "Viridis"
          title: "Bandwidth Heatmap"

        - type: "scatter"
          x_var: "nodes"
          y_var: "processes_per_node"
          color_by: "bandwidth"

    iops:
      plots:
        - type: "bar"
          x_var: "concurrency"
          show_error_bars: true
          title: "IOPS by Concurrency Level"

        - type: "line"
          x_var: "block_size"
          group_by: "nodes"
          title: "IOPS Scaling"

  plot_defaults:
    height: 500
    width: null
```

### Multi-Metric Comparison

```yaml
reporting:
  enabled: true

  metrics:
    bandwidth:
      plots:
        - type: "line"
          x_var: "block_size"
          group_by: "nodes"

    latency:
      plots:
        - type: "line"
          x_var: "block_size"
          group_by: "nodes"

    efficiency:
      plots:
        - type: "scatter"
          x_var: "bandwidth"
          y_var: "latency"
          color_by: "nodes"
          title: "Bandwidth vs Latency Trade-off"
```

### Dark Theme Report

```yaml
reporting:
  enabled: true

  theme:
    style: "plotly_dark"
    colors: ["#00d4ff", "#ff006e", "#ffbe0b", "#8338ec"]

  metrics:
    bandwidth:
      plots:
        - type: "heatmap"
          x_var: "nodes"
          y_var: "block_size"
          colorscale: "Plasma"
```

---

## Configuration Priority

When using `--report-config`, the configuration priority is:

1. **CLI-provided config** (`--report-config custom.yaml`): Highest priority
2. **Metadata config** (stored in workdir from execution): Used if no CLI override
3. **Legacy defaults**: Fallback behavior for old runs without reporting metadata

---

## Backward Compatibility

The reporting feature is **fully backward compatible**:

- Old workdirs without `reporting` configuration can still be analyzed with `iops --analyze`
- Reports are **opt-in** (disabled by default with `enabled: false`)
- Existing configurations continue to work without modification

---

## Best Practices

### 1. Start Simple

Begin with the minimal configuration and enable auto-generation:

```yaml
reporting:
  enabled: true
```

Review the default report, then customize as needed.

### 2. Use Report-Config for Iteration

After running your benchmark once, experiment with visualizations using `--report-config`:

```bash
# Run benchmark once
iops config.yaml

# Try different visualizations
iops --analyze /workdir/run_001 --report-config viz_v1.yaml
iops --analyze /workdir/run_001 --report-config viz_v2.yaml
```

### 3. Match Plot Types to Data

- **Categorical/discrete variables**: Use bar charts
- **Continuous trends**: Use line plots
- **Two-variable relationships**: Use heatmaps or scatter plots
- **Distribution analysis**: Use box/violin plots (when available)
- **Multi-dimensional**: Use parallel coordinates or scatter with color/size

### 4. Control Section Visibility

Disable irrelevant sections to keep reports focused:

```yaml
reporting:
  sections:
    bayesian_evolution: false    # Disable if not using Bayesian
    pareto_frontier: false       # Disable for single-metric benchmarks
```

### 5. Customize for Presentation

For presentations or reports, use custom themes and high-resolution plots:

```yaml
reporting:
  theme:
    style: "simple_white"
    font_family: "Arial, sans-serif"

  plot_defaults:
    height: 600
    width: 1000
```

---

## Troubleshooting

### Report Not Generated

**Problem**: Report doesn't appear after execution.

**Solution**: Verify `reporting.enabled: true` in your configuration.

### Missing Plots

**Problem**: Expected plots don't appear in the report.

**Solution**: Check that:
- `sections.custom_plots: true`
- Metric names in `metrics` match parser output exactly
- Required fields (`x_var`, etc.) are specified for plot type

### Incorrect Variable Names

**Problem**: Plots show errors about missing variables.

**Solution**: Use `iops --analyze /workdir/run_001 --dry-run` to see available variables and metrics (feature request).

Verify variable names match those in your `vars` section.

### Theme Not Applied

**Problem**: Custom theme/colors not showing.

**Solution**: Ensure `theme` is at the correct level:

```yaml
reporting:
  enabled: true
  theme:                # Correct: under reporting
    style: "plotly_dark"
```

---

## Next Steps

- Explore the [YAML Schema Reference](../reference/yaml-schema.md) for complete reporting configuration options
- See [Example with Reporting](../examples/example_with_reporting.yaml) for a working configuration
- Learn about [Analysis & Reports](analysis.md) for general analysis workflows
