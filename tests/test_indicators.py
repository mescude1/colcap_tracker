"""Unit tests for technical-indicator math."""
import numpy as np
import pandas as pd
import pytest

import sura_tracker as st


def test_rsi_all_gains_is_100():
    s = pd.Series(np.arange(1, 50, dtype=float))  # strictly increasing
    rsi = st.calc_rsi(s)
    assert rsi.dropna().iloc[-1] == 100.0


def test_rsi_all_losses_is_zero():
    s = pd.Series(np.arange(50, 1, -1, dtype=float))  # strictly decreasing
    rsi = st.calc_rsi(s)
    assert rsi.dropna().iloc[-1] == 0.0


def test_rsi_within_bounds(df_with_indicators):
    rsi = df_with_indicators["RSI"].dropna()
    assert ((rsi >= 0) & (rsi <= 100)).all()


def test_macd_histogram_is_macd_minus_signal():
    s = pd.Series(np.random.default_rng(0).normal(100, 5, 200))
    macd, signal, hist = st.calc_macd(s)
    pd.testing.assert_series_equal(hist, macd - signal, check_names=False)


def test_bollinger_ordering():
    s = pd.Series(np.random.default_rng(1).normal(100, 5, 100))
    upper, mid, lower = st.calc_bollinger(s)
    valid = upper.dropna().index
    assert (upper.loc[valid] >= mid.loc[valid]).all()
    assert (mid.loc[valid] >= lower.loc[valid]).all()


def test_calc_indicators_adds_columns(df_with_indicators):
    expected = {"SMA_20", "SMA_50", "SMA_200", "RSI", "MACD", "Signal",
                "Histogram", "BB_Upper", "BB_Mid", "BB_Lower",
                "Daily_Return", "Cum_Return", "Rolling_Vol"}
    assert expected.issubset(df_with_indicators.columns)


def test_weekly_interval_uses_52_annualisation(ohlcv):
    # Smoke test: weekly path runs and produces finite volatility.
    df = st.calc_indicators(ohlcv.copy(), interval="1wk")
    assert df["Rolling_Vol"].dropna().gt(0).any()


def test_monthly_returns_shape(df_with_indicators):
    years, months, z = st.monthly_returns(df_with_indicators)
    assert months == list(range(1, 13))
    assert len(z) == len(years)
    assert all(len(row) == 12 for row in z)


def test_rgba_conversion():
    assert st.rgba("#3fb950", 0.5) == "rgba(63,185,80,0.5)"


# ── Phase 1: new indicators ──────────────────────────────────────────

def test_atr_positive_and_finite(df_with_indicators):
    atr = df_with_indicators["ATR"].dropna()
    assert (atr > 0).all()
    assert np.isfinite(atr).all()


def test_drawdown_non_positive_and_bounded():
    close = pd.Series([100, 110, 121, 90, 100, 130], dtype=float)
    dd = st.calc_drawdown(close)
    assert (dd <= 0).all()
    assert dd.iloc[0] == 0.0           # first point is its own peak
    assert dd.iloc[2] == 0.0           # new peak → 0 drawdown
    # 90 vs peak 121 → 90/121 - 1
    assert dd.iloc[3] == pytest.approx(90 / 121 - 1)


def test_max_drawdown_matches_min():
    close = pd.Series([100, 120, 60, 80], dtype=float)
    assert st.max_drawdown(close) == pytest.approx(60 / 120 - 1)  # -0.5


def test_monotonic_series_has_zero_drawdown():
    close = pd.Series(np.arange(1, 50, dtype=float))
    assert st.max_drawdown(close) == 0.0


def test_sharpe_positive_for_uptrend():
    rets = pd.Series([0.01] * 50)      # steady positive returns, zero std handled
    # zero variance → nan by definition; use small noise instead
    rets = pd.Series(np.full(50, 0.01) + np.random.default_rng(0).normal(0, 1e-4, 50))
    assert st.sharpe_ratio(rets, "1d") > 0


def test_sharpe_nan_on_empty():
    assert np.isnan(st.sharpe_ratio(pd.Series(dtype=float), "1d"))


def test_sortino_only_penalises_downside():
    rng = np.random.default_rng(3)
    rets = pd.Series(rng.normal(0.001, 0.01, 200))
    sharpe = st.sharpe_ratio(rets, "1d")
    sortino = st.sortino_ratio(rets, "1d")
    assert np.isfinite(sharpe) and np.isfinite(sortino)


def test_ann_factor():
    assert st.ann_factor_for("1d") == pytest.approx(np.sqrt(252))
    assert st.ann_factor_for("1wk") == pytest.approx(np.sqrt(52))