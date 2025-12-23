---
title: "Parameter Constraints"
---


This example demonstrates parameter constraint validation to filter invalid configurations before execution.

## Overview

Constraints prevent wasted time on invalid parameter combinations. For example, in IOR benchmarks, the block size must be a multiple of the transfer size. IOPS can validate these relationships and filter invalid tests automatically.

## Configuration

```yaml title="example_with_constraints.yaml"
benchmark:
  name: "IOR with Constraints"
  workdir: "./workdir_constraints"
  executor: "local"
  search_method: "exhaustive"
  repetitions: 1

vars:
  block_size:
    type: int
    sweep:
      mode: list
      values: [4, 8, 16, 32, 64]

  transfer_size:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4, 8]

  num_processes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4]

# Constraint validation - placed right after vars
constraints:
  # Ensure block size is multiple of transfer size
  - name: "block_transfer_alignment"
    rule: "block_size % transfer_size == 0"
    violation_policy: "skip"
    description: "Block size must be a multiple of transfer size"

  # Transfer size cannot exceed block size
  - name: "transfer_size_limit"
    rule: "transfer_size <= block_size"
    violation_policy: "skip"

  # Warn about small total sizes
  - name: "reasonable_total_size"
    rule: "block_size * num_processes >= 8"
    violation_policy: "warn"
    description: "Total data size should be at least 8MB"

command:
  template: "echo 'Running with block_size={{ block_size }}, transfer_size={{ transfer_size }}, processes={{ num_processes }}'"

scripts:
  - name: "test"
    submit: "bash"
    script_template: |
      #!/bin/bash
      {{ command.template }}

    parser:
      file: "{{ execution_dir }}/stdout"
      metrics:
        - name: block_size
      parser_script: |
        def parse(file_path: str):
            return {"block_size": 1}

output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
```

## Running

```bash
# Dry-run to see constraint filtering
iops content/examples/example_with_constraints.yaml --dry-run

# Execute
iops content/examples/example_with_constraints.yaml
```

## What It Does

1. **Without constraints**: 5 block_size × 4 transfer_size × 3 processes = **60 combinations**
2. **With constraints**: Filters invalid combinations where:
   - `block_size % transfer_size != 0` (e.g., block_size=4, transfer_size=8)
   - `transfer_size > block_size`
3. **Result**: Only **valid combinations** are executed (57 tests in this case)
4. **Warnings**: Logs warnings for small total sizes without skipping tests

## Violation Policies

- **`skip`** (default): Filter out invalid combinations
- **`error`**: Fail immediately when constraint violated
- **`warn`**: Log warning but proceed with execution

## Example Output

```
Constraint filtering: 6 instances skipped, 4 warnings issued
Total tests after filtering: 57 (reduced from 60)
```

## Use Cases

**Parameter divisibility:**
```yaml
rule: "block_size % transfer_size == 0"
```

**Relationship validation:**
```yaml
rule: "transfer_size <= block_size"
```

**Resource limits:**
```yaml
rule: "nodes * processes_per_node <= 256"
```

**Complex conditions:**
```yaml
rule: "nodes > 1 and processes_per_node >= 4"
```

See `content/examples/example_with_constraints.yaml` for the full example.
