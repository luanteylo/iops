---
title: "Design Philosophy"
---

Five design principles guide IOPS development. They explain why IOPS looks the way it does and what trade-offs were chosen.

## 1. One YAML to Rule Them All

A single, self-contained specification captures the complete benchmark lifecycle: workload definition, parameter space, run rules, environment, and validation criteria. You should never need a second file, a sidecar script, or a hidden environment variable to understand what a study does. The YAML is the source of truth.

**What this means in practice:**

- Sharing a study is sharing a YAML file; reviewing a study is reading one.
- Reproducing a study (months or years later) starts with that same YAML file.

## 2. Declarative First: Specify Before, Execute After

The YAML declares the complete intent of a campaign: what to measure, under which rules, with which environment, and how to validate the results. IOPS resolves the parameter space, validates the configuration, and renders all templates **before** running anything, which makes runs predictable, auditable, and easy to dry-run.

**What this means in practice:**

- `iops check config.yaml` validates without running.
- `iops run --dry-run` shows the full execution matrix before launching.
- Errors in the spec surface early, not midway through a 12-hour campaign.

## 3. Backward Compatibility by Default

Once a YAML file is valid under a given specification version, it will always be executable. Features that depend on fields introduced later are simply unavailable for older specifications, but all existing fields retain their semantics. So old configs keep working across upgrades, and studies remain reproducible long after they were authored.

When something must change, IOPS follows a **2 minor version deprecation cycle** with clear warnings and a migration path (see [Deprecations](deprecations) for the policy and active deprecations).

## 4. Lean Core, Opt-in Extras

`pip install iops-benchmark` ships only the minimum dependencies needed to run IOPS. Advanced features live behind optional extras, keeping the default install lightweight and minimizing dependency conflicts on clusters, where Python environments are often constrained.

**Available extras:**

| Extra | Enables |
|-------|---------|
| `bayesian` | Bayesian search planner (`scikit-optimize`) |
| `parquet` | Parquet output sink (`pyarrow`) |
| `watch` | Pretty terminal UI (`rich`) |
| `plots` | Static image export from reports (`kaleido`) |

```bash
pip install iops-benchmark                      # core only
pip install iops-benchmark[bayesian,parquet]    # selected extras
```

## 5. Plugin-Based Extensibility

IOPS uses a registry-based plugin architecture. New search strategies and execution backends are added by implementing a small interface and registering a decorator, without modifying the core engine:

```python
@BasePlanner.register("my_strategy")
class MyPlanner(BasePlanner):
    ...
```

Adding a new executor (e.g., for a new scheduler) is a local change, a new search strategy does not touch the runner, and third parties can ship plugins as separate packages.
