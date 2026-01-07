---
title: "IOPS YAML Format Reference"
---


*Complete guide to the IOPS benchmark configuration format*

---

## Table of Contents

1. [Introduction](#introduction)
2. [File Structure Overview](#file-structure-overview)
3. [Section: `benchmark`](#section-benchmark)
4. [Section: `vars`](#section-vars)
5. [Section: `constraints` (Optional)](#section-constraints-optional)
6. [Section: `command`](#section-command)
7. [Section: `scripts`](#section-scripts)
8. [Section: `output`](#section-output)
9. [Section: `reporting` (Optional)](#section-reporting-optional)
10. [Jinja2 Templating](#jinja2-templating)
11. [Complete Examples](#complete-examples)

---

## Introduction

The IOPS YAML format defines **parametric benchmark experiments**. Instead of writing individual job scripts, you describe:

- **Parameters to sweep** (what varies between tests)
- **Command templates** (how to construct benchmark commands)
- **Execution scripts** (how to run the benchmark)
- **Result parsing** (how to extract metrics)
- **Output storage** (where to save results)

IOPS automatically generates all execution instances and manages the entire workflow.

### Key Concepts

- **Execution Instance**: One concrete test run with specific parameter values
- **Cartesian Product**: All combinations of swept variables
- **Lazy Rendering**: Templates are evaluated at runtime using Jinja2
- **Repetitions**: Each test can be run multiple times for statistical validity

---

## File Structure Overview

A complete IOPS YAML file has these sections:

```yaml
benchmark:       # Global configuration (name, workdir, etc.)
  ...

vars:            # Variable definitions (swept and derived)
  ...

constraints:     # (Optional) Parameter validation rules
  ...

command:         # Command template and metadata
  ...

scripts:         # Execution scripts and parsers
  ...

output:          # Output configuration (CSV, Parquet, SQLite)
  ...

reporting:       # (Optional) Custom report generation
  ...
```

**All sections are required except `constraints` and `reporting`.**

---

## Section: `benchmark`

Defines global benchmark configuration.

### Schema

```yaml
benchmark:
  name: string                    # Required: benchmark name
  description: string             # Optional: human-readable description
  workdir: path                   # Required: base working directory
  sqlite_db: path                 # Optional: cache database location
  repetitions: integer            # Optional: global repetitions (default: 1)
  search_method: string           # Optional: "exhaustive" | "greedy" | "bayesian"
  executor: string                # Optional: "local" | "slurm" (default: "slurm")
  executor_options:               # Optional: executor-specific configuration
    commands:                     # Optional: customize SLURM command templates
      submit: string              # Optional: submit command (default: "sbatch")
      status: string              # Optional: status template (default: "squeue -j {job_id} --noheader --format=%T")
      info: string                # Optional: info template (default: "scontrol show job {job_id}")
      cancel: string              # Optional: cancel template (default: "scancel {job_id}")
    poll_interval: integer        # Optional: status polling interval in seconds (default: 30)
  random_seed: integer            # Optional: seed for randomization (default: 42)
  cache_exclude_vars: list        # Optional: variables to exclude from cache hash
  exhaustive_vars: list           # Optional: variables to test exhaustively at each search point
  report_vars: list               # Optional: variables to include in analysis reports
  max_core_hours: float           # Optional: CPU core-hours budget limit
  cores_expr: string              # Optional: Jinja expression to compute cores (default: "1")
  estimated_time_seconds: float   # Optional: Estimated test duration for dry-run (seconds)
```

### Field Details

#### `name` (required)
Human-readable benchmark name. Used in logs and output.

```yaml
name: "IOR I/O Performance Benchmark"
```

#### `description` (optional)
Free-text description of the benchmark purpose.

```yaml
description: "Measures parallel I/O performance using IOR with varying parameters"
```

#### `workdir` (required)
Base directory for all benchmark outputs. IOPS creates subdirectories:

```
<workdir>/
├── run_001/
│   ├── runs/      # Execution scripts and results
│   └── logs/      # Log files
├── run_002/
...
```

```yaml
workdir: "/scratch/benchmarks/ior"
```

Supports environment variables:

```yaml
workdir: "$HOME/benchmarks"  # Expands to /home/user/benchmarks
```

#### `sqlite_db` (optional)
Path to SQLite database for caching execution results. **Required for `--use-cache` flag.**

```yaml
sqlite_db: "/scratch/benchmarks/ior_cache.db"
```

#### `repetitions` (optional, default: 1)
Number of times each test should be repeated. Each repetition gets a unique ID.

```yaml
repetitions: 3  # Each test runs 3 times
```

#### `search_method` (optional, default: "exhaustive")
Test selection strategy:
- `exhaustive`: Run all parameter combinations (full sweep)
- `random`: Randomly sample N configurations from parameter space
- `bayesian`: Bayesian optimization using Gaussian Process models
- `greedy`: (future) Greedy search optimization

```yaml
search_method: "exhaustive"
```

**When to use each method**:
- **Exhaustive**: Small parameter spaces, need complete coverage, want deterministic results
- **Random**: Large parameter spaces, quick exploration, initial reconnaissance
- **Bayesian**: Expensive evaluations, smooth objective functions, focused optimization

See `random_config` and `bayesian_config` sections below for configuration details.

#### `executor` (optional, default: "slurm")
Execution backend:
- `local`: Run on local machine using subprocess
- `slurm`: Submit via SLURM scheduler

```yaml
executor: "local"
```

#### `executor_options` (optional)
Executor-specific configuration options.

**For SLURM executor**: Customize command templates used for job management. Commands are templates that support `{job_id}` placeholder for runtime substitution. This is useful when running on systems with command wrappers or custom SLURM installations.

```yaml
executor_options:
  commands:
    submit: "sbatch"                                      # Default submit command
    status: "squeue -j {job_id} --noheader --format=%T"  # Job status query template
    info: "scontrol show job {job_id}"                   # Job information template
    cancel: "scancel {job_id}"                           # Job cancellation template
  poll_interval: 30                                       # Status polling interval (seconds)
```

**Example with wrapper and custom flags**:
```yaml
executor_options:
  commands:
    submit: "lrms-wrapper sbatch"
    status: "lrms-wrapper -r {job_id} --custom-format"   # Custom flags: -r instead of -j
    info: "lrms-wrapper info {job_id}"
    cancel: "lrms-wrapper kill {job_id}"
  poll_interval: 10                                       # Check status every 10 seconds
```

**Placeholders**:
- `{job_id}` - Replaced with the SLURM job ID at runtime

**Notes**:
- The `submit` command specified here is a default. Individual scripts can override it via `scripts[].submit`.
- The `{job_id}` placeholder is required for status, info, and cancel commands.

#### `random_seed` (optional, default: 42)
Seed for random operations (e.g., repetition interleaving).

```yaml
random_seed: 12345
```

#### `cache_exclude_vars` (optional)
List of variable names to exclude from cache hash calculation. **Use this when variables contain run-specific values that change between executions but shouldn't invalidate the cache.**

**Common use case**: Derived variables that include the run directory path (e.g., `summary_file`, `output_path`) will differ between runs (`run_001` vs `run_002`), causing cache misses even for identical tests.

```yaml
cache_exclude_vars: ["summary_file", "output_dir"]
```

**Example scenario**:
```yaml
vars:
  nodes:
    type: int
    sweep: { mode: list, values: [2, 4, 8] }

  summary_file:
    type: str
    expr: "{{ execution_dir }}/summary.txt"  # Contains run_NNN path

benchmark:
  cache_exclude_vars: ["summary_file"]  # Exclude from cache matching
```

Without `cache_exclude_vars`, the same test would generate different cache keys:
- Run 1: `summary_file=/workdir/run_001/summary.txt` → hash: `abc123`
- Run 2: `summary_file=/workdir/run_002/summary.txt` → hash: `def456` (cache miss!)

With `cache_exclude_vars: ["summary_file"]`, both runs match the same cache entry.

**Note**: Only exclude variables that don't affect benchmark behavior. Excluding a variable like `block_size` would be incorrect since it directly impacts results.

#### `exhaustive_vars` (optional)

List of variable names to test exhaustively at each search point. **This enables hybrid search strategies** that combine intelligent search (Bayesian/random) with exhaustive testing for specific variables.

**How it works:**
- With Bayesian/random search: The search method selects points in the reduced space (non-exhaustive variables), then IOPS expands each point with all combinations of exhaustive variables
- With exhaustive search: No effect (already tests all combinations)

**Use cases:**
- Analyze the impact of specific variables (e.g., OST count) while efficiently exploring others
- Combine intelligent search for expensive parameters with exhaustive testing for cheap ones
- Reduce total test count while maintaining complete coverage for variables of interest

```yaml
exhaustive_vars: ["ost_num"]
```

**Example scenario:**

Without `exhaustive_vars` (pure Bayesian search):
```yaml
vars:
  nodes: { type: int, sweep: { mode: list, values: [2, 4, 8, 16] } }
  block_size: { type: int, sweep: { mode: list, values: [4, 8, 16, 32] } }
  ost_num: { type: int, sweep: { mode: list, values: [1, 2, 4, 8] } }

benchmark:
  search_method: "bayesian"
  bayesian_config:
    n_iterations: 20  # Tests 20 random points in 3D space
```

With `exhaustive_vars`:
```yaml
vars:
  nodes: { type: int, sweep: { mode: list, values: [2, 4, 8, 16] } }
  block_size: { type: int, sweep: { mode: list, values: [4, 8, 16, 32] } }
  ost_num: { type: int, sweep: { mode: list, values: [1, 2, 4, 8] } }

benchmark:
  search_method: "bayesian"
  exhaustive_vars: ["ost_num"]  # Test all OST values at each Bayesian point
  bayesian_config:
    n_iterations: 5  # Tests 5 points in 2D space (nodes, block_size)
  # Total tests: 5 points × 4 ost_num values = 20 tests
```

**Result**: Same number of tests, but you get complete OST coverage at each selected (nodes, block_size) configuration.

**Example with multiple exhaustive variables:**
```yaml
benchmark:
  search_method: "random"
  exhaustive_vars: ["io_pattern", "ost_num"]
  random_config:
    n_samples: 10
# If io_pattern has 2 values and ost_num has 4 values:
# Total tests: 10 samples × 2 patterns × 4 OSTs = 80 tests
```

**Notes:**
- Implementation: `matrix.py` partitions swept variables into search space and exhaustive space, then builds their cross-product
- Works with Bayesian and random search methods
- With exhaustive search, this option has no effect (already exhaustive)

#### `report_vars` (optional)

List of variable names to include in analysis reports. **Use this to control which variables appear in plots and Pareto frontier analysis.**

When generating reports with `iops analyze`, only these variables will be used for:
- Parameter sweep plots
- Pareto frontier calculations
- Variable correlation analysis

**Use cases:**
- Exclude string variables that can't be meaningfully plotted
- Focus analysis on key parameters
- Simplify reports for large parameter spaces

```yaml
report_vars: ["nodes", "processes_per_node", "volume_size_gb"]
```

**Example scenario:**

Configuration with many variables:
```yaml
vars:
  nodes: { type: int, sweep: { mode: list, values: [2, 4, 8] } }
  processes_per_node: { type: int, sweep: { mode: list, values: [16, 32] } }
  volume_size_gb: { type: int, sweep: { mode: list, values: [4, 8, 16] } }
  filesystem_path: { type: str, sweep: { mode: list, values: ["/scratch", "/beegfs"] } }
  test_id: { type: str, expr: "test_{{ execution_id }}" }

benchmark:
  report_vars: ["nodes", "processes_per_node", "volume_size_gb"]
  # Excludes filesystem_path and test_id from plots
```

**Default behavior:**
If `report_vars` is not specified, all **numeric swept variables** are included in analysis reports.

**Notes:**
- Only affects report generation with `iops analyze`
- Does not affect execution or result storage
- All variables are still saved in output files

#### `max_core_hours` (optional)
Maximum CPU core-hours budget for benchmark execution. When specified, IOPS will stop scheduling new tests once the accumulated core-hours exceeds this limit. **Can be overridden by the `--max-core-hours` CLI argument.**

```yaml
max_core_hours: 1000.0  # Stop after 1000 core-hours
```

**Core-hours calculation**: `cores × execution_time_hours`

**Behavior**:
- Tests already running will complete
- No new tests will be scheduled once budget is exceeded
- Budget status is logged after each test (DEBUG level)
- Final summary shows total core-hours used and utilization percentage

**Use cases**:
- Limit costs on cloud/HPC systems with core-hour billing
- Control resource usage for long-running parameter sweeps
- Enforce time-bounded exploration in optimization workflows

#### `cores_expr` (optional, default: "1")
Jinja2 expression to compute the number of CPU cores used by each test. Used for budget tracking with `max_core_hours`. **Defaults to 1 core if not specified.**

```yaml
benchmark:
  cores_expr: "{{ nodes * ppn }}"  # Total cores = nodes × processes-per-node
  max_core_hours: 500.0
```

**Examples**:

Simple core count:
```yaml
vars:
  cores:
    type: int
    sweep: { mode: list, values: [4, 8, 16] }

benchmark:
  cores_expr: "{{ cores }}"
```

Computed from multiple variables:
```yaml
vars:
  nodes:
    type: int
    sweep: { mode: list, values: [2, 4, 8] }
  ppn:  # processes per node
    type: int
    expr: "16"

benchmark:
  cores_expr: "{{ nodes * ppn }}"  # e.g., 4 nodes × 16 ppn = 64 cores
```

**Notes**:
- Expression is evaluated for each test using its variable values
- Must evaluate to an integer
- Used only when `max_core_hours` is set (via config or CLI)
- If evaluation fails, defaults to 1 core with a warning

#### `estimated_time_seconds` (optional)
Estimated execution time per test in seconds. Used for core-hours estimation in dry-run mode. **Can be overridden by the `--time-estimate` CLI argument.**

```yaml
estimated_time_seconds: 300.0  # Estimate 5 minutes per test
```

**Use cases**:
- Preview total core-hours before execution with `--dry-run`
- Validate budget constraints
- Plan experiment timelines
- Compare different parameter sweep configurations

**Dry-run example**:
```bash
# Preview execution plan
iops config.yaml --dry-run --time-estimate 120
iops config.yaml -n --time-estimate 120

# Output shows:
# - Total tests to execute
# - Core-hours estimates per test
# - Total estimated core-hours
# - Budget comparison (if budget set)
# - Wall-clock time estimate
# - Sample test configurations
```

#### `random_config` (optional, required if `search_method: "random"`)
Configuration for random sampling planner. Randomly samples N configurations from the full parameter space instead of exhaustive search.

**When to use**:
- Large parameter spaces where exhaustive search is too expensive
- Initial exploration before focused optimization
- Quick reconnaissance of parameter space
- Budget-constrained experiments

**Configuration options**:
```yaml
benchmark:
  search_method: "random"
  random_config:
    # Option 1: Explicit number of samples (mutually exclusive with percentage)
    n_samples: 20  # Sample exactly 20 random configurations

    # Option 2: Percentage of total space (mutually exclusive with n_samples)
    # percentage: 0.1  # Sample 10% of parameter space

    # Optional: behavior when n_samples >= total_space
    fallback_to_exhaustive: true  # Use full space if sample >= total (default: true)
```

**Parameters**:
- **`n_samples`** (int, optional): Explicit number of configurations to sample
  - Must be positive integer
  - Mutually exclusive with `percentage`
  - If `n_samples >= total_space`, behavior depends on `fallback_to_exhaustive`

- **`percentage`** (float, optional): Proportion of parameter space to sample
  - Value between 0.0 and 1.0 (e.g., 0.1 = 10%)
  - Mutually exclusive with `n_samples`
  - Clamped to 1.0 if > 1.0 (with warning)
  - Ensures at least 1 sample even for very small percentages

- **`fallback_to_exhaustive`** (bool, optional, default: true): Behavior when sample size >= total space
  - `true`: Use exhaustive search (all configurations)
  - `false`: Clamp sample size to total space size

**Examples**:

Explicit number of samples:
```yaml
vars:
  processes: { type: int, sweep: { mode: list, values: [1,2,4,8,16,32] } }  # 6 values
  volume: { type: int, sweep: { mode: list, values: [1,2,4,8,16] } }        # 5 values
  # Total space: 6 × 5 = 30 configurations

benchmark:
  search_method: "random"
  random_config:
    n_samples: 10  # Sample 10 out of 30 (33%)
  repetitions: 3   # Each sample runs 3 times
  # Total tests: 10 × 3 = 30 test executions
```

Percentage-based sampling:
```yaml
benchmark:
  search_method: "random"
  random_config:
    percentage: 0.2  # Sample 20% of parameter space
  random_seed: 42    # Ensures reproducible sampling
```

**Reproducibility**:
Use `random_seed` in the benchmark config to ensure consistent sampling across runs:
```yaml
benchmark:
  search_method: "random"
  random_config:
    n_samples: 15
  random_seed: 12345  # Same seed = same sample
```

**Notes**:
- Sampling is without replacement (no duplicate configurations)
- Samples complete ExecutionInstance objects (preserves derived variables)
- Repetitions are randomly interleaved for statistical robustness
- Same `random_seed` produces identical samples across runs

#### `bayesian_config` (optional, required if `search_method: "bayesian"`)
Configuration for Bayesian optimization planner. Uses surrogate models to intelligently explore parameter space and find optimal configurations with fewer evaluations than exhaustive search.

**Requires**: `scikit-optimize` package (`pip install scikit-optimize`)

**Configuration**:
```yaml
benchmark:
  search_method: "bayesian"
  bayesian_config:
    objective_metric: "throughput"  # Required: metric to optimize (must match parser output)
    objective: "minimize"           # Optimization direction (default: "minimize")
    n_initial_points: 5             # Random exploration before optimization (default: 5)
    n_iterations: 20                # Total evaluations (default: 20)
    acquisition_func: "EI"          # Acquisition function (default: "EI")
    base_estimator: "RF"            # Surrogate model type (default: "RF")
    xi: 0.01                        # Exploration trade-off for EI/PI (default: 0.01)
    kappa: 1.96                     # Exploration parameter for LCB (default: 1.96)
```

**Parameters**:
- **`objective_metric`** (str, **required**): Name of metric to optimize. Must match a metric defined in the `parser.metrics` section.
- **`objective`** (str, default: `"minimize"`): Optimization direction: `"maximize"` or `"minimize"`
- **`n_initial_points`** (int, default: 5): Number of random samples before Bayesian optimization starts
- **`n_iterations`** (int, default: 20): Total number of parameter configurations to evaluate
- **`acquisition_func`** (str, default: `"EI"`): Acquisition function to select next point:
  - `"EI"`: Expected Improvement - balanced exploration/exploitation
  - `"PI"`: Probability of Improvement - more exploitative
  - `"LCB"`: Lower Confidence Bound - configurable via kappa
- **`base_estimator`** (str, default: `"RF"`): Surrogate model type:
  - `"RF"`: Random Forest - robust, handles categorical variables well
  - `"GP"`: Gaussian Process - best for continuous variables, struggles with categorical
  - `"ET"`: Extra Trees - similar to RF with more randomness
  - `"GBRT"`: Gradient Boosted Regression Trees
- **`xi`** (float, default: 0.01): Exploration-exploitation trade-off for EI/PI. Higher values favor exploration.
- **`kappa`** (float, default: 1.96): Exploration parameter for LCB. Higher values favor exploration.

**Example with throughput maximization**:
```yaml
benchmark:
  search_method: "bayesian"
  bayesian_config:
    objective_metric: "bwMiB"
    objective: "maximize"
    n_initial_points: 10
    n_iterations: 50
    base_estimator: "RF"
    acquisition_func: "EI"
```

**Notes**:
- Bayesian optimization is most effective when evaluations are expensive and the parameter space is large
- The optimizer reports search space coverage: how many configurations it will evaluate vs. exhaustive search
- Random Forest (`RF`) is recommended for mixed parameter spaces (numeric + categorical)
- Use with `exhaustive_vars` to combine intelligent search with exhaustive testing of specific variables

**See**: `docs/examples/example_bayesian.yaml` for complete example

### Complete Example

```yaml
benchmark:
  name: "IOR Parallel I/O Benchmark"
  description: "Testing I/O performance with MPI-IO"
  workdir: "/scratch/$USER/ior_benchmark"
  sqlite_db: "/scratch/$USER/ior_cache.db"
  repetitions: 3
  search_method: "exhaustive"
  executor: "local"
  cache_exclude_vars: ["summary_file"]  # Exclude path-based derived vars
  random_seed: 42
```

---

## Section: `vars`

Defines the parameter space and derived variables.

### Variable Types

1. **Swept Variables**: Create multiple executions via Cartesian product
2. **Derived Variables**: Computed from other variables

### Swept Variables

#### Schema

```yaml
vars:
  variable_name:
    type: string              # Required: "int" | "float" | "str" | "bool"
    sweep:                    # Required for swept vars
      mode: string            # Required: "list" | "range"
      values: list            # For mode: list
      start: number           # For mode: range
      end: number             # For mode: range
      step: number            # For mode: range
```

#### List Mode

Explicit list of values:

```yaml
vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4, 8]

  io_pattern:
    type: str
    sweep:
      mode: list
      values: ["sequential", "random"]
```

Creates: **4 nodes × 2 patterns = 8 executions**

#### Range Mode

Numeric range (inclusive):

```yaml
vars:
  processes_per_node:
    type: int
    sweep:
      mode: range
      start: 8
      end: 32
      step: 8
```

Creates values: `[8, 16, 24, 32]`

**Note**: `end` is inclusive. `step` can be negative for descending ranges.

### Derived Variables

Computed from other variables using expressions.

#### Schema

```yaml
vars:
  variable_name:
    type: string              # Required: "int" | "float" | "str" | "bool"
    expr: string              # Required: expression (Python or Jinja2)
```

#### Expression Syntax

**Python Expressions** (for arithmetic):

```yaml
vars:
  block_size_mb:
    type: int
    expr: "(volume_size_gb * 1024) / (nodes * processes_per_node)"
```

Available functions: `min()`, `max()`, `abs()`, `round()`, `floor()`, `ceil()`, `int()`, `float()`

**Jinja2 Templates** (for strings or complex logic):

```yaml
vars:
  summary_file:
    type: str
    expr: "{{ execution_dir }}/summary_{{ execution_id }}_{{ repetition }}.json"

  output_dir:
    type: str
    expr: "{{ workdir }}/results/node_{{ nodes }}"
```

### Built-in Variables

Available in all expressions:

| Variable | Type | Description |
|----------|------|-------------|
| `execution_id` | int | Unique execution ID (1, 2, 3, ...) |
| `repetition` | int | Current repetition (1, 2, 3, ...) |
| `repetitions` | int | Total repetitions for this test |
| `workdir` | str | Base working directory |
| `execution_dir` | str | Per-execution directory |

### Complete Example

```yaml
vars:
  # Swept variables
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4]

  processes_per_node:
    type: int
    sweep:
      mode: range
      start: 8
      end: 16
      step: 8

  volume_size_gb:
    type: int
    sweep:
      mode: list
      values: [2, 4, 8]

  # Derived variables
  total_processes:
    type: int
    expr: "nodes * processes_per_node"

  block_size_mb:
    type: int
    expr: "(volume_size_gb * 1024) / total_processes"

  summary_file:
    type: str
    expr: "{{ execution_dir }}/summary_{{ execution_id }}_{{ repetition }}.json"
```

**Generates**: `3 nodes × 2 processes × 3 volumes = 18 executions`

---

## Section: `constraints` (Optional)

Defines validation rules for parameter combinations. Constraints filter invalid configurations before execution, preventing wasted time on tests that would fail.

### Schema

```yaml
constraints:
  - name: string              # Required: unique constraint identifier
    rule: string              # Required: Python expression returning bool
    violation_policy: string  # Optional: "skip" | "error" | "warn" (default: "skip")
    description: string       # Optional: human-readable explanation
```

### Fields

#### `name` (required)
Unique identifier for this constraint. Used in logs and error messages.

#### `rule` (required)
Python expression that must evaluate to `True` (valid) or `False` (invalid).

**Available in expressions:**
- All variables (swept, derived, and fixed)
- Math functions: `min`, `max`, `abs`, `round`, `floor`, `ceil`, `int`, `float`

**Expression must return boolean:**
- Valid: `block_size % transfer_size == 0`
- Valid: `nodes * processes_per_node <= 128`
- Valid: `transfer_size <= block_size`

#### `violation_policy` (optional, default: "skip")

Action to take when constraint is violated:

- **`skip`** (default): Silently filter out invalid parameter combinations
- **`error`**: Stop execution immediately with error message
- **`warn`**: Log warning but proceed with execution

#### `description` (optional)
Human-readable explanation of the constraint. Included in violation messages.

### Example

```yaml
vars:
  block_size:
    type: int
    sweep:
      mode: list
      values: [4, 8, 16, 32, 64]

  transfer_size:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4, 8]

  num_processes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4]

constraints:
  # Ensure block size is multiple of transfer size (common in IOR)
  - name: "block_transfer_alignment"
    rule: "block_size % transfer_size == 0"
    violation_policy: "skip"
    description: "Block size must be a multiple of transfer size"

  # Transfer size cannot exceed block size
  - name: "transfer_size_limit"
    rule: "transfer_size <= block_size"
    violation_policy: "skip"

  # Warn about potentially problematic configurations
  - name: "reasonable_total_size"
    rule: "block_size * num_processes >= 8"
    violation_policy: "warn"
    description: "Total data size should be at least 8MB"
```

**Effect:**
- Without constraints: `5 block_size × 4 transfer_size × 3 processes = 60 combinations`
- With constraints: Filters invalid combinations (e.g., `block_size=4, transfer_size=8`)
- Result: Only valid combinations are executed

### Common Use Cases

**Parameter divisibility:**
```yaml
rule: "block_size % transfer_size == 0"
```

**Relationship validation:**
```yaml
rule: "transfer_size <= block_size"
```

**Resource limits:**
```yaml
rule: "nodes * processes_per_node <= 256"
```

**Minimum thresholds:**
```yaml
rule: "volume_size_gb >= 16"
```

**Complex conditions:**
```yaml
rule: "nodes > 1 and processes_per_node >= 4"
```

---

## Section: `command`

Defines the benchmark command template and metadata.

### Schema

```yaml
command:
  template: string            # Required: command template (Jinja2)
  metadata: dict              # Optional: arbitrary metadata (Jinja2)
  env: dict                   # Optional: environment variables (Jinja2)
```

### `template` (required)

The benchmark command as a Jinja2 template. All variables are available.

```yaml
command:
  template: >
    mpirun -np {{ total_processes }}
    ior -w -b {{ block_size_mb }}mb -t 1mb
    -O summaryFile={{ summary_file }}
    -O summaryFormat=JSON
    -o {{ output_dir }}/data.ior
```

**Multi-line commands**: Use `>` or `|` for readability.

### `metadata` (optional)

Arbitrary key-value metadata stored with execution results. Can use templates.

```yaml
command:
  metadata:
    operation: "write"
    io_engine: "MPI-IO"
    access_pattern: "contiguous"
    transfer_size: "{{ block_size_mb }}"
    total_data: "{{ volume_size_gb }}"
```

Metadata appears in output as `metadata.operation`, `metadata.io_engine`, etc.

### `env` (optional)

Environment variables to set before command execution. Can use templates.

```yaml
command:
  env:
    OMP_NUM_THREADS: "{{ processes_per_node }}"
    MPI_BUFFER_SIZE: "{{ block_size_mb * 1024 }}"
    CUSTOM_VAR: "benchmark_{{ execution_id }}"
```

### Complete Example

```yaml
command:
  template: >
    mpirun --mca btl ^openib
    -np {{ nodes * processes_per_node }}
    ior -w -b {{ block_size_mb }}mb -t 1mb
    -O summaryFile={{ summary_file }}
    -o {{ output_dir }}/data.ior

  metadata:
    operation: "write"
    io_engine: "MPI-IO"
    nodes: "{{ nodes }}"
    processes: "{{ total_processes }}"

  env:
    OMP_NUM_THREADS: "1"
    MPI_BUFFER_SIZE: "4194304"
```

---

## Section: `scripts`

Defines execution scripts, submission commands, and result parsers.

### Schema

```yaml
scripts:
  - name: string                    # Required: script identifier
    submit: string                  # Required: submission command
    script_template: string         # Required: script content (Jinja2)
    post:                           # Optional: post-processing script
      script: string                # Required if post is present
    parser:                         # Optional: result parser
      file: string                  # Required: output file to parse
      metrics:                      # Required: list of metrics
        - name: string              # Required: metric name
          path: string              # Optional: future use
      parser_script: string         # Required: Python parser function
```

### `name` (required)

Script identifier. Used for file naming.

```yaml
name: "ior_benchmark"
```

### `submit` (required)

Command to execute the script:
- **Local executor**: `bash` or `sh`
- **SLURM executor**: `sbatch` or custom submission command

```yaml
submit: "bash"                    # Local
submit: "sbatch --parsable"       # SLURM with parsable output
```

### `script_template` (required)

The script content as a Jinja2 template. All variables available, plus `{{ command.template }}`.

#### Local Executor Example

```yaml
script_template: |
  #!/bin/bash
  set -euo pipefail

  echo "Starting execution {{ execution_id }}, repetition {{ repetition }}"

  # Load modules
  module load mpi ior

  # Run benchmark
  {{ command.template }}

  echo "Completed successfully"
```

#### SLURM Executor Example

```yaml
script_template: |
  #!/bin/bash
  #SBATCH --job-name=ior_{{ execution_id }}
  #SBATCH --output={{ execution_dir }}/stdout
  #SBATCH --error={{ execution_dir }}/stderr
  #SBATCH --nodes={{ nodes }}
  #SBATCH --ntasks-per-node={{ processes_per_node }}
  #SBATCH --time=01:00:00

  module load mpi ior

  {{ command.template }}
```

### `post` (optional)

Post-processing script executed after main script completes.

```yaml
post:
  script: |
    #!/bin/bash
    echo "Job completed at $(date)"
    echo "Summary file: {{ summary_file }}"
    ls -lh {{ execution_dir }}
```

### `parser` (optional but recommended)

Defines how to extract metrics from benchmark output.

#### `file` (required)

Path to output file (can be templated):

```yaml
parser:
  file: "{{ summary_file }}"
```

#### `metrics` (required)

List of metrics to extract:

```yaml
parser:
  metrics:
    - name: bwMiB
    - name: iops
    - name: latency
```

#### `parser_script` (required)

Python function that parses the output file. **Must be named `parse` and return a dict.**

```yaml
parser:
  parser_script: |
    import json

    def parse(file_path: str):
        """
        Parse IOR JSON output.

        Returns:
            dict with metric names as keys
        """
        with open(file_path, "r") as f:
            data = json.load(f)

        tests = data.get("tests", [])
        if not tests:
            raise ValueError("No tests found")

        results = tests[0].get("Results", [])[0]

        return {
            "bwMiB": float(results["bwMiB"]),
            "iops": float(results["OPs"]),
            "latency": float(results["MeanTime"])
        }
```

**Requirements**:
- Function must be named `parse`
- Takes one argument: `file_path` (str)
- Returns dict with metric names matching `metrics` list
- Must not have side effects

### Complete Example

```yaml
scripts:
  - name: "ior_mpi"
    submit: "bash"

    script_template: |
      #!/bin/bash
      set -euo pipefail

      # Setup
      module load openmpi/4.1.1 ior/3.3.0

      echo "Execution {{ execution_id }}, repetition {{ repetition }}/{{ repetitions }}"
      echo "Parameters: nodes={{ nodes }}, ppn={{ processes_per_node }}"

      # Run benchmark
      {{ command.template }}

      echo "Completed at $(date)"

    post:
      script: |
        #!/bin/bash
        echo "Results saved to {{ summary_file }}"
        echo "File size: $(stat -f%z {{ summary_file }} 2>/dev/null || stat -c%s {{ summary_file }})"

    parser:
      file: "{{ summary_file }}"
      metrics:
        - name: bwMiB
        - name: iops
        - name: latency
      parser_script: |
        import json

        def parse(file_path: str):
            with open(file_path, "r") as f:
                data = json.load(f)

            result = data["tests"][0]["Results"][0]

            return {
                "bwMiB": float(result["bwMiB"]),
                "iops": float(result["OPs"]),
                "latency": float(result["MeanTime"])
            }
```

---

## Section: `output`

Defines where and how to store execution results.

### Schema

```yaml
output:
  sink:
    type: string              # Required: "csv" | "parquet" | "sqlite"
    path: string              # Required: output file path (Jinja2)
    mode: string              # Optional: "append" | "overwrite" (default: append)
    include: list             # Optional: fields to include (mutually exclusive with exclude)
    exclude: list             # Optional: fields to exclude (mutually exclusive with include)
    table: string             # Optional: table name for SQLite (default: "results")
```

### `type` (required)

Output format:
- `csv`: Comma-separated values
- `parquet`: Apache Parquet (columnar)
- `sqlite`: SQLite database

```yaml
type: csv
```

### `path` (required)

Output file path. Can use templates:

```yaml
path: "{{ workdir }}/results.csv"
path: "{{ workdir }}/results.parquet"
path: "/scratch/benchmark_results.db"
```

### `mode` (optional, default: "append")

Write mode:
- `append`: Add new results to existing file
- `overwrite`: Replace file contents

```yaml
mode: append
```

**Schema evolution**: For CSV/Parquet, if new columns appear during append, the file is rewritten with extended schema.

### `include` / `exclude` (optional, mutually exclusive)

Field filtering using dot notation.

#### Available Fields

| Prefix | Fields |
|--------|--------|
| `benchmark.*` | `name`, `description`, `workdir`, etc. |
| `execution.*` | `execution_id`, `repetition`, `execution_dir`, etc. |
| `vars.*` | All variable names (e.g., `vars.nodes`) |
| `metadata.*` | All command metadata keys |
| `metrics.*` | All parser metric names |

#### Include Example

```yaml
output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
    include:
      - "execution.execution_id"
      - "vars.nodes"
      - "vars.processes_per_node"
      - "vars.block_size_mb"
      - "metrics.bwMiB"
      - "metrics.iops"
```

#### Exclude Example

```yaml
output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
    exclude:
      - "benchmark.description"
      - "metadata.access_pattern"
```

### `table` (optional, SQLite only)

Table name for SQLite output:

```yaml
output:
  sink:
    type: sqlite
    path: "{{ workdir }}/results.db"
    table: "ior_results"
```

### Complete Examples

#### CSV Output

```yaml
output:
  sink:
    type: csv
    path: "{{ workdir }}/ior_results.csv"
    mode: append
    exclude:
      - "benchmark.description"
```

#### Parquet Output

```yaml
output:
  sink:
    type: parquet
    path: "{{ workdir }}/results.parquet"
    mode: append
    include:
      - "execution.*"
      - "vars.*"
      - "metrics.*"
```

#### SQLite Output

```yaml
output:
  sink:
    type: sqlite
    path: "/scratch/benchmarks/all_results.db"
    table: "ior_benchmark"
    mode: append
```

---

## Section: `reporting` (Optional)

Enables user-configurable report generation with custom plots and visualizations.

### Overview

The `reporting` section allows you to:

- Auto-generate interactive HTML reports after benchmark execution
- Define custom plots per metric with full control over visualization
- Customize report themes, colors, and styling
- Control which report sections to include
- Regenerate reports with different configurations using `--report-config`

**This feature is optional and disabled by default** (opt-in with `enabled: true`).

### When to Use

- **Automatic reports**: Set `enabled: true` to generate reports after each execution
- **Custom visualizations**: Define per-metric plots for detailed analysis
- **Post-execution analysis**: Use `iops --analyze` to generate reports from completed runs
- **Visualization iteration**: Use `--report-config` to try different plot configurations without re-running benchmarks

### Schema

```yaml
reporting:
  # Core settings
  enabled: boolean                  # Optional: enable auto-generation (default: false)
  output_dir: path                  # Optional: report output directory (default: workdir)
  output_filename: string           # Optional: report filename (default: "analysis_report.html")

  # Theme configuration
  theme:
    style: string                   # Optional: plotly theme name (default: "plotly_white")
    colors: list                    # Optional: custom color palette
    font_family: string             # Optional: font family (default: "Segoe UI, sans-serif")

  # Section control
  sections:
    test_summary: boolean           # Optional: execution statistics (default: true)
    best_results: boolean           # Optional: top configurations (default: true)
    variable_impact: boolean        # Optional: variance analysis (default: true)
    parallel_coordinates: boolean   # Optional: multi-dimensional plot (default: true)
    pareto_frontier: boolean        # Optional: multi-objective analysis (default: true)
    bayesian_evolution: boolean     # Optional: Bayesian progress (default: true)
    custom_plots: boolean           # Optional: user-defined plots (default: true)

  # Best results configuration
  best_results:
    top_n: integer                  # Optional: number of top configs (default: 5)
    show_command: boolean           # Optional: include rendered command (default: true)
    min_samples: integer            # Optional: minimum repetitions required (default: 1)

  # Per-metric plot definitions
  metrics:
    metric_name:                    # Metric name from parser
      plots:
        - type: string              # Required: plot type
          x_var: string             # Optional: x-axis variable
          y_var: string             # Optional: y-axis variable (scatter, surface_3d)
          z_metric: string          # Optional: z-axis metric (heatmap, surface_3d)
          group_by: string          # Optional: grouping variable
          color_by: string          # Optional: color mapping variable
          size_by: string           # Optional: size mapping variable
          title: string             # Optional: plot title
          xaxis_label: string       # Optional: x-axis label
          yaxis_label: string       # Optional: y-axis label
          colorscale: string        # Optional: colorscale name (default: "Viridis")
          show_error_bars: boolean  # Optional: show error bars (default: true)
          show_outliers: boolean    # Optional: show outliers (default: true)
          height: integer           # Optional: plot height in pixels
          width: integer            # Optional: plot width in pixels
          per_variable: boolean     # Optional: one plot per variable (default: false)

  # Default plots (fallback for metrics without specific config)
  default_plots:
    - type: string                  # Same schema as metrics.*.plots
      per_variable: boolean
      # ... other plot options

  # Plot sizing defaults
  plot_defaults:
    height: integer                 # Optional: default height (default: 500)
    width: integer                  # Optional: default width (default: null/auto)
    margin:                         # Optional: plot margins
      l: integer                    # Left margin
      r: integer                    # Right margin
      t: integer                    # Top margin
      b: integer                    # Bottom margin
```

### Field Details

#### `enabled` (optional, default: false)

Enable automatic report generation after benchmark execution.

```yaml
reporting:
  enabled: true
```

**When disabled (default)**, reports can still be generated manually using `iops --analyze`.

#### `output_dir` (optional)

Directory where reports are saved. Defaults to the run's workdir if not specified.

```yaml
reporting:
  output_dir: "/custom/path/to/reports"
```

#### `output_filename` (optional, default: "analysis_report.html")

Name of the generated HTML report file.

```yaml
reporting:
  output_filename: "benchmark_report.html"
```

#### `theme` (optional)

Customizes report appearance.

##### `theme.style` (optional, default: "plotly_white")

Plotly theme name. Available themes:
- `"plotly_white"` - Clean white background (default)
- `"plotly"` - Plotly default
- `"plotly_dark"` - Dark theme
- `"ggplot2"` - ggplot2-style
- `"seaborn"` - Seaborn-style
- `"simple_white"` - Minimal white

```yaml
reporting:
  theme:
    style: "plotly_dark"
```

##### `theme.colors` (optional)

Custom color palette for plots (hex codes).

```yaml
reporting:
  theme:
    colors:
      - "#636EFA"
      - "#EF553B"
      - "#00CC96"
      - "#AB63FA"
```

##### `theme.font_family` (optional, default: "Segoe UI, sans-serif")

Font family for all text in plots.

```yaml
reporting:
  theme:
    font_family: "Arial, Helvetica, sans-serif"
```

#### `sections` (optional)

Controls which sections appear in the report. All sections are enabled by default.

```yaml
reporting:
  sections:
    test_summary: true           # Execution statistics
    best_results: true           # Top N configurations
    variable_impact: true        # Variance-based importance
    parallel_coordinates: true   # Multi-dimensional visualization
    pareto_frontier: true        # Multi-objective analysis
    bayesian_evolution: false    # Skip if not using Bayesian
    custom_plots: true           # User-defined plots
```

**Section descriptions:**

- **`test_summary`**: Execution statistics (runtime, cache hits, core-hours, success rate, parameter space)
- **`best_results`**: Top N configurations per metric with parameter values
- **`variable_impact`**: Variance-based analysis showing which variables affect metrics most
- **`parallel_coordinates`**: Multi-dimensional plot showing all variables and metrics
- **`pareto_frontier`**: Multi-objective optimization analysis (requires 2+ metrics)
- **`bayesian_evolution`**: Optimization progress over iterations (Bayesian search only)
- **`custom_plots`**: User-defined plots from `metrics` section

#### `best_results` (optional)

Configures the best results section.

```yaml
reporting:
  best_results:
    top_n: 10                # Show top 10 configurations (default: 5)
    show_command: true       # Include rendered command (default: true)
    min_samples: 3           # Require at least 3 repetitions (default: 1)
```

#### `metrics` (optional)

Defines custom plots for specific metrics. Each metric can have multiple plots.

```yaml
reporting:
  metrics:
    bandwidth:               # Metric name (must match parser output)
      plots:
        - type: "line"
          x_var: "block_size"
          group_by: "nodes"
          title: "Bandwidth vs Block Size"

        - type: "heatmap"
          x_var: "nodes"
          y_var: "block_size"
```

**Plot types:**

1. **`bar`** - Bar charts with error bars (mean ± std dev)
2. **`line`** - Line plots with optional grouping
3. **`scatter`** - Scatter plots with color/size mapping
4. **`heatmap`** - 2D heatmaps for two variables
5. **`box`** - Box plots showing distribution statistics
6. **`violin`** - Violin plots with kernel density estimation
7. **`surface_3d`** - 3D surface plots
8. **`parallel_coordinates`** - Multi-dimensional parallel coordinates
9. **`execution_scatter`** - Scatter plot showing metric per execution with full parameter details on hover
10. **`coverage_heatmap`** - Multi-variable heatmap showing complete parameter space coverage with hierarchical indexing

**Parameter Requirements by Plot Type:**

| Plot Type | Required Parameters | Key Optional Parameters |
|-----------|-------------------|------------------------|
| `bar` | `x_var` | `show_error_bars`, `title`, axis labels, sizing |
| `line` | `x_var` | `group_by`, `title`, axis labels, sizing |
| `scatter` | `x_var` | `y_var`, `color_by`, `colorscale`, `title`, axis labels, sizing |
| `heatmap` | `x_var`, `y_var` | `z_metric`, `colorscale`, `title`, axis labels, sizing |
| `box` | `x_var` | `show_outliers`, `title`, axis labels, sizing |
| `violin` | `x_var` | `title`, axis labels, sizing |
| `surface_3d` | `x_var`, `y_var` | `z_metric`, `colorscale`, `title`, axis labels, sizing |
| `parallel_coordinates` | None | `colorscale`, `title` |
| `execution_scatter` | None | `title`, axis labels, `colorscale`, sizing |
| `coverage_heatmap` | `row_vars`, `col_var` | `aggregation`, `show_missing`, `sort_rows_by`, `sort_cols_by`, `sort_ascending`, `colorscale`, `title`, axis labels, sizing |

**All plot options:**

- **`type`** (required): Plot type (see above)
- **`x_var`**: Variable for x-axis (required for most plot types)
- **`y_var`**: Variable for y-axis (required for heatmap and surface_3d; optional for scatter)
- **`z_metric`**: Metric to display as z-axis/surface (optional; default: current metric; applies to heatmap, surface_3d)
- **`group_by`**: Variable to group by (optional; creates multiple lines/series; applies to line)
- **`color_by`**: Variable or metric to map to point color (optional; default: current metric; applies to scatter)
- **`size_by`**: Variable to map to point size (optional; applies to scatter)
- **`title`**: Plot title (optional)
- **`xaxis_label`**: X-axis label (optional)
- **`yaxis_label`**: Y-axis label (optional)
- **`colorscale`**: Plotly colorscale name (optional; default: "Viridis"; applies to heatmap, scatter, surface_3d, parallel_coordinates, execution_scatter, coverage_heatmap)
- **`show_error_bars`**: Show error bars (optional; default: true; applies to bar, line)
- **`show_outliers`**: Show outliers beyond whiskers (optional; default: false; applies to box)
- **`height`**: Plot height in pixels (optional; default: 500)
- **`width`**: Plot width in pixels (optional; default: auto/responsive)
- **`per_variable`**: Generate one plot per swept variable (optional; default: false)
- **`row_vars`**: List of variables for row multi-index (required for coverage_heatmap)
- **`col_var`**: Variable for column axis (required for coverage_heatmap)
- **`aggregation`**: Aggregation function - "mean", "median", "count", "std", "min", "max" (optional; default: "mean"; applies to coverage_heatmap)
- **`show_missing`**: Highlight missing data (NaN) with distinct color (optional; default: true; applies to coverage_heatmap)
- **`sort_rows_by`**: Sort rows by "index" (variable values, default) or "values" (metric aggregation with hierarchical multi-level sorting) (optional; applies to coverage_heatmap)
- **`sort_cols_by`**: Sort columns by "index" (variable values, default) or "values" (metric aggregation) (optional; applies to coverage_heatmap)
- **`sort_ascending`**: Sort direction for "values" mode - false (highest first, default) or true (lowest first) (optional; applies to coverage_heatmap)

**Note**: When using `sort_rows_by: "values"` with multi-level row indices, each level is sorted hierarchically by its group's mean performance. For example, with `row_vars: ["nodes", "processes_per_node"]`, the nodes are first sorted by their overall mean performance, then within each nodes group, the processes_per_node values are sorted by their mean performance within that specific nodes group.

#### `default_plots` (optional)

Fallback plots for metrics without specific `metrics.{name}` configuration.

```yaml
reporting:
  default_plots:
    - type: "bar"
      per_variable: true      # One bar chart per variable
      show_error_bars: true
```

These plots are only used when:
- `sections.custom_plots: true`
- A metric has no entry in `metrics`

#### `plot_defaults` (optional)

Default sizing for all plots.

```yaml
reporting:
  plot_defaults:
    height: 600              # Default height (default: 500)
    width: null              # Auto width (default: null)
    margin:
      l: 80                  # Left margin
      r: 80                  # Right margin
      t: 100                 # Top margin
      b: 80                  # Bottom margin
```

Individual plots can override these defaults.

### Examples

#### Minimal Configuration

Enable auto-generation with defaults:

```yaml
reporting:
  enabled: true
```

#### Custom Theme

```yaml
reporting:
  enabled: true
  theme:
    style: "plotly_dark"
    colors: ["#00d4ff", "#ff006e", "#ffbe0b"]
    font_family: "Arial, sans-serif"
```

#### Per-Metric Custom Plots

```yaml
reporting:
  enabled: true

  metrics:
    bandwidth:
      plots:
        - type: "line"
          x_var: "block_size"
          group_by: "nodes"
          title: "Bandwidth vs Block Size"
          xaxis_label: "Block Size (MB)"
          yaxis_label: "Bandwidth (MB/s)"

        - type: "heatmap"
          x_var: "nodes"
          y_var: "block_size"
          colorscale: "Viridis"
          title: "Bandwidth Heatmap"

        - type: "scatter"
          x_var: "nodes"
          y_var: "processes_per_node"
          color_by: "bandwidth"

    latency:
      plots:
        - type: "bar"
          x_var: "concurrency"
          show_error_bars: true
```

#### Section Control

```yaml
reporting:
  enabled: true

  sections:
    test_summary: true
    best_results: true
    variable_impact: true
    parallel_coordinates: false    # Skip for simple benchmarks
    pareto_frontier: false         # Skip for single-metric benchmarks
    bayesian_evolution: false      # Not using Bayesian search
    custom_plots: true

  best_results:
    top_n: 10
    show_command: true
    min_samples: 3
```

#### Complete Example

```yaml
reporting:
  enabled: true
  output_dir: "/scratch/reports"
  output_filename: "ior_performance.html"

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
    bayesian_evolution: false
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
          title: "Bandwidth Scaling"
          show_error_bars: true

        - type: "heatmap"
          x_var: "nodes"
          y_var: "block_size"
          colorscale: "Viridis"

    iops:
      plots:
        - type: "bar"
          x_var: "concurrency"
          show_error_bars: true
          height: 600

  default_plots:
    - type: "bar"
      per_variable: true
      show_error_bars: true

  plot_defaults:
    height: 500
    width: null
```

### Usage Modes

#### 1. Automatic Generation

Set `enabled: true` in your config:

```yaml
reporting:
  enabled: true
```

Run benchmark normally - report generates automatically:

```bash
iops config.yaml
```

#### 2. Manual Generation

Generate report from completed run:

```bash
iops --analyze /path/to/workdir/run_001
```

Works with any run, regardless of whether `reporting` was configured.

#### 3. Custom Report Config

Regenerate with custom visualization settings:

```bash
iops --analyze /path/to/workdir/run_001 --report-config custom_report.yaml
```

**custom_report.yaml** contains only the `reporting` section:

```yaml
reporting:
  enabled: true
  theme:
    style: "plotly_dark"
  metrics:
    bandwidth:
      plots:
        - type: "line"
          x_var: "block_size"
          group_by: "nodes"
```

This allows experimenting with different visualizations without re-running benchmarks.

### Configuration Priority

When using `--report-config`:

1. **CLI-provided config** (highest priority)
2. **Metadata from execution** (stored in workdir)
3. **Legacy defaults** (fallback)

### Backward Compatibility

- **Fully backward compatible**: Old runs without `reporting` config can still be analyzed
- **Opt-in by default**: `enabled: false` prevents surprise report generation
- **No breaking changes**: Existing configurations work without modification

### Notes

- Reports are self-contained HTML files with embedded interactive Plotly visualizations
- All plots are interactive (zoom, pan, hover for details)
- Metric names in `metrics` must exactly match parser output
- Variable names must match those defined in `vars`
- See [Custom Reports & Visualization](../user-guide/reporting.md) for detailed usage guide

---

## Jinja2 Templating

All string fields support Jinja2 templating with `{{ variable }}` syntax.

### Available Context

| Category | Variables |
|----------|-----------|
| **Execution** | `execution_id`, `repetition`, `repetitions` |
| **Benchmark** | `workdir`, `execution_dir` |
| **Variables** | All vars (swept and derived) |
| **Metadata** | All command.metadata keys |
| **Command** | `command.template` |

### Examples

```yaml
# File paths
summary_file: "{{ execution_dir }}/summary_{{ execution_id }}_r{{ repetition }}.json"

# Conditional logic
script_name: "{% if nodes > 4 %}large_scale{% else %}small_scale{% endif %}_job.sh"

# Loops (advanced)
module_list: "{% for mod in ['mpi', 'ior', 'hdf5'] %}module load {{ mod }}; {% endfor %}"

# Filters
uppercase_name: "{{ benchmark.name | upper }}"
```

### Strict Mode

Templates use `StrictUndefined`: referencing undefined variables raises an error immediately.

---

## Complete Examples

### Example 1: Simple Local Execution

```yaml
benchmark:
  name: "Simple IOR Test"
  workdir: "/tmp/ior_test"
  executor: "local"
  repetitions: 2

vars:
  processes:
    type: int
    sweep:
      mode: list
      values: [4, 8]

  summary_file:
    type: str
    expr: "{{ execution_dir }}/summary.json"

command:
  template: >
    mpirun -np {{ processes }}
    ior -w -b 1gb -t 1mb
    -O summaryFile={{ summary_file }}
    -O summaryFormat=JSON

scripts:
  - name: "ior"
    submit: "bash"
    script_template: |
      #!/bin/bash
      {{ command.template }}

    parser:
      file: "{{ summary_file }}"
      metrics:
        - name: bwMiB
      parser_script: |
        import json
        def parse(file_path: str):
            with open(file_path) as f:
                data = json.load(f)
            return {"bwMiB": data["tests"][0]["Results"][0]["bwMiB"]}

output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
```

### Example 2: SLURM Execution

```yaml
benchmark:
  name: "IOR Optimization"
  workdir: "/scratch/$USER/ior_benchmark"
  sqlite_db: "/scratch/$USER/ior_cache.db"
  executor: "slurm"
  repetitions: 3

vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4, 8]

  processes_per_node:
    type: int
    sweep:
      mode: list
      values: [16, 32]

  volume_size_gb:
    type: int
    sweep:
      mode: list
      values: [4, 8, 16]

  block_size_mb:
    type: int
    expr: "(volume_size_gb * 1024) / (nodes * processes_per_node)"

  summary_file:
    type: str
    expr: "{{ execution_dir }}/summary.json"

command:
  template: >
    mpirun -np {{ nodes * processes_per_node }}
    ior -w -b {{ block_size_mb }}mb -t 1mb
    -O summaryFile={{ summary_file }}
    -O summaryFormat=JSON

scripts:
  - name: "ior_slurm"
    submit: "sbatch --parsable"

    script_template: |
      #!/bin/bash
      #SBATCH --job-name=ior_{{ execution_id }}
      #SBATCH --nodes={{ nodes }}
      #SBATCH --ntasks-per-node={{ processes_per_node }}
      #SBATCH --output={{ execution_dir }}/stdout
      #SBATCH --error={{ execution_dir }}/stderr
      #SBATCH --time=00:30:00

      module load openmpi ior
      {{ command.template }}

    parser:
      file: "{{ summary_file }}"
      metrics:
        - name: bwMiB
        - name: iops
      parser_script: |
        import json
        def parse(file_path: str):
            with open(file_path) as f:
                data = json.load(f)
            result = data["tests"][0]["Results"][0]
            return {
                "bwMiB": float(result["bwMiB"]),
                "iops": float(result["OPs"])
            }

output:
  sink:
    type: parquet
    path: "{{ workdir }}/results.parquet"
    exclude:
      - "benchmark.description"
```

### Example 3: Caching and Custom Metadata

```yaml
benchmark:
  name: "Cached IOR Sweep"
  workdir: "/scratch/ior"
  sqlite_db: "/scratch/ior_cache.db"  # Enable caching
  executor: "local"
  repetitions: 3
  random_seed: 12345

vars:
  nodes:
    type: int
    sweep:
      mode: range
      start: 1
      end: 4
      step: 1

  block_size_mb:
    type: int
    sweep:
      mode: list
      values: [16, 32, 64]

  summary_file:
    type: str
    expr: "{{ execution_dir }}/summary_{{ execution_id }}.json"

command:
  template: >
    ior -w -b {{ block_size_mb }}mb
    -O summaryFile={{ summary_file }}
    -O summaryFormat=JSON

  metadata:
    benchmark_version: "1.0"
    nodes_used: "{{ nodes }}"
    block_size: "{{ block_size_mb }}"

  env:
    IOR_BUFFER_SIZE: "{{ block_size_mb * 1048576 }}"

scripts:
  - name: "ior"
    submit: "bash"
    script_template: |
      #!/bin/bash
      set -euo pipefail
      echo "Run {{ repetition }}/{{ repetitions }}"
      {{ command.template }}

    parser:
      file: "{{ summary_file }}"
      metrics:
        - name: bwMiB
      parser_script: |
        import json
        def parse(file_path: str):
            with open(file_path) as f:
                data = json.load(f)
            return {"bwMiB": data["tests"][0]["Results"][0]["bwMiB"]}

output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
    include:
      - "execution.execution_id"
      - "execution.repetition"
      - "vars.nodes"
      - "vars.block_size_mb"
      - "metadata.*"
      - "metrics.*"
```
