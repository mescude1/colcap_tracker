"""Phase 9 contract: the bvc package modules are the source of the re-exports."""
import bvc.indicators
import bvc.period
import bvc.sentiment
import sura_tracker as st


def test_indicators_reexported_identically():
    for name in ("calc_rsi", "calc_macd", "calc_bollinger", "calc_atr",
                 "calc_drawdown", "sharpe_ratio", "sortino_ratio", "max_drawdown",
                 "calc_beta", "tracking_error", "calc_indicators", "monthly_returns",
                 "ann_factor_for"):
        assert getattr(st, name) is getattr(bvc.indicators, name)


def test_period_reexported_identically():
    assert st.parse_period is bvc.period.parse_period


def test_sentiment_reexported_identically():
    for name in ("classify_sentiment", "_parse_pub_date", "_relevance_score",
                 "BULLISH_WORDS", "BEARISH_WORDS"):
        assert getattr(st, name) is getattr(bvc.sentiment, name)


def test_package_namespaces_present():
    # Modules are reachable both as bvc.X and st.X (re-exported namespace).
    assert st.indicators is bvc.indicators
    assert st.period is bvc.period
    assert st.sentiment is bvc.sentiment
