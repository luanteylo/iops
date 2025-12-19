# IOPS YAML Format Reference

*Complete guide to the IOPS benchmark configuration format*

---

## Table of Contents

1. [Introduction](#introduction)
2. [File Structure Overview](#file-structure-overview)
3. [Section: `benchmark`](#section-benchmark)
4. [Section: `vars`](#section-vars)
5. [Section: `command`](#section-command)
6. [Section: `scripts`](#section-scripts)
7. [Section: `output`](#section-output)
8. [Section: `rounds` (Optional)](#section-rounds-optional)
9. [Jinja2 Templating](#jinja2-templating)
10. [Complete Examples](#complete-examples)

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

command:         # Command template and metadata
  ...

scripts:         # Execution scripts and parsers
  ...

output:          # Output configuration (CSV, Parquet, SQLite)
  ...

rounds:          # (Optional) Multi-round optimization workflow
  ...
```

**All sections are required except `rounds`.**

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
  random_seed: integer            # Optional: seed for randomization (default: 42)
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
Path to SQLite database for caching execution results. **Required for `--use_cache` flag.**

```yaml
sqlite_db: "/scratch/benchmarks/ior_cache.db"
```

#### `repetitions` (optional, default: 1)
Number of times each test should be repeated. Each repetition gets a unique ID.

```yaml
repetitions: 3  # Each test runs 3 times
```

**Note**: Round-level `repetitions` override this global value.

#### `search_method` (optional, default: "exhaustive")
Test selection strategy:
- `exhaustive`: Run all parameter combinations
- `greedy`: (future) Greedy search optimization
- `bayesian`: (future) Bayesian optimization

```yaml
search_method: "exhaustive"
```

#### `executor` (optional, default: "slurm")
Execution backend:
- `local`: Run on local machine using subprocess
- `slurm`: Submit via SLURM scheduler

```yaml
executor: "local"
```

#### `random_seed` (optional, default: 42)
Seed for random operations (e.g., repetition interleaving).

```yaml
random_seed: 12345
```

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
| `round_name` | str | Current round name (if using rounds) |
| `round_index` | int | Current round index (if using rounds) |

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
path: "{{ workdir }}/results_{{ round_name }}.parquet"
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
| `round.*` | `name`, `index`, `repetitions` |
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
    path: "{{ workdir }}/results_{{ round_name }}.parquet"
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

## Section: `rounds` (Optional)

Enables multi-round optimization workflows where results from one round inform the next.

### Use Cases

- **Progressive parameter refinement**: Find best nodes first, then optimize block size
- **Multi-stage optimization**: Coarse search → fine search
- **Adaptive workflows**: Adjust parameters based on previous results

### Schema

```yaml
rounds:
  - name: string                  # Required: round identifier
    description: string           # Optional: human-readable description
    sweep_vars: list              # Required: which vars to sweep in this round
    fixed_overrides: dict         # Optional: override var values for this round
    repetitions: integer          # Optional: round-specific repetitions
    search:                       # Required: optimization criteria
      metric: string              # Required: metric name to optimize
      objective: string           # Required: "max" | "min"
      select: string              # Optional: future use
```

### Workflow

1. **Round 1**: Sweep specified variables, others use defaults
2. **Select best**: Choose best execution based on search metric
3. **Propagate**: Best parameters become defaults for next round
4. **Round 2**: Sweep new variables with propagated defaults
5. Repeat...

### `name` (required)

Round identifier. Used in logs and output.

```yaml
name: "optimize_nodes"
```

### `sweep_vars` (required)

List of variables to sweep in this round. Other swept variables use their default (first) value.

```yaml
sweep_vars: ["nodes"]          # Only sweep nodes
sweep_vars: ["nodes", "processes_per_node"]  # Sweep both
```

### `fixed_overrides` (optional)

Override specific variable values for this round:

```yaml
fixed_overrides:
  block_size_mb: 16           # Force this value
  processes_per_node: 32      # Force this value
```

### `repetitions` (optional)

Override global repetitions for this round:

```yaml
repetitions: 5                # Run 5 times per test in this round
```

### `search` (required)

Optimization criteria for selecting best result.

#### `metric` (required)

Metric name from parser output:

```yaml
search:
  metric: "bwMiB"
```

#### `objective` (required)

Optimization goal:
- `max`: Maximize metric
- `min`: Minimize metric

```yaml
search:
  objective: "max"
```

### Complete Example

```yaml
rounds:
  # Round 1: Find optimal number of nodes
  - name: "optimize_nodes"
    description: "Find best node count for maximum bandwidth"
    sweep_vars: ["nodes"]
    fixed_overrides:
      processes_per_node: 16
      volume_size_gb: 4
    repetitions: 3
    search:
      metric: "bwMiB"
      objective: "max"

  # Round 2: With best nodes, optimize processes per node
  - name: "optimize_processes"
    description: "Find best process count using optimal nodes from round 1"
    sweep_vars: ["processes_per_node"]
    repetitions: 3
    search:
      metric: "bwMiB"
      objective: "max"

  # Round 3: Fine-tune block size
  - name: "optimize_block_size"
    description: "Fine-tune block size with optimal nodes and processes"
    sweep_vars: ["block_size_mb"]
    repetitions: 5
    search:
      metric: "bwMiB"
      objective: "max"
```

### Behavior

- Results are saved per round: `runs/round_01_optimize_nodes/`
- Best execution from each round propagates to next
- Cache is round-aware when using `--use_cache`

---

## Jinja2 Templating

All string fields support Jinja2 templating with `{{ variable }}` syntax.

### Available Context

| Category | Variables |
|----------|-----------|
| **Execution** | `execution_id`, `repetition`, `repetitions` |
| **Benchmark** | `workdir`, `execution_dir` |
| **Rounds** | `round_name`, `round_index` |
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

### Example 2: SLURM with Rounds

```yaml
benchmark:
  name: "IOR Optimization"
  workdir: "/scratch/$USER/ior_benchmark"
  sqlite_db: "/scratch/$USER/ior_cache.db"
  executor: "slurm"

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

rounds:
  - name: "optimize_nodes"
    sweep_vars: ["nodes"]
    fixed_overrides:
      processes_per_node: 16
      volume_size_gb: 8
    repetitions: 3
    search:
      metric: "bwMiB"
      objective: "max"

  - name: "optimize_processes"
    sweep_vars: ["processes_per_node"]
    repetitions: 3
    search:
      metric: "bwMiB"
      objective: "max"
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

---

## Summary

The IOPS YAML format provides a powerful, declarative way to define parametric benchmarks:

- ✅ **Parametric**: Define parameter spaces with swept variables
- ✅ **Flexible**: Derived variables and Jinja2 templating
- ✅ **Scalable**: Cartesian product generates all combinations
- ✅ **Reproducible**: Cache and random seed for consistency
- ✅ **Optimizable**: Multi-round workflows with adaptive search
- ✅ **Portable**: Local or SLURM execution
- ✅ **Analyzable**: Structured output (CSV, Parquet, SQLite)

For more examples, see `docs/yaml_examples/`.
