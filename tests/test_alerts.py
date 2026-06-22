"""Tests for the alerts engine + digest page (offline)."""
import numpy as np
import pandas as pd

import sura_tracker as st


def _frame(closes):
    idx = pd.bdate_range("2022-01-03", periods=len(closes))
    df = pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                       "Close": closes, "Volume": [1]*len(closes)}, index=idx)
    return st.calc_indicators(df, "1d")


def test_no_alerts_on_short_frame():
    assert st.generate_alerts(pd.DataFrame()) == []


def test_oversold_rsi_fires_bullish():
    # Long uptrend then a sharp sustained drop → RSI < 30.
    closes = list(np.linspace(100, 200, 60)) + list(np.linspace(200, 120, 20))
    alerts = st.generate_alerts(_frame(closes))
    kinds = {(k, d) for k, d, _ in alerts}
    assert ("RSI", "bullish") in kinds


def test_overbought_rsi_fires_bearish():
    closes = list(np.linspace(200, 100, 60)) + list(np.linspace(100, 180, 20))
    alerts = st.generate_alerts(_frame(closes))
    assert ("RSI", "bearish") in {(k, d) for k, d, _ in alerts}


def test_new_high_fires():
    closes = list(np.linspace(100, 300, 300))   # strictly rising → last is the high
    alerts = st.generate_alerts(_frame(closes))
    assert ("Range", "bullish") in {(k, d) for k, d, _ in alerts}


def test_build_alerts_html_empty_state():
    html = st.build_alerts_html([], "2 Years", "1d")
    assert "No symbols with data" in html
    assert html.startswith("<!DOCTYPE html>")


def _verdict(label="BUY", state="bullish", score=2, bull=3, bear=1, neutral=1):
    return {"label": label, "state": state, "score": score,
            "bull": bull, "bear": bear, "neutral": neutral, "total": bull+bear+neutral}


def test_build_alerts_html_renders_verdict_and_events():
    results = [("GRUPOSURA", "Grupo SURA", 33000.0, "COP", _verdict(),
                [("RSI", "bullish", "Oversold · RSI 25")])]
    html = st.build_alerts_html(results, "2 Years", "1d")
    assert "GRUPOSURA" in html
    assert "BUY" in html and "score +2" in html
    assert "Oversold · RSI 25" in html


def test_build_alerts_html_sorts_by_score():
    results = [
        ("SELLER", "S", 100.0, "COP", _verdict("STRONG SELL", "bearish", -4, 0, 5, 2), []),
        ("BUYER",  "B", 100.0, "COP", _verdict("STRONG BUY", "bullish", 5, 6, 1, 0), []),
    ]
    html = st.build_alerts_html(results, "2 Years", "1d")
    assert html.index("BUYER") < html.index("SELLER")   # strongest buy first
