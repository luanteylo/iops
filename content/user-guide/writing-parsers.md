---
title: "Writing Parsers"
---

IOPS does not know the output format of your benchmark. Instead, you provide a small Python script (the **parser**) that reads whatever your benchmark produces and returns the metrics you care about. This page explains how parsers work, how to write one, and where the extracted data ends up.

---

## Why You Need a Parser

Every benchmark writes its results differently: JSON files, plain text logs, CSV tables, binary formats. IOPS handles orchestration (running tests, sweeping parameters, managing repetitions) but delegates result extraction to you, because only you know your benchmark's output format.

The parser is the bridge between raw benchmark output and structured data that IOPS can store, plot, and analyze.

---

## How It Works

After each execution completes, IOPS runs your parser through this sequence:

1. **Locate the output file** using the `parser.file` path (resolved with Jinja2)
2. **Load your parser script** and inject execution context as Python globals
3. **Call your `parse(file_path)` function** with the resolved file path
4. **Validate the result**, checking that all declared metrics are present
5. **Store the metrics** alongside the execution parameters in the configured output sink

```
Benchmark runs  ──>  Output file  ──>  Your parser  ──>  Metrics dict  ──>  Results file
                     (any format)      parse(path)       {"metric": val}    (CSV/Parquet/SQLite)
```

---

## Configuration

The parser is defined inside the `scripts[]` section of your YAML configuration:

```yaml
scripts:
  - name: "my_benchmark"
    submit: "bash"
    script_template: |
      #!/bin/bash
      ./my_benchmark --output {{ execution_dir }}/results.json
    parser:
      file: "{{ execution_dir }}/results.json"
      metrics:
        - name: throughput
        - name: latency
      parser_script: |
        import json

        def parse(file_path):
            with open(file_path) as f:
                data = json.load(f)
            return {
                "throughput": data["bw_mb"],
                "latency": data["avg_latency_ms"]
            }
```

### Fields

| Field | Required | Description |
|-------|----------|-------------|
| `file` | Yes | Path to the output file. Supports Jinja2 (e.g., `{{ execution_dir }}/output.txt`). |
| `metrics` | Yes | List of metric names to extract. Each entry has a `name` field. |
| `parser_script` | Yes | Inline Python code or path to an external `.py` file. |

---

## Writing the `parse()` Function

Your script must define a function named `parse` that takes one argument (the file path) and returns a dictionary mapping metric names to their values.

### Rules

- The function **must be named `parse`** and accept exactly one positional argument
- It **must return a dict** with keys matching every metric declared in `metrics`
- Values can be numeric (`int`, `float`) or `None` if the metric could not be extracted
- You can return extra keys beyond the declared metrics (they will be ignored)
- You can `import` any module available in your Python environment
- The script itself is **not** Jinja2-templated; use context globals instead (see below)

### Minimal Example

```python
def parse(file_path):
    with open(file_path) as f:
        value = float(f.read().strip())
    return {"throughput": value}
```

---

## Context Variables

Your parser script has access to execution context through Python global variables. These are injected before your script runs, so you can use them directly, without imports or arguments.

| Variable | Type | Description |
|----------|------|-------------|
| `vars` | dict | All execution variables (e.g., `vars["nodes"]`, `vars["block_size"]`) |
| `env` | dict | Rendered `command.env` variables |
| `os_env` | dict | System environment variables (e.g., `os_env["HOME"]`) |
| `execution_id` | str | Execution identifier (e.g., `"exec_0001"`) |
| `execution_dir` | str | Path to the execution directory |
| `workdir` | str | Root working directory path |
| `log_dir` | str | Logs directory path |
| `repetition` | int | Current repetition number |
| `repetitions` | int | Total number of repetitions |
| `metrics` | list | List of declared metric names |

These globals let you write parsers that adapt to the execution context without hardcoding values.

---

## Examples

### JSON Output (I/O Benchmark)

A benchmark writes performance results as JSON:

```yaml
parser:
  file: "{{ execution_dir }}/results.json"
  metrics:
    - name: bandwidth
    - name: iops
  parser_script: |
    import json

    def parse(file_path):
        with open(file_path) as f:
            data = json.load(f)
        return {
            "bandwidth": data["bw_MiBps"],
            "iops": data["iops"]
        }
```

### Plain Text with Regex (Simulation)

A simulation prints results mixed with log messages:

```
[INFO] Starting simulation...
[INFO] Grid size: 256x256
[RESULT] Elapsed time: 12.453 seconds
[RESULT] Iterations: 5000
[RESULT] GFLOPS: 42.7
```

```yaml
parser:
  file: "{{ execution_dir }}/simulation.log"
  metrics:
    - name: elapsed_time
    - name: gflops
  parser_script: |
    import re

    def parse(file_path):
        with open(file_path) as f:
            content = f.read()
        time = float(re.search(r"Elapsed time: ([\d.]+)", content).group(1))
        gflops = float(re.search(r"GFLOPS: ([\d.]+)", content).group(1))
        return {"elapsed_time": time, "gflops": gflops}
```

### CSV Output (ML Training)

A training script writes epoch-level metrics to CSV. The parser reads the final row:

```yaml
parser:
  file: "{{ execution_dir }}/training_log.csv"
  metrics:
    - name: final_loss
    - name: accuracy
  parser_script: |
    import csv

    def parse(file_path):
        with open(file_path) as f:
            rows = list(csv.DictReader(f))
        last = rows[-1]
        return {
            "final_loss": float(last["loss"]),
            "accuracy": float(last["accuracy"])
        }
```

### Using Context Variables (Derived Metrics)

Compute per-node throughput using the `vars` global:

```yaml
parser:
  file: "{{ execution_dir }}/output.json"
  metrics:
    - name: total_bandwidth
    - name: bandwidth_per_node
  parser_script: |
    import json

    def parse(file_path):
        with open(file_path) as f:
            data = json.load(f)
        total = data["bandwidth_mb"]
        return {
            "total_bandwidth": total,
            "bandwidth_per_node": total / vars["nodes"]
        }
```

### Conditional Logic Based on Parameters

Parse different fields depending on a variable:

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
        if vars["operation"] == "write":
            return {"performance": data["write_bw"]}
        else:
            return {"performance": data["read_bw"]}
```

### External Parser File

For complex parsers, keep the script in a separate file instead of inlining it:

```yaml
parser:
  file: "{{ execution_dir }}/output.json"
  metrics:
    - name: throughput
  parser_script: ./scripts/my_parser.py
```

The external file has the same structure and access to the same context globals:

```python
# ./scripts/my_parser.py
import json

def parse(file_path):
    with open(file_path) as f:
        data = json.load(f)
    return {"throughput": data["bandwidth"] / vars["nodes"]}
```

---

## Where the Data Goes

After parsing, IOPS combines your metrics with the execution parameters and writes everything to the configured output sink:

```yaml
output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
```

Each row in the results file contains:

| Category | Fields |
|----------|--------|
| **Execution info** | `execution_id`, `repetition` |
| **Benchmark info** | `benchmark.name`, `benchmark.description` |
| **Parameters** | All variables from the `vars` section |
| **Your metrics** | Every metric returned by your `parse()` function |
| **Metadata** | Status, timing, job IDs (depending on executor) |

Supported output formats are `csv`, `parquet`, and `sqlite`. The results file is then used by `iops report` to generate interactive HTML reports, and you can also load it directly for custom analysis with tools like pandas or R.

---

## Debugging

When a parser fails, IOPS captures diagnostic output to help you investigate:

- **stdout/stderr** from your script are saved to `parser_stdout` and `parser_stderr` files in the execution directory
- The execution status is set to `ERROR` with a message describing the failure
- Use `iops find /path/to/workdir --status ERROR` to locate failed executions

Common issues:

| Problem | Cause | Fix |
|---------|-------|-----|
| `ParserContractError: no parse() function` | Missing or misspelled function | Ensure your script defines `def parse(file_path):` |
| `ParserContractError: expected dict` | `parse()` returns wrong type | Return a dictionary, not a list or scalar |
| `Missing metric "X"` | Return dict missing a declared metric | Ensure every name in `metrics` appears as a key in the returned dict |
| `FileNotFoundError` | Output file path is wrong | Check the `file` path, use `--dry-run` to preview resolved paths |
| `KeyError` / `IndexError` | Unexpected output format | Add print statements for debugging; check `parser_stdout` |

---

## Tips

- **Start simple.** Write and test your parser on a single output file before integrating it into the full YAML configuration.
- **Use `print()` for debugging.** Anything printed during parsing is captured in `parser_stdout`, so you can inspect it if something goes wrong.
- **Return `None` for missing metrics.** If a metric cannot be extracted from a particular run, return `None` instead of raising an exception. This keeps the rest of the study intact.
- **Keep parsers focused.** The parser's job is to extract numbers from a file. Avoid heavy computation or side effects.
- **Use external files for complex parsers.** If your parser exceeds ~20 lines, put it in a separate `.py` file for easier editing and testing.
