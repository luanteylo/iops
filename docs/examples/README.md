# IOPS Examples

This directory contains example configurations demonstrating various IOPS features and use cases.

---

## 📁 Example Files

### Basic Examples

#### `example_simple.yaml`
**Basic local IOR benchmark with exhaustive search**

- **Executor**: Local
- **Search Method**: Exhaustive
- **Variables**: `processes_per_node`, `volume_size_gb`
- **Metrics**: Write bandwidth (bwMiB)
- **Features**:
  - Simple parameter sweep
  - JSON output parsing
  - SQLite database output
  - Derived variables (block_size_mb)

**Use case**: Getting started with IOPS, testing I/O performance on a single machine

**Run it**:
```bash
cd /path/to/iops
iops docs/examples/example_simple.yaml
```

---

#### `example_simple_rounds.yaml`
**Multi-round optimization with staged execution**

- **Executor**: Local
- **Search Method**: Exhaustive (per round)
- **Rounds**: 2 stages
  1. Warmup round (1 repetition, processes=4)
  2. Main round (5 repetitions, processes=1-16)
- **Features**:
  - Multi-stage workflows
  - Different repetitions per round
  - Round-specific variable overrides

**Use case**: Staged benchmarking with warmup phase, progressive refinement

---

### Bayesian Optimization

#### `example_bayesian.yaml`
**Intelligent parameter search with Bayesian optimization**

- **Executor**: Local
- **Search Method**: Bayesian
- **Bayesian Config**:
  - Target metric: bwMiB
  - Objective: maximize
  - Initial points: 5 (random exploration)
  - Total iterations: 20
  - Acquisition: Expected Improvement (EI)
- **Variables**: `processes_per_node` (1-8), `volume_size_gb` (1, 4, 8)
- **Efficiency**: ~90% fewer tests than exhaustive (24 vs 240)

**Use case**: Finding optimal configurations quickly, reducing experimentation time

**Why use Bayesian?**
- Large parameter spaces (>50 combinations)
- Expensive tests (long runtime or high resource cost)
- Want to find "good enough" configurations without testing everything

---

### SLURM Cluster Examples

#### `example_plafrim.yaml`
**Multi-node SLURM execution with budget tracking**

- **Executor**: SLURM
- **Search Method**: Exhaustive
- **Variables**: `nodes` (4, 8, 32), `processes_per_node` (8), `ost_count` (BeeGFS paths)
- **Features**:
  - Multi-node job submission
  - Budget control (max_core_hours)
  - Core-hours tracking (cores_expr)
  - SLURM script generation
  - Automatic job monitoring
  - SLURM constraint targeting (bora nodes)

**Use case**: Systematic cluster performance studies, multi-node scaling analysis

**Budget Management**:
```yaml
benchmark:
  max_core_hours: 1000  # Stop after 1000 core-hours
  cores_expr: "{{ ntasks }}"  # Calculate cores from variables
```

---

#### `example_plafrim_bayesian.yaml`
**Cluster execution + Bayesian optimization (best of both worlds)**

- **Executor**: SLURM
- **Search Method**: Bayesian
- **Variables**: `nodes` (4-32), `processes_per_node` (4-16), `volume_size_gb` (16-128), `ost_number` (1-8)
- **Search Space**: 4×3×4×4 = 192 combinations
- **Bayesian Tests**: Only 20 configurations (10% sampling)
- **Total Runs**: 20 configs × 3 repetitions = 60 tests
- **Time Savings**: ~5 hours vs ~50 hours (exhaustive)

**Features**:
  - Intelligent multi-dimensional search
  - Automatic SLURM script generation
  - Budget tracking and enforcement
  - Evolution plots in reports
  - Convergence visualization

**Use case**: Optimizing complex HPC applications, finding best node/process/data size combinations

**When to use this**:
- Cluster resource costs are high
- Parameter space is large (>100 combinations)
- Tests are expensive (minutes to hours per test)
- You need actionable results quickly

---

## 🛠️ Support Files

### `scripts/`
Helper scripts for parsing and execution:

- **`ior_parser.py`**: Python script to extract metrics from IOR JSON output
- **`ior_plafrim_slurm.sh`**: SLURM job script template for PlaFRIM cluster

---

## 🚀 Quick Start Guide

### 1. Choose an Example

| If you want to... | Use this example |
|-------------------|------------------|
| Learn IOPS basics | `example_simple.yaml` |
| Test multi-round workflows | `example_simple_rounds.yaml` |
| Find optimal configs quickly | `example_bayesian.yaml` |
| Run on SLURM cluster | `example_plafrim.yaml` |
| Optimize cluster runs | `example_plafrim_bayesian.yaml` |

### 2. Customize for Your System

Edit the example to match your environment:

```yaml
benchmark:
  workdir: "/your/path/workdir"  # Where to store results
  executor: "local" or "slurm"   # Execution environment
```

For SLURM:
```yaml
scripts:
  - script_template: |
      #!/bin/bash
      #SBATCH --partition=YOUR_PARTITION
      #SBATCH --constraint=YOUR_CONSTRAINT
      ...
```

### 3. Run a Dry-Run First

```bash
iops docs/examples/example_simple.yaml --dry-run
```

This shows:
- How many tests will run
- Estimated execution time
- Core-hours consumption
- Budget analysis
- Sample test configurations

### 4. Execute the Benchmark

```bash
# Local execution
iops docs/examples/example_simple.yaml

# SLURM with budget control
iops docs/examples/example_plafrim.yaml --max-core-hours 500

# With caching
iops docs/examples/example_bayesian.yaml --use_cache
```

### 5. Generate Analysis Report

```bash
iops analyze /path/to/workdir/run_001
```

Opens an HTML report with:
- Best configurations found
- Interactive parameter plots
- Statistical analysis
- Execution time and core-hours
- (For Bayesian) Evolution and convergence plots

---

## 📊 Understanding the Output

### Directory Structure

```
workdir/
├── run_001/                      # First execution
│   ├── runs/                     # Execution directories
│   │   └── exec_0001/
│   │       └── repetition_001/
│   │           ├── run_script.sh  # Generated script
│   │           ├── stdout        # Job output
│   │           ├── stderr        # Error output
│   │           └── summary.json  # Parsed results
│   ├── logs/                     # Execution logs
│   └── run_metadata.json         # Metadata for reports
├── results.db                    # SQLite results (or .csv, .parquet)
└── analysis_report.html          # Generated report
```

### Results Files

Depending on `output.sink.type`:

**CSV** (`results.csv`):
```
vars.processes_per_node,vars.volume_size_gb,metrics.bwMiB,...
8,32,12345.67,...
```

**SQLite** (`results.db`):
```sql
SELECT vars.processes_per_node, metrics.bwMiB
FROM results
WHERE metrics.bwMiB > 10000;
```

**Parquet** (`results.parquet`):
- Columnar format for efficient analytics
- Use pandas, polars, or duckdb

---

## 💡 Tips and Best Practices

### Start Small
Begin with a few parameter values to verify the setup works:
```yaml
vars:
  processes:
    sweep:
      mode: list
      values: [4, 8]  # Start with 2 values
```

Then expand:
```yaml
      values: [1, 2, 4, 8, 16, 32]  # Full range
```

### Use Dry-Run
Always run with `--dry-run` first to check:
- Script generation works
- Variables are rendered correctly
- Budget estimates are reasonable

### Enable Caching
For iterative development:
```bash
iops config.yaml --use_cache
```

Reuses results when re-running with same parameters.

### Debug Mode
See detailed execution flow:
```bash
iops config.yaml --log_level DEBUG --log_terminal
```

### Budget Management
Set limits to avoid runaway costs:
```yaml
benchmark:
  max_core_hours: 1000  # Hard stop after 1000 core-hours
```

Override from CLI:
```bash
iops config.yaml --max-core-hours 500
```

---

## 🔧 Customizing Examples

### Changing Variables

**Add a new variable**:
```yaml
vars:
  my_new_var:
    type: int
    sweep:
      mode: list
      values: [10, 20, 30]
```

**Use it in command**:
```yaml
command:
  template: "my_app --threads {{ my_new_var }}"
```

### Custom Parsers

Replace `scripts/ior_parser.py` with your own:

```python
def parse(file_path):
    with open(file_path) as f:
        content = f.read()

    # Extract your metrics
    throughput = extract_throughput(content)
    latency = extract_latency(content)

    return {
        'throughput': throughput,
        'latency': latency
    }
```

### Different Output Formats

**CSV**:
```yaml
output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
```

**SQLite** (recommended for large datasets):
```yaml
output:
  sink:
    type: sqlite
    path: "{{ workdir }}/results.db"
    table: results
```

**Parquet** (best for analytics):
```yaml
output:
  sink:
    type: parquet
    path: "{{ workdir }}/results.parquet"
```

---

## 🆘 Troubleshooting

### Example doesn't run

1. **Check paths are correct**:
   ```bash
   cd /path/to/iops
   pwd  # Should be at repository root
   iops docs/examples/example_simple.yaml
   ```

2. **Verify workdir exists or can be created**:
   ```yaml
   workdir: "/tmp/iops_test"  # Use temp for testing
   ```

3. **Check script paths**:
   ```yaml
   parser_script: scripts/ior_parser.py  # Relative to example location
   ```

### SLURM jobs fail

1. **Check partition exists**:
   ```bash
   sinfo  # List available partitions
   ```

2. **Verify constraints**:
   ```bash
   sinfo -o "%N %f"  # List node features/constraints
   ```

3. **Test sbatch manually**:
   ```bash
   sbatch docs/examples/runs/exec_0001/repetition_001/run_script.sh
   ```

### Parsing errors

1. **Check output file exists**:
   ```bash
   ls docs/examples/runs/*/repetition_*/summary.json
   ```

2. **Test parser manually**:
   ```bash
   python docs/examples/scripts/ior_parser.py
   ```

3. **Enable debug logging**:
   ```bash
   iops config.yaml --log_level DEBUG
   ```

---

## 📚 Learn More

- **Main README**: [`../../README.md`](../../README.md) - Full documentation
- **YAML Format**: [`../YAML_FORMAT.md`](../YAML_FORMAT.md) - Complete specification
- **Caching**: [`../CACHE_USAGE.md`](../CACHE_USAGE.md) - Caching system details
- **Setup Wizard**: `iops --generate_setup` - Interactive configuration builder

---

## 🤝 Contributing Examples

Have a useful example? Please contribute!

1. Add your example YAML to this directory
2. Test it works: `iops docs/examples/your_example.yaml --dry-run`
3. Document it in this README
4. Submit a pull request

**Good examples**:
- Different applications (LAMMPS, GROMACS, custom codes)
- Interesting optimization strategies
- Real-world HPC workflows
- Novel use cases

---

**Happy benchmarking! 🚀**
