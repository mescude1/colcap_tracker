"""Tests for portfolio weight parsing + payload + page (offline)."""
import numpy as np
import pandas as pd
import pytest

import sura_tracker as st


def test_parse_weights_normalizes():
    w = st.parse_weights("GRUPOSURA:0.4,ECOPETROL:0.3,ISA:0.3")
    assert sum(w.values()) == pytest.approx(1.0)
    assert w["GRUPOSURA"] == pytest.approx(0.4)


def test_parse_weights_rescales_non_unit():
    w = st.parse_weights("A:1,B:1,C:2")
    assert w == {"A": 0.25, "B": 0.25, "C": 0.5}


def test_parse_weights_sums_duplicates():
    w = st.parse_weights("A:1,A:1,B:2")
    assert w["A"] == pytest.approx(0.5) and w["B"] == pytest.approx(0.5)


@pytest.mark.parametrize("bad", ["", "A", "A:x,B:1", "A:-1,B:1", "A:0"])
def test_parse_weights_invalid(bad):
    with pytest.raises(ValueError):
        st.parse_weights(bad)


def _closes():
    idx = pd.bdate_range("2023-01-02", periods=20)
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "GRUPOSURA": 30000 * np.exp(np.cumsum(rng.normal(0, 0.01, 20))),
        "ECOPETROL": 2000 * np.exp(np.cumsum(rng.normal(0, 0.01, 20))),
    }, index=idx)


def test_portfolio_payload_structure():
    w = st.parse_weights("GRUPOSURA:0.5,ECOPETROL:0.5")
    payload = st.build_portfolio_payload(_closes(), w, {"GRUPOSURA": "Grupo SURA"})
    assert payload["symbols"] == ["GRUPOSURA", "ECOPETROL"]
    assert payload["weights"]["GRUPOSURA"] == pytest.approx(0.5)
    assert len(payload["series"]["ECOPETROL"]["close"]) == 20


def test_build_portfolio_html_has_inputs_and_charts():
    w = st.parse_weights("GRUPOSURA:0.5,ECOPETROL:0.5")
    payload = st.build_portfolio_payload(_closes(), w, {})
    html = st.build_portfolio_html(payload, "1 Month", "1d")
    assert html.startswith("<!DOCTYPE html>")
    assert 'data-sym="GRUPOSURA"' in html        # weight input
    assert "function recompute" in html
    assert 'id="risk"' in html and 'id="cum"' in html
    assert "cdn.plot.ly" in html
