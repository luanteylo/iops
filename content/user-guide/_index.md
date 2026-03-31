---
title: "User Guide"
weight: 20
---

Comprehensive guide to using IOPS features and capabilities.

## Configuration

- **[YAML Schema Reference](yaml-schema)** - Complete reference for all configuration options (`benchmark`, `vars`, `command`, `scripts`, `output`, `reporting`, `machines`)
- **[Templating and Context](templating-and-context)** - Jinja2 syntax, dynamic values, conditionals, and context variables per configuration section
- **[Matrix Generation](matrix-generation)** - How IOPS builds the parameter space from variables, including conditional variables
- **[Machine Overrides](machines)** - Use a single config for multiple systems with per-machine overrides
- **[Writing Parsers](writing-parsers)** - Extract metrics from benchmark output with custom Python scripts
- **[Using IOPS on Grid'5000](/iops/blog/grid500/)** - Run IOPS with OAR scheduler using wrapper scripts

## Execution

- **[Search Methods](search-methods)** - Parameter space exploration: exhaustive, random sampling, Bayesian optimization, and adaptive probing
- **[Bayesian Optimization](bayesian-optimization)** - Surrogate-model guided search: parameter encoding, surrogate models, acquisition functions, and convergence
- **[Adaptive Variables](adaptive-variables)** - Find threshold values automatically with adaptive probing (max memory, performance cliffs)
- **[Execution Backends](execution-backends)** - Run locally or on SLURM clusters
- **[Single-Allocation Mode](single-allocation-mode)** - Run all tests in one SLURM allocation (MPI setup, troubleshooting)
- **[Result Caching](caching)** - Skip redundant tests with smart caching
- **[Budget Control](budget-control)** - Limit core-hours consumption with `max_core_hours` and `cores_expr`
- **[Resource Sampling](resource-tracing)** - Sample CPU, memory, and GPU metrics (power, utilization, temperature) during benchmark execution

## Results & Analysis

- **[Exploring Executions](exploring-executions)** - Use `iops find` to locate, filter, and monitor executions
- **[Archiving Workdirs](exploring-executions#archiving-workdirs)** - Create portable archives with `iops archive` for sharing and backup
- **[Custom Reports & Visualization](reporting)** - Generate interactive HTML reports with Plotly charts

## Migration

- **[JUBE Conversion](jube-conversion)** - Convert JUBE XML benchmarks to IOPS YAML with `iops convert`

## Reference

- **[Command Line Interface](cli)** - Complete CLI reference for `iops run`, `iops find`, `iops report`, and more
- **[Metadata Files](metadata-files)** - `__iops_*` files: structure, I/O overhead, and how to disable them
