"""Tests for CSV/JSON export payload + buttons (offline)."""
import numpy as np

import sura_tracker as st


def test_export_payload_shape(df_with_indicators):
    payload = st.export_payload(df_with_indicators)
    assert payload["columns"][0] == "Date"
    assert "Close" in payload["columns"] and "RSI" in payload["columns"]
    assert len(payload["rows"]) == len(df_with_indicators)
    # Each row = Date + one value per column.
    assert all(len(r) == len(payload["columns"]) for r in payload["rows"])


def test_export_payload_nan_becomes_none(df_with_indicators):
    payload = st.export_payload(df_with_indicators)
    rsi_idx = payload["columns"].index("RSI")
    # RSI is NaN for the first rows (warm-up) → serialised as None.
    assert payload["rows"][0][rsi_idx] is None


def test_export_payload_dates_iso(df_with_indicators):
    first = st.export_payload(df_with_indicators)["rows"][0][0]
    assert len(first) == 10 and first[4] == "-"   # YYYY-MM-DD


def test_build_html_has_export_buttons(df_with_indicators):
    sym = {"bvc": "TESTCO", "yahoo": "TESTCO.CL", "company": "Test Co",
           "sector": "X", "has_fundamentals": False, "exchange": "BVC",
           "currency": "COP", "keywords": ["testco"], "search_name": "Testco"}
    html = st.build_html(df_with_indicators, info={}, period="2 Years",
                         interval="1d", news_items=[], sym=sym)
    assert "EXPORT_DATA" in html
    assert "exportTable(EXPORT_DATA,'testco_1d','csv')" in html
    assert "function exportTable" in html
