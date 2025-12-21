# SLURM Cluster Example

This example demonstrates running benchmarks on an HPC cluster with SLURM.

See `docs/examples/example_plafrim.yaml` for the complete configuration.

## Key Features

- Automatic job submission via sbatch
- Resource management and monitoring
- Budget tracking with core-hours
- Multi-node execution

## Configuration Highlights

```yaml
benchmark:
  executor: "slurm"
  max_core_hours: 1000
  cores_expr: "{{ nodes * processes_per_node }}"

scripts:
  - name: "mpi_benchmark"
    submit: "sbatch --parsable"
    script_template: |
      #!/bin/bash
      #SBATCH --job-name=bench_{{ execution_id }}
      #SBATCH --nodes={{ nodes }}
      #SBATCH --ntasks-per-node={{ processes_per_node }}
      #SBATCH --time=01:00:00

      module load openmpi
      {{ command.template }}
```

## Running

```bash
# Dry-run to estimate resource usage
iops config.yaml --dry-run --estimated-time 300

# Execute
iops config.yaml --max-core-hours 1000
```
