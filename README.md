# IOPS - I/O Performance Suite

If you've ever tried to optimize I/O performance on an HPC cluster, you know the challenge. You write bash scripts to run IOR with different parameters. Then more scripts to parse the results. Then more scripts to generate graphs. Then you realize you need to test on another machine and have to adapt everything again.

We've been there. Back in 2022, we published [this paper](https://inria.hal.science/hal-03753813/) where we ran countless IOR experiments on our cluster and discovered some really interesting things—including configuration mistakes that were crippling our performance. The process involved significant manual work: scripting, data aggregation, and result analysis.

However, this approach was not sustainable in the long term. We needed a tool that could automate the entire process, making it reproducible, portable, and efficient. IOPS was born.

## What Does IOPS Actually Do?

IOPS is a benchmark orchestration framework. Here's what that means:

**The Problem**: To get maximum I/O bandwidth from your parallel file system, you need to find the sweet spot for multiple parameters:
- Number of compute nodes and processes
- Data volume (file sizes)
- Access patterns
- Striping configurations (OST counts, stripe sizes)

And here's the catch: these parameters are interdependent. You can't just test them independently. You need to test file sizes with 4 nodes, find the plateau, then test with 8 nodes, go back and re-test file sizes, rinse and repeat until you find the optimal combination.

**The Traditional Approach**: Write multiple bash scripts, run tests for days, manually aggregate results, generate graphs in Python, analyze data to identify patterns, and often discover mistakes that require re-running everything.

**The IOPS Approach**: Write one YAML file. Run `iops run config.yaml`. IOPS generates an HTML report with interactive plots showing exactly where your bottlenecks are and what parameters give you peak performance.

### Key Features

IOPS isn't just a "run all combinations" tool (though it can do that). It provides intelligent optimization:

**Bayesian Optimization**: Instead of testing all 192 parameter combinations, IOPS uses Gaussian Process optimization to find the optimal configuration in just 20 tests. That's a 90% reduction in execution time and compute resources.

**Intelligent Caching**: Ran some tests already? IOPS remembers. It won't re-run tests with identical parameters. Change one thing, re-run with `--use_cache`, and only the new configurations get tested.

**Budget Control**: Set a core-hours limit and IOPS stops when you hit it. No more accidentally burning through your allocation.

**Automatic Reports**: Rich HTML reports with interactive Plotly graphs, statistical analysis, Pareto frontiers, and best configurations automatically identified. No more manual graph generation.

---

## The Evolution

IOPS started as an IOR-specific automation tool and evolved into a general-purpose benchmark orchestration framework:

- ✅ **Originally**: IOR-specific, bash scripts, manual everything
- ✅ **Version 0.x**: Python automation, multi-round testing
- ✅ **Version 1.0**: Generic YAML framework, Bayesian optimization, SLURM integration, interactive reports, setup wizard

Now you can use IOPS for any benchmark, not just IOR: LAMMPS, GROMACS, or your custom I/O application.

---

## Quick Start

### Installation

```bash
# Clone the repo
git clone https://gitlab.inria.fr/lgouveia/iops.git
cd iops

# Install dependencies
pip install -r requirements.txt
pip install -e .

# Verify it works
iops --version
```

### Create Your First Benchmark

Use the interactive wizard:

```bash
iops --generate_setup
```

The wizard will ask you questions like "What do you want to benchmark?" and "Where do you want to run it?" and generate a proper YAML configuration for you. No YAML knowledge required.

Or copy an example:

```bash
cp docs/examples/example_simple.yaml my_benchmark.yaml
```

### Run It

```bash
# Preview what will happen (always do this first)
iops run my_benchmark.yaml --dry-run

# Actually run it
iops run my_benchmark.yaml

# With budget control (for SLURM)
iops run my_benchmark.yaml --max-core-hours 500
```

### Get Beautiful Reports

```bash
iops analyze /path/to/workdir/run_001
```

Opens an HTML report with everything you need: best configurations, interactive plots, statistics, execution time, core-hours consumed.

---

## Understanding How It Works

### Core Concepts

**Variables**: Things you want to vary
```yaml
vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [4, 8, 16, 32]
```

**Commands**: What to run (with Jinja2 templating)
```yaml
command:
  template: "ior -w -b {{ block_size }}mb -o /output"
```

**Metrics**: What to measure
```yaml
metrics:
  - name: bwMiB  # Bandwidth in MiB/s
```

**Search Methods**:
- **exhaustive**: Test everything (safe, thorough, slow)
- **bayesian**: Use machine learning to find optima (fast, efficient, smart)
- **random**: Random sampling (useful for statistical analysis)

### Example Configuration

Here's a real, working example:

```yaml
benchmark:
  name: "My IOR Study"
  workdir: "./workdir"
  executor: "local"  # or "slurm" for clusters
  search_method: "bayesian"

  bayesian_config:
    target_metric: "bwMiB"
    objective: "maximize"
    n_iterations: 20

vars:
  processes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4, 8]

  block_size_mb:
    type: int
    sweep:
      mode: list
      values: [1, 4, 16]

command:
  template: >
    ior -w -b {{ block_size_mb }}mb -t 1mb
    -O summaryFile={{ output_file }}
    -O summaryFormat=JSON

scripts:
  - name: "ior"
    parser:
      file: "{{ output_file }}"
      metrics:
        - name: bwMiB
      parser_script: scripts/ior_parser.py

output:
  sink:
    type: sqlite
    path: "{{ workdir }}/results.db"
```

### What Happens When You Run This?

1. **Planning**: IOPS generates execution instances for your parameter combinations
2. **Execution**: Runs tests (locally or submits SLURM jobs)
3. **Monitoring**: Tracks job status, handles failures gracefully
4. **Parsing**: Extracts metrics from output files
5. **Storage**: Saves results to CSV/SQLite/Parquet
6. **Analysis**: Generates HTML reports with plots and statistics

All automatic. All reproducible. All tracked.

---

## SLURM Integration

IOPS provides native SLURM support:

```yaml
benchmark:
  executor: "slurm"
  max_core_hours: 1000
  cores_expr: "{{ nodes * processes_per_node }}"

scripts:
  - name: "benchmark"
    submit: "sbatch"
    script_template: |
      #!/bin/bash
      #SBATCH --nodes={{ nodes }}
      #SBATCH --ntasks-per-node={{ processes_per_node }}
      #SBATCH --time=01:00:00
      #SBATCH --exclusive

      module load mpi/openmpi
      {{ command.template }}
```

Features:
- Automatic job submission and monitoring
- Budget tracking (core-hours limits)
- Signal handling (Ctrl+C cancels all jobs)
- Multi-node allocation
- Job status tracking without sacct

---

## Examples

Check `docs/examples/` for real, working examples:

| Example | What It Does | Why You'd Use It |
|---------|--------------|------------------|
| `example_simple.yaml` | Basic IOR benchmark | Learning IOPS |
| `example_bayesian.yaml` | Bayesian optimization | Finding optima fast |
| `example_plafrim.yaml` | Multi-node SLURM | Cluster performance studies |
| `example_plafrim_bayesian.yaml` | Cluster + Bayesian | Optimizing HPC apps efficiently |

Each example is documented and ready to run.

---

## Advanced Features

### Multi-Round Execution

Test in stages, carry best results forward:

```yaml
rounds:
  - name: "warmup"
    repetitions: 1
    vars:
      processes: [4]

  - name: "main"
    repetitions: 5
    vars:
      processes: [1, 2, 4, 8, 16]
```

### Custom Parsers

Extract metrics from any output format:

```python
# my_parser.py
def parse(file_path):
    with open(file_path) as f:
        data = json.load(f)

    return {
        'bandwidth': data['results']['bw'],
        'latency': data['results']['lat']
    }
```

### Caching System

Avoid redundant tests:

```bash
# First run - executes everything
iops run config.yaml

# Second run - reuses cached results
iops run config.yaml --use_cache
```

### Budget Management

Never exceed your allocation:

```yaml
benchmark:
  max_core_hours: 500
  cores_expr: "{{ nodes * ppn }}"
```

```bash
iops run config.yaml --max-core-hours 1000  # Override from CLI
```

---

## Analysis Reports: What You Get

After running, `iops analyze` generates reports with:

### Summary Statistics
- Total tests, execution time, core-hours consumed
- Variable ranges, metric distributions

### Best Configurations
- Top 5 parameter combinations per metric
- Statistical confidence (mean, std, sample count)
- Actual commands for reproducibility

### Interactive Visualizations
- Parameter sweep heatmaps
- Metric evolution over iterations
- Pareto frontiers for multi-objective optimization
- Bayesian evolution plots (exploration vs exploitation)

### Real Example Output:
```
Execution Overview
┌────────────────────────────┬──────────────┐
│ Total Tests                │ 60           │
│ Total Execution Time       │ 2h 15m 30s   │
│ Total Core-Hours           │ 1250.50      │
│ Average Cores per Test     │ 32.0         │
└────────────────────────────┴──────────────┘

Best Configuration for bwMiB
┌──────┬────────┬─────────────────┬──────────────┐
│ Rank │ Nodes  │ Processes/Node  │ bwMiB (mean) │
├──────┼────────┼─────────────────┼──────────────┤
│  1   │ 32     │ 16              │ 45234.2      │
│  2   │ 16     │ 16              │ 38901.7      │
│  3   │ 32     │ 8               │ 35678.3      │
└──────┴────────┴─────────────────┴──────────────┘
```

---

## Why Should You Care About All This?

Three reasons:

1. **Tune Your Applications**: Find the parameters that give you maximum I/O performance
2. **Validate Your System**: Ensure your cluster delivers expected performance
3. **Identify Bottlenecks**: Discover misconfigured file systems, network issues, or resource contention

Back to that paper we mentioned earlier—we found configuration problems that were limiting our cluster's performance. IOPS helps you find those problems automatically.

---

## Technical Architecture

### Architecture

```
iops/
├── config/         # YAML parsing and validation
├── execution/      # Test orchestration
│   ├── planner.py     # Search strategies (exhaustive, Bayesian)
│   ├── executors/     # Local and SLURM execution
│   └── cache.py       # Result caching
├── reporting/      # HTML report generation
└── setup/          # Interactive wizard
```

### Key Design Decisions

**Lazy Rendering**: Variables are templates until needed, allowing dynamic modification

**Jinja2 Everywhere**: Commands, scripts, file paths—all support `{{ variable }}` syntax

**Registry Pattern**: Executors and planners register themselves, easy to extend

**Reproducibility First**: Every run saves metadata, configurations, and provenance

### Extending IOPS

Want to add a new executor? Easy:

```python
@BaseExecutor.register("my_executor")
class MyExecutor(BaseExecutor):
    def submit(self, test):
        # Your submission logic
        pass

    def wait_and_collect(self, test):
        # Your collection logic
        pass
```

Same for planners, parsers, output formats—everything is pluggable.

---

## Command-Line Reference

```bash
# Run benchmark
iops run <config.yaml> [options]

# Options:
  --dry-run              Preview execution without running
  --use_cache            Reuse results from previous runs
  --max-core-hours N     Budget limit (stops after N core-hours)
  --estimated-time N     Time estimate per test (seconds)
  --log_level LEVEL      Logging verbosity (DEBUG, INFO, WARNING)

# Generate report
iops analyze <workdir>

# Interactive setup wizard
iops --generate_setup [output.yaml]

# Show version
iops --version
```

---

## Detailed Installation

### Prerequisites

- Python 3.10+
- For IOR benchmarks: MPI, IOR compiled and in PATH
- For SLURM: Access to a cluster with SLURM scheduler

### Install from GitLab

```bash
git clone https://gitlab.inria.fr/lgouveia/iops.git
cd iops
pip install -r requirements.txt
pip install -e .
```

### Verify Installation

```bash
iops --version  # Should show: IOPS Tool v1.0.0
```

### Optional: Conda Environment

```bash
conda env create -f environment.yml
conda activate iops_env
pip install -e .
```

---

## The Tools Folder (Legacy Utilities)

The `tools/` directory contains utilities from our original research:

- `code_shooter.py`: Generate randomized test sequences
- `hourglass.py`: Temporal spacing for test repetitions
- `ior_2_csv.py`: Process IOR outputs to CSV
- `file_tracker.py`: Monitor file attributes on BeeGFS

These were developed for [the paper](https://inria.hal.science/hal-03753813/) and are kept for backward compatibility. For new work, use the main IOPS framework.

