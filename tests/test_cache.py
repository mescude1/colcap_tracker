"""Unit tests for the price cache + resilient fetch (offline)."""
import os
import time

import pandas as pd
import pytest

import sura_tracker as st


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path, monkeypatch):
    """Point the cache at a temp dir for every test."""
    monkeypatch.setattr(st, "CACHE_DIR", str(tmp_path / "cache"))


def _df(val=1.0):
    idx = pd.bdate_range("2023-01-02", periods=3)
    return pd.DataFrame({"Close": [val, val + 1, val + 2]}, index=idx)


def test_cache_key_stable_and_distinct():
    k1 = st._cache_key("GRUPOSURA.CL", "1d", {"period": "2y"})
    k2 = st._cache_key("GRUPOSURA.CL", "1d", {"period": "2y"})
    k3 = st._cache_key("GRUPOSURA.CL", "1wk", {"period": "2y"})
    assert k1 == k2 and k1 != k3


def test_write_then_read_roundtrip():
    path = st._cache_path("abc")
    st.cache_write(path, _df())
    out = st.cache_read(path, max_age_min=60)
    pd.testing.assert_frame_equal(out, _df())


def test_cache_read_respects_ttl():
    path = st._cache_path("ttl")
    st.cache_write(path, _df())
    old = time.time() - 7200          # 2 hours ago
    os.utime(path, (old, old))
    assert st.cache_read(path, max_age_min=60) is None      # stale per TTL
    assert st.cache_read_any(path) is not None              # but still readable


def test_cached_fetch_writes_and_hits():
    calls = {"n": 0}
    def fetch():
        calls["n"] += 1
        return _df(10.0)
    a = st.cached_fetch("k", fetch, use_cache=True, max_age_min=60)
    b = st.cached_fetch("k", fetch, use_cache=True, max_age_min=60)
    assert calls["n"] == 1            # second call served from cache
    pd.testing.assert_frame_equal(a, b)


def test_cached_fetch_stale_fallback_on_failure():
    st.cached_fetch("s", lambda: _df(5.0), use_cache=True, max_age_min=60)
    # Expire the entry, then a failing fetch should fall back to stale.
    os.utime(st._cache_path("s"), (time.time() - 7200,) * 2)
    def boom():
        raise RuntimeError("rate limited")
    out = st.cached_fetch("s", boom, use_cache=True, max_age_min=60)
    pd.testing.assert_frame_equal(out, _df(5.0))


def test_cached_fetch_no_cache_bypasses():
    calls = {"n": 0}
    def fetch():
        calls["n"] += 1
        return _df()
    st.cached_fetch("nc", fetch, use_cache=False)
    st.cached_fetch("nc", fetch, use_cache=False)
    assert calls["n"] == 2            # never cached → always fetches
    assert not os.path.exists(st._cache_path("nc"))


def test_cached_fetch_returns_empty_when_no_data_no_cache():
    out = st.cached_fetch("missing", lambda: pd.DataFrame(),
                          use_cache=True, max_age_min=60)
    assert out.empty
