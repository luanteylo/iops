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

**With IOPS**: Write one YAML config → Run `iops run config.yaml` → Get interactive HTML reports

Originally designed for I/O performance studies (see [our 2022 paper](https://inria.hal.science/hal-03753813/)), IOPS has evolved into a generic framework for any parametric benchmark workflow.

## Key Features

- **Parameter Sweeping**: Automatically generate and execute tests for all parameter combinations
- **Multiple Search Strategies**: Exhaustive, Bayesian optimization, or random sampling
- **Execution Backends**: Run locally or submit to SLURM clusters
- **Execution Exploration**: Find and filter execution folders by parameter values
- **Smart Caching**: Skip redundant tests with parameter-aware result caching
- **Budget Control**: Set core-hour limits to avoid exceeding compute allocations
- **Automatic Reports**: Generate interactive HTML reports with plots and statistical analysis
- **Flexible Output**: Export results to CSV, Parquet, or SQLite

## From the Blog

Real studies and interesting ways to use IOPS:

- [Bayesian Optimization Benchmark](/blog/bayesian-optimization-study/) - Testing BO search against random sampling using cached HPC results
- [TOTO Overhead Analysis](/blog/toto-overhead-analysis/) - Measuring runtime overhead of an I/O interception library

## Links

- **Repository**: [GitLab](https://gitlab.inria.fr/lgouveia/iops)
- **Issues**: [Issue Tracker](https://gitlab.inria.fr/lgouveia/iops/-/issues)
- **PyPI**: [iops-benchmark](https://pypi.org/project/iops-benchmark/)
