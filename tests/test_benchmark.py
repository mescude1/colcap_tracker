"""Unit tests for benchmark beta / tracking error + overlay (offline)."""
import numpy as np
import pandas as pd
import pytest

import sura_tracker as st


def test_beta_of_series_vs_itself_is_one():
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0, 0.01, 200))
    assert st.calc_beta(r, r) == pytest.approx(1.0)


def test_beta_scales_with_amplitude():
    rng = np.random.default_rng(1)
    idx = pd.Series(rng.normal(0, 0.01, 200))
    stock = 2.0 * idx                       # exactly 2x the index moves
    assert st.calc_beta(stock, idx) == pytest.approx(2.0)


def test_beta_nan_when_insufficient_data():
    assert np.isnan(st.calc_beta(pd.Series([0.01]), pd.Series([0.01])))


def test_tracking_error_zero_when_identical():
    r = pd.Series([0.01, -0.02, 0.03, 0.0])
    assert st.tracking_error(r, r, "1d") == pytest.approx(0.0)


def test_tracking_error_positive_when_different():
    rng = np.random.default_rng(2)
    a = pd.Series(rng.normal(0, 0.01, 200))
    b = pd.Series(rng.normal(0, 0.01, 200))
    assert st.tracking_error(a, b, "1d") > 0


def test_build_html_with_benchmark_shows_cards(df_with_indicators):
    # Benchmark close aligned to the same index → beta/excess cards render.
    bench_close = df_with_indicators["Close"] * 0.5 + 1000
    sym = {"bvc": "TESTCO", "yahoo": "TESTCO.CL", "company": "Test Co",
           "sector": "X", "has_fundamentals": False, "exchange": "BVC",
           "currency": "COP", "keywords": ["t"], "search_name": "t"}
    html = st.build_html(df_with_indicators, info={}, period="2 Years",
                         interval="1d", news_items=[], sym=sym,
                         benchmark={"label": "COLCAP", "close": bench_close})
    assert "Beta vs COLCAP" in html
    assert "Excess vs COLCAP" in html
    assert "(benchmark)" in html        # overlay trace name


def test_build_html_without_benchmark_omits_cards(df_with_indicators):
    sym = {"bvc": "TESTCO", "yahoo": "TESTCO.CL", "company": "Test Co",
           "sector": "X", "has_fundamentals": False, "exchange": "BVC",
           "currency": "COP", "keywords": ["t"], "search_name": "t"}
    html = st.build_html(df_with_indicators, info={}, period="2 Years",
                         interval="1d", news_items=[], sym=sym)
    assert "Beta vs COLCAP" not in html
