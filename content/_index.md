---
title: "IOPS"
weight: 1
---

# IOPS

**A generic benchmark orchestration framework for automated parametric experiments.**

IOPS automates the generation, execution, and analysis of benchmark experiments. Instead of writing custom scripts for each study, you define a YAML configuration describing what to vary, what to run, and what to measure; IOPS handles the rest.

**Without IOPS**: Write bash scripts → Parse outputs → Aggregate data → Generate plots → Repeat for each parameter change

**With IOPS**: Write one YAML config → Run `iops run config.yaml` → Get interactive HTML reports

Originally designed for I/O performance studies (see [our 2022 paper](https://inria.hal.science/hal-03753813/)), IOPS has evolved into a generic framework for any parametric benchmark workflow.

## Key Features

- **Parameter Sweeping**: Generate and execute tests for all parameter combinations
- **Search Strategies**: Exhaustive, Bayesian optimization, or random sampling
- **Execution Backends**: Run locally or submit to SLURM clusters
- **Execution Exploration**: Find and filter execution folders by parameter values
- **Caching**: Skip redundant tests with parameter-aware result caching
- **Budget Control**: Set core-hour limits to avoid exceeding compute allocations
- **Reports**: Interactive HTML reports with plots and statistical analysis
- **Output**: Export results to CSV, Parquet, or SQLite

## Blog

Tutorials and use cases on the [blog]({{< ref "/blog" >}}):

- [Measuring the runtime overhead of an I/O interception library]({{< ref "/blog/toto-overhead-analysis" >}}) - Quantifying TOTO's overhead with conditional variables and resource tracing
- [Testing IOPS's Bayesian search against random sampling]({{< ref "/blog/bayesian-optimization-study" >}}) - How guided search reaches the optimum with far fewer evaluations
- [Using IOPS on Grid'5000]({{< ref "/blog/grid500" >}}) - Run IOPS with OAR scheduler on Grid'5000

## Links

- **Slides**: [IOPS overview (PDF)](slides/iops_presentation.pdf) - YAML configuration, search strategies, parsers, and reports, with a running IOR example
- **Repository**: [GitLab](https://gitlab.inria.fr/lgouveia/iops)
- **Issues**: [Issue Tracker](https://gitlab.inria.fr/lgouveia/iops/-/issues)
- **PyPI**: [iops-benchmark](https://pypi.org/project/iops-benchmark/)
