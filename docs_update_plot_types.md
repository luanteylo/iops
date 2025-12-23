# Plot Types Documentation Update

This file contains the comprehensive documentation for all 8 plot types to be added to both yaml-schema.md and reporting.md

## Plot Types Reference

### 1. Bar Charts (`bar`)

**Description**: Bar charts displaying metric values with error bars (mean ± standard deviation).

**Required Parameters**:
- `x_var` (string): Variable for x-axis (categorical grouping)

**Optional Parameters**:
- `show_error_bars` (boolean): Display error bars showing standard deviation (default: true)
- `title` (string): Custom plot title
- `xaxis_label` (string): Custom x-axis label
- `yaxis_label` (string): Custom y-axis label
- `height` (integer): Plot height in pixels
- `width` (integer): Plot width in pixels

**Example**:
```yaml
metrics:
  bandwidth:
    plots:
      - type: "bar"
        x_var: "block_size"
        show_error_bars: true
        title: "Bandwidth by Block Size"
        xaxis_label: "Block Size (MB)"
        yaxis_label: "Bandwidth (MB/s)"
```

**When to use**: Comparing discrete parameter values, showing statistical variation across categories.

---

### 2. Line Plots (`line`)

**Description**: Line plots showing trends with optional grouping by another variable.

**Required Parameters**:
- `x_var` (string): Variable for x-axis

**Optional Parameters**:
- `group_by` (string): Variable to group by (creates multiple lines, one per group value)
- `title` (string): Custom plot title
- `xaxis_label` (string): Custom x-axis label
- `yaxis_label` (string): Custom y-axis label
- `height` (integer): Plot height in pixels
- `width` (integer): Plot width in pixels

**Example**:
```yaml
metrics:
  bandwidth:
    plots:
      - type: "line"
        x_var: "block_size"
        group_by: "nodes"           # Creates one line per node count
        title: "Bandwidth Scaling"
        xaxis_label: "Block Size (MB)"
        yaxis_label: "Bandwidth (MB/s)"
```

**When to use**: Visualizing trends, scaling behavior, comparing groups across a continuous range.

---

### 3. Scatter Plots (`scatter`)

**Description**: Scatter plots showing individual data points with optional color/size mapping.

**Required Parameters**:
- `x_var` (string): Variable for x-axis

**Optional Parameters**:
- `y_var` (string): Variable for y-axis (if not provided, uses metric value)
- `color_by` (string): Variable or metric to map to point color (default: current metric)
- `colorscale` (string): Plotly colorscale name (default: "Viridis")
- `title` (string): Custom plot title
- `xaxis_label` (string): Custom x-axis label
- `yaxis_label` (string): Custom y-axis label
- `height` (integer): Plot height in pixels
- `width` (integer): Plot width in pixels

**Example**:
```yaml
metrics:
  bandwidth:
    plots:
      - type: "scatter"
        x_var: "nodes"
        y_var: "processes_per_node"
        color_by: "bandwidth"       # Color points by bandwidth value
        title: "Parameter Space Exploration"
```

**When to use**: Exploring relationships between variables, identifying patterns, visualizing high-dimensional parameter spaces.

---

### 4. Heatmaps (`heatmap`)

**Description**: 2D heatmaps showing metric values across two variables.

**Required Parameters**:
- `x_var` (string): Variable for x-axis
- `y_var` (string): Variable for y-axis

**Optional Parameters**:
- `z_metric` (string): Metric to display as color (default: current metric)
- `colorscale` (string): Plotly colorscale name (default: "Viridis")
- `title` (string): Custom plot title
- `xaxis_label` (string): Custom x-axis label
- `yaxis_label` (string): Custom y-axis label
- `height` (integer): Plot height in pixels
- `width` (integer): Plot width in pixels

**Example**:
```yaml
metrics:
  bandwidth:
    plots:
      - type: "heatmap"
        x_var: "nodes"
        y_var: "block_size"
        colorscale: "Viridis"
        title: "Bandwidth Heatmap"
```

**Supported colorscales**: `Viridis`, `Plasma`, `Inferno`, `Magma`, `Cividis`, `Blues`, `Greens`, `Reds`, `RdBu`, `RdYlGn`, `Spectral`. Add `_r` suffix to reverse (e.g., `Viridis_r`).

**When to use**: Visualizing performance across two-dimensional parameter grids, identifying optimal regions.

---

### 5. Box Plots (`box`)

**Description**: Box plots showing distribution statistics (quartiles, median) with optional outliers.

**Required Parameters**:
- `x_var` (string): Variable for categorical grouping (x-axis)

**Optional Parameters**:
- `show_outliers` (boolean): Display outlier points beyond whiskers (default: false)
- `title` (string): Custom plot title
- `xaxis_label` (string): Custom x-axis label
- `yaxis_label` (string): Custom y-axis label
- `height` (integer): Plot height in pixels
- `width` (integer): Plot width in pixels

**Example**:
```yaml
metrics:
  latency:
    plots:
      - type: "box"
        x_var: "concurrency"
        show_outliers: true
        title: "Latency Distribution by Concurrency"
```

**When to use**: Understanding distributions, detecting outliers, comparing variability across parameter values.

---

### 6. Violin Plots (`violin`)

**Description**: Violin plots showing distribution with kernel density estimation and embedded box plot.

**Required Parameters**:
- `x_var` (string): Variable for categorical grouping (x-axis)

**Optional Parameters**:
- `title` (string): Custom plot title
- `xaxis_label` (string): Custom x-axis label
- `yaxis_label` (string): Custom y-axis label
- `height` (integer): Plot height in pixels
- `width` (integer): Plot width in pixels

**Example**:
```yaml
metrics:
  latency:
    plots:
      - type: "violin"
        x_var: "nodes"
        title: "Latency Distribution by Node Count"
```

**When to use**: Detailed distribution analysis, comparing shapes of distributions, visualizing density patterns.

---

### 7. 3D Surface Plots (`surface_3d`)

**Description**: 3D surface plots showing metric values across two variables.

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

**Example**:
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
```

**When to use**: Visualizing smooth response surfaces, finding optimal regions in 2D parameter space, understanding interactions between two variables.

---

### 8. Parallel Coordinates (`parallel_coordinates`)

**Description**: Multi-dimensional visualization showing all numeric swept variables and the metric as parallel axes.

**Required Parameters**: None (automatically includes all numeric swept variables)

**Optional Parameters**:
- `colorscale` (string): Colorscale for lines colored by metric value (default: "Viridis")
- `title` (string): Custom plot title

**Example**:
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

## Common Parameters (All Plot Types)

All plot types support these common parameters:

- `title` (string): Custom plot title
- `height` (integer): Plot height in pixels (default: 500)
- `width` (integer): Plot width in pixels (default: auto/responsive)

Additionally, plot types with axes support:
- `xaxis_label` (string): Custom x-axis label
- `yaxis_label` (string): Custom y-axis label

---

## Parameter Quick Reference Table

| Plot Type | Required | Optional |
|-----------|----------|----------|
| `bar` | `x_var` | `show_error_bars`, `title`, `xaxis_label`, `yaxis_label`, `height`, `width` |
| `line` | `x_var` | `group_by`, `title`, `xaxis_label`, `yaxis_label`, `height`, `width` |
| `scatter` | `x_var` | `y_var`, `color_by`, `colorscale`, `title`, `xaxis_label`, `yaxis_label`, `height`, `width` |
| `heatmap` | `x_var`, `y_var` | `z_metric`, `colorscale`, `title`, `xaxis_label`, `yaxis_label`, `height`, `width` |
| `box` | `x_var` | `show_outliers`, `title`, `xaxis_label`, `yaxis_label`, `height`, `width` |
| `violin` | `x_var` | `title`, `xaxis_label`, `yaxis_label`, `height`, `width` |
| `surface_3d` | `x_var`, `y_var` | `z_metric`, `colorscale`, `title`, `xaxis_label`, `yaxis_label`, `height`, `width` |
| `parallel_coordinates` | None | `colorscale`, `title` |
