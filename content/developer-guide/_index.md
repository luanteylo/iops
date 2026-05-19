---
title: "Developer Guide"
weight: 80
---

This section is aimed at contributors and developers who need to understand how
IOPS is built, where to find things, and how to extend it. It complements the
[User Guide](/user-guide/), which covers YAML configuration and day-to-day
usage.

## Contents

- [Architecture]({{< relref "architecture" >}}) - High-level mental model and package map
- [CLI Overview]({{< relref "cli-overview" >}}) - Subcommand dispatch and entry points
- [Execution Loop]({{< relref "execution-loop" >}}) - Runner, Planner, and Executor architecture
- [Extension Points]({{< relref "extension-points" >}}) - How to add planners, executors, probes, and more
- [Probe System]({{< relref "probe-system" >}}) - System information collection mechanism
- [Data Sources]({{< relref "data-sources" >}}) - Where CLI commands get their data from
- [Memory Profiling]({{< relref "memory-profiling" >}}) - Diagnosing memory leaks in the runner
- [API Reference]({{< relref "api-reference" >}}) - Auto-generated reference from docstrings
