"""Unit tests for Yahoo fundamentals normalizer + tab rendering (offline)."""
import pandas as pd

import sura_tracker as st


class FakeStock:
    """Minimal stand-in for a yfinance Ticker exposing only .financials."""
    def __init__(self, financials):
        self.financials = financials


def _financials_df():
    cols = [pd.Timestamp("2024-12-31"), pd.Timestamp("2022-12-31"),
            pd.Timestamp("2023-12-31")]  # deliberately unordered
    return pd.DataFrame(
        {
            cols[0]: [37.2e12, 9.2e12, 2.4e12, 6144.0],
            cols[1]: [33.0e12, 4.0e12, 2.1e12, 5000.0],
            cols[2]: [35.5e12, 4.6e12, 2.3e12, 5500.0],
        },
        index=["Total Revenue", "Operating Income", "Net Income", "Diluted EPS"],
    )


def test_fetch_fundamentals_normalizes_and_sorts():
    fund = st.fetch_fundamentals(FakeStock(_financials_df()))
    assert fund["available"] is True
    assert fund["years"] == ["2022", "2023", "2024"]          # ascending
    assert fund["revenue"] == [33.0, 35.5, 37.2]              # scaled to trillions
    assert fund["net_income"] == [2.1, 2.3, 2.4]
    assert fund["eps"] == [5000.0, 5500.0, 6144.0]            # raw, not scaled


def test_fetch_fundamentals_empty():
    fund = st.fetch_fundamentals(FakeStock(pd.DataFrame()))
    assert fund["available"] is False
    assert fund["years"] == []


def test_fetch_fundamentals_none():
    fund = st.fetch_fundamentals(FakeStock(None))
    assert fund["available"] is False


def test_fetch_fundamentals_partial_rows():
    # Only revenue present; other line items missing entirely.
    df = pd.DataFrame(
        {pd.Timestamp("2023-12-31"): [10.0e12]},
        index=["Total Revenue"],
    )
    fund = st.fetch_fundamentals(FakeStock(df))
    assert fund["available"] is True
    assert fund["revenue"] == [10.0]
    assert fund["net_income"] == [None]
    assert fund["eps"] == [None]


def test_fetch_fundamentals_exception_safe():
    class Boom:
        @property
        def financials(self):
            raise RuntimeError("network down")
    assert st.fetch_fundamentals(Boom())["available"] is False


def test_yahoo_fund_tab_renders():
    fund = st.fetch_fundamentals(FakeStock(_financials_df()))
    html = st.build_yahoo_fund_tab(fund, "TESTCO", "TESTCO.CL", "COP")
    assert "chart-rev" in html and "chart-ni" in html and "chart-eps" in html
    assert "FY2024" in html
    assert "Yahoo Finance" in html


def test_build_html_uses_yahoo_fundamentals():
    from conftest import make_ohlcv
    df = st.calc_indicators(make_ohlcv().copy(), interval="1d")
    fund = st.fetch_fundamentals(FakeStock(_financials_df()))
    sym = {"bvc": "TESTCO", "yahoo": "TESTCO.CL", "company": "Test Co",
           "sector": "X", "has_fundamentals": False, "exchange": "BVC",
           "currency": "COP", "keywords": ["testco"], "search_name": "Testco"}
    html = st.build_html(df, info={}, period="2 Years", interval="1d",
                         news_items=[], sym=sym, fundamentals=fund)
    assert "Annual Financials — Yahoo Finance" in html
