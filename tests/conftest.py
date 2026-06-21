"""Shared pytest fixtures — all offline, no network access."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

# Make the repo root importable so `import sura_tracker` works from tests/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_ohlcv(n: int = 400, seed: int = 42, start: str = "2022-01-03") -> pd.DataFrame:
    """Deterministic synthetic OHLCV frame with a business-day DatetimeIndex."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start=start, periods=n)
    # Geometric random walk for a realistic, strictly-positive close.
    rets = rng.normal(0.0004, 0.015, n)
    close = 30000 * np.exp(np.cumsum(rets))
    open_ = close * (1 + rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    vol = rng.integers(50_000, 500_000, n)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol},
        index=idx,
    )


@pytest.fixture
def ohlcv():
    """Raw synthetic price frame (no indicators)."""
    return make_ohlcv()


@pytest.fixture
def df_with_indicators(ohlcv):
    """Price frame with all technical-indicator columns computed."""
    import sura_tracker as st
    return st.calc_indicators(ohlcv.copy(), interval="1d")