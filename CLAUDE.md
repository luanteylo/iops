# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

IOPS (I/O Performance Suite) is a generic benchmark orchestration framework that automates the generation, execution, and analysis of parametric benchmark experiments. Instead of writing individual job scripts, users define a YAML configuration describing:
- Variables to sweep (with ranges or lists)
- Command templates (using Jinja2)
- Execution scripts and parsing logic
- Output formats (CSV, Parquet, SQLite)

The framework generates execution instances for all parameter combinations, manages job submission (local or SLURM), parses results, and stores outputs.

## Common Development Commands

### Installation
```bash
# Install in development mode
pip install -e .

# Install dependencies
pip install -r requirements.txt
```

### Running the Tool
```bash
# Run with a configuration file
iops setup.yaml

# Or via python module
python -m iops.main setup.yaml

# Check configuration validity
iops setup.yaml --check_setup

# Show version
iops --version

# Enable verbose logging
iops setup.yaml --log_level DEBUG --log_terminal
```

### Testing
```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_main.py

# Run with verbose output
pytest -v tests/

# Run specific test
pytest tests/test_main.py::test_function_name
```

## High-Level Architecture

### Core Flow (from main.py)

1. **Configuration Loading** (`config/loader.py` and `config/models.py`):
   - Parses YAML configuration file
   - Validates benchmark, vars, command, scripts, output sections
   - Supports "rounds" for multi-stage optimization workflows
   - Creates working directory structure: `<workdir>/run_NNN/runs/` and `<workdir>/run_NNN/logs/`

2. **Execution Matrix Building** (`execution/matrix.py`):
   - Generates Cartesian product of swept variables
   - Each `ExecutionInstance` contains templates, NOT rendered values
   - All rendering is lazy via `@property` (allows runtime modification by planner)
   - Supports derived variables with expressions (Python or Jinja2)
   - Handles rounds with per-round variable sweeps and fixed overrides

3. **Planning** (`execution/planner.py`):
   - `BasePlanner` defines the test selection strategy
   - `Exhaustive` planner: sweeps all parameter combinations
   - Supports multiple rounds with best-result propagation
   - Random interleaving of repetitions for statistical robustness

4. **Execution** (`execution/executors/`):
   - `BaseExecutor` provides abstract interface for job submission
   - `LocalExecutor`: runs jobs locally using subprocess
   - `SlurmExecutor`: submits jobs via SLURM, polls status with squeue
   - Captures stdout/stderr, tracks job status, handles failures
   - Calls parser after successful execution

5. **Parsing** (`results/parser.py`):
   - Executes user-defined `parse()` function from YAML
   - Validates returned metrics match expected names
   - Returns dict with metrics for storage

6. **Output Writing** (`results/writer.py`):
   - Flattens nested execution data (vars, metadata, metrics, benchmark info)
   - Applies include/exclude field filters
   - Supports schema evolution for CSV/Parquet
   - Writes to CSV, Parquet, or SQLite

### Key Design Patterns

**Lazy Rendering**:
`ExecutionInstance` stores templates, not rendered values. Properties like `command`, `env`, `script_text`, and `vars` are rendered on-access using current state. This allows the planner to modify `base_vars` or `metadata` at runtime without regenerating instances.

**Jinja2 Context**:
Available in all templates:
- `{{ execution_id }}` - unique ID for each execution
- `{{ repetition }}` - current repetition number (1-based)
- `{{ execution_dir }}` - per-execution working directory
- `{{ workdir }}` - base working directory
- `{{ vars.* }}` - all variables (swept and derived)
- `{{ metadata.* }}` - runtime metadata
- `{{ command.template }}` - rendered command
- `{{ round_name }}`, `{{ round_index }}` - round information (if using rounds)

**Registry Pattern**:
Planners and Executors use class-level registries with decorators:
```python
@BasePlanner.register("exhaustive")
class Exhaustive(BasePlanner):
    ...
```
This allows selecting implementations by name from YAML config.

### File Organization

```
iops/
├── main.py                     # Entry point, CLI argument parsing
├── logger.py                   # Logging setup and HasLogger mixin
│
├── config/                     # Configuration management
│   ├── models.py               # Data models (BenchmarkConfig, VarConfig, etc.)
│   ├── loader.py               # YAML loading and validation
│   └── legacy/                 # Legacy IOR-specific config (not used by generic YAML)
│       ├── config_loader.py
│       └── file_utils.py
│
├── execution/                  # Execution engine
│   ├── matrix.py               # ExecutionInstance and matrix generation
│   ├── planner.py              # Test selection strategies (exhaustive, etc.)
│   ├── runner.py               # Main orchestrator (IOPSRunner)
│   └── executors/              # Execution backends
│       └── __init__.py         # BaseExecutor, LocalExecutor, SlurmExecutor
│
├── results/                    # Results processing
│   ├── parser.py               # Metric parsing from user scripts
│   ├── validation.py           # AST validation for parser scripts
│   └── writer.py               # Result serialization (CSV/Parquet/SQLite)
│
└── templates/                  # Jinja2 templates for job scripts
```

### Variable Types in YAML

**Swept variables** (varies across executions):
```yaml
vars:
  processes_per_node:
    type: int
    sweep:
      mode: list
      values: [8, 16, 32]
```

**Derived variables** (computed from other vars):
```yaml
vars:
  block_size_mb:
    type: int
    expr: "{{ volume_size_gb * 1024 / processes_per_node }}"
```

Derived vars can use:
- Jinja2 syntax: `"{{ var1 + var2 }}"`
- Python expressions: `"var1 * 2 + var2"`
- Functions: `min()`, `max()`, `round()`, `floor()`, `ceil()`

### Rounds Feature

Rounds enable multi-stage optimization:
```yaml
rounds:
  - name: "optimize_nodes"
    sweep_vars: ["nodes"]
    fixed_overrides:
      processes_per_node: 16
    search:
      metric: "bwMiB"
      objective: "max"
    repetitions: 3
```

Best result from each round propagates as defaults to the next round.

### Executor Status Values

Defined in `BaseExecutor`:
- `SUCCEEDED`: Job completed successfully
- `FAILED`: Job submitted but failed
- `RUNNING`: Currently executing
- `PENDING`: Queued but not running
- `ERROR`: Error before submission
- `UNKNOWN`: Status cannot be determined

### Output Field Naming

Flattened output columns follow dot notation:
- `benchmark.name`, `benchmark.description`
- `execution.execution_id`, `execution.repetition`
- `round.name`, `round.index`
- `vars.<varname>` (e.g., `vars.processes_per_node`)
- `metadata.<key>` (e.g., `metadata.operation`)
- `metrics.<metricname>` (e.g., `metrics.bwMiB`)

Use `include` or `exclude` in YAML to filter output fields.

## Important Implementation Notes

1. **Legacy code in `config/legacy/`**: The files `config_loader.py` and `file_utils.py` are legacy modules for the old IOR-specific configuration format. The new generic YAML format uses `config/loader.py`, `config/models.py`, and `execution/matrix.py`. The legacy code is kept for backwards compatibility but should not be modified.

2. **Parser scripts must define `parse(file_path: str) -> dict`**: The function name and signature are validated at config load time using AST parsing (no execution).

3. **SLURM executor does not use sacct or sbatch --wait**: Status tracking uses `squeue` polling and `scontrol show job` for finalization. Falls back to parser output existence if job ages out of SLURM records.

4. **Repetitions are randomly interleaved**: The exhaustive planner randomly selects which test+repetition to run next, improving statistical validity when jobs have variable runtime.

5. **Schema evolution for CSV/Parquet**: If new columns appear during append, the entire file is rewritten with the extended schema. Old rows get `None` for new columns.

6. **Working directory structure**:
   ```
   <workdir>/
   ├── run_001/
   │   ├── runs/
   │   │   ├── round_01_name/
   │   │   │   └── exec_0001/
   │   │   │       └── repetition_001/
   │   │   │           ├── run_ior.sh
   │   │   │           ├── post_ior.sh
   │   │   │           ├── stdout
   │   │   │           └── stderr
   │   └── logs/
   └── run_002/
       ...
   ```

7. **Jinja2 strict mode**: Templates use `StrictUndefined`, so referencing undefined variables raises errors immediately rather than silently producing empty strings.

## Configuration Validation

When adding new features to the YAML format:
- Add dataclass fields in `config/models.py`
- Add parsing logic in `config/loader.py` `load_generic_config()` function
- Add validation in `config/loader.py` `validate_generic_config()` function
- Update `_collect_allowed_output_fields()` if fields are exposed in output
- Test with `--check_setup` flag

## Debugging Tips

- Use `--log_level DEBUG --log_terminal` to see detailed execution flow
- Check `<workdir>/run_NNN/runs/*/repetition_*/stdout` and `stderr` for job output
- Enable `test.describe()` output by setting log level to DEBUG (shows full rendered templates)
- Use `execution_id` in file paths to avoid collisions: `"{{ execution_dir }}/output_{{ execution_id }}.dat"`
