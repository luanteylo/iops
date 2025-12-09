# IOPS Generic YAML Manual

*A practical guide to defining benchmark executions*

---

## 1. Introduction

The IOPS YAML format is designed to describe **benchmark experiments**, not scripts.

Instead of writing dozens or hundreds of job scripts by hand, you describe:

* **what parameters vary**
* **how commands are constructed**
* **how jobs are executed**
* **how outputs are parsed**

From this single YAML file, IOPS automatically generates a set of **execution instances**, each corresponding to one concrete experiment.

Each execution instance is self-contained and can be:

* scheduled (e.g. via Slurm)
* monitored
* parsed
* stored in CSV or a database

---

## 2. Mental model: executions and `execution_id`

### What is an execution?

An **execution** is one concrete run of a benchmark, with:

* specific values for variables (e.g. `nodes=1`, `block_size_mb=16`)
* a fully rendered command
* a fully rendered job script
* defined output locations and parsers

If your YAML defines *N* combinations of variables, IOPS creates *N* execution instances.

---

### The `execution_id` variable

`execution_id` is a **special variable automatically provided by IOPS**.

* It is **always available**
* It starts at **1**
* It is **unique per execution**
* It increases sequentially as executions are generated

You **do not define it** in the YAML — it always exists.

#### Why is `execution_id` important?

It solves a very practical problem: **file name collisions**.

When running many executions, writing outputs like:

```text
summary.json
output.txt
results.log
```

would cause files to overwrite each other.

Instead, you should include `execution_id` in file names:

```yaml
summary_file:
  type: str
  expr: "{{ workdir }}/summary_{{ execution_id }}.json"
```

This guarantees that **each execution writes to its own files**.

✅ Recommended usage:

* output files
* log files
* temporary directories
* result identifiers

---

## 3. General structure of the YAML file

A complete YAML file has the following sections:

```yaml
benchmark:
vars:
command:
scripts:
output:
```

You don’t have to think about execution loops or job arrays — IOPS takes care of that.

---

## 4. `benchmark`: global information

```yaml
benchmark:
  name: "IOR Benchmark"
  description: "A benchmark to measure I/O performance using the IOR tool."
  workdir: "/home/luan/workdir/"
```

### Purpose

This section defines **global context** shared by all executions.

### Fields

* `name`: Human-readable benchmark name
* `description`: Optional free text
* `workdir`: Base directory used for:

  * output files
  * CSV results
  * generated scripts

You can reference `workdir` anywhere using:

```yaml
{{ workdir }}
```

---

## 5. `vars`: defining what changes between executions

The `vars` section controls **how many executions are generated**.

There are two kinds of variables:

1. **Swept variables** → create multiple executions
2. **Derived variables** → computed per execution

---

### 5.1 Swept variables (Cartesian product)

Swept variables define the **parameter space**.

Each swept variable contributes to a **Cartesian product**.

Example:

```yaml
vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 2]

  block_size_mb:
    type: int
    sweep:
      mode: list
      values: [16, 32]
```

This creates **4 executions**:

| execution_id | nodes | block_size_mb |
| ------------ | ----- | ------------- |
| 1            | 1     | 16            |
| 2            | 1     | 32            |
| 3            | 2     | 16            |
| 4            | 2     | 32            |

---

### Sweep modes

#### `list` mode

Explicit list of values:

```yaml
mode: list
values: [1, 4, 8]
```

#### `range` mode

Numeric range (inclusive):

```yaml
mode: range
start: 1
end: 16
step: 1
```

---

### Variable types

Supported types:

* `int`
* `float`
* `str`
* `bool`

Types are enforced when values are generated and when expressions are evaluated.

---

### 5.2 Derived variables (`expr`)

Derived variables are **computed after swept variables**.

They do **not** create new executions.

Example:

```yaml
summary_file:
  type: str
  expr: "{{ workdir }}/summary_{{ execution_id }}.json"
```

```yaml
total_data_size:
  type: float
  expr: "nodes * processes_per_node * block_size_mb"
```

#### Expression rules

* If the expression contains `{{ ... }}`, it is treated as a **Jinja2 template**
* Otherwise, it is treated as a **Python arithmetic expression**
* Derived variables may depend on:

  * swept variables
  * other derived variables
  * `workdir`
  * `execution_id`

⚠️ Circular dependencies are not allowed.

---

## 6. `command`: how the benchmark is run

```yaml
command:
  template: >
    mpirun
    ior -w -b {{ block_size_mb }}mb
    -O summaryFile={{ summary_file }}
    -o {{ ost_path }}/output.ior
```

### Key idea

The command is a **template**, not a fixed string.

It is rendered **separately for each execution**.

You can use:

* swept variables
* derived variables
* `execution_id`

---

### Metadata

```yaml
metadata:
  total_data_size: "{{ total_data_size }}"
```

Metadata:

* does not affect execution
* is stored in CSV / databases
* is useful for analysis later

---

### Environment variables

```yaml
env:
  OMP_NUM_THREADS: "1"
```

These are exported when the command is run.

---

## 7. `scripts`: how commands are submitted/executed

Scripts define **execution backends**.

Most commonly: Slurm.

```yaml
scripts:
  - name: "slurm_mpi"
    mode: "slurm"
    submit: "sbatch"
    script_template: |
      #!/bin/bash
      #SBATCH --nodes={{ nodes }}
      #SBATCH --ntasks-per-node={{ processes_per_node }}

      {{ command.template }}
```

### Important concept: `command.template`

Inside a script, you should **not re-encode the command logic**.

Instead, use:

```yaml
{{ command.template }}
```

This injects the already-rendered command into the script.

---

### Post-processing (optional)

```yaml
post:
  script: |
    echo "Execution {{ execution_id }} finished"
```

Executed locally **after job completion**.

---

### Parsing results

```yaml
parser:
  type: json
  file: "{{ summary_file }}"
  metrics:
    - name: write_bandwidth
      path: results[0].bw_MiB
```

This tells IOPS:

* where to find output files
* how to extract metrics per execution

---

## 8. `output`: storing results

```yaml
output:
  csv:
    path: "{{ workdir }}/results.csv"
    include:
      - nodes
      - block_size_mb
      - total_data_size
      - write_bandwidth
```

Each execution appends one row to the CSV.

Fields can reference:

* variables
* derived variables
* parser metrics
* metadata

