"""Unit + functional tests for the multi-symbol compare page (offline)."""
import json

import numpy as np
import pandas as pd

import sura_tracker as st


def _closes():
    idx = pd.bdate_range("2023-01-02", periods=10)
    return pd.DataFrame({
        "GRUPOSURA": np.linspace(30000, 33000, 10),
        "ECOPETROL": np.linspace(2000, 1900, 10),
        "EMPTY":     [np.nan] * 10,          # symbol with no data → dropped
    }, index=idx)


def test_payload_structure_and_drops_empty():
    payload = st.build_compare_payload(_closes(), {"GRUPOSURA": "Grupo SURA"})
    assert payload["symbols"] == ["GRUPOSURA", "ECOPETROL"]   # EMPTY dropped
    assert len(payload["dates"]) == 10
    assert payload["series"]["GRUPOSURA"]["name"] == "Grupo SURA"
    assert len(payload["series"]["ECOPETROL"]["close"]) == 10


def test_payload_preserves_nulls():
    idx = pd.bdate_range("2023-01-02", periods=4)
    closes = pd.DataFrame({"AAA": [1.0, np.nan, 3.0, 4.0]}, index=idx)
    payload = st.build_compare_payload(closes, {})
    assert payload["series"]["AAA"]["close"] == [1.0, None, 3.0, 4.0]


def test_payload_is_json_serialisable():
    payload = st.build_compare_payload(_closes(), {})
    json.dumps(payload)   # must not raise


def test_build_compare_html_contains_data_and_controls():
    payload = st.build_compare_payload(_closes(), {})
    html = st.build_compare_html(payload, "2 Years", "1d")
    assert html.startswith("<!DOCTYPE html>")
    assert "cdn.plot.ly" in html              # github-pages friendly CDN load
    assert 'data-sym="GRUPOSURA"' in html     # selector chip present
    assert "overlay" in html and "corr" in html and "stats" in html
    assert "const DATA =" in html             # embedded payload
    assert "</script>" not in payload["symbols"]  # sanity


def test_compare_html_escapes_script_close():
    # The embedded JSON must not contain a raw </ that could close the script tag.
    payload = st.build_compare_payload(_closes(), {})
    html = st.build_compare_html(payload, "2 Years", "1d")
    data_line = [l for l in html.splitlines() if l.startswith("const DATA =")][0]
    assert "</" not in data_line


def test_compare_html_weekly_annualisation():
    payload = st.build_compare_payload(_closes(), {})
    html = st.build_compare_html(payload, "2 Years", "1wk")
    assert "Math.sqrt(52)" in html


def test_compare_html_phase6_features():
    payload = st.build_compare_payload(_closes(), {})
    html = st.build_compare_html(payload, "2 Years", "1d")
    # Drawdown overlay + rolling correlation containers
    assert 'id="ddown"' in html
    assert 'id="rollcorr"' in html
    assert "function renderRollCorr" in html
    # Shareable URL-hash state
    assert "function applyHash" in html
    assert "function updateHash" in html
    assert "hashchange" in html
