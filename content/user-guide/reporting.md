---
title: "Custom Reports & Visualization"
---

IOPS includes a reporting system that generates interactive HTML reports with custom plots and statistical analysis from your benchmark results.

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
10. [Per-Test Image Gallery](#per-test-image-gallery)
11. [Software Version Capture Probe](#software-version-capture-probe)
12. [Examples](#examples)

---

## Introduction

Reports are generated as self-contained HTML files with embedded interactive Plotly visualizations. You can auto-generate reports after execution, define custom plots and themes per metric, control which sections appear, regenerate reports with different configurations without re-running benchmarks, and optionally export all plots as image files (requires kaleido).

---

## Basic Usage

### Enabling Auto-Generation

Add the `reporting` section to your configuration and set `enabled: true`:

```yaml
reporting:
  enabled: true
```

IOPS then automatically generates a report after benchmark execution using default settings.

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

The `--report-config` file contains only the `reporting` section, so you can experiment with different visualizations without re-running benchmarks.

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

Generated reports can include the following sections (all enabled by default except Bayesian Parameter Evolution):

### Image Gallery

Embeds per-execution images into the HTML report as a thumbnail grid grouped by execution, with click-to-enlarge. Useful for visual sanity checks: confirm that a simulation "looks right" before trusting its metrics. Images are base64-embedded so the report remains self-contained. The section appears automatically when `reporting.gallery.enabled: true` and at least one image is found. See [Per-Test Image Gallery](#per-test-image-gallery) for configuration.

### Software Versions

Renders a table of captured software and library versions per execution. When a component reports more than one distinct version across executions, a prominent drift warning is shown, with outlier cells highlighted. This warning is the cache-mixing detector: it catches studies that mix freshly executed results with older cached results produced by a different software version. The section appears automatically when `benchmark.probes.versions` is configured and at least one `__iops_versions.json` file is present. See [Software Version Capture Probe](#software-version-capture-probe) for configuration.

### Test Summary

Displays execution statistics and parameter space information: total execution time, number of tests executed, cache hit rate (if caching enabled), core-hours consumed (if budget tracking enabled), success/failure counts, and parameter space coverage.

### Best Results

Shows the top N configurations for each metric: parameter values, metric values (mean, standard deviation, sample count), and optionally the rendered command for reproducibility.

**Configuration**:

```yaml
reporting:
  best_results:
    top_n: 10                # Show top N configurations (default: 5)
    show_command: true       # Include rendered commands
    min_samples: 3           # Require at least 3 repetitions (filters unreliable results)
```

### Variable Impact Analysis

Analyzes which variables have the strongest effect on metrics using variance-based importance, helping focus optimization efforts.

**When to use**: Large parameter spaces where you need to identify the most influential variables.

### Parallel Coordinates Plot

Multi-dimensional visualization showing relationships between all variables and metrics: parameter correlations and trade-offs between metrics.

**When to use**: Understanding relationships in multi-variable optimization.

### Bayesian Evolution

Shows optimization progress over iterations: convergence behavior, exploration vs exploitation balance, and improvement over time.

**When to use**: Only relevant when using `search_method: "bayesian"`.

### Bayesian Parameter Evolution

Shows which parameter values were explored at each iteration, with colors indicating the metric value achieved. Disabled by default (can be verbose with many parameters); enable with `bayesian_parameter_evolution: true` in the `sections` config.

### Adaptive Probing Results

Shows adaptive probing outcomes, included automatically when using `search_method: "adaptive"` with no additional configuration:

- **Probing Configuration** (collapsible): the adaptive variable settings (initial value, step method, stop condition, direction, max iterations)
- **Probe Results Summary**: one row per swept variable combination showing the last passing value, the value that triggered the stop condition, iteration count, and stop reason
- **Trajectory Plots**: per metric, an interactive line chart of the metric versus the adaptive variable, one trace per swept variable combination; found values are marked with green-outlined circles, stop-triggered values with red X markers

### Resource Sampling

Displays a summary table (min/max/mean) of resource metrics collected by IOPS probes during execution (CPU/memory utilization, GPU power, temperature, energy, etc.). Appears automatically when `__iops_resource_summary.csv` exists. Resource metrics are also available as regular metrics for custom plots (see [Resource Sampling Plots](#resource-sampling-plots)).

### Custom Plots

User-defined plots specified in the `metrics` section (see below). This includes both benchmark metrics (from parser scripts) and resource sampling metrics (from probes).

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
    bayesian_evolution: true     # Optimization progress (Bayesian only)
    bayesian_parameter_evolution: false  # Parameter exploration (default: false)
    resource_sampling: true      # Resource metrics summary table
    custom_plots: true           # User-defined plots
    gallery: true                # Per-execution image gallery (auto-enabled when images exist)
    versions: true               # Software versions table (auto-enabled when probe data exists)
```

---

## Custom Plots

Define custom plots per metric for detailed analysis.

### Plot Types

IOPS supports 10 plot types. All types accept these optional parameters: `title` (string), `xaxis_label` (string), `yaxis_label` (string, default: metric name), `height` (pixels), and `width` (pixels). Type-specific parameters are listed below.

#### 1. Execution Scatter

A scatter plot showing metric values for each test execution in sequential order. Hover displays all parameter values for each test.

**Required Parameters**: None (uses execution index as x-axis; default x-axis label is "Test Execution ID")

```yaml
metrics:
  bandwidth:
    plots:
      - type: "execution_scatter"
        title: "Bandwidth per Test Execution"
        xaxis_label: "Test ID"
        yaxis_label: "Bandwidth (MB/s)"
```

**When to use**: Identifying outliers, trends across execution order, or verifying result consistency. This is the default first plot in legacy report mode.

#### 2. Bar Charts

Displays metric values with error bars (mean ± standard deviation). Good for comparing discrete parameter values and showing statistical variation.

```yaml
metrics:
  bandwidth:
    plots:
      - type: "bar"
        x_var: "block_size"
        show_error_bars: true
        title: "Bandwidth by Block Size"
```

#### 3. Line Plots

Shows trends across continuous or ordered parameters: scaling behavior, grouped comparisons.

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

#### 4. Scatter Plots

Shows individual data points with optional color/size mapping, for exploring relationships in high-dimensional data.

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

#### 5. Heatmaps

2D heatmaps showing metric values across a two-variable parameter grid.

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

**Supported colorscales**: `"Viridis"`, `"Plasma"`, `"Inferno"`, `"Magma"`, `"Cividis"`, `"Blues"`, `"Reds"`, `"RdBu"`, etc.

#### 6. Box Plots

Box plots showing distribution statistics (quartiles, median) with optional outliers.

**Required Parameters**:
- `x_var` (string): Variable for categorical grouping (x-axis)

**Optional Parameters**:
- `show_outliers` (boolean): Display outlier points beyond whiskers (default: false)

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

#### 7. Violin Plots

Violin plots showing distribution with kernel density estimation and embedded box plot, for detailed comparison of distribution shapes.

**Required Parameters**:
- `x_var` (string): Variable for categorical grouping (x-axis)

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

#### 8. 3D Surface Plots

3D surface plots showing metric values across two variables.

**Required Parameters**:
- `x_var` (string): Variable for x-axis
- `y_var` (string): Variable for y-axis

**Optional Parameters**:
- `z_metric` (string): Metric to display as z-axis/surface (default: current metric)
- `colorscale` (string): Plotly colorscale name (default: "Viridis")

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

**When to use**: Visualizing response surfaces, finding optimal regions in 2D parameter space, understanding interactions between two variables.

#### 9. Parallel Coordinates

Multi-dimensional visualization showing all numeric swept variables and the metric as parallel axes.

**Required Parameters**: None (automatically includes all numeric swept variables)

**Optional Parameters**:
- `colorscale` (string): Colorscale for lines colored by metric value (default: "Viridis")

```yaml
metrics:
  bandwidth:
    plots:
      - type: "parallel_coordinates"
        colorscale: "Plasma"
        title: "Multi-Dimensional Parameter Analysis"
```

**When to use**: Visualizing relationships across many variables simultaneously, identifying parameter correlations.

#### 10. Coverage Heatmap

Multi-variable heatmap showing parameter space coverage with hierarchical row/column indices, similar to a pivot table.

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

```yaml
metrics:
  bandwidth:
    plots:
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
        sort_rows_by: "values"
        sort_cols_by: "values"
        sort_ascending: false
        title: "Bandwidth Sorted by Performance"
```

**When to use**: Visualizing metric values across all variable combinations, spotting coverage gaps (untested combinations show as visually distinct NaN cells), or showing repetition counts with `aggregation: "count"`.

**How it works**:
- Multiple `row_vars` create hierarchical row labels (e.g., "nodes=4, processes_per_node=16")
- Cell values are aggregated with the chosen function when multiple tests share the same parameter combination
- `sort_rows_by`/`sort_cols_by: "index"` (default) sorts by variable values in natural order; `"values"` sorts hierarchically by mean metric performance, level by level, grouping similar-performing configurations
- Interactive hover shows all variable values and the metric value per cell
- Keep total variables to 2-3 for best performance (more variables means a larger pivot table)

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

These plots are used when the `custom_plots` section is enabled and a metric has no specific `metrics.{metric_name}` configuration, giving quick coverage of all parameters without specifying each plot.

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

Define a custom color palette, used for grouping, categorical variables, and multi-series plots:

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

By default, reports are saved to the run's workdir (e.g., `/workdir/run_001/analysis_report.html`). Customize the location:

```yaml
reporting:
  enabled: true
  output_dir: "/custom/path/to/reports"     # Custom directory
  output_filename: "benchmark_report.html"  # Custom filename
```

### Plot Export (Optional)

IOPS can export all plots as image files for publications, presentations, or external documents. This requires the `kaleido` package and is enabled via CLI options:

```bash
pip install iops-benchmark[plots]
```

```bash
iops report ./workdir/run_001 --export-plots                     # PDF (default)
iops report ./workdir/run_001 --export-plots --plot-format png
iops report ./workdir/run_001 --export-plots --plot-format svg   # vector, editable
```

**Supported formats:**

| Format | Extension | Type | Best For |
|--------|-----------|------|----------|
| `pdf` | .pdf | Vector | Publications, LaTeX documents |
| `png` | .png | Raster | Web, presentations, general use |
| `svg` | .svg | Vector | Editable in Inkscape, Illustrator |
| `jpg` | .jpg | Raster | Smaller file size (lossy) |
| `webp` | .webp | Raster | Modern web format, good compression |

**Output structure:**

```
workdir/run_001/
├── analysis_report.html
└── __iops_plots/
    ├── 001_test_summary.pdf
    ├── 002_best_configurations_bandwidth.pdf
    └── ...
```

Files are numbered in report order, with names based on the plot type and metric.

**Note:** Plot export is opt-in; without `--export-plots`, only the HTML report is generated. If `kaleido` is not installed and `--export-plots` is used, a warning is displayed.

---

## Per-Test Image Gallery

The gallery feature embeds per-execution images into the HTML report as a thumbnail grid grouped by execution, with click-to-enlarge (see [Report Sections](#image-gallery)). Pillow is an optional dependency for downscaling; without it, images are embedded at full size.

### Enabling the Gallery

Add `reporting.gallery` to your config and set `enabled: true`:

```yaml
reporting:
  enabled: true
  gallery:
    enabled: true
```

With this minimal configuration, IOPS automatically scans `<execution_dir>/images/` for `*.png` files.

### Image Discovery

IOPS supports two discovery methods that can be combined; results are deduplicated by resolved path.

**1. Convention folder (zero-config beyond enabling)**

Any file matching `pattern` inside `folder` (relative to each execution directory or its `repetition_*` subdirectories) is discovered automatically:

```yaml
reporting:
  gallery:
    enabled: true
    folder: images       # default; scans <execution_dir>/images/
    pattern: "*.png"     # default glob pattern
```

**2. Explicit sources**

Provide a list of Jinja2-templated paths resolved per execution. Glob characters are honored. Absolute paths are used as-is; relative paths are resolved against the execution or repetition directories:

```yaml
reporting:
  gallery:
    enabled: true
    sources:
      - "{{ execution_dir }}/final_state.png"
      - "{{ execution_dir }}/plots/*.png"
```

### Writing Images from Scripts

Use the `{{ artifacts_dir }}` built-in variable in `script_template` to place images in the gallery folder without hardcoding the folder name:

```yaml
scripts:
  - name: "sim"
    script_template: |
      #!/bin/bash
      {{ command.template }}
      mkdir -p {{ artifacts_dir }}
      cp final_state.png {{ artifacts_dir }}/
```

`{{ artifacts_dir }}` resolves to `<execution_dir>/<gallery.folder>` (default: `<execution_dir>/images`) and updates automatically when you change `gallery.folder`.

### Gallery Options

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `false` | Enable the gallery section |
| `folder` | `"images"` | Convention folder scanned per execution directory |
| `sources` | none | Explicit Jinja2-templated paths resolved per execution |
| `pattern` | `"*.png"` | Glob pattern used when scanning the convention folder |
| `max_width` | none | Maximum width in pixels of the embedded image (requires Pillow; degrades gracefully without it). Used for both the thumbnail and the click-to-enlarge view, so set it generously (e.g. 800 to 1200); the grid thumbnail is shrunk to fit its card regardless. Omit to embed images at original resolution. |
| `caption_vars` | report_vars | Variable names shown as the caption under each execution's cards |
| `title` | `"Image Gallery"` | Heading for the gallery section |

Full configuration example:

```yaml
reporting:
  enabled: true
  gallery:
    enabled: true
    folder: images
    sources:
      - "{{ execution_dir }}/final_state.png"
    pattern: "*.png"
    max_width: 512
    caption_vars: [nodes, ppn]
    title: "Simulation thumbnails"
```

To hide the gallery from the report without disabling image collection, use the section toggle:

```yaml
reporting:
  sections:
    gallery: false
```

---

## Software Version Capture Probe

The versions probe captures software and library versions once per execution (metadata, not a measured metric). It is most useful for detecting version drift: when a study mixes freshly executed results with older cached results produced by a different software version, the HTML report shows a prominent warning.

### Configuration

Add `benchmark.probes.versions` with a mapping of component name to a shell snippet that prints the version:

```yaml
benchmark:
  probes:
    versions:
      app: "myapp --version"
      mpi: "mpirun --version | head -1"
      compiler: "gcc --version | head -1"
```

Failing commands record an empty string rather than aborting the run.

### How It Works

1. IOPS writes `__iops_atexit_versions.sh` to each repetition folder and sources it from the generated benchmark script (after the shebang/`#SBATCH` header).
2. The capture function is registered with the centralized exit handler, so it runs **after the benchmark body** via the `EXIT` trap. This matters on HPC systems: the version tools (`mpirun`, your application, compilers) are often only on `PATH` once the benchmark has run its own `module load` commands. Because the trap fires in the same shell, the modified environment is in scope.
3. The probe runs each configured command, captures stdout (first 4000 bytes), and writes `__iops_versions.json`.
4. During report generation, IOPS reads all `__iops_versions.json` files and renders the Software Versions section.
5. The captured versions are also written to the results sink (CSV/Parquet/SQLite) as `version.<component>` columns (e.g. `version.app`, `version.mpi`), one per row, making versions queryable alongside the metrics. To omit them, add `version.*` to `output.sink.exclude`.

> **Note:** Capturing at exit means versions reflect the environment the benchmark actually ran in. If the benchmark crashes before loading its modules, the affected commands record an empty string.

### Report Output

The HTML report includes a table with one row per execution and one column per component, plus a drift warning when any component reports more than one distinct value across executions (outlier cells highlighted). The warning reads: "Warning: software version drift detected. The following components differ across executions. Results produced by different versions may not be comparable (this often happens when a study mixes freshly executed tests with older cached results)."

### Controlling the Section

To hide the Software Versions section from the report:

```yaml
reporting:
  sections:
    versions: false
```

---

## Examples

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

    iops:
      plots:
        - type: "bar"
          x_var: "concurrency"
          show_error_bars: true
          title: "IOPS by Concurrency Level"

  plot_defaults:
    height: 500
    width: null
```

### Multi-Metric Comparison

Metrics can also be used as plot axes to visualize trade-offs:

```yaml
reporting:
  enabled: true

  metrics:
    efficiency:
      plots:
        - type: "scatter"
          x_var: "bandwidth"
          y_var: "latency"
          color_by: "nodes"
          title: "Bandwidth vs Latency Trade-off"
```

### Resource Sampling Plots

When `probes.resource_sampling` or `probes.gpu_sampling` is enabled, resource metrics are automatically registered and can be used in custom plots just like benchmark metrics. Available resource metrics are listed in the generated `report_config.yaml` under "Resource Sampling Metrics".

```yaml
reporting:
  enabled: true

  metrics:
    # GPU energy consumption vs benchmark parameters
    gpu_energy_j:
      plots:
        - type: "bar"
          x_var: "matrix_size"
          title: "GPU Energy Consumption by Matrix Size"
          yaxis_label: "Energy (Joules)"

    # CPU utilization across configurations
    cpu_avg_pct:
      plots:
        - type: "bar"
          x_var: "nodes"
          title: "CPU Utilization by Node Count"
```

Per-GPU metrics (`gpu0_*`, `gpu1_*`, ...) are available on multi-GPU machines.

**Common resource metrics:**

| Metric | Description | Probe |
|--------|-------------|-------|
| `cpu_avg_pct` | Average CPU utilization (%) | `resource_sampling` |
| `cpu_max_pct` | Peak CPU utilization (%) | `resource_sampling` |
| `mem_peak_gb` | Peak memory used (GB) | `resource_sampling` |
| `gpu_avg_utilization_pct` | Average GPU utilization (%) | `gpu_sampling` |
| `gpu_avg_power_w` | Average GPU power draw (W) | `gpu_sampling` |
| `gpu_energy_j` | Total GPU energy consumed (J) | `gpu_sampling` |
| `gpu_avg_temperature_c` | Average GPU temperature (C) | `gpu_sampling` |
| `gpu_mem_peak_mib` | Peak GPU memory used (MiB) | `gpu_sampling` |
| `gpu0_energy_j` | Energy consumed by GPU 0 (J) | `gpu_sampling` |
| `gpu0_avg_power_w` | Average power draw of GPU 0 (W) | `gpu_sampling` |


