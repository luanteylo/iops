---
title: "Custom Reports & Visualization"
---

IOPS includes a comprehensive reporting system that generates interactive HTML reports with custom plots and statistical analysis from your benchmark results.

---

## Table of Contents

1. [Introduction](#introduction)
2. [Basic Usage](#basic-usage)
3. [Report Sections](#report-sections)
4. [Controlling Sections](#controlling-sections)
5. [Custom Plots](#custom-plots)
6. [Default Plots](#default-plots)
7. [Themes and Styling](#themes-and-styling)
8. [Plot Sizing and Defaults](#plot-sizing-and-defaults)
9. [Output Configuration](#output-configuration)
10. [Examples](#examples)

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
iops report /path/to/workdir/run_001
```

This works with any completed run, regardless of whether `reporting` was configured during execution.

### Custom Report Configuration

Generate a report with custom visualization settings:

```bash
iops report /path/to/workdir/run_001 --report-config custom_report.yaml
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
- Metric values (mean, standard deviation, sample count)
- Optionally includes the rendered command for reproducibility
- Can filter by minimum sample count to ensure statistical reliability

**Configuration**:

```yaml
reporting:
  best_results:
    top_n: 10                # Show top 10 configurations
    show_command: true       # Include rendered commands
    min_samples: 3           # Require at least 3 repetitions (filters unreliable results)
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
    bayesian_evolution: false    # Skip (not using Bayesian)
    custom_plots: true           # User-defined plots
```

---

## Custom Plots

Define custom plots per metric for detailed analysis.

### Plot Types

IOPS supports 9 plot types:

#### 1. Execution Scatter

A simple scatter plot showing metric values for each test execution in sequential order.

**Required Parameters**: None (automatically uses execution index as x-axis)

**Optional Parameters**:
- `title` (string): Custom plot title
- `xaxis_label` (string): Custom x-axis label (default: "Test Execution ID")
- `yaxis_label` (string): Custom y-axis label (default: metric name)
- `height` (integer): Plot height in pixels
- `width` (integer): Plot width in pixels

```yaml
metrics:
  bandwidth:
    plots:
      - type: "execution_scatter"
        title: "Bandwidth per Test Execution"
        xaxis_label: "Test ID"
        yaxis_label: "Bandwidth (MB/s)"
```

**When to use**: Quick visualization of all metric values in execution order. Hover displays all parameter values for each test. This is the default first plot when using legacy report mode. Useful for identifying outliers, trends across test execution order, or verifying result consistency.

#### 2. Bar Charts

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

#### 3. Line Plots

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

#### 4. Scatter Plots

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

#### 5. Heatmaps

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

#### 6. Box Plots

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

#### 7. Violin Plots

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

#### 8. 3D Surface Plots

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

#### 9. Parallel Coordinates

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

#### 10. Coverage Heatmap

Multi-variable heatmap showing parameter space coverage with hierarchical indexing. This plot displays selected variables using multi-level row/column indices, similar to a pivot table.

**Required Parameters**:
- `row_vars` (list of strings): Variables to use as row indices (supports multi-level indexing)
- `col_var` (string): Variable to use as column axis

**Optional Parameters**:
- `aggregation` (string): Aggregation function - "mean" (default), "median", "count", "std", "min", "max"
- `show_missing` (boolean): Highlight missing data (NaN) with distinct color (default: true)
- `sort_rows_by` (string): Sort rows by - "index" (variable values, default) or "values" (metric aggregation)
- `sort_cols_by` (string): Sort columns by - "index" (variable values, default) or "values" (metric aggregation)
- `sort_ascending` (boolean): Sort direction for "values" mode (default: false = highest values first)
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
      # Simple heatmap with 2 variables
      - type: "coverage_heatmap"
        row_vars: ["nodes"]
        col_var: "transfer_size_kb"
        aggregation: "mean"
        title: "Bandwidth Coverage Matrix"

      # Multi-level row index with 3 variables
      - type: "coverage_heatmap"
        row_vars: ["nodes", "processes_per_node"]
        col_var: "transfer_size_kb"
        aggregation: "count"  # Show how many tests per combination
        colorscale: "Blues"
        title: "Test Coverage by Configuration"

      # Sorted by performance (highest bandwidth configurations first)
      - type: "coverage_heatmap"
        row_vars: ["nodes", "processes_per_node"]
        col_var: "transfer_size_kb"
        aggregation: "mean"
        sort_rows_by: "values"     # Sort rows by metric performance
        sort_cols_by: "values"     # Sort columns by metric performance
        sort_ascending: false      # Highest values first
        title: "Bandwidth Sorted by Performance"
```

**When to use**:
- Visualizing the complete parameter space and metric values across all variable combinations
- Identifying coverage gaps in your experimental design (missing combinations show as NaN)
- Understanding how metrics vary across multi-dimensional parameter spaces
- Showing test repetition counts with `aggregation: "count"`
- Creating comprehensive coverage reports similar to pivot tables

**How it works**:
- **Variable selection**: You must specify which variables to visualize using `row_vars` (1+ variables) and `col_var` (1 variable)
- **Multi-level indices**: Multiple `row_vars` create hierarchical row labels (e.g., "nodes=4, processes_per_node=16")
- **Aggregation**: Cell values are aggregated using the specified function (useful when multiple tests share the same parameter combination)
- **Sorting modes**:
  - **`"index"`** (default): Sort by variable values in natural order (e.g., nodes: 1, 2, 4, 8; transfer_size: 64, 128, 256)
  - **`"values"`**: Hierarchical performance-based sorting - for multi-level rows, each level is sorted by its group's average performance:
    - First, all values of the first variable are sorted by their mean performance
    - Within each first-level group, the second variable values are sorted by their mean performance within that group
    - This continues for all levels, creating well-organized groupings of similar-performing configurations
- **Missing data**: NaN values (untested combinations) are visually distinct, making it easy to spot coverage gaps
- **Interactive hover**: Shows all variable values and the metric value for each cell
- **Performance**: Keep total variables to 2-3 for best performance (more variables = larger pivot table)




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
- Quick exploration of all parameters without manually specifying each plot.
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

##  Examples

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
    bayesian_evolution: false      # Not using Bayesian search
    custom_plots: true

  best_results:
    top_n: 10
    show_command: true
    min_samples: 3

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


