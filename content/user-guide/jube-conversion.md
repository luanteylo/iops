---
title: "JUBE Conversion"
---

> **Experimental Feature**
>
> JUBE conversion is experimental. It may contain bugs or undergo breaking changes in future releases. Please report any issues you encounter.

Convert existing [JUBE](https://github.com/FZJ-JSC/JUBE) benchmark configurations to IOPS format using `iops convert`.

---

## Overview

JUBE (Juelich Benchmarking Environment) is an HPC benchmarking framework that uses XML configurations. If you already have JUBE benchmarks, `iops convert` provides a best-effort translation to IOPS YAML format, saving you from rewriting configurations manually.

The converter uses JUBE's own Python library to parse the XML, ensuring accurate interpretation of all JUBE-specific syntax. The output includes TODO markers for features that require manual adjustment.

### Prerequisites

The JUBE Python library must be installed:

```bash
pip install git+https://github.com/FZJ-JSC/JUBE.git
```

JUBE is not available on PyPI. If `iops convert` is run without JUBE installed, it will display installation instructions.

---

## Usage

```bash
iops convert <input.xml> [options]
```

**Arguments:**

- `input.xml` (positional) - Path to the JUBE XML benchmark file

**Options:**

- `-o, --output PATH` - Output YAML path (default: `<input_stem>_iops.yaml`)
- `--benchmark NAME` - Select a specific benchmark if the XML contains multiple
- `--executor {local,slurm}` - Target executor (default: `local`)
- `-n, --dry-run` - Print converted YAML to stdout instead of writing a file

**Examples:**

```bash
# Basic conversion
iops convert benchmark.xml

# Specify output path
iops convert benchmark.xml -o my_config.yaml

# Convert for SLURM execution
iops convert benchmark.xml --executor slurm

# Preview output without writing a file
iops convert benchmark.xml --dry-run

# Select specific benchmark from multi-benchmark XML
iops convert multi.xml --benchmark ior_bench
```

---

## Concept Mapping

| JUBE Element | IOPS Equivalent | Notes |
|-------------|-----------------|-------|
| `<parameter>` (comma-separated values) | `vars[].sweep.mode=list` | Values split by separator, cast to type |
| `<parameter>` (single value) | `vars[]` with literal value | No sweep |
| `<parameter mode="python">` | `vars[].expr` | `$var` converted to `{{ var }}` |
| `<parameter mode="shell">` | TODO marker | Cannot auto-convert |
| `<step>` with `<do>` operations | `scripts[].script_template` | Operations concatenated |
| Variable substitution (`$var`) | Jinja2 `{{ var }}` | Automatic syntax conversion |
| `<fileset>` (copy/link) | Shell commands in script preamble | `cp -r` / `ln -sf` commands |
| `<patternset>` (regex) | `scripts[].parser.parser_script` | Generates Python `parse()` function |
| Derived pattern | Computed metric in parser | Expression converted to Python |
| `<analyser>` | `scripts[].parser` | Maps output file and metrics |
| `<result>` table | `output.sink` type=csv | Default CSV output |
| Step `iterations` | `benchmark.repetitions` | Approximate mapping |

---

## Example Walkthrough

### Input: JUBE XML

```xml
<?xml version="1.0" encoding="UTF-8"?>
<jube>
  <benchmark name="io_bench" outpath="bench_run">
    <comment>I/O performance benchmark</comment>

    <parameterset name="system_params">
      <parameter name="nodes" type="int">1,2,4,8</parameter>
      <parameter name="ppn" type="int">4,8</parameter>
      <parameter name="total_procs" type="int" mode="python">
        $nodes * $ppn
      </parameter>
    </parameterset>

    <step name="execute">
      <use>system_params</use>
      <do>mpirun -np $total_procs ./io_benchmark --nodes $nodes</do>
    </step>

    <patternset name="metrics">
      <pattern name="bandwidth" type="float">
        Bandwidth: $jube_pat_fp MB/s
      </pattern>
    </patternset>

    <analyser name="analyse">
      <use>metrics</use>
      <analyse step="execute">
        <file>stdout</file>
      </analyse>
    </analyser>
  </benchmark>
</jube>
```

### Command

```bash
iops convert io_bench.xml -o io_bench_iops.yaml
```

### Output: IOPS YAML

```yaml
benchmark:
  name: io_bench
  description: I/O performance benchmark
  workdir: ./workdir
  executor: local
  search_method: exhaustive
  repetitions: 1

vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4, 8]
  ppn:
    type: int
    sweep:
      mode: list
      values: [4, 8]
  total_procs:
    type: int
    expr: "{{ nodes * ppn }}"

command:
  template: "mpirun -np {{ total_procs }} ./io_benchmark --nodes {{ nodes }}"

scripts:
  - name: main
    submit: bash
    script_template: |
      #!/bin/bash

      {{ command.template }}
    parser:
      file: "{{ execution_dir }}/stdout"
      metrics:
        - name: bandwidth
      parser_script: |
        import re

        def parse(file_path):
            results = {}
            with open(file_path) as f:
                content = f.read()
            m = re.search(r"Bandwidth: ([+-]?(?:\d*\.?\d+(?:[eE][-+]?\d+)?|\d+\.))", content)
            if m:
                results["bandwidth"] = float(m.group(1))
            return results

output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
```

---

## Limitations and Manual Adjustments

The following JUBE features cannot be automatically converted and will produce TODO markers or warnings:

**Parameters:**
- **Shell-mode parameters** (`mode="shell"`) execute shell commands to compute values. These must be manually replaced with IOPS expressions or pre-computed values.
- **Perl-mode parameters** are not supported.

**Workflow:**
- **Multi-step DAG workflows** are flattened. JUBE allows defining step dependencies as a directed acyclic graph, while IOPS uses a flat script model. Steps are concatenated in dependency order but may need restructuring.
- **Step cycles** (`cycles` attribute) have no direct equivalent. Consider increasing `repetitions` or restructuring the workflow.
- **Shared directories** between workpackages are not supported in IOPS.

**Execution:**
- **Async operations** (checking for completion files) are handled by IOPS executors differently. Remove async-related operations from the script template.
- **Substitutesets** targeting external files (not the script template) are not converted. Add file manipulation to the script preamble if needed.

**Other:**
- **JUBE internal variables** (`$jube_wp_id`, `$jube_wp_relpath`, etc.) are preserved as-is and should be replaced with IOPS equivalents (`{{ execution_id }}`, `{{ execution_dir }}`, etc.).
- **Tag-based parameter selection** is simplified to static values.

---

## Post-Conversion Validation

After converting, always validate and preview before running:

```bash
# Validate the generated configuration
iops check io_bench_iops.yaml

# Preview the execution plan
iops run io_bench_iops.yaml --dry-run

# Run the benchmark
iops run io_bench_iops.yaml
```

Search for `TODO` markers in the generated YAML and address them before execution. The converter prints a summary of warnings to help identify areas needing attention.
