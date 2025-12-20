# IOPS YAML Examples

This directory contains example YAML configuration files demonstrating various IOPS features.

## Examples

### 1. Simple Local Execution (`01_simple_local.yaml`)

**Demonstrates:**
- Local execution without SLURM
- Basic parameter sweep (2 variables)
- CSV output
- Repetitions

**Use Case:** Quick local testing and development

**Command:**
```bash
# Create workdir first
mkdir -p /tmp/ior_simple

# Run benchmark
iops docs/yaml_examples/01_simple_local.yaml

# With cache
iops docs/yaml_examples/01_simple_local.yaml --use_cache
```

**Generates:** 3 processes × 2 block sizes × 2 repetitions = **12 executions**

---

### 2. SLURM Parameter Sweep (`02_slurm_sweep.yaml`)

**Demonstrates:**
- SLURM job submission
- Multi-dimensional parameter sweep
- Derived variables
- Execution caching with SQLite
- Parquet output with field filtering

**Use Case:** Production parameter sweeps on HPC clusters

**Command:**
```bash
# Set workdir (adjust to your cluster)
export WORKDIR=/scratch/$USER/ior_sweep
mkdir -p $WORKDIR

# Run benchmark
iops docs/yaml_examples/02_slurm_sweep.yaml

# Re-run with cache (skips completed tests)
iops docs/yaml_examples/02_slurm_sweep.yaml --use_cache
```

**Generates:** 3 nodes × 2 processes_per_node × 3 volumes × 3 repetitions = **54 executions**

---

### 3. Multi-Round Optimization (`03_multi_round_optimization.yaml`)

**Demonstrates:**
- Multi-round optimization workflow
- Progressive parameter refinement
- Round-specific configurations
- Result propagation between rounds
- SQLite output

**Use Case:** Automated parameter optimization (find best configuration)

**Workflow:**
1. **Round 1**: Find optimal nodes (sweep 4 values)
2. **Round 2**: With best nodes, find optimal processes_per_node (sweep 3 values)
3. **Round 3**: With best nodes+processes, find optimal volume_size (sweep 4 values)
4. **Round 4**: With all above optimal, find optimal stripe_count (sweep 3 values)

**Command:**
```bash
# Set workdir
export WORKDIR=/scratch/$USER/ior_optimization
mkdir -p $WORKDIR

# Run optimization
iops docs/yaml_examples/03_multi_round_optimization.yaml
```

**Generates:**
- Round 1: 4 nodes × 3 repetitions = 12 executions
- Round 2: 3 processes × 3 repetitions = 9 executions
- Round 3: 4 volumes × 3 repetitions = 12 executions
- Round 4: 3 stripes × 5 repetitions = 15 executions
- **Total: 48 executions** (instead of 4×3×4×3 = 144 without rounds!)

---

## Customizing Examples

### Changing Workdir

All examples use placeholders. Update to your environment:

```yaml
benchmark:
  workdir: "/path/to/your/workdir"
  sqlite_db: "/path/to/your/cache.db"
```

### Changing Parameters

Modify the `vars` section:

```yaml
vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4, 8, 16]  # Add more values
```

### Changing Executors

Switch between local and SLURM:

```yaml
benchmark:
  executor: "local"   # or "slurm"
```

## Validation

Check your YAML before running:

```bash
# Validates config without executing
iops your_config.yaml --check_setup
```

## Complete Documentation

See [YAML_FORMAT.md](../YAML_FORMAT.md) for complete reference.

## Tips

1. **Start small**: Begin with `01_simple_local.yaml` and modify incrementally
2. **Use cache**: Always set `sqlite_db` and use `--use_cache` for iterative development
3. **Test locally first**: Validate with `executor: local` before using SLURM
4. **Check logs**: Use `--log_level DEBUG` for detailed output
5. **Rounds for optimization**: Use multi-round workflows to reduce total executions
