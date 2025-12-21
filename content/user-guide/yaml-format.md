---
title: "YAML Configuration Format"
---


This page provides a complete reference for the IOPS YAML configuration format.

For a comprehensive, detailed guide with all options and examples, see the full [YAML Format Reference](../reference/yaml-schema.md).

## Quick Overview

An IOPS configuration file has these main sections:

```yaml
benchmark:    # Global configuration
vars:         # Parameter definitions
command:      # Command template
scripts:      # Execution scripts and parsers
output:       # Output configuration
rounds:       # (Optional) Multi-round optimization
```

## Basic Example

```yaml
benchmark:
  name: "My Benchmark"
  workdir: "./workdir"
  executor: "local"
  repetitions: 3

vars:
  threads:
    type: int
    sweep:
      mode: list
      values: [1, 2, 4, 8]

command:
  template: "my_benchmark --threads {{ threads }}"

scripts:
  - name: "benchmark"
    submit: "bash"
    script_template: |
      #!/bin/bash
      {{ command.template }}

    parser:
      file: "{{ execution_dir }}/output.json"
      metrics:
        - name: throughput
      parser_script: |
        import json
        def parse(file_path: str):
            with open(file_path) as f:
                data = json.load(f)
            return {"throughput": data["throughput"]}

output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
```

## Next Steps

- See the complete [YAML Schema Reference](../reference/yaml-schema.md)
- Learn about [Search Methods](search-methods.md)
- Explore [Execution Backends](execution-backends.md)
- Understand [Result Caching](caching.md)
