---
title: "Templating and Context Reference"
---

IOPS uses Jinja2 templating throughout the configuration to enable dynamic values, conditional logic, and computed expressions. This guide covers both the Jinja2 syntax and the context variables available in each configuration section.

---

## Table of Contents

1. [Overview](#overview)
2. [Jinja2 Syntax Reference](#jinja2-syntax-reference)
   - [Variable Substitution](#variable-substitution)
   - [Conditionals](#conditionals)
   - [Loops](#loops)
   - [Filters](#filters)
   - [Expressions](#expressions)
3. [Context by Configuration Section](#context-by-configuration-section)
   - [command.template](#commandtemplate)
   - [command.env](#commandenv)
   - [scripts[].script_template](#scriptsscript_template)
   - [scripts[].post.script](#scriptspostscript)
   - [scripts[].parser.file](#scriptsparserfile)
   - [scripts[].parser.parser_script](#scriptsparserparsers_cript)
   - [vars[].expr](#varsexpr)
   - [output.sink.path](#outputsinkpath)
4. [Complete Example](#complete-example)

---

## Overview

### Template Support by Field

| Field | Jinja2 Support | File Path Support | Inline Support |
|-------|----------------|-------------------|----------------|
| `command.template` | Yes | No | Yes |
| `command.env` values | Yes | No | Yes |
| `scripts[].script_template` | Yes | Yes | Yes |
| `scripts[].post.script` | Yes | Yes | Yes |
| `scripts[].parser.file` | Yes | No | Yes |
| `scripts[].parser.parser_script` | **No** | Yes | Yes |
| `vars[].expr` | Yes | No | Yes |
| `output.sink.path` | Yes | No | Yes |

### Standard Context Variables

These variables are available in all Jinja2 templates:

| Variable | Type | Description |
|----------|------|-------------|
| `execution_id` | int | Unique execution ID (1, 2, 3, ...) |
| `repetition` | int | Current repetition number (1, 2, 3, ...) |
| `repetitions` | int | Total repetitions for this test |
| `workdir` | str | Base working directory |
| `log_dir` | str | Logs directory path (`workdir/logs`) |
| `execution_dir` | str | Per-execution directory path |
| `os_env` | dict | System environment variables (e.g., `{{ os_env.HOME }}`) |
| All user `vars` | varies | All swept and derived variables by name |

---

## Jinja2 Syntax Reference

### Variable Substitution

The most common use case is variable interpolation using `{{ variable_name }}`:

```yaml
command:
  template: "ior -w -b {{ block_size }}mb -t {{ transfer_size }}mb -o {{ output_file }}"

vars:
  summary_file:
    type: str
    expr: "{{ execution_dir }}/summary_{{ execution_id }}_r{{ repetition }}.json"
```

### System Environment Variables

Access system environment variables via `os_env`:

```yaml
# Use system paths in commands
command:
  template: "{{ os_env.HOME }}/bin/benchmark --scratch {{ os_env.SCRATCH | default('/tmp') }}"

# Reference environment in derived variables
vars:
  scratch_dir:
    type: str
    expr: "{{ os_env.SCRATCH | default('/tmp') }}/iops_{{ execution_id }}"

# Conditional based on cluster environment
scripts:
  - name: "benchmark"
    script_template: |
      #!/bin/bash
      {% if os_env.SLURM_JOB_ID is defined %}
      echo "Running in SLURM job {{ os_env.SLURM_JOB_ID }}"
      {% endif %}
      {{ command.template }}
```

### Conditionals

Use `{% if condition %}` for conditional logic:

```yaml
# Basic conditional
command:
  template: >
    my_benchmark --input data.bin
    {% if use_compression %} --compress {% endif %}
    --output {{ output_file }}

# With else clause
command:
  template: >
    ior {% if operation == "write" %} -w {% else %} -r {% endif %}
    -b {{ block_size }}mb
    -o {{ output_path }}

# Numeric comparison
command:
  template: >
    mpirun -np {{ ntasks }}
    ./benchmark {% if nodes > 8 %} --large-scale {% endif %}

# Complex conditions
command:
  template: >
    benchmark
    {% if nodes > 1 and processes_per_node >= 4 %} --parallel-mode {% endif %}
    --config {{ config_file }}

# Membership test
command:
  template: >
    benchmark
    {% if filesystem in ["lustre", "gpfs"] %} --parallel-fs {% endif %}
    {% if access_pattern not in ["sequential"] %} --random-io {% endif %}
    --output {{ output_file }}
```

**Available operators:**
- Comparison: `==`, `!=`, `<`, `>`, `<=`, `>=`
- Logical: `and`, `or`, `not`
- Membership: `in`, `not in`

**Critical syntax requirement:** Spaces are REQUIRED inside `{% %}` tags:
- Correct: `{% if condition %}`
- Wrong: `{%if condition%}` (causes TemplateSyntaxError)

### Loops

Use `{% for %}` to iterate over sequences:

```yaml
# Iterate over a list
vars:
  module_list:
    type: str
    expr: "{% for mod in ['mpi', 'ior', 'hdf5'] %}module load {{ mod }}; {% endfor %}"

# Iterate over a range
command:
  template: >
    benchmark
    {% for i in range(3) %} --file{{ i }} input{{ i }}.dat {% endfor %}

# Iterate with index
script_template: |
  #!/bin/bash
  {% for i in range(nodes) %}
  echo "Processing node {{ i }}"
  {% endfor %}
```

**Loop variables:**
- `loop.index`: Current iteration (1-indexed)
- `loop.index0`: Current iteration (0-indexed)
- `loop.first`: True on first iteration
- `loop.last`: True on last iteration

### Filters

Filters transform values using the `|` operator:

```yaml
# Default value for optional variables
command:
  template: "benchmark --config {{ config_path | default('./default.conf') }}"

# String manipulation
vars:
  uppercase_name:
    type: str
    expr: "{{ benchmark.name | upper }}"

  lowercase_name:
    type: str
    expr: "{{ benchmark.name | lower }}"

  filename:
    type: str
    expr: "{{ output_path | basename }}"

# Numeric filters
vars:
  rounded_value:
    type: float
    expr: "{{ block_size_mb | round(2) }}"

  absolute_value:
    type: int
    expr: "{{ difference | abs }}"
```

**Common filters:**

| Filter | Description |
|--------|-------------|
| `default(value)` | Provide fallback for empty/falsy values |
| `upper` | Convert to uppercase |
| `lower` | Convert to lowercase |
| `basename` | Extract filename from path |
| `dirname` | Extract directory from path |
| `round(precision)` | Round to N decimal places |
| `abs` | Absolute value |
| `int` | Convert to integer |
| `float` | Convert to float |
| `string` | Convert to string |
| `length` | Get length of sequence |

### Expressions

Combine variables with arithmetic and function calls:

```yaml
# Arithmetic in derived variables
vars:
  total_processes:
    type: int
    expr: "{{ nodes * processes_per_node }}"

  block_size_mb:
    type: int
    expr: "{{ (volume_size_gb * 1024) // (nodes * ppn) }}"

  percentage:
    type: float
    expr: "{{ (current_value / max_value) * 100.0 }}"

# Using functions
vars:
  max_cores:
    type: int
    expr: "{{ max(nodes * ppn, 16) }}"

  min_block_size:
    type: int
    expr: "{{ min(block_size_mb, 1024) }}"
```

**Available functions:**
- `min()`, `max()`: Minimum/maximum values
- `abs()`: Absolute value
- `round()`: Round to nearest integer
- `floor()`, `ceil()`: Floor/ceiling
- `int()`, `float()`: Type conversion

---

## Context by Configuration Section

### `command.template`

The main benchmark command template.

**Jinja2 Support:** Yes
**File Path Support:** No (inline only)

**Available Context:**
- All standard Jinja2 context variables
- All `command.labels` keys

```yaml
command:
  template: >
    mpirun -np {{ nodes * ppn }}
    {% if use_collective %} --collective {% endif %}
    ./benchmark --block-size {{ block_size }}mb
    --output {{ execution_dir }}/results.dat
  labels:
    operation: "write"
```

---

### `command.env`

Environment variables passed to the execution. Values support Jinja2 templating.

**Jinja2 Support:** Yes (for values)
**File Path Support:** No

**Available Context:**
- All standard Jinja2 context variables

```yaml
command:
  template: "./benchmark"
  env:
    OMP_NUM_THREADS: "{{ ppn }}"
    IOPS_NODES: "{{ nodes }}"
    IOPS_BLOCK_SIZE: "{{ block_size }}"
    IOPS_EXEC_DIR: "{{ execution_dir }}"
    MY_STATIC_VAR: "some_value"
```

**Using in script_template:**

Environment variables are available via `command_env` in your script template:

```yaml
scripts:
  - name: "benchmark"
    script_template: |
      #!/bin/bash

      # Export all environment variables from command.env
      {% for key, value in command_env.items() %}
      export {{ key }}="{{ value }}"
      {% endfor %}

      # Run the command
      {{ command.template }}
```

This renders to:

```bash
#!/bin/bash

export OMP_NUM_THREADS="8"
export IOPS_NODES="2"
export IOPS_BLOCK_SIZE="1024"
export IOPS_EXEC_DIR="/path/to/workdir/run_001/exec_0001"
export MY_STATIC_VAR="some_value"

./benchmark
```

---

### `scripts[].script_template`

The main execution script content.

**Jinja2 Support:** Yes
**File Path Support:** Yes

**Available Context:**
- All standard Jinja2 context variables
- `command.template` - The rendered command
- `command_env` - Environment variables dictionary
- `command_labels` - Labels dictionary
- `vars` - All variables as a dictionary

#### Inline Content

```yaml
scripts:
  - name: "ior"
    script_template: |
      #!/bin/bash
      #SBATCH --job-name=iops_{{ execution_id }}
      #SBATCH --nodes={{ nodes }}
      #SBATCH --ntasks-per-node={{ ppn }}

      module load mpi ior
      srun {{ command.template }}
```

#### External File

You can reference an external file instead of inline content:

```yaml
scripts:
  - name: "ior"
    script_template: /path/to/my_script_template.sh
```

Or relative to the YAML config file:

```yaml
scripts:
  - name: "ior"
    script_template: ./templates/slurm_template.sh
```

The external file can contain Jinja2 templates:

```bash
#!/bin/bash
#SBATCH --job-name=iops_{{ execution_id }}
#SBATCH --nodes={{ nodes }}
#SBATCH --ntasks-per-node={{ ppn }}
#SBATCH --output={{ execution_dir }}/stdout
#SBATCH --error={{ execution_dir }}/stderr

module load mpi ior

echo "Running execution {{ execution_id }}, repetition {{ repetition }}"
echo "Variables: nodes={{ nodes }}, ppn={{ ppn }}, block_size={{ block_size }}"

{% for key, value in command_env.items() %}
export {{ key }}="{{ value }}"
{% endfor %}

srun {{ command.template }}
```

#### File Detection Logic

IOPS determines if the value is a file path using these rules:
1. Single line (no newlines)
2. Not too many `{` characters (to distinguish from inline Jinja2)
3. File exists (checked relative to config directory first, then as absolute path)

If the file doesn't exist, the value is treated as inline content.

---

### `scripts[].post.script`

Optional post-processing script executed after the main script completes.

**Jinja2 Support:** Yes
**File Path Support:** Yes

**Available Context:**
Same as `script_template`:
- All standard Jinja2 context variables
- `command.template`, `command_env`, `command_labels`, `vars`

```yaml
scripts:
  - name: "benchmark"
    script_template: |
      #!/bin/bash
      {{ command.template }}

    post:
      script: |
        #!/bin/bash
        echo "Execution {{ execution_id }} completed at $(date)"
        echo "Output directory: {{ execution_dir }}"
        ls -lh {{ execution_dir }}
```

#### External File

```yaml
scripts:
  - name: "benchmark"
    script_template: ./templates/main.sh

    post:
      script: ./templates/post_process.sh
```

---

### `scripts[].parser.file`

Path to the output file that the parser should read.

**Jinja2 Support:** Yes
**File Path Support:** N/A (this IS a file path)

**Available Context:**
- All standard Jinja2 context variables

```yaml
parser:
  file: "{{ execution_dir }}/output.json"
  # or
  file: "{{ workdir }}/run_{{ execution_id }}/results_{{ repetition }}.txt"
```

---

### `scripts[].parser.parser_script`

Python script that extracts metrics from the output file.

**Jinja2 Support:** No
**File Path Support:** Yes

The parser script does NOT support Jinja2 templating, but has access to execution context via **Python global variables**:

| Variable | Type | Description |
|----------|------|-------------|
| `vars` | dict | All execution variables (e.g., `vars["nodes"]`) |
| `env` | dict | Rendered `command.env` variables |
| `os_env` | dict | System environment variables (e.g., `os_env["PATH"]`) |
| `execution_id` | str | The execution ID |
| `execution_dir` | str | The execution directory path |
| `workdir` | str | The root working directory path |
| `log_dir` | str | The logs directory path |
| `repetition` | int | Current repetition number |
| `repetitions` | int | Total number of repetitions |

#### Inline Content

```yaml
parser:
  file: "{{ execution_dir }}/output.json"
  metrics:
    - name: throughput
    - name: latency
  parser_script: |
    import json

    def parse(file_path):
        with open(file_path) as f:
            data = json.load(f)

        return {
            "throughput": data["bandwidth_mb"],
            "latency": data["latency_ms"]
        }
```

#### Using Context Variables

Access execution context via global variables:

**Example 1: Per-node throughput**
```yaml
parser:
  file: "{{ execution_dir }}/output.json"
  metrics:
    - name: throughput_per_node
  parser_script: |
    import json

    def parse(file_path):
        with open(file_path) as f:
            data = json.load(f)
        # Normalize by number of nodes
        return {"throughput_per_node": data["total_bw"] / vars["nodes"]}
```

**Example 2: Efficiency metric**
```yaml
parser:
  file: "{{ execution_dir }}/results.txt"
  metrics:
    - name: bandwidth
    - name: efficiency
  parser_script: |
    import re

    def parse(file_path):
        with open(file_path) as f:
            content = f.read()
        bw = float(re.search(r"Bandwidth: ([\d.]+)", content).group(1))
        # Efficiency = bandwidth per core
        eff = bw / (vars["nodes"] * vars["ppn"])
        return {"bandwidth": bw, "efficiency": eff}
```

**Example 3: Conditional parsing based on operation type**
```yaml
parser:
  file: "{{ execution_dir }}/output.json"
  metrics:
    - name: performance
  parser_script: |
    import json

    def parse(file_path):
        with open(file_path) as f:
            data = json.load(f)
        # Use different field based on operation variable
        if vars["operation"] == "write":
            return {"performance": data["write_bw"]}
        else:
            return {"performance": data["read_bw"]}
```

**Example 4: Using system environment variables**
```yaml
parser:
  file: "{{ execution_dir }}/output.json"
  metrics:
    - name: throughput
    - name: cluster
  parser_script: |
    import json

    def parse(file_path):
        with open(file_path) as f:
            data = json.load(f)
        # Include cluster name from environment for multi-cluster studies
        cluster = os_env.get("CLUSTER_NAME", "unknown")
        return {
            "throughput": data["bandwidth"],
            "cluster": cluster
        }
```

#### External File

```yaml
parser:
  file: "{{ execution_dir }}/output.json"
  metrics:
    - name: throughput
  parser_script: ./parsers/my_parser.py
```

The external file (`./parsers/my_parser.py`):

```python
import json

def parse(file_path):
    # Context globals available: vars, env, os_env, execution_id, execution_dir, workdir, log_dir, repetition, repetitions
    with open(file_path) as f:
        data = json.load(f)
    return {"throughput": data["bandwidth"] / vars["nodes"]}
```

#### Requirements

- Must define a function named `parse`
- Function takes one argument: `file_path` (str)
- Returns a dict with keys matching the `metrics` names

---

### `vars[].expr`

Expression for derived (computed) variables.

**Jinja2 Support:** Yes
**File Path Support:** No

**Available Context:**
- All standard Jinja2 context variables
- All previously defined variables (order matters!)
- Built-in functions: `min()`, `max()`, `abs()`, `round()`, `floor()`, `ceil()`

#### Arithmetic expressions

```yaml
vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4]

  ppn:
    type: int
    sweep:
      mode: list
      values: [4, 8]

  total_processes:
    type: int
    expr: "{{ nodes * ppn }}"

  block_size_per_process:
    type: int
    expr: "{{ (total_volume_gb * 1024) // total_processes }}"
```

#### String templates

```yaml
vars:
  output_file:
    type: str
    expr: "{{ execution_dir }}/output_{{ execution_id }}_r{{ repetition }}.json"

  job_name:
    type: str
    expr: "benchmark_n{{ nodes }}_p{{ ppn }}"
```

#### Conditional expressions

```yaml
vars:
  partition:
    type: str
    expr: "{% if nodes > 4 %}large{% else %}small{% endif %}"
```

#### Using environment variables

Access system environment variables via `os_env`:

```yaml
vars:
  scratch_path:
    type: str
    expr: "{{ os_env.SCRATCH | default('/tmp') }}/iops_{{ execution_id }}"

  home_bin:
    type: str
    expr: "{{ os_env.HOME }}/bin"

  # Conditional based on cluster environment
  queue:
    type: str
    expr: "{% if os_env.CLUSTER_NAME == 'hpc1' %}batch{% else %}default{% endif %}"
```

#### List variables for correlated parameters

The `list` type allows defining arrays that can be indexed in templates. This is useful when you have multiple parameters that must change together (correlated parameters).

**Use case**: You want to sweep over simulation configurations where grid size and time steps are paired, not all combinations.

```yaml
vars:
  # Sweep over an index
  config_index:
    type: int
    sweep:
      mode: list
      values: [0, 1, 2, 3, 4]

  # Define correlated parameter lists
  grid_sizes:
    type: list
    expr: "[100, 200, 400, 800, 1600]"

  time_steps:
    type: list
    expr: "[1000, 2000, 4000, 8000, 16000]"

command:
  template: >
    simulation --grid {{ grid_sizes[config_index] }}
               --steps {{ time_steps[config_index] }}
```

This creates **5 executions** with correlated parameters:
| `config_index` | `grid_sizes[...]` | `time_steps[...]` |
|----------------|-------------------|-------------------|
| 0 | 100 | 1000 |
| 1 | 200 | 2000 |
| 2 | 400 | 4000 |
| 3 | 800 | 8000 |
| 4 | 1600 | 16000 |

Without list variables, sweeping `grid_size: [100, 200, 400, 800, 1600]` and `time_steps: [1000, 2000, 4000, 8000, 16000]` would create **25 executions** (all combinations).

---

### `output.sink.path`

Path to the output results file.

**Jinja2 Support:** Yes
**File Path Support:** N/A (this IS a file path)

**Available Context:**
- `workdir` - Base working directory
- Other standard context variables

```yaml
output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"

# Or with more complex path
output:
  sink:
    type: parquet
    path: "{{ workdir }}/results/{{ benchmark.name }}_results.parquet"
```

#### Default Paths

If `path` is not specified, IOPS uses sensible defaults:

| Type | Default Path |
|------|--------------|
| `csv` | `{{ workdir }}/results.csv` |
| `parquet` | `{{ workdir }}/results.parquet` |
| `sqlite` | `{{ workdir }}/results.db` |

---

## Complete Example

Here's a complete configuration demonstrating all script types and their context:

```yaml
benchmark:
  name: "IO Benchmark"
  workdir: "/scratch/benchmarks"
  executor: "slurm"
  repetitions: 3

vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4]

  ppn:
    type: int
    sweep:
      mode: list
      values: [4, 8]

  # Derived variable using Jinja2
  total_procs:
    type: int
    expr: "{{ nodes * ppn }}"

  # Path variable using Jinja2
  summary_file:
    type: str
    expr: "{{ execution_dir }}/summary.json"

command:
  template: >
    ior -w -r -b 1g -t 1m
    -O summaryFile={{ summary_file }}

  # Environment variables with Jinja2
  env:
    IOPS_NODES: "{{ nodes }}"
    IOPS_PPN: "{{ ppn }}"
    IOPS_TOTAL: "{{ total_procs }}"

  labels:
    operation: "write-read"

scripts:
  - name: "ior"

    # Can be inline or file path - Jinja2 supported
    script_template: |
      #!/bin/bash
      #SBATCH --job-name=iops_{{ execution_id }}
      #SBATCH --nodes={{ nodes }}
      #SBATCH --ntasks-per-node={{ ppn }}
      #SBATCH --output={{ execution_dir }}/stdout

      # Export command.env variables
      {% for key, value in command_env.items() %}
      export {{ key }}="{{ value }}"
      {% endfor %}

      module load mpi ior
      srun {{ command.template }}

    # Optional post script - Jinja2 supported
    post:
      script: |
        #!/bin/bash
        echo "Completed: {{ execution_id }}"

    parser:
      # File path with Jinja2
      file: "{{ summary_file }}"

      metrics:
        - name: write_bw
        - name: read_bw
        - name: efficiency

      # No Jinja2, but has access to vars, env, os_env, execution_id, execution_dir, workdir, log_dir, repetition, repetitions
      parser_script: |
        import json

        def parse(file_path):
            # Access context variables
            nodes = vars["nodes"]
            ppn = vars["ppn"]

            with open(file_path) as f:
                data = json.load(f)

            write_bw = data["tests"][0]["Results"][0]["bwMiB"]
            read_bw = data["tests"][1]["Results"][0]["bwMiB"]

            return {
                "write_bw": write_bw,
                "read_bw": read_bw,
                "efficiency": write_bw / (nodes * ppn)
            }

output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
```
