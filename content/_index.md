---
title: "IOPS - I/O Performance Suite"
type: docs
---

# IOPS - I/O Performance Suite

**A generic benchmark orchestration framework for automated parametric experiments.**

IOPS automates the generation, execution, and analysis of benchmark experiments. Instead of writing custom scripts for each benchmark study, you define a YAML configuration describing what to vary, what to run, and what to measure—IOPS handles the rest.

## What is IOPS?

IOPS (I/O Performance Suite) is a framework that transforms benchmark experiments from manual scripting into automated, reproducible workflows.

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

## Quick Links

- **[Installation](docs/getting-started/installation)** - Get started with IOPS in minutes
- **[Quick Start](docs/getting-started/quickstart)** - Run your first benchmark in 5 minutes
- **[User Guide](docs/user-guide/configuration)** - Learn how to configure and use IOPS
- **[Examples](docs/examples/)** - Explore working examples and templates

## How It Works

IOPS follows a simple workflow:

1. **Configuration**: Define variables to sweep, commands to run, and metrics to measure in a YAML file
2. **Planning**: IOPS generates execution instances for parameter combinations
3. **Execution**: Runs tests locally or submits SLURM jobs
4. **Parsing**: Extracts metrics from output files using your parser script
5. **Storage**: Saves results to CSV, SQLite, or Parquet
6. **Analysis**: Generates HTML reports with interactive plots and statistics

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

## Community and Support

- **Repository**: [GitLab](https://gitlab.inria.fr/lgouveia/iops)
- **Issues**: [Issue Tracker](https://gitlab.inria.fr/lgouveia/iops/-/issues)
- **PyPI**: [iops-benchmark](https://pypi.org/project/iops-benchmark/)

## License

This project is developed at INRIA. See the [License](docs/about/license) page for details.
