# GPU Stress Test

Synthetic CUDA workload for testing IOPS GPU sampling probes. Uses cuBLAS SGEMM
(dense matrix multiplication) to generate sustained, predictable GPU load.

## What it tests

- GPU utilization (should be near 100% during SGEMM)
- Power draw (sustained high wattage)
- Temperature (rises under load)
- Memory usage (scales with matrix size)
- Clock speeds (should boost under load)
- Energy consumption (integrated from power trace)

## Prerequisites

- NVIDIA GPU with compute capability 3.5+
- CUDA toolkit (nvcc, libcublas)

## Quick start

```bash
# Build
make

# Validate config
iops check gpu_stress.yaml

# Preview execution plan
iops run gpu_stress.yaml --dry-run

# Run
iops run gpu_stress.yaml
```

## Parameters

The IOPS config sweeps over:

| Variable | Values | Effect |
|----------|--------|--------|
| `matrix_size` | 2048, 4096 | Controls GPU memory and compute intensity |
| `duration` | 5, 10 | Seconds to run (affects energy measurement) |

## Output

After the run, check:

- `workdir_gpu_stress/__iops_resource_summary.csv` for aggregated GPU metrics
- `workdir_gpu_stress/run_*/exec_*/repetition_*/__iops_gpu_trace_*.csv` for raw time series
- `workdir_gpu_stress/run_*/exec_*/repetition_*/__iops_sysinfo.json` for GPU hardware info

## Standalone usage

```bash
./gpu_stress --size 4096 --duration 10 --gpu 0
```

Outputs JSON to stdout: `{"duration_s": 10.02, "matrix_size": 4096, "gflops": 1234.5, "iterations": 42}`
