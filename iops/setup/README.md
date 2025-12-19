# IOPS Setup Wizard

Interactive wizard for creating IOPS benchmark configurations.

## Usage

```bash
# Start the wizard
iops --generate_setup

# Or specify output filename
iops --generate_setup my_benchmark.yaml
```

## Features

- **Template-based**: Choose from pre-built templates (IOR, MPI apps, custom scripts)
- **Step-by-step**: Guided questions for all configuration options
- **Intelligent**: Context-aware suggestions based on your choices
- **Validated**: Input validation at every step
- **Flexible**: Support for exhaustive, Bayesian, and random search strategies

## Workflow

1. **Choose Template** - Start from a template or from scratch
2. **Configure Basics** - Name, executor type, working directory
3. **Search Strategy** - Exhaustive, Bayesian optimization, or random
4. **Variables** - Define swept and derived parameters
5. **Command** - Specify the benchmark command template
6. **Scripts** - Configure execution scripts (SLURM or local)
7. **Metrics** - Define output parsing and metrics
8. **Output** - Choose output format (CSV, SQLite, Parquet)
9. **Advanced** - Repetitions, budget, caching options
10. **Review & Save** - Preview and save configuration

## Templates

### IOR Benchmark
Pre-configured for I/O performance testing with IOR:
- Suggests typical variables (processes_per_node, volume_size_gb, block_size_mb)
- Includes JSON output parsing
- Ready for SLURM execution

### MPI Application
Generic template for MPI applications:
- Node and process configuration
- Flexible for any MPI-based benchmark

### Custom Script
Minimal template for custom benchmarks:
- Bring your own script
- Configure metrics and parsing

## Examples

### Creating an IOR Benchmark

```
$ iops --generate_setup

[1/10] Benchmark Template
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
→ Choose a template:
  1. ior          - IOR Benchmark
  2. custom_script - Custom Script
  3. mpi_app      - MPI Application
  4. scratch      - Start from scratch
  Choice [1-4]: 1

✓ Using template: IOR Benchmark

[2/10] Benchmark Basics
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
→ Benchmark name [default: IOR Benchmark]: My IOR Study
→ Description (optional): Testing IOR on PlaFRIM cluster
→ Working directory [default: ./workdir]: /home/user/workdir
→ Executor type:
  1. local   - Run scripts locally
  2. slurm   - Submit to SLURM cluster
  Choice [1-2]: 2

...
```

### Creating a Bayesian Optimization Study

Select "bayesian" as the search strategy and the wizard will guide you through:
- Target metric to optimize
- Objective (maximize/minimize)
- Number of initial random points
- Total number of iterations
- Acquisition function

## Tips

- **Default values**: Press Enter to accept suggested defaults
- **Templates**: Start with a template and customize it
- **Variables**: Use Jinja2 syntax `{{ variable_name }}` in commands and scripts
- **Validation**: The wizard validates inputs as you type
- **Cancel**: Press Ctrl+C to cancel at any time
- **Review**: Always review the generated YAML before running

## Next Steps

After the wizard completes:

```bash
# Review the generated configuration
cat my_benchmark.yaml

# Test with dry-run
iops run my_benchmark.yaml --dry-run

# Execute the benchmark
iops run my_benchmark.yaml
```
