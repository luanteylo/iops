---
title: "Execution Matrix Generation"
weight: 30
---

*How IOPS builds the parameter space from your variable definitions*

---

## Overview

IOPS generates an **execution matrix** from your variable definitions; each row is a unique parameter combination to test.

```
vars:                          Execution Matrix:
  nodes: [1, 2]          →     | nodes | threads |
  threads: [4, 8]              |   1   |    4    |
                               |   1   |    8    |
                               |   2   |    4    |
                               |   2   |    8    |
```

---

## Variable Types

### Swept Variables

Variables with `sweep` define the parameter space. IOPS creates a **Cartesian product** of all swept variables.

```yaml
vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4]      # 3 values

  block_size:
    type: int
    sweep:
      mode: list
      values: [64, 128]      # 2 values
```

**Result:** 3 × 2 = 6 test combinations

### Derived Variables

Variables with `expr` are computed from other variables. They don't add to the matrix size.

```yaml
vars:
  nodes:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4]

  total_cores:
    type: int
    expr: "nodes * 8"        # Computed per execution
```

**Result:** 3 combinations (derived variable doesn't multiply)

---

## Conditional Variables

Use `when` and `default` to make a swept variable conditional on another variable. This eliminates redundant combinations.

### The Problem

Sweeping `use_compression: [true, false]` and `compression_level: [1, 5, 9]` unconditionally creates 2 × 3 = 6 combinations, but the 3 combinations with `use_compression: false` are redundant: the level is ignored, so they run the same test three times.

### The Solution

```yaml
vars:
  use_compression:
    type: bool
    sweep:
      mode: list
      values: [true, false]

  compression_level:
    type: int
    sweep:
      mode: list
      values: [1, 5, 9]
    when: "use_compression"   # Only sweep when true
    default: 0                # Use 0 when false
```

**With `when`:** 3 + 1 = 4 combinations

| use_compression | compression_level | Notes |
|-----------------|-------------------|-------|
| true | 1 | swept |
| true | 5 | swept |
| true | 9 | swept |
| false | 0 | default value |

### Step-by-Step Example

Consider a benchmark where `--threads` only matters when `--parallel` is enabled:

```yaml
vars:
  parallel:
    type: bool
    sweep:
      mode: list
      values: [true, false]

  threads:
    type: int
    sweep:
      mode: list
      values: [2, 4]
    when: "parallel"
    default: 1

command:
  template: "benchmark {% if parallel %}--parallel --threads={{ threads }}{% endif %}"
```

IOPS processes `parallel` first (no dependencies), then `threads`: for `parallel: true` the `when` condition holds and `[2, 4]` is swept; for `parallel: false` the default `1` is used.

#### Final Matrix

| parallel | threads | command |
|----------|---------|---------|
| true | 2 | `benchmark --parallel --threads=2` |
| true | 4 | `benchmark --parallel --threads=4` |
| false | 1 | `benchmark` |

**Without `when`:** 2 × 2 = 4 executions (2 redundant)
**With `when`:** 3 executions

---

## Matrix Size Calculation

| Scenario | Formula | Example |
|----------|---------|---------|
| All unconditional | Product of all sweep sizes | 3 × 2 × 4 = 24 |
| With conditional (simple) | Base + conditional expansions | 3 + 1 = 4 |
| Mixed | Depends on conditions | Varies |

Use `--dry-run` to see the actual matrix size before execution:

```bash
iops run config.yaml --dry-run
```

---

## Tips

1. **Start simple**: begin with unconditional variables, add `when` to reduce redundant tests
2. **Avoid circular dependencies**: variable A's `when` cannot reference variable B if B's `when` references A
3. **Use meaningful defaults**: the `default` value appears in results, so choose values that make sense for analysis
