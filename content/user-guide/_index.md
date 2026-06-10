---
title: "User Guide"
weight: 20
---

Guides for IOPS features and capabilities.

## Configuration

- **[YAML Schema Reference](yaml-schema)** - All configuration options (`benchmark`, `vars`, `command`, `scripts`, `output`, `reporting`, `machines`)
- **[Templating and Context](templating-and-context)** - Jinja2 syntax, dynamic values, conditionals, and context variables per section
- **[Matrix Generation](matrix-generation)** - How IOPS builds the parameter space, including conditional variables
- **[Machine Overrides](machines)** - One config for multiple systems with per-machine overrides
- **[Writing Scripts](writing-scripts)** - The shell script IOPS runs per test: executor differences, input files, post-execution hooks, debugging
- **[Writing Parsers](writing-parsers)** - Extract metrics from benchmark output with Python scripts
- **[Using IOPS on Grid'5000](/iops/blog/grid500/)** - Run IOPS with OAR scheduler using wrapper scripts

## Execution

- **[Search Methods](search-methods)** - Exhaustive, random sampling, Bayesian optimization, and adaptive probing
- **[Bayesian Optimization](bayesian-optimization)** - Parameter encoding, surrogate models, acquisition functions, and convergence
- **[Adaptive Variables](adaptive-variables)** - Find threshold values with adaptive probing (max memory, performance cliffs)
- **[Execution Backends](execution-backends)** - Run locally or on SLURM clusters
- **[Single-Allocation Mode](single-allocation-mode)** - Run all tests in one SLURM allocation (MPI setup, troubleshooting)
- **[Result Caching](caching)** - Skip redundant tests
- **[Budget Control](budget-control)** - Limit core-hours with `max_core_hours` and `cores_expr`
- **[Resource Sampling](resource-tracing)** - Sample CPU, memory, and GPU metrics (power, utilization, temperature) during execution

## Results & Analysis

- **[Exploring Executions](exploring-executions)** - Locate, filter, and monitor executions with `iops find`
- **[Archiving Workdirs](exploring-executions#archiving-workdirs)** - Portable archives with `iops archive` for sharing and backup
- **[Custom Reports & Visualization](reporting)** - Interactive HTML reports with Plotly charts

## Migration

- **[JUBE Conversion](jube-conversion)** - Convert JUBE XML benchmarks to IOPS YAML with `iops convert`

## Reference

- **[Command Line Interface](cli)** - Complete CLI reference for `iops run`, `iops find`, `iops report`, and more
- **[Metadata Files](metadata-files)** - `__iops_*` files: structure, I/O overhead, and how to disable them
