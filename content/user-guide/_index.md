---
title: "User Guide"
weight: 20
---

Comprehensive guide to using IOPS features and capabilities.

## Configuration

- **[YAML Schema Reference](yaml-schema)** - Complete reference for all configuration options (`benchmark`, `vars`, `command`, `scripts`, `output`, `reporting`)
- **[Templating and Context](templating-and-context)** - Jinja2 syntax, dynamic values, conditionals, and context variables per configuration section
- **[Matrix Generation](matrix-generation)** - How IOPS builds the parameter space from variables, including conditional variables

## Execution

- **[Search Methods](search-methods)** - Parameter space exploration: exhaustive, random sampling, and Bayesian optimization
- **[Execution Backends](execution-backends)** - Run locally or on SLURM clusters
- **[Single-Allocation Mode](single-allocation-mode)** - Run all tests in one SLURM allocation (MPI setup, troubleshooting)
- **[Result Caching](caching)** - Skip redundant tests with smart caching
- **[Budget Control](budget-control)** - Limit core-hours consumption with `max_core_hours` and `cores_expr`
- **[Resource Tracing](resource-tracing)** - Trace CPU and memory utilization during benchmark execution

## Results & Analysis

- **[Exploring Executions](exploring-executions)** - Use `iops find` to locate, filter, and monitor executions
- **[Archiving Workdirs](exploring-executions#archiving-workdirs)** - Create portable archives with `iops archive` for sharing and backup
- **[Custom Reports & Visualization](reporting)** - Generate interactive HTML reports with Plotly charts

## Reference

- **[Command Line Interface](cli)** - Complete CLI reference for `iops run`, `iops find`, `iops report`, and more
- **[Metadata Files](metadata-files)** - `__iops_*` files: structure, I/O overhead, and how to disable them
