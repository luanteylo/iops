---
title: "IOPS"
weight: 1
---

# IOPS 

**A generic benchmark orchestration framework for automated parametric experiments.**

IOPS automates the generation, execution, and analysis of benchmark experiments. Instead of writing custom scripts for each benchmark study, you define a YAML configuration describing what to vary, what to run, and what to measure—IOPS handles the rest.

## What is IOPS?

IOPS is a framework that transforms benchmark experiments from manual scripting into automated, reproducible workflows.

**Without IOPS**: Write bash scripts → Parse outputs → Aggregate data → Generate plots → Repeat for each parameter change

**With IOPS**: Write one YAML config → Run `iops config.yaml` → Get interactive HTML reports

Originally designed for I/O performance studies (see [our 2022 paper](https://inria.hal.science/hal-03753813/)), IOPS has evolved into a generic framework for any parametric benchmark workflow.

## Key Features

- **Parameter Sweeping**: Automatically generate and execute tests for all parameter combinations
- **Multiple Search Strategies**: Exhaustive, Bayesian optimization, or random sampling
- **Execution Backends**: Run locally or submit to SLURM clusters
- **Smart Caching**: Skip redundant tests with parameter-aware result caching
- **Budget Control**: Set core-hour limits to avoid exceeding compute allocations
- **Automatic Reports**: Generate interactive HTML reports with plots and statistical analysis
- **Flexible Output**: Export results to CSV, Parquet, or SQLite

## Quick Start

Get started quickly with these guides:

- [Installation](getting-started/installation) - Get IOPS installed in minutes
- [Quick Start](getting-started/quickstart) - Run your first benchmark
- [Basic Concepts](getting-started/concepts) - Understand how IOPS works

## Documentation Sections

- **[Getting Started](getting-started)** - Installation, quick start, and basic concepts
- **[User Guide](user-guide)** - Detailed guides for using all IOPS features
- **[Examples](examples)** - Working examples and templates
- **[Reference](reference)** - CLI and YAML schema reference
- **[About](about)** - Changelog, license, and contributing

## Simple Example

```yaml
benchmark:
  name: "My Benchmark Study"
  workdir: "./workdir"
  executor: "local"
  search_method: "exhaustive"
  repetitions: 3

vars:
  threads:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4, 8]

command:
  template: "my_benchmark --threads {{ threads }}"

scripts:
  - name: "benchmark"
    parser:
      file: "{{ execution_dir }}/output.json"
      metrics:
        - name: throughput
      parser_script: scripts/parse_results.py

output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
```

Run it with:

```bash
iops config.yaml
```

## Links

- **Repository**: [GitLab](https://gitlab.inria.fr/lgouveia/iops)
- **Issues**: [Issue Tracker](https://gitlab.inria.fr/lgouveia/iops/-/issues)
- **PyPI**: [iops-benchmark](https://pypi.org/project/iops-benchmark/)
