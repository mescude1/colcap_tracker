"""Tests for the signal-posture engine + buy/sell verdict (offline)."""
import numpy as np
import pandas as pd

import sura_tracker as st


def _frame(closes):
    idx = pd.bdate_range("2021-06-01", periods=len(closes))
    df = pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                       "Close": closes, "Volume": [1]*len(closes)}, index=idx)
    return st.calc_indicators(df, "1d")


def test_no_signals_on_empty():
    assert st.evaluate_signals(pd.DataFrame()) == []


def test_uptrend_is_bullish_verdict():
    df = _frame(list(np.linspace(100, 300, 300)))   # steady rise
    sigs = st.evaluate_signals(df)
    verdict = st.signal_verdict(sigs)
    assert verdict["state"] == "bullish"
    assert verdict["label"] in ("BUY", "STRONG BUY")
    assert verdict["bull"] > verdict["bear"]


def test_downtrend_is_bearish_verdict():
    df = _frame(list(np.linspace(300, 100, 300)))   # steady fall
    verdict = st.signal_verdict(st.evaluate_signals(df))
    assert verdict["state"] == "bearish"
    assert verdict["label"] in ("SELL", "STRONG SELL")


def test_signals_have_expected_fields():
    df = _frame(list(np.linspace(100, 300, 300)))
    for s in st.evaluate_signals(df):
        assert set(s) == {"name", "state", "detail"}
        assert s["state"] in ("bullish", "bearish", "neutral")


def test_verdict_thresholds():
    assert st.signal_verdict([{"name": "x", "state": "bullish", "detail": ""}]*4)["label"] == "STRONG BUY"
    assert st.signal_verdict([{"name": "x", "state": "bullish", "detail": ""}]*2)["label"] == "BUY"
    assert st.signal_verdict([])["label"] == "HOLD"
    assert st.signal_verdict([{"name": "x", "state": "bearish", "detail": ""}]*2)["label"] == "SELL"
    assert st.signal_verdict([{"name": "x", "state": "bearish", "detail": ""}]*4)["label"] == "STRONG SELL"


def test_verdict_counts():
    sigs = [{"name": "a", "state": "bullish", "detail": ""},
            {"name": "b", "state": "bearish", "detail": ""},
            {"name": "c", "state": "neutral", "detail": ""}]
    v = st.signal_verdict(sigs)
    assert (v["bull"], v["bear"], v["neutral"], v["score"]) == (1, 1, 1, 0)
