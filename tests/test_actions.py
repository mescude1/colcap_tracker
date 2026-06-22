"""Tests for dividends / corporate-actions normalizer + tab (offline)."""
import pandas as pd

import sura_tracker as st


class FakeStock:
    def __init__(self, dividends=None, splits=None):
        self._div = dividends
        self._spl = splits

    @property
    def dividends(self):
        if self._div is None:
            raise RuntimeError("no data")
        return self._div

    @property
    def splits(self):
        return self._spl if self._spl is not None else pd.Series(dtype=float)


def _div_series():
    idx = pd.to_datetime(["2022-04-01", "2023-04-01", "2024-04-01"])
    return pd.Series([1400.0, 1450.0, 1500.0], index=idx)


def test_fetch_actions_normalizes():
    actions = st.fetch_actions(FakeStock(_div_series()))
    assert actions["dividends"] == [
        ("2022-04-01", 1400.0), ("2023-04-01", 1450.0), ("2024-04-01", 1500.0)]
    assert actions["splits"] == []


def test_fetch_actions_with_splits():
    spl = pd.Series([2.0], index=pd.to_datetime(["2020-01-02"]))
    actions = st.fetch_actions(FakeStock(_div_series(), spl))
    assert actions["splits"] == [("2020-01-02", 2.0)]


def test_fetch_actions_handles_errors():
    # dividends raises, splits empty → both empty, no exception.
    actions = st.fetch_actions(FakeStock(None, None))
    assert actions == {"dividends": [], "splits": []}


def test_dividends_tab_empty_state():
    html = st.build_dividends_tab({"dividends": [], "splits": []}, "COP")
    assert "No dividend or split history" in html


def test_dividends_tab_renders_chart_and_table():
    actions = st.fetch_actions(FakeStock(_div_series()))
    html = st.build_dividends_tab(actions, "COP")
    assert "chart-divhist" in html
    assert "Recent Dividends" in html
    assert "1,500.00" in html


def test_build_html_includes_dividends_tab(df_with_indicators):
    sym = {"bvc": "TESTCO", "yahoo": "TESTCO.CL", "company": "Test Co",
           "sector": "X", "has_fundamentals": False, "exchange": "BVC",
           "currency": "COP", "keywords": ["t"], "search_name": "t"}
    actions = st.fetch_actions(FakeStock(_div_series()))
    html = st.build_html(df_with_indicators, info={}, period="2 Years",
                         interval="1d", news_items=[], sym=sym, actions=actions)
    assert "tab-dividends" in html
    assert "💰 Dividends" in html
