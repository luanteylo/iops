"""
Tests for the BLAS/OpenMP thread cap used by the Bayesian planner.

The Gaussian Process surrogate fit calls into numpy/BLAS, which defaults to one
thread per core. On many-core (often shared) nodes that is dozens of threads of
pure overhead. _blas_thread_limit caps them for the duration of the GP math
without affecting the optimizer's suggestions.
"""

import os

import pytest

from iops.execution.planner import _blas_thread_limit, _limit_blas_threads

threadpoolctl = pytest.importorskip("threadpoolctl")
from threadpoolctl import threadpool_info  # noqa: E402


def _pool_threads():
    return {d.get("internal_api"): d.get("num_threads") for d in threadpool_info()}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("IOPS_BLAS_THREADS", raising=False)
    yield


def test_default_caps_to_one_and_restores():
    # Force BLAS to load and report a baseline above 1, otherwise the cap is
    # not observable on this machine (e.g. a single-core runner).
    import numpy as np

    np.linalg.svd(np.random.rand(8, 8))
    before = _pool_threads()
    if not any((v or 0) > 1 for v in before.values()):
        pytest.skip("BLAS already single-threaded on this host; nothing to cap")

    with _blas_thread_limit():
        inside = _pool_threads()
    after = _pool_threads()

    assert all(v == 1 for v in inside.values()), inside
    assert after == before  # limit restored on exit


def test_env_override_zero_disables_cap(monkeypatch):
    monkeypatch.setenv("IOPS_BLAS_THREADS", "0")
    before = _pool_threads()
    with _blas_thread_limit():
        inside = _pool_threads()
    assert inside == before  # no-op when disabled


def test_env_override_sets_specific_count(monkeypatch):
    import numpy as np

    np.linalg.svd(np.random.rand(8, 8))
    before = _pool_threads()
    if not any((v or 0) > 2 for v in before.values()):
        pytest.skip("not enough BLAS threads on this host to test a cap of 2")

    monkeypatch.setenv("IOPS_BLAS_THREADS", "2")
    with _blas_thread_limit():
        inside = _pool_threads()
    assert all(v == 2 for v in inside.values()), inside


def test_invalid_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("IOPS_BLAS_THREADS", "not-a-number")
    # Should not raise; defaults to a cap of 1.
    with _blas_thread_limit():
        pass


def test_decorator_caps_and_returns_value():
    @_limit_blas_threads
    def work(x):
        return {"x": x, "pools": _pool_threads()}

    result = work(42)
    assert result["x"] == 42
    assert all(v == 1 for v in result["pools"].values()), result["pools"]
