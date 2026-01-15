---
title: "Jinja2 Templating"
---

IOPS uses Jinja2 templating throughout the configuration to enable dynamic values, conditional logic, and computed expressions. All string fields in the configuration support Jinja2 syntax.

---

## Table of Contents

1. [Available Context](#available-context)
2. [Variable Substitution](#1-variable-substitution)
3. [Conditionals](#2-conditionals)
4. [Loops](#3-loops)
5. [Filters](#4-filters)
6. [Expressions](#5-expressions)
7. [Where Jinja2 Templates Are Used](#6-where-jinja2-templates-are-used)

---

## Available Context

Templates have access to:

| Category | Variables |
|----------|-----------|
| **Execution** | `execution_id`, `repetition`, `repetitions` |
| **Benchmark** | `workdir`, `execution_dir` |
| **Variables** | All vars (swept and derived) |
| **Labels** | All command.labels keys |
| **Command** | `command.template` |

## 1. Variable Substitution

The most common use case is variable interpolation using `{{ variable_name }}`:

```yaml
command:
  template: "ior -w -b {{ block_size }}mb -t {{ transfer_size }}mb -o {{ output_file }}"

vars:
  summary_file:
    type: str
    expr: "{{ execution_dir }}/summary_{{ execution_id }}_r{{ repetition }}.json"
```


## 2. Conditionals

Use `{% if condition %}` for conditional logic in templates:

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


## 3. Loops

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



## 4. Filters

Filters transform values using the `|` operator:

```yaml
# Default value for optional label
command:
  template: "benchmark --config {{ config_path | default('./default.conf') }}"
  labels:
    config_path: ""  # Empty string uses default

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
- `default(value)`: Provide fallback for empty/falsy values
- `upper`: Convert to uppercase
- `lower`: Convert to lowercase
- `basename`: Extract filename from path
- `dirname`: Extract directory from path
- `round(precision)`: Round to N decimal places
- `abs`: Absolute value
- `int`: Convert to integer
- `float`: Convert to float
- `string`: Convert to string
- `length`: Get length of sequence

## 5. Expressions

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
- `int()`, `float()`: Type conversion

## 6. Where Jinja2 Templates Are Used

Jinja2 templating is available in these configuration sections:

1. **`command.template`**: The benchmark command
   ```yaml
   command:
     template: "mpirun -np {{ ntasks }} {% if debug %} --verbose {% endif %} ./benchmark"
   ```

2. **`scripts[].script_template`**: Script content (inline or file reference)
   ```yaml
   script_template: |
     #!/bin/bash
     {% if nodes > 1 %}
     #SBATCH --nodes={{ nodes }}
     {% endif %}
     {{ command.template }}
   ```

3. **`vars[].expr`**: Derived variable expressions
   ```yaml
   vars:
     output_dir:
       type: str
       expr: "{{ workdir }}/{% if use_cache %}cached{% else %}fresh{% endif %}/results"
   ```

4. **`output.sink.path`**: Output file paths
   ```yaml
   output:
     sink:
       path: "{{ workdir }}/results_{% if production %}prod{% else %}dev{% endif %}.csv"
   ```

5. **`scripts[].parser.file`**: Parser file paths
   ```yaml
   parser:
     file: "{{ execution_dir }}/output_{{ repetition }}.json"
   ```

6. **`benchmark.workdir`**: Working directory
   ```yaml
   benchmark:
     workdir: "/scratch/{{ username }}/benchmarks"
   ```
