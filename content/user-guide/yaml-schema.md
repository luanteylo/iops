---
title: "IOPS YAML Format Reference"
weight: 10
---

*Complete guide to the IOPS benchmark configuration format*

---

## Table of Contents

1. [File Structure Overview](#file-structure-overview)
2. [`benchmark`](#benchmark)
3. [`vars`](#vars)
4. [`constraints` (optional)](#constraints-optional)
5. [`command`](#command)
6. [`scripts`](#scripts)
7. [`output`](#output)
8. [`reporting` (optional)](#reporting-optional)
9. [`machines` (optional)](#machines-optional)

See also: [Templating and Context Reference](../templating-and-context) for Jinja2 syntax, dynamic values, conditionals, and context variables.

---

## File Structure Overview

```yaml
benchmark:       # Global configuration (name, workdir, executor, search method)
vars:            # Variable definitions (swept and derived)
constraints:     # (Optional) Parameter validation rules
command:         # Command template and labels
scripts:         # Execution scripts and parsers
output:          # Output configuration (CSV, Parquet, SQLite)
reporting:       # (Optional) Report generation settings
machines:        # (Optional) Per-machine config overrides
```

**Required sections:** `benchmark`, `vars`, `command`, `scripts`, `output`

---

## `benchmark`

Defines global benchmark configuration.

```yaml
benchmark:
  name: string                      # Required: benchmark name
  workdir: path                     # Required: base working directory
  description: string               # Optional: human-readable description
  repetitions: integer              # Optional: repetitions per test (default: 1)

  search_method: string             # Optional: "exhaustive" | "random" | "bayesian" | "adaptive"
  random_config:                    # Required if search_method: "random"
    n_samples: integer              #   Sample exactly N configurations
    percentage: float               #   OR sample percentage of parameter space
    fallback_to_exhaustive: boolean #   Use full space if sample >= total (default: true)
  bayesian_config:                  # Required if search_method: "bayesian"
    objective_metric: string        #   Required: metric to optimize
    objective: string               #   "minimize" | "maximize" (default: "minimize")
    fallback_to_exhaustive: boolean #   Use exhaustive if n_iterations >= total space (default: true)
    n_iterations: integer           #   Total evaluations (default: 20)
    n_initial_points: integer       #   Random samples before optimization (default: 5)
    acquisition_func: string        #   "EI" | "PI" | "LCB" (default: "EI")
    base_estimator: string          #   "RF" | "GP" | "ET" | "GBRT" (default: "RF")
    xi: float                       #   Exploration trade-off for EI/PI (default: 0.01)
    kappa: float                    #   Exploration parameter for LCB (default: 1.96)
    early_stop_on_convergence: bool #   Stop when optimizer converges (default: false)
    convergence_patience: integer   #   Convergences before early stop (default: 3)
    xi_boost_factor: float          #   xi multiplier when stuck (default: 5.0)
    max_retries: integer            #   Re-asks per iteration on a visited point before random fallback (default: 10)

  executor: string                  # Optional: "local" | "slurm" (default: "slurm")
  slurm_options:                 # Optional: SLURM-specific configuration
    commands:                       #   SLURM command templates
      submit: string                #     Submit command (default: "sbatch")
      status: string                #     Status template (default: "squeue -j {job_id} ...")
      info: string                  #     Info template (default: "scontrol show job {job_id}")
      cancel: string                #     Cancel template (default: "scancel {job_id}")
    poll_interval: integer          #   Status polling interval in seconds (default: 30)
    allocation:                     #   Single-allocation mode (SLURM only)
      mode: string                  #     "single" | "per-test" (default: "per-test")
      allocation_script: string     #     SBATCH directives for allocation (required if mode: "single")
      test_timeout: integer         #     Per-test timeout in seconds (default: 3600)

  random_seed: integer              # Optional: seed for randomization (default: 42)
  cache_file: path                  # Optional: cache file location
  cache_exclude_vars: list          # Optional: vars to exclude from cache hash

  probes:                           # Optional: probe configuration
    system_snapshot: boolean        #   Collect system info (default: true)
    execution_index: boolean        #   Write metadata files (default: true)
    resource_sampling: boolean      #   Enable CPU/memory sampling (default: false)
    gpu_sampling: boolean           #   Enable GPU metrics tracing (default: false)
    sampling_interval: float        #   Sampling interval in seconds (default: 1.0)
    versions:                       #   Optional: capture software/library versions
      component_name: string        #   name -> shell command (e.g. "myapp --version")

  parallel: integer                 # Optional: max concurrent tests (default: 1)

  create_folders_upfront: boolean   # Optional: create all folders at start (default: false)
  exhaustive_vars: list             # Optional: vars to test exhaustively
  report_vars: list                 # Optional: vars to include in reports
  max_core_hours: float             # Optional: CPU core-hours budget limit
  cores_expr: string                # Optional: Jinja expression for cores (default: "1")
  estimated_time_seconds: float     # Optional: estimated test duration (seconds)
```

#### `name` (required)
Human-readable benchmark name. Used in logs and output.

#### `workdir` (required)
Base directory for all benchmark outputs. Supports environment variables. Created automatically on first run if it does not exist.

#### `repetitions` (optional, default: 1)
Number of times each test is repeated.

#### `search_method` (optional, default: "exhaustive")
Test selection strategy: `exhaustive`, `random`, `bayesian`, or `adaptive`. See [Adaptive Variables](../adaptive-variables) for the `adaptive` method.

<details>
<summary><strong>random_config</strong> (required if search_method: "random")</summary>

- `n_samples` and `percentage` are mutually exclusive
- `percentage` is a fraction between 0 and 1 (e.g., `0.5` samples 50% of the space); values above 1.0 are rejected

</details>

<details>
<summary><strong>bayesian_config</strong> (required if search_method: "bayesian")</summary>

Default values are empirically tuned: with 20 iterations (~7% of search space), Bayesian optimization achieves ~90% of optimal vs ~79% for random search.

**Options:**
- `fallback_to_exhaustive` (default: true): switches to exhaustive search when `n_iterations >= total_space_size`, avoiding optimizer overhead for small parameter spaces.
- `early_stop_on_convergence` (default: false): when the optimizer converges (keeps suggesting already-visited configurations), `xi` is boosted by `xi_boost_factor` (default: 5.0) to encourage exploration and escape local optima; after `convergence_patience` (default: 3) consecutive convergences, the run stops early.
- `max_retries` (default: 10): how many times per iteration the optimizer is re-asked when its suggestion maps to an already-visited point before falling back to random sampling from unvisited points. Each retry refits the surrogate model, so lower values (e.g. 2-3) speed up large `n_iterations` runs where suggestions frequently collide.

**Surrogate models:**
- `RF`: Random Forest (default) - most consistent results, handles categorical/mixed spaces well
- `ET`: Extra Trees - similar to RF, slightly higher variance
- `GP`: Gaussian Process - best for continuous spaces, struggles with categoricals
- `GBRT`: Gradient Boosted Regression Trees

</details>

#### `executor` (optional, default: "slurm")
Execution backend: `local` or `slurm`.

<details>
<summary><strong>slurm_options</strong> (optional, SLURM only)</summary>

`commands` customizes the SLURM command templates (see defaults in the schema above); the `{job_id}` placeholder is replaced at runtime. Useful for systems with command wrappers or custom SLURM installations.

**Single-Allocation Mode:**

Run all tests within ONE SLURM allocation instead of submitting individual jobs per test:

```yaml
benchmark:
  executor: "slurm"
  slurm_options:
    allocation:
      mode: "single"
      test_timeout: 300  # 5 minutes per test (default: 3600)
      allocation_script: |
        #SBATCH --nodes=8
        #SBATCH --time=02:00:00
        #SBATCH --partition=batch
        #SBATCH --account=myaccount
        #SBATCH --exclusive
```

**When to use:** HPC systems with job limits, long queue wait times, or many small tests.

See [Single-Allocation Mode](../single-allocation-mode) for details.

</details>

#### `random_seed` (optional, default: 42)
Seed for random operations (repetition interleaving, random/bayesian sampling).

#### `cache_file` (optional)
Path to cache file. Required for `--use-cache` flag.

#### `cache_exclude_vars` (optional)
Variables to exclude from cache hash (e.g., path-based derived variables).

<details>
<summary><strong>probes</strong> (optional)</summary>

Configuration for IOPS probes (system monitoring and execution tracking):

| Field | Default | Description |
|-------|---------|-------------|
| `system_snapshot` | `true` | Collect hardware/environment info from compute nodes |
| `execution_index` | `true` | Write metadata files for `iops find` command |
| `resource_sampling` | `false` | Enable CPU and memory sampling during execution. See [Resource Sampling](../resource-tracing) |
| `gpu_sampling` | `false` | Enable GPU metrics sampling (utilization, power, temperature, memory, clocks). Supports NVIDIA GPUs via nvidia-smi. See [Resource Sampling](../resource-tracing) |
| `sampling_interval` | `1.0` | Sampling interval in seconds for resource and GPU sampling |
| `versions` | none | Capture software/library versions per execution. Mapping of component name to shell command. Captured after the benchmark body (via the exit handler, so tools loaded by the benchmark's own `module load` commands are in scope) into `__iops_versions.json`, and also written to the results sink as `version.<component>` columns. The HTML report shows a drift warning when versions differ across executions. |

</details>

#### `create_folders_upfront` (optional, default: false)
Create all execution folders at run start instead of lazily during execution.

When enabled, all `exec_XXXX` folders exist before execution begins and tests skipped by constraints or planner selection get a `SKIPPED` status, giving full visibility into the parameter space (useful for debugging constraints and planner behavior). When disabled, folders are created lazily and skipped tests have no folder. Requires `probes.execution_index: true` to write status files.

#### `exhaustive_vars` (optional)
Variables to test exhaustively at each search point (for hybrid strategies).

#### `max_core_hours` (optional)
CPU core-hours budget. Overridable via `--max-core-hours`.

#### `cores_expr` (optional, default: "1")
Jinja2 expression to compute cores per test (e.g., `"{{ nodes * ppn }}"`).

#### `estimated_time_seconds` (optional)
Estimated time per test. Used for dry-run budget analysis.

#### `parallel` (optional, default: 1)
Maximum number of tests to run concurrently (thread pool). Overridable via `--parallel N`. Works with both `local` and `slurm` executors.

Planner-aware behavior:
- **Exhaustive / Random**: Supports any degree of parallelism (tests are independent).
- **Bayesian**: Always capped to 1 (the optimizer's ask/tell cycle is strictly sequential). A warning is logged if a higher value is requested.
- **Adaptive**: Parallelism is capped to the number of independent probes (one per swept-variable combination). Tests within a single probe remain sequential.

Ignored in single-allocation mode (`slurm_options.allocation.mode: "single"`).

---

## `vars`

Defines the parameter space (swept variables) and computed values (derived variables).

```yaml
vars:
  # Swept variable (list mode)
  variable_name:
    type: string                # Required: "int" | "float" | "str" | "bool" | "list"
    sweep:
      mode: list
      values: [1, 2, 4, 8]

  # Swept variable (range mode)
  variable_name:
    type: int
    sweep:
      mode: range
      start: 8
      end: 32
      step: 8

  # Conditional variable (swept only when condition is true)
  variable_name:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4]
    when: "other_var == true"   # Optional: condition expression
    default: 0                  # Required if 'when' is specified

  # Adaptive variable (probing search)
  variable_name:
    type: int
    adaptive:
      initial: 1000             # Starting value (required)
      factor: 2                 # Multiplicative step (one of factor/increment/step_expr)
      stop_when: "exit_code != 0"  # Stop condition (required)
      max_iterations: 10        # Safety limit (optional)
      direction: "ascending"    # "ascending" (default) or "descending"

  # Derived variable
  variable_name:
    type: int
    expr: "nodes * processes_per_node"
```

#### `type` (required)
Data type: `int`, `float`, `str`, `bool`, or `list`.

The `list` type is used for derived variables that hold arrays, enabling indexed access in templates. See [Templating Guide](../templating-and-context#list-variables-for-correlated-parameters) for examples.

#### `sweep` (for swept variables)
Defines values to sweep. Creates executions via Cartesian product. Mutually exclusive with `expr` and `adaptive`.

`mode: list` takes an explicit `values` list. `mode: range` takes `start`, `end`, `step` (inclusive; `start: 8, end: 32, step: 8` creates `[8, 16, 24, 32]`); `step` can be negative for descending ranges.

#### `expr` (for derived variables)
Expression to compute the variable. Mutually exclusive with `sweep` and `adaptive`.

<details>
<summary><strong>Expression Examples</strong></summary>

**Python arithmetic:**
```yaml
vars:
  block_size_mb:
    type: int
    expr: "(volume_size_gb * 1024) // (nodes * processes_per_node)"

  total_processes:
    type: int
    expr: "nodes * processes_per_node"
```

**Jinja2 templates:**
```yaml
vars:
  summary_file:
    type: str
    expr: "{{ execution_dir }}/summary_{{ execution_id }}_{{ repetition }}.json"

  output_path:
    type: str
    expr: "{{ workdir }}/results/node_{{ nodes }}"
```

Available functions: `min()`, `max()`, `abs()`, `round()`, `floor()`, `ceil()`, `int()`, `float()`

</details>

Built-in variables (`execution_id`, `repetition`, `repetitions`, `workdir`, `execution_dir`, `artifacts_dir`, `os_env`, ...) are available in expressions; see [Standard Context Variables](../templating-and-context#standard-context-variables).

#### `adaptive` (for adaptive/probing variables)
Defines a variable that is explored by adaptive probing. Mutually exclusive with `sweep` and `expr`. Requires `benchmark.search_method: "adaptive"`. Only one adaptive variable is allowed per config.

See [Adaptive Variables](../adaptive-variables) for a full guide with examples.

<details>
<summary><strong>Adaptive Configuration Fields</strong></summary>

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `initial` | Yes | | Starting value |
| `factor` | One of three | | Multiplicative step (next = previous * factor) |
| `increment` | One of three | | Additive step (next = previous + increment) |
| `step_expr` | One of three | | Jinja2 expression for custom progression |
| `stop_when` | Yes | | Python expression evaluated after each execution |
| `max_iterations` | No | No limit | Maximum number of values to test |
| `direction` | No | `"ascending"` | `"ascending"` or `"descending"` |

</details>

#### `when` (for conditional variables, optional)
Condition expression for conditional sweep. When true, the variable is swept normally; when false, it uses the `default` value. Only valid for swept variables. This eliminates redundant combinations where a variable is irrelevant given another variable's value. See [Execution Matrix Generation](../matrix-generation#conditional-variables) for how conditional variables shape the matrix.

#### `default` (required if `when` is specified)
Value to use when the `when` condition is false. Must be compatible with the variable's `type`.

<details>
<summary><strong>Conditional Variable Examples</strong></summary>

**Basic conditional:**
```yaml
vars:
  use_compression:
    type: bool
    sweep:
      mode: list
      values: [true, false]

  compression_level:
    type: int
    sweep:
      mode: list
      values: [1, 5, 9]
    when: "use_compression"    # Only sweep when use_compression is true
    default: 0                 # Use 0 when use_compression is false
```

Without `when`: 2 × 3 = 6 combinations
With `when`: 3 (true) + 1 (false) = 4 combinations

Conditions can chain: a variable's `when` may reference another conditional variable (e.g., `when: "feature_mode != 'disabled'"` where `feature_mode` itself has a `when`).

**Available operators:** `==`, `!=`, `<`, `>`, `<=`, `>=`, `and`, `or`, `not`

**Available functions:** `min()`, `max()`, `abs()`, `round()`, `floor()`, `ceil()`

</details>

---

## `constraints` (optional)

Defines validation rules for parameter combinations.

```yaml
constraints:
  - name: string              # Required: unique constraint identifier
    rule: string              # Required: Python expression returning bool
    violation_policy: string  # Optional: "skip" | "error" | "warn" (default: "skip")
    description: string       # Optional: human-readable explanation
```

#### `name` (required)
Unique identifier for this constraint.

#### `rule` (required)
Python expression evaluating to `True` (valid) or `False` (invalid).

Available context:
- All variables defined in `vars`
- `os_env`: System environment variables (dict) - e.g., `os_env.get('MY_VAR', '')`
- Math functions: `min`, `max`, `abs`, `round`, `floor`, `ceil`, `int`, `float`

#### `violation_policy` (optional, default: "skip")
- `skip`: Filter out invalid combinations
- `error`: Stop execution immediately
- `warn`: Log warning but proceed

#### `description` (optional)
Human-readable explanation.

<details>
<summary><strong>Examples</strong></summary>

```yaml
constraints:
  # Divisibility
  - name: "block_transfer_alignment"
    rule: "block_size % transfer_size == 0"
    violation_policy: "skip"
    description: "Block size must be a multiple of transfer size"

  # Resource limits
  - name: "max_processes"
    rule: "nodes * processes_per_node <= 256"
    violation_policy: "warn"

  # Environment variable requirement
  - name: "require_scratch_dir"
    rule: "os_env.get('SCRATCH', '') != ''"
    violation_policy: "error"
    description: "SCRATCH environment variable must be set"
```

</details>

---

## `command`

Defines the benchmark command template and labels.

```yaml
command:
  template: string              # Required: command template (Jinja2)
  labels:                       # Optional: user-defined labels
    key: value
```

#### `template` (required)
The benchmark command as a Jinja2 template.

```yaml
command:
  template: >
    ior -w -b {{ block_size_mb }}mb -t 1mb
    -O summaryFile={{ summary_file }}
    -o {{ output_path }}/data.ior
```

#### `labels` (optional)
User-defined key-value labels stored with results. Appears as `labels.*` columns in output.

Note: `metadata.*` is reserved for IOPS internal fields (executor status, timing, errors).

```yaml
command:
  labels:
    operation: "write"
    io_engine: "MPI-IO"
    access_pattern: "contiguous"
```

---

## `scripts`

Defines execution scripts, submission commands, and result parsers.

```yaml
scripts:
  - name: string                    # Required: script identifier
    script_template: |              # Required: script content (Jinja2)
      #!/bin/bash
      ...
      {{ command.template }}

    inputs:                         # Optional: input files generated before script runs
      - name: string                #   Required: logical id, referenced as {{ inputs.<name>.path }}
        path: string                #   Required: destination path on disk (Jinja2)
        template: |                 #   Inline content (Jinja2). Use EITHER template OR file.
          ...
        file: string                #   Path to external template file (alternative to `template`)
        mode: string                #   Optional octal string, e.g. "0644"

    post:                           # Optional: post-processing
      script: |
        #!/bin/bash
        ...

    parser:                         # Optional: result parser
      file: string                  #   Output file to parse
      metrics:                      #   Metrics to extract
        - name: string
      parser_script: |              #   Python parser function
        def parse(file_path: str):
            ...
            return {"metric": value}
```

#### `name` (required)
Script identifier. Used for file naming.

#### `script_template` (required)
Script content as Jinja2 template. Use `{{ command.template }}` to include the command.

```yaml
scripts:
  - name: "ior"
    script_template: |
      #!/bin/bash
      #SBATCH --job-name=iops_{{ execution_id }}
      #SBATCH --output={{ execution_dir }}/stdout
      #SBATCH --nodes={{ nodes }}
      #SBATCH --ntasks-per-node={{ processes_per_node }}
      #SBATCH --time=01:00:00

      module load mpi ior
      mpirun {{ command.template }}
```

For local execution, omit the `#SBATCH` directives. See [Writing Scripts](../writing-scripts) for practical guidance and more examples.

<details>
<summary><strong>inputs</strong> (optional)</summary>

Declarative input files generated before the script runs, for benchmarks that read parameters from a config file (or hostfile, manifest, etc.) instead of the command line.

Files are rendered with the same Jinja2 context as `script_template` and written at preparation time, alongside `run_*.sh`, so the exact input of every execution is on disk for inspection even when the script aborts before producing output.

```yaml
scripts:
  - name: "ior"
    inputs:
      - name: ior_config
        path: "{{ execution_dir }}/ior.conf"
        template: |
          IOR START
            api = POSIX
            blockSize = {{ block_size_mb }}m
            transferSize = {{ transfer_size_kb }}k
            numTasks = {{ nodes * processes_per_node }}
          IOR STOP
      - name: hostfile
        file: "./templates/hostfile.j2"
        mode: "0644"

    script_template: |
      #!/bin/bash
      ior -f {{ inputs.ior_config.path }} \
          --hostfile {{ inputs.hostfile.path }}
```

**Fields per entry:**

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Identifier used in `{{ inputs.<name>.path }}` references. Must be a valid Python identifier, unique within the script. |
| `path` | Yes | Destination path on disk, Jinja2-rendered (e.g. `"{{ execution_dir }}/ior.conf"`). |
| `template` | One of | Inline content, rendered with the full execution context. |
| `file` | One of | Path to an external template file (resolved relative to the YAML config, or as an absolute path). The file content replaces `template` at load time. |
| `mode` | No | Octal string (e.g., `"0644"`) applied with chmod after the file is written. |

**Context available in `template` and `path`:**
- All swept and derived variables (`{{ nodes }}`, `{{ block_size_mb }}`, ...)
- `{{ execution_dir }}`, `{{ workdir }}`, `{{ execution_id }}`, `{{ repetition }}`, `{{ repetitions }}`
- `{{ os_env.* }}` for environment variables
- `{{ inputs.<other>.path }}` to reference another input's resolved path (within the same script)

`{{ inputs.<name>.path }}` also works in `script_template`, `post.script`, and the top-level `command.template`.

**Rules:**
- Jinja2 syntax in `template` and `path` is validated at load time (alongside `script_template`).
- The file is rewritten on every repetition, so each repetition_NNN folder gets its own copy.

</details>

<details>
<summary><strong>post</strong> (optional)</summary>

Post-processing script executed after main script completes:

```yaml
scripts:
  - name: "ior"
    script_template: |
      ...

    post:
      script: |
        #!/bin/bash
        echo "Job completed at $(date)"
        echo "Summary: {{ summary_file }}"
        ls -lh {{ execution_dir }}
```

</details>

<details>
<summary><strong>parser</strong> (required)</summary>

Defines how to extract metrics from benchmark output:

```yaml
scripts:
  - name: "ior"
    script_template: |
      ...

    parser:
      file: "{{ summary_file }}"
      metrics:
        - name: bwMiB
        - name: iops
      parser_script: |
        import json

        def parse(file_path: str):
            with open(file_path, "r") as f:
                data = json.load(f)
            results = data["tests"][0]["Results"][0]
            return {
                "bwMiB": float(results["bwMiB"]),
                "iops": float(results["OPs"])
            }
```

**Requirements:**
- Function must be named `parse`
- Takes one argument: `file_path` (str)
- Returns dict with metric names matching `metrics` list

See [Writing Parsers](../writing-parsers) for context globals and more examples.

</details>

---

## `output`

Defines where and how to store execution results.

```yaml
output:
  sink:
    type: string              # Required: "csv" | "parquet" | "sqlite"
    path: string              # Optional: output file path (Jinja2), has sensible defaults
    exclude:                  # Optional: fields to exclude from output
      - "benchmark.description"
    table: string             # Optional: table name for SQLite (default: "results")
```

#### `type` (required)
Output format: `csv`, `parquet`, or `sqlite`.

#### `path` (optional)
Output file path. Can use Jinja2 templates.

**Defaults by type:**
- `csv` → `{{ workdir }}/results.csv`
- `parquet` → `{{ workdir }}/results.parquet`
- `sqlite` → `{{ workdir }}/results.db`

#### `exclude` (optional)
Exclude specific fields from output using dot notation. Wildcards are supported.

| Prefix | Fields |
|--------|--------|
| `benchmark.*` | `name`, `description` |
| `execution.*` | `repetitions`, `workdir`, `execution_dir` (note: `execution_id` and `repetition` are protected) |
| `vars.*` | All variable names |
| `labels.*` | All user-defined labels from `command.labels` |
| `metadata.*` | IOPS internal fields (executor_status, start, end, error, jobid) |
| `metrics.*` | All parser metric names |

**Protected fields:** `execution.execution_id` and `execution.repetition` cannot be excluded as they are required for identifying results.

#### `table` (optional, SQLite only)
Table name (default: "results").

---

## `reporting` (optional)

Enables HTML report generation with interactive plots. Disabled by default.

```yaml
reporting:
  enabled: boolean              # Optional: enable auto-generation (default: false)
  output_dir: path              # Optional: report output directory (default: workdir)
  output_filename: string       # Optional: report filename (default: "analysis_report.html")

  theme:                        # Optional: theme configuration
    style: string               #   Plotly theme: "plotly_white" (default), "plotly",
                                #   "plotly_dark", "ggplot2", "seaborn", "simple_white"
    colors: list                #   Custom color palette (hex codes)
    font_family: string         #   Font family (e.g., "Arial, sans-serif")

  sections:                     # Optional: section visibility
    test_summary: boolean       #   Execution statistics (default: true)
    best_results: boolean       #   Top N configurations (default: true)
    variable_impact: boolean    #   Variance-based importance (default: true)
    parallel_coordinates: boolean #   Multi-dimensional visualization (default: true)
    bayesian_evolution: boolean #   Optimization progress, Bayesian only (default: true)
    bayesian_parameter_evolution: boolean #   Parameter exploration (default: false)
    resource_sampling: boolean  #   Resource metrics summary table (default: true)
    custom_plots: boolean       #   User-defined plots (default: true)
    gallery: boolean            #   Per-execution image gallery (default: true; auto-enabled when images exist)
    versions: boolean           #   Software versions table (default: true; auto-enabled when probe data exists)

  gallery:                      # Optional: per-execution image gallery
    enabled: boolean            #   Enable the gallery section (default: false)
    folder: string              #   Convention folder per execution dir (default: "images")
    sources: list               #   OPTIONAL: Jinja2-templated paths resolved per execution
    pattern: string             #   Glob for convention folder (default: "*.png")
    max_width: integer          #   OPTIONAL: downscale cap in pixels (requires Pillow)
    caption_vars: list          #   OPTIONAL: variable names shown under each card
    title: string               #   Gallery section heading (default: "Image Gallery")

  best_results:                 # Optional: best results configuration
    top_n: integer              #   Number of top configs (default: 5)
    show_command: boolean       #   Include rendered command (default: true)
    min_samples: integer        #   Minimum repetitions required (default: 1)

  metrics:                      # Optional: per-metric plot definitions
    metric_name:                #   Benchmark metrics (from parsers) or resource
      plots:                    #   sampling metrics (cpu_avg_pct, gpu_energy_j, etc.)
        - type: string
          x_var: string
          ...

  default_plots:                # Optional: fallback plots
    - type: string
      per_variable: boolean
      ...

  plot_defaults:                # Optional: default sizing
    height: integer             #   (default: 500)
    width: integer              #   (default: null = auto)
    margin:                     #   (default: null = Plotly defaults)
      l: integer
      r: integer
      t: integer
      b: integer
```

Reports can also be generated manually with `iops report`, regardless of `enabled`.

<details>
<summary><strong>metrics</strong> (optional)</summary>

Define custom plots per metric. Both benchmark metrics (from parser scripts) and resource sampling metrics (from probes) can be used:

```yaml
reporting:
  metrics:
    # Benchmark metric (from parser)
    bwMiB:
      plots:
        - type: "line"
          x_var: "block_size_mb"
          group_by: "nodes"
          title: "Bandwidth vs Block Size"

        - type: "heatmap"
          x_var: "nodes"
          y_var: "processes_per_node"
          colorscale: "Viridis"

    # Resource sampling metric (from gpu_sampling probe)
    gpu_energy_j:
      plots:
        - type: "bar"
          x_var: "nodes"
          title: "GPU Energy Consumption"
```

Available resource metrics are listed in the generated `report_config.yaml`. See [Custom Reports](../reporting#resource-sampling-plots) for the full list.

**Plot types:** `bar`, `line`, `scatter`, `heatmap`, `box`, `violin`, `surface_3d`, `parallel_coordinates`, `execution_scatter`, `coverage_heatmap`

| Plot Type | Required | Key Options |
|-----------|----------|-------------|
| `bar` | `x_var` | `show_error_bars` |
| `line` | `x_var` | `group_by` |
| `scatter` | `x_var` | `y_var`, `color_by` |
| `heatmap` | `x_var`, `y_var` | `colorscale` |
| `box` | `x_var` | `show_outliers` |
| `coverage_heatmap` | `row_vars`, `col_var` | `aggregation`, `sort_rows_by` |

</details>

<details>
<summary><strong>default_plots</strong> (optional)</summary>

Fallback plots for metrics without custom configuration:

```yaml
reporting:
  default_plots:
    - type: "execution_scatter"
    - type: "bar"
      per_variable: true
      show_error_bars: true
```

</details>

---

## `machines` (optional)

Per-machine configuration overrides. Select at runtime with `--machine NAME` or `IOPS_MACHINE` env var.

```yaml
machines:
  machine_name:       # Arbitrary machine identifier
    benchmark: {}     # Optional: benchmark overrides
    vars: {}          # Optional: variable overrides
    command: {}       # Optional: command overrides
    scripts: []       # Optional: script overrides
    output: {}        # Optional: output overrides
    constraints: []   # Optional: constraint overrides
    reporting: {}     # Optional: reporting overrides
```

Each machine entry can override any combination of the standard top-level sections. Overrides are deep-merged into the base configuration: only what you specify is changed.

See the [Machine Overrides Guide](machines) for merge rules, examples, and best practices.
