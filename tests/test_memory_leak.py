"""Smoke test for memory growth in IOPSRunner orchestration.

Runs many trivial executions with the local executor and asserts that the
Python heap (tracked by tracemalloc) does not grow unboundedly. This catches
regressions where caches, completed-test lists, or report fixtures retain
references they should not.

The thresholds are intentionally loose. If this test fires, do not just
raise the limit -- run the same scenario under IOPS_MEMPROFILE=1 and look
at the top growth sites in the runner log.
"""

import gc
import tracemalloc
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from conftest import load_config
from iops.execution.runner import IOPSRunner


# How many executions to run. Large enough that a per-iteration leak shows
# up clearly above noise from interpreter caches and one-time allocations.
NUM_EXECUTIONS = 60

# Allow heap growth budget (bytes) across the full run. Most one-time
# allocations happen during the first few iterations; we measure growth
# from a warmup snapshot to the end snapshot to exclude them.
MAX_GROWTH_BYTES = 5 * 1024 * 1024  # 5 MiB


@pytest.fixture
def trivial_config(tmp_path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    config = {
        "benchmark": {
            "name": "MemLeakSmokeTest",
            "workdir": str(workdir),
            "executor": "local",
            "repetitions": 1,
            "random_seed": 0,
        },
        "vars": {
            "n": {
                "type": "int",
                "sweep": {"mode": "list", "values": list(range(NUM_EXECUTIONS))},
            },
        },
        "command": {"template": "echo n={{ n }}"},
        "scripts": [
            {
                "name": "trivial",
                "script_template": (
                    "#!/bin/bash\n"
                    "echo {{ n }} > {{ execution_dir }}/out.txt\n"
                ),
                "parser": {
                    "file": "{{ execution_dir }}/out.txt",
                    "metrics": [{"name": "n", "type": "int"}],
                    "parser_script": (
                        "def parse(file_path):\n"
                        "    with open(file_path) as f:\n"
                        "        return {'n': int(f.read().strip())}\n"
                    ),
                },
            }
        ],
        "output": {"sink": {"type": "csv", "path": str(workdir / "results.csv")}},
    }

    config_file = tmp_path / "memleak_config.yaml"
    with config_file.open("w") as f:
        yaml.dump(config, f)
    return config_file


def _make_args():
    args = Mock()
    args.use_cache = False
    args.cache_only = False
    args.log_level = "WARNING"
    args.max_core_hours = None
    args.parallel = 1
    args.fail_fast = False
    return args


def test_no_unbounded_heap_growth(trivial_config, monkeypatch):
    # Disable the runner's own profiler so this test owns tracemalloc.
    monkeypatch.delenv("IOPS_MEMPROFILE", raising=False)

    config = load_config(trivial_config)
    args = _make_args()

    tracemalloc.start(10)
    runner = IOPSRunner(config, args)

    # Warmup: take a snapshot after construction so the diff excludes
    # one-time allocations (planner, executor, cache, logging).
    gc.collect()
    warmup_snap = tracemalloc.take_snapshot()

    runner.run()

    gc.collect()
    end_snap = tracemalloc.take_snapshot()
    tracemalloc.stop()

    # Sanity: the run actually executed something.
    output = Path(config.benchmark.workdir).parent / "results.csv"
    assert output.exists(), "expected results.csv from the trivial run"

    diffs = end_snap.compare_to(warmup_snap, "lineno")
    total_growth = sum(d.size_diff for d in diffs if d.size_diff > 0)

    if total_growth > MAX_GROWTH_BYTES:
        # Surface the worst offenders so failures are actionable.
        top = "\n".join(
            f"  +{d.size_diff} B (count +{d.count_diff}) "
            f"{d.traceback[0].filename}:{d.traceback[0].lineno}"
            for d in diffs[:15]
        )
        pytest.fail(
            f"Heap grew by {total_growth} bytes across {NUM_EXECUTIONS} "
            f"executions (limit: {MAX_GROWTH_BYTES}).\nTop growth sites:\n{top}"
        )
