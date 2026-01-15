---
title: "Scripts and Context Variables"
---

IOPS uses several types of scripts and templates throughout the configuration. Each has access to different context variables and supports different input methods (inline content or external files).

---

## Table of Contents

1. [Overview](#overview)
2. [Context Variables Reference](#context-variables-reference)
3. [command.template](#commandtemplate)
4. [command.env](#commandenv)
5. [scripts[].script_template](#scriptsscript_template)
6. [scripts[].post.script](#scriptspostscript)
7. [scripts[].parser.file](#scriptsparserfile)
8. [scripts[].parser.parser_script](#scriptsparserparsers_cript)
9. [vars[].expr](#varsexpr)
10. [output.sink.path](#outputsinkpath)

---

## Overview

| Field | Jinja2 Support | File Path Support | Inline Support |
|-------|----------------|-------------------|----------------|
| `command.template` | Yes | No | Yes |
| `command.env` values | Yes | No | Yes |
| `scripts[].script_template` | Yes | Yes | Yes |
| `scripts[].post.script` | Yes | Yes | Yes |
| `scripts[].parser.file` | Yes | No | Yes |
| `scripts[].parser.parser_script` | No | Yes | Yes |
| `vars[].expr` | Yes | No | Yes |
| `output.sink.path` | Yes | No | Yes |

---

## Context Variables Reference

Different templates have access to different context variables. Here's a comprehensive reference:

### Standard Jinja2 Context

Available in `command.template`, `script_template`, `post.script`, `vars[].expr`, and `output.sink.path`:

| Variable | Type | Description |
|----------|------|-------------|
| `execution_id` | int | Unique execution ID (1, 2, 3, ...) |
| `repetition` | int | Current repetition number (1, 2, 3, ...) |
| `repetitions` | int | Total repetitions for this test |
| `workdir` | str | Base working directory |
| `execution_dir` | str | Per-execution directory path |
| All user `vars` | varies | All swept and derived variables by name |

### Script Template Additional Context

Available in `scripts[].script_template` and `scripts[].post.script`:

| Variable | Type | Description |
|----------|------|-------------|
| `command.template` | str | The rendered command string |
| `command_env` | dict | Rendered environment variables from `command.env` |
| `command_labels` | dict | Labels from `command.labels` |
| `vars` | dict | All variables as a dictionary |

### Parser Script Context

Available as **global variables** in `parser_script` (not Jinja2, but Python globals):

| Variable | Type | Description |
|----------|------|-------------|
| `vars` | dict | All execution variables (e.g., `vars["nodes"]`) |
| `env` | dict | Rendered `command.env` variables |
| `execution_id` | str | The execution ID |
| `repetition` | int | Current repetition number |

---

## `command.template`

The main benchmark command template.

**Jinja2 Support:** Yes
**File Path Support:** No (inline only)

### Available Context

All standard Jinja2 context variables plus `command.labels` keys.

### Example

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

## `command.env`

Environment variables passed to the execution. Values support Jinja2 templating.

**Jinja2 Support:** Yes (for values)
**File Path Support:** No

### Available Context

All standard Jinja2 context variables.

### Example

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

### Using in script_template

Environment variables are available via `command_env` in your script template:

```yaml
scripts:
  - name: "benchmark"
    submit: "bash"
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

## `scripts[].script_template`

The main execution script content.

**Jinja2 Support:** Yes
**File Path Support:** Yes

### Available Context

- All standard Jinja2 context variables
- `command.template` - The rendered command
- `command_env` - Environment variables dictionary
- `command_labels` - Labels dictionary
- `vars` - All variables as a dictionary

### Inline Content

```yaml
scripts:
  - name: "ior"
    submit: "sbatch"
    script_template: |
      #!/bin/bash
      #SBATCH --job-name=iops_{{ execution_id }}
      #SBATCH --nodes={{ nodes }}
      #SBATCH --ntasks-per-node={{ ppn }}

      module load mpi ior
      srun {{ command.template }}
```

### External File

You can reference an external file instead of inline content:

```yaml
scripts:
  - name: "ior"
    submit: "sbatch"
    script_template: /path/to/my_script_template.sh
```

Or relative to the YAML config file:

```yaml
scripts:
  - name: "ior"
    submit: "sbatch"
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

### File Detection Logic

IOPS determines if the value is a file path using these rules:
1. Single line (no newlines)
2. Not too many `{` characters (to distinguish from inline Jinja2)
3. File exists (checked relative to config directory first, then as absolute path)

If the file doesn't exist, the value is treated as inline content.

---

## `scripts[].post.script`

Optional post-processing script executed after the main script completes.

**Jinja2 Support:** Yes
**File Path Support:** Yes

### Available Context

Same as `script_template`:
- All standard Jinja2 context variables
- `command.template`, `command_env`, `command_labels`, `vars`

### Example

```yaml
scripts:
  - name: "benchmark"
    submit: "bash"
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

### External File

```yaml
scripts:
  - name: "benchmark"
    submit: "bash"
    script_template: ./templates/main.sh

    post:
      script: ./templates/post_process.sh
```

---

## `scripts[].parser.file`

Path to the output file that the parser should read.

**Jinja2 Support:** Yes
**File Path Support:** N/A (this IS a file path)

### Available Context

All standard Jinja2 context variables.

### Example

```yaml
parser:
  file: "{{ execution_dir }}/output.json"
  # or
  file: "{{ workdir }}/run_{{ execution_id }}/results_{{ repetition }}.txt"
```

---

## `scripts[].parser.parser_script`

Python script that extracts metrics from the output file.

**Jinja2 Support:** No
**File Path Support:** Yes

### Available Context (Python Globals)

The parser script has access to these **global variables** (not Jinja2, but Python globals injected at runtime):

| Variable | Type | Description |
|----------|------|-------------|
| `vars` | dict | All execution variables |
| `env` | dict | Rendered `command.env` variables |
| `execution_id` | str | The execution ID |
| `repetition` | int | Current repetition number |

### Inline Content

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

### Using Context Variables

Access execution context via global variables. Here are simple, practical examples:

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

### External File

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
    # Context globals available: vars, env, execution_id, repetition
    with open(file_path) as f:
        data = json.load(f)
    return {"throughput": data["bandwidth"] / vars["nodes"]}
```

### Requirements

- Must define a function named `parse`
- Function takes one argument: `file_path` (str)
- Returns a dict with keys matching the `metrics` names

---

## `vars[].expr`

Expression for derived (computed) variables.

**Jinja2 Support:** Yes
**File Path Support:** No

### Available Context

- All standard Jinja2 context variables
- All previously defined variables (order matters!)
- Built-in functions: `min()`, `max()`, `abs()`, `round()`, `floor()`, `ceil()`

### Examples

**Arithmetic expressions:**
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

**String templates:**
```yaml
vars:
  output_file:
    type: str
    expr: "{{ execution_dir }}/output_{{ execution_id }}_r{{ repetition }}.json"

  job_name:
    type: str
    expr: "benchmark_n{{ nodes }}_p{{ ppn }}"
```

**Conditional expressions:**
```yaml
vars:
  partition:
    type: str
    expr: "{% if nodes > 4 %}large{% else %}small{% endif %}"
```

---

## `output.sink.path`

Path to the output results file.

**Jinja2 Support:** Yes
**File Path Support:** N/A (this IS a file path)

### Available Context

- `workdir` - Base working directory
- Other standard context variables

### Examples

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

### Default Paths

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
    submit: "sbatch"

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

      # No Jinja2, but has access to vars, env, execution_id, repetition
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
