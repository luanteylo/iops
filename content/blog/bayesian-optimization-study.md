---
title: "Bayesian Optimization Benchmark"
subtitle: "Testing IOPS's BO search against random sampling using cached HPC results"
date: 2025-01-15
tags: ["bayesian-optimization", "caching", "benchmarking"]
---



IOPS can use Bayesian Optimization when the objective is to find the parameter combination that yields the maximum (or minimum) metric value in a search space. In this article, we decided to test the efficiency of IOPS's BO search by comparing it against IOPS's random search. The idea is simple: given a search space, run both IOPS BO and Random, then compare the results to see which one reaches the optimal first. And of course, it should not be a surprise at this point that we used an I/O benchmark to do it. So the study was: find the best parameter combination that maximizes I/O bandwidth performance. We started writing a script to run these tests, but at some point we realized that this was just another PARAMETER EXPLORATION. So we ran `iops generate` and started editing a YAML file to make IOPS run itself, like in the movie Inception. 

In this inception-style study, we demonstrate the effectiveness of BO when running I/O benchmarks, but also showcase a bunch of interesting IOPS features. First, we use IOPS's capability of running benchmarks entirely from cached results. Using the `--cache-only` flag, we replay thousands of HPC experiments offline, enabling rapid comparison without consuming compute resources.

This was possible because of the cache feature implemented in IOPS (explained [here](/user-guide/caching)). The cache was generated during another execution campaign that will be published here soon (when the paper gets accepted). It contains 1,049 execution results (304 unique configurations × 3 repetitions) from IOR benchmarks run on the IRENE supercomputer (CEA, France), covering a 5-dimensional parameter space:

| Parameter | Values | Description |
|-----------|--------|-------------|
| `nodes` | 1, 32, 64 | Compute nodes |
| `processes_per_node` | 1, 64, 128 | MPI ranks per node |
| `ost_count` | 1, 4, 8, 16, 24, 32, 40 | Lustre OST count |
| `transfer_size_kb` | 32, 1024, 8192, 32768, 65536 | I/O transfer size |
| `volume_size_gb` | 128 | Fixed data volume |

After constraint filtering, the parameter space contains 315 valid configurations. Each optimization run explores only 20 of them—that's just 6.3% of the space.

---

## Study Design

We compared three search methods across 25 random seeds:

| Method | Search Strategy | Configuration |
|--------|-----------------|---------------|
| `random` | Random sampling | 20 random configurations |
| `bayesian_default` | Bayesian (EI+RF) | 5 initial + 15 guided iterations |
| `bayesian_tuned` | Bayesian (EI+ET) | Extra Trees estimator |

Each execution spawns a nested IOPS run that queries the shared cache:

```yaml
command:
  template: "iops run {{ inner_config }} --use-cache --cache-only"
```

The `--cache-only` flag ensures all results come from the pre-populated cache—no actual benchmarks are executed. This let us run 75 complete optimization studies (3 methods × 25 seeds) in under 5 minutes on a laptop. Pretty cool, right?

### How the Nested Execution Works

The script template generates YAML configurations dynamically using embedded Python, then invokes IOPS with that configuration. The parser analyzes each run's CSV output to extract the best bandwidth found, number of iterations, and unique configurations explored.

---

## Results

### Performance Comparison

The boxplot below shows the best bandwidth found by each method across 25 seeds:

![Performance Boxplot](../../images/blog/performance_boxplot.png)

The optimal configuration achieves 72.4 GB/s. Bayesian optimization finds configurations within 10% of optimal in most runs, while random sampling shows higher variance and generally lower performance.

### Search Effectiveness

![Percentage of Optimal](../../images/blog/percentage_optimal.png)

Bayesian optimization achieves a 10 percentage point improvement over random sampling while exploring only 6% of the parameter space. The Extra Trees (ET) estimator provides a slight edge over Random Forest (RF) for this workload.

### Convergence

![Convergence Curves](../../images/blog/convergence_curves.png)

The convergence plot shows how each method progresses over iterations. The shaded regions represent standard deviation across seeds. Bayesian methods start with 5 random points (the exploration phase), then use the surrogate model to guide the search. Both Bayesian variants converge faster and reach higher performance than random sampling.

---

## Considerations

This study has a fundamental limitation: with only 315 valid configurations, the problem is relatively modest, which increases the probability of finding good configurations by chance.

More importantly, the `nodes` parameter dominates performance in this workload. Since it has only 3 values (1, 32, 64), random sampling has a 33% chance of selecting the optimal node count on each iteration. The figure below illustrates how each method selects node counts over iterations:

![Node Selection Distribution](../../images/blog/node_selection.png)

The y-axis shows the proportion of seeds (out of 25) that selected each node value at a given iteration. For example, if 20 out of 25 seeds selected `nodes=64` at iteration 15, the green bar would show 0.8 (80%) at that point.

The Bayesian methods quickly learn that higher node counts yield better performance and concentrate their search accordingly—by iteration 10, nearly all seeds are selecting `nodes=64`. Random sampling, by contrast, distributes selections uniformly across all node values throughout the run.

Despite these limitations, the study shows that Bayesian optimization provides consistent improvements over random sampling, and that IOPS's cache-only mode enables rapid algorithmic experimentation without HPC resources. A follow-up study with a larger parameter space would likely show an even bigger gap between the methods.

---

## Full Configuration

Here's the complete YAML configuration we used:

```yaml
benchmark:
  name: "Bayesian vs Random Optimization Comparison"
  workdir: "./"
  executor: "local"
  search_method: "exhaustive"
  repetitions: 1
  track_executions: true

vars:
  method:
    type: str
    sweep:
      mode: list
      values: ["random", "bayesian_default", "bayesian_tuned"]

  seed:
    type: int
    sweep:
      mode: list
      values: [1992, 2023, 42, 123, 456, 789, 1000, 2000, 3000, 4000,
               5000, 6000, 7000, 8000, 9000, 10000, 11111, 22222, 33333, 44444,
               55555, 66666, 77777, 88888, 99999]

  actual_search_method:
    type: str
    expr: "{% if method == 'random' %}random{% else %}bayesian{% endif %}"

  base_estimator:
    type: str
    expr: "{% if method == 'bayesian_tuned' %}ET{% else %}RF{% endif %}"

  inner_workdir:
    type: str
    expr: "{{ execution_dir }}/inner_run"

  inner_config:
    type: str
    expr: "{{ execution_dir }}/inner_config.yaml"

constraints:
  - name: "require_cache_env"
    rule: "os_env.get('IOPS_CACHE', '') != ''"
    violation_policy: "error"
    description: "IOPS_CACHE environment variable must be set"

command:
  template: "iops run {{ inner_config }} --use-cache --cache-only --log-level WARNING"
  labels:
    study_type: "optimization_comparison"

scripts:
  - name: "run_inner_iops"
    submit: "bash"
    script_template: |
      #!/bin/bash
      set -e

      python3 << 'PYTHON_EOF'
      import yaml
      import os
      from pathlib import Path

      cache_file = os.environ.get('IOPS_CACHE', './cache.db')

      config = {
          "benchmark": {
              "name": "{{ method }} seed {{ seed }}",
              "workdir": "{{ inner_workdir }}",
              "cache_file": cache_file,
              "repetitions": 3,
              "search_method": "{{ actual_search_method }}",
              "executor": "local",
              "random_seed": {{ seed }},
              "cache_exclude_vars": ["summary_file"],
              "track_executions": True,
          },
          "vars": {
              "nodes": {"type": "int", "sweep": {"mode": "list", "values": [1, 32, 64]}},
              "processes_per_node": {"type": "int", "sweep": {"mode": "list", "values": [1, 64, 128]}},
              "volume_size_gb": {"type": "int", "sweep": {"mode": "list", "values": [128]}},
              "ost_count": {"type": "int", "sweep": {"mode": "list", "values": [1, 4, 8, 16, 24, 32, 40]}},
              "transfer_size_kb": {"type": "int", "sweep": {"mode": "list", "values": [32, 1024, 8192, 32768, 65536]}},
          },
          "constraints": [
              {"name": "block_transfer_alignment", "rule": "(block_size_mb * 1024) % transfer_size_kb == 0", "violation_policy": "skip"},
              {"name": "transfer_size_limit", "rule": "transfer_size_kb <= (block_size_mb * 1024)", "violation_policy": "skip"}
          ],
          "command": {
              "template": "ior -w -b {{ block_size_mb }}mb -t {{ transfer_size_kb }}kb -O summaryFile={{ summary_file }} -O summaryFormat=JSON -o {{ ost_path }}/output.ior",
              "metadata": {"operation": "write", "filestrategy": "shared-file", "spatiality": "contig"}
          },
          "scripts": [{
              "name": "ior",
              "submit": "bash",
              "script_template": "#!/bin/bash\necho \"Placeholder - using cached results\"",
              "parser": {
                  "file": "{{ summary_file }}",
                  "metrics": [{"name": "bwMiB"}],
                  "parser_script": "def parse(file_path):\n    return {\"bwMiB\": 0}"
              }
          }],
          "output": {"sink": {"type": "csv", "path": "{{ workdir }}/results.csv"}}
      }

      # Add method-specific configuration
      if "{{ actual_search_method }}" == "bayesian":
          config["benchmark"]["bayesian_config"] = {
              "objective_metric": "bwMiB",
              "objective": "maximize",
              "n_initial_points": 5,
              "n_iterations": 20,
              "acquisition_func": "EI",
              "base_estimator": "{{ base_estimator }}",
          }
      else:
          config["benchmark"]["random_config"] = {"n_samples": 20}

      with open("{{ inner_config }}", "w") as f:
          yaml.dump(config, f)
      PYTHON_EOF

      {{ command.template }}

    parser:
      file: "{{ inner_workdir }}/run_001/results.csv"
      metrics:
        - name: best_bw
        - name: iterations
        - name: unique_configs
        - name: final_bw
      parser_script: |
        import pandas as pd

        def parse(file_path):
            df = pd.read_csv(file_path)
            best_bw = df['metrics.bwMiB'].max()
            param_cols = ['vars.nodes', 'vars.processes_per_node', 'vars.ost_count', 'vars.transfer_size_kb']
            unique_configs = len(df.groupby(param_cols))
            return {"best_bw": best_bw, "iterations": unique_configs, "unique_configs": unique_configs}

output:
  sink:
    type: csv
    path: "./results.csv"
```
