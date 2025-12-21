# Simple Local Example

This example demonstrates basic IOPS usage with local execution.

## Configuration

```yaml title="example_simple.yaml"
benchmark:
  name: "Simple Example"
  workdir: "./workdir"
  executor: "local"
  search_method: "exhaustive"
  repetitions: 1

vars:
  size:
    type: int
    sweep:
      mode: list
      values: [100, 1000, 10000]

command:
  template: "echo 'Processing size: {{ size }}' && sleep 1"

scripts:
  - name: "test"
    submit: "bash"
    script_template: |
      #!/bin/bash
      set -euo pipefail
      {{ command.template }}

    parser:
      file: "{{ execution_dir }}/stdout"
      metrics:
        - name: size
      parser_script: |
        import sys
        import re
        with open(sys.argv[1]) as f:
            content = f.read()
            match = re.search(r'size: (\d+)', content)
            if match:
                print(f"size,{match.group(1)}")

output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
```

## Running

```bash
iops example_simple.yaml
```

## What It Does

1. Sweeps over three size values: 100, 1000, 10000
2. For each value, runs a simple echo command
3. Parses the output to extract the size
4. Saves results to CSV

See `docs/examples/example_simple.yaml` for the full example.
