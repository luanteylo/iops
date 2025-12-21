---
title: "Examples"
---


This section provides working examples demonstrating various IOPS features.

## Available Examples

### Basic Examples

- **[Simple Local Example](simple.md)**: Basic local execution with parameter sweeping
- **[Bayesian Optimization](bayesian.md)**: Using Bayesian optimization for parameter tuning

### Advanced Examples

- **[SLURM Cluster](slurm.md)**: Running benchmarks on HPC clusters with SLURM

## Example Files

The `docs/examples/` directory contains ready-to-use configuration files:

- `example_simple.yaml` - Basic local execution
- `example_simple_rounds.yaml` - Multi-round optimization
- `example_bayesian.yaml` - Bayesian optimization
- `example_random.yaml` - Random sampling
- `example_plafrim.yaml` - SLURM cluster deployment
- `example_plafrim_bayesian.yaml` - SLURM with Bayesian search

## Using the Examples

```bash
# Copy an example
cp docs/examples/example_simple.yaml my_config.yaml

# Edit for your needs
nano my_config.yaml

# Validate
iops my_config.yaml --check_setup

# Run
iops my_config.yaml
```

## Next Steps

- Review the [User Guide](../user-guide/configuration.md)
- Check the [YAML Schema Reference](../reference/yaml-schema.md)
