---
title: "User Guide"
weight: 20
---

Comprehensive guide to using IOPS features and capabilities.

## Configuration

- **[YAML Schema Reference](yaml-schema)** - Complete reference for all configuration options (`benchmark`, `vars`, `command`, `scripts`, `output`, `reporting`)
- **[Jinja2 Templating](jinja2-templating)** - Dynamic values, conditionals, loops, and expressions in templates
- **[Matrix Generation](matrix-generation)** - How IOPS builds the parameter space from variables, including conditional variables

## Execution

- **[Search Methods](search-methods)** - Parameter space exploration: exhaustive, random sampling, and Bayesian optimization
- **[Execution Backends](execution-backends)** - Run locally or on SLURM clusters
- **[Result Caching](caching)** - Skip redundant tests with smart caching

## Results & Analysis

- **[Exploring Executions](exploring-executions)** - Use `iops find` to locate, filter, and monitor executions
- **[Metadata Files](metadata-files)** - `__iops_*` files: structure, I/O overhead, and how to disable them
- **[Custom Reports & Visualization](reporting)** - Generate interactive HTML reports with Plotly charts

## Reference

- **[Command Line Interface](cli)** - Complete CLI reference for `iops run`, `iops find`, `iops report`, and more
