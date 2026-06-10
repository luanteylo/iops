---
title: "Writing Scripts"
---

The `scripts[]` section of your YAML tells IOPS *how* to launch your benchmark. IOPS owns the parameter sweep and the result database; you own the shell script that actually runs the workload. This page is the practical guide to writing scripts; for the schema (every field, every option), see [YAML Schema Reference / scripts](../yaml-schema/#scripts).

---

## Why You Need a Script Template

IOPS does not assume anything about how your benchmark is launched: some benchmarks are a single executable, others need MPI launchers, module loads, environment setup, or pre-flight checks. The `script_template` is the bridge: a Jinja2-rendered shell script that IOPS materializes to disk and hands to the configured executor. Per test execution, IOPS writes it to `<execution_dir>/run_<name>.sh` so you can inspect (or rerun) exactly what was executed.

---

## How It Works

For each test execution, IOPS goes through this sequence:

1. **Resolve variables** for the current execution (sweep vars, derived vars, conditional vars)
2. **Render input files** declared in `inputs:` (see [Generating Input Files](#generating-input-files))
3. **Render the script template** with the full execution context
4. **Inject IOPS helper scripts** (system probe, resource sampler, exit handler) if enabled
5. **Write the script** to `<execution_dir>/repetition_NNN/run_<name>.sh`
6. **Submit it** with the executor (`bash` locally, `sbatch` on SLURM)
7. **Wait for completion**, capture `stdout` / `stderr`
8. **Run the parser** (and the optional `post.script`)

Each repetition gets its own folder with its own script, so different repetitions of the same test can be inspected independently.

---

## Configuration

Scripts live under the top-level `scripts:` list:

```yaml
scripts:
  - name: "ior_write"
    submit: "bash"                  # or "sbatch" for SLURM (defaults from executor)
    script_template: |
      #!/bin/bash
      module load mpi
      mpirun -np {{ ntasks }} {{ command.template }}
    inputs: []                      # optional, see "Generating Input Files"
    post: { script: ... }           # optional, post-execution hook
    parser: { ... }                 # see "Writing Parsers" guide
```

### Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Identifier used in generated filenames (`run_<name>.sh`). |
| `script_template` | Yes | Inline shell script body (Jinja2-rendered) or path to an external file. |
| `submit` | No | Submission command. Defaults to `bash` for local executor, `sbatch` for SLURM. |
| `inputs` | No | Declarative parameter files generated before the script runs. |
| `post` | No | Post-execution script (cleanup, summaries). |
| `parser` | Yes | How to extract metrics from output (see [Writing Parsers](../writing-parsers/)). |

You can define multiple scripts in the list; each one produces an independent test for every parameter combination.

---

## Writing the `script_template`

A script template is a regular shell script with `{{ var }}` placeholders. There is no required structure beyond what your benchmark needs, but a few habits make scripts easier to debug:

### Anatomy of a Good Script

```bash
#!/bin/bash

# 1. SLURM directives (only when executor: "slurm")
#SBATCH --nodes={{ nodes }}
#SBATCH --ntasks={{ ntasks }}
#SBATCH --time=01:00:00
#SBATCH --chdir={{ execution_dir }}
#SBATCH -o batch%j.out
#SBATCH -e batch%j.err

# 2. Fail fast
set -euo pipefail

# 3. Environment
module purge
module load mpi/openmpi/4.1
export OMP_NUM_THREADS={{ processes_per_node }}

# 4. Logging
echo "=== Execution {{ execution_id }} rep {{ repetition }}/{{ repetitions }} ==="
echo "Nodes: $SLURM_JOB_NUM_NODES, Tasks: $SLURM_NTASKS"

# 5. Run the benchmark
mpirun -np {{ ntasks }} {{ command.template }}
```

This layout works well because SLURM directives must come first (parsed by `sbatch` before anything runs), `set -euo pipefail` catches failures early, explicit modules and env vars make the environment reproducible, and logging the resolved parameters helps when a specific test misbehaves.

### Rules

- The shell language is yours to choose (`#!/bin/bash`, `#!/bin/zsh`, `#!/usr/bin/env python3`, anything `submit` can execute)
- `{{ }}` placeholders are rendered **before** the script is written; the running shell never sees Jinja2
- Lines starting with `#SBATCH` are ignored by `bash` but parsed by `sbatch`, so you can leave them in a local-executor script if you sometimes switch executors
- The script's working directory at runtime is **not** guaranteed to be the execution directory; use `{{ execution_dir }}` for absolute paths instead of relying on `cwd`

---

## Context Variables

The full execution context is injected into the Jinja2 template: all declared `vars`, `execution_id`, `repetition`, `repetitions`, `execution_dir` (per-repetition output directory, where `run_*.sh` lives), `workdir`, `log_dir`, `os_env`, `command.template` (the rendered benchmark command), `command_env`, `command_labels`, and `inputs` (`{{ inputs.<name>.path }}`, see below).

The complete table with examples lives in [Templating and Context / `scripts[].script_template`](../templating-and-context/#scriptsscript_template); for Jinja2 syntax itself (conditionals, loops, filters), see [Templating and Context / Jinja2 Syntax](../templating-and-context/#jinja2-syntax-reference).

---

## Including the Benchmark Command

`command.template` is the benchmark invocation defined separately under `command:`. Reusing it inside the script keeps the command in one place:

```yaml
command:
  template: "ior -w -b {{ block_size_mb }}mb -t 1mb -o {{ execution_dir }}/data.ior"

scripts:
  - name: "ior_write"
    script_template: |
      #!/bin/bash
      module load mpi ior
      mpirun -np {{ ntasks }} {{ command.template }}
```

`{{ command.template }}` expands to the fully rendered string. Do **not** repeat arguments that are already in the template; doing so usually duplicates flags and produces confusing failures.

---

## Generating Input Files

Many benchmarks read their parameters from a config file rather than the command line. The `inputs:` field generates these files at preparation time, alongside the script:

```yaml
scripts:
  - name: "io500"
    inputs:
      - name: config_ini
        path: "{{ execution_dir }}/config.ini"
        template: |
          [global]
          datadir = {{ os_env.SCRATCH }}/io500_data
          api = POSIX

          [ior-easy]
          blockSize = {{ block_size_gb }}g
          transferSize = 2m
    script_template: |
      #!/bin/bash
      ./io500 {{ inputs.config_ini.path }}
```

The file is written **before** the script runs and stays on disk even if the script aborts, so you can always check what input a particular execution actually received. See [YAML Schema / inputs](../yaml-schema/#scripts) for the full reference.

---

## Post-Execution Scripts

`post.script` runs after the main script finishes (success or failure). Use it for cleanup, summaries, or moving result files out of `$TMPDIR`:

```yaml
scripts:
  - name: "ior"
    script_template: |
      #!/bin/bash
      ior -w -o $TMPDIR/data.ior > {{ execution_dir }}/summary.txt
    post:
      script: |
        #!/bin/bash
        echo "Cleanup at $(date)"
        rm -f $TMPDIR/data.ior
        ls -lh {{ execution_dir }}
```

The post script receives the same Jinja2 context as `script_template`, including `{{ inputs.<name>.path }}` references, and runs with the same executor as the main script.

---

## External Script Files

For long or shared scripts, point `script_template` at a file instead of inlining the body:

```yaml
scripts:
  - name: "ior"
    script_template: ./scripts/run_ior.sh
    parser: { ... }
```

The file is resolved relative to the YAML, loaded at config-load time, then rendered with Jinja2 the same way an inline string would be. The same external-file shortcut works for `post.script` and `parser.parser_script`.

---

## Examples

### Local Executor: Single Binary

```yaml
benchmark:
  executor: "local"
scripts:
  - name: "stream"
    script_template: |
      #!/bin/bash
      set -euo pipefail
      export OMP_NUM_THREADS={{ threads }}
      ./stream_c.exe > {{ execution_dir }}/stream.out
    parser:
      file: "{{ execution_dir }}/stream.out"
      metrics: [{ name: bandwidth }]
      parser_script: |
        import re
        def parse(file_path):
            content = open(file_path).read()
            return {"bandwidth": float(re.search(r"Triad:\s+([\d.]+)", content).group(1))}
```

For a SLURM MPI job, see the [anatomy script above](#anatomy-of-a-good-script): set `executor: "slurm"` and keep the `#SBATCH` directives.

### Conditional Directives (Different Resource Tiers)

```yaml
scripts:
  - name: "ior"
    script_template: |
      #!/bin/bash
      #SBATCH --nodes={{ nodes }}
      {% if nodes > 16 %}
      #SBATCH --time=04:00:00
      #SBATCH --partition=large
      {% else %}
      #SBATCH --time=01:00:00
      #SBATCH --partition=batch
      {% endif %}

      srun {{ command.template }}
```

Note the required spaces inside `{% %}`: `{%if%}` raises a `TemplateSyntaxError`.

### Reusing a Script Across Machines

A single `script_template` plus a `machines:` block lets the same study run on a laptop and a cluster (see [Machine Overrides](../machines/)):

```yaml
scripts:
  - name: "ior"
    script_template: |
      #!/bin/bash
      module load mpi ior
      mpirun -np {{ ntasks }} {{ command.template }}

machines:
  laptop:
    benchmark:
      executor: "local"
      repetitions: 1

  cluster:
    benchmark:
      executor: "slurm"
      repetitions: 5
    scripts:
      - name: "ior"        # override merges by name
        script_template: |
          #!/bin/bash
          #SBATCH --nodes={{ nodes }}
          #SBATCH --time=01:00:00
          module load mpi ior
          srun {{ command.template }}
```

---

## Single-Allocation Mode

When `slurm_options.allocation.mode: "single"`, IOPS submits **one** SLURM job and runs every test inside that allocation via `srun --jobid=<id> --overlap`. The implications for `script_template`:

- **Drop the `#SBATCH` directives**: resources are controlled by `slurm_options.allocation.allocation_script`
- **Load modules inside the script**: each `srun` starts a fresh shell
- For MPI programs, use `srun` directly with the variables (no `mpirun` wrapper needed)

See [Single-Allocation Mode](../single-allocation-mode/) for the full picture and a complete example.

---

## Where Script Artifacts Go

After execution, every test directory contains a complete record of what ran:

```
<workdir>/run_001/runs/exec_0001/
├── __iops_params.json            # Resolved parameter values for this execution
└── repetition_001/
    ├── run_<name>.sh             # The rendered main script
    ├── post_<name>.sh            # The rendered post script (if any)
    ├── <files from inputs:>      # Input files generated by the inputs: block
    ├── stdout                    # Captured script stdout
    ├── stderr                    # Captured script stderr
    ├── batch<jobid>.out          # SLURM stdout (SLURM only)
    ├── batch<jobid>.err          # SLURM stderr (SLURM only)
    ├── __iops_status.json        # Execution status (SUCCEEDED, FAILED, ...)
    └── __iops_sysinfo.json       # System info (if system_snapshot probe is on)
```

`run_<name>.sh` is the exact, fully rendered script that ran (no `{{ }}` placeholders). You can rerun it by hand to reproduce a failure: `cd repetition_001 && bash run_<name>.sh`.

---

## Debugging

| Symptom | Where to look | Common cause |
|---------|---------------|--------------|
| `TemplateSyntaxError` on load | Loader error message | Missing space in `{% if cond %}`, mismatched `{% endif %}` |
| `UndefinedError: 'X' is undefined` | Loader or runtime error | Variable not in `vars:`, or referenced before it's available |
| Script not executable / wrong shell | `stderr`, `batch*.err` | Missing or wrong shebang; `submit:` mismatched with shebang |
| SLURM `#SBATCH` ignored | Job submitted but no resource limits | Lines before the shebang, or extra blank lines splitting the directive block |
| Job runs but writes nothing | `stderr`, `__iops_status.json` | `set -e` not enabled; module load silently failed |
| Parameters look wrong | `__iops_params.json`, top of `run_<name>.sh` | Derived variable expression has the wrong precedence |
| Input file missing at runtime | `<execution_dir>/repetition_001/` | Forgot `inputs:` entry, or `path:` rendered to an unexpected location |

A few practical commands:

```bash
# Validate the config without running anything
iops check my_study.yaml

# Show what each test would do (resolved variables, command, cache lookups)
iops run my_study.yaml --dry-run

# Inspect failed executions
iops find ./workdir/run_001 --status FAILED

# Rerun a single failed test
cd ./workdir/run_001/runs/exec_0017/repetition_001 && bash run_ior.sh
```

---

## Tips

- **Start with `iops check` and `--dry-run`.** They catch most YAML and template mistakes before any job goes out.
- **Use `set -euo pipefail`.** A silent module-load failure that leaves the benchmark unrun is far more painful than a loud error.
- **Capture parameters at the top of the script** (`echo "nodes={{ nodes }} ppn={{ processes_per_node }}"`) so the values are right there when you scan logs later.
- **Use absolute paths via `{{ execution_dir }}`.** Don't rely on the script's working directory being anywhere in particular.
- **Don't put `iops`-specific logic in the script.** IOPS injects what it needs (probes, samplers) automatically.
- **Externalize long scripts.** Past ~30 lines, move the body into a `.sh` file (`script_template: ./scripts/run.sh`) for easier linting and testing.
