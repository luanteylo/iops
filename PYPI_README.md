# IOPS

**A generic benchmark orchestration framework for automated parametric experiments.**

IOPS transforms benchmark experiments from manual scripting into automated, reproducible workflows. Define a YAML configuration describing what to vary, what to run, and what to measure—IOPS handles the rest.

## Features

- **Parameter Sweeping** — Automatically generate and execute tests for all parameter combinations
- **Multiple Search Strategies** — Exhaustive, Bayesian optimization, or random sampling
- **Execution Backends** — Run locally or submit to SLURM clusters
- **Smart Caching** — Skip redundant tests with parameter-aware result caching
- **Budget Control** — Set core-hour limits to avoid exceeding compute allocations
- **Automatic Reports** — Generate interactive HTML reports with plots and statistical analysis

## Quick Start

```bash
# Generate a configuration template
iops generate my_config.yaml

# Preview what will be executed
iops run my_config.yaml --dry-run

# Run the benchmark
iops run my_config.yaml

# Explore executions and filter by parameters
iops find ./workdir/run_001
iops find ./workdir/run_001 threads=4 buffer_size=256

# Generate an HTML report
iops report ./workdir/run_001
```

## Example Configuration

```yaml
benchmark:
  name: "My Benchmark Study"
  workdir: "./workdir"
  executor: "local"
  repetitions: 3

vars:
  threads:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4, 8]

  buffer_size:
    type: int
    sweep:
      mode: list
      values: [64, 256, 1024]

command:
  template: "my_benchmark --threads {{ threads }} --buffer {{ buffer_size }}"

scripts:
  - name: "benchmark"
    submit: "bash"
    script_template: |
      #!/bin/bash
      # Built-in variables: execution_id, execution_dir, repetition
      echo "Running execution {{ execution_id }}, repetition {{ repetition }}"
      {{ command.template }} > output.txt

    parser:
      # execution_dir is automatically set to each execution's folder
      file: "{{ execution_dir }}/output.txt"
      metrics:
        - name: throughput
      parser_script: |
        import re

        def parse(file_path: str):
            with open(file_path) as f:
                content = f.read()
            match = re.search(r"throughput:\s*([\d.]+)", content)
            return {"throughput": float(match.group(1)) if match else 0}

output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
```

## Documentation

Full documentation, examples, and tutorials: **[https://lgouveia.gitlabpages.inria.fr/iops/](https://lgouveia.gitlabpages.inria.fr/iops/)**

## License

BSD-3-Clause — Developed at Inria.
