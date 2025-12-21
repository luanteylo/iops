---
title: "Analysis & Reports"
---


IOPS can generate interactive HTML reports with plots and statistical analysis from your benchmark results.

## Generating Reports

After your benchmark completes, generate a report:

```bash
iops analyze /path/to/workdir/run_001
```

The report includes:

- Interactive plots of your metrics
- Statistical summaries
- Parameter correlations
- Performance comparisons

## Output Formats

IOPS supports multiple output formats for results:

### CSV

Simple, human-readable format:

```yaml
output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
    mode: append
```

### Parquet

Efficient columnar format for large datasets:

```yaml
output:
  sink:
    type: parquet
    path: "{{ workdir }}/results.parquet"
    mode: append
```

### SQLite

Queryable database format:

```yaml
output:
  sink:
    type: sqlite
    path: "{{ workdir }}/results.db"
    table: "benchmark_results"
    mode: append
```

## Field Filtering

Control which fields appear in output:

### Include Specific Fields

```yaml
output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
    include:
      - "execution.execution_id"
      - "vars.*"
      - "metrics.*"
```

### Exclude Fields

```yaml
output:
  sink:
    type: csv
    path: "{{ workdir }}/results.csv"
    exclude:
      - "benchmark.description"
      - "metadata.internal_flag"
```

## Analyzing Results

You can analyze results using various tools:

### pandas

```python
import pandas as pd

# Read CSV results
df = pd.read_csv("workdir/results.csv")

# Analyze
print(df.groupby("vars.threads")["metrics.throughput"].mean())
```

### SQLite

```bash
sqlite3 results.db "SELECT AVG(metrics_throughput) FROM results GROUP BY vars_threads"
```

## Next Steps

- Learn about [Configuration](configuration.md)
- Explore [Examples](../examples/index.md)
