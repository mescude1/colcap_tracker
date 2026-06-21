"""Unit tests for the ticker resolver + coverage note (offline)."""
import pandas as pd
import pytest

import sura_tracker as st


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CACHE_DIR", str(tmp_path / "cache"))


def _df():
    idx = pd.bdate_range("2023-01-02", periods=3)
    return pd.DataFrame({"Close": [1.0, 2.0, 3.0]}, index=idx)


def test_candidate_order_and_dedup():
    meta = {"yahoo": "GEB.CL", "yahoo_alt": ["GEB.CL", "GEBSA.CL"]}
    cands = st.candidate_tickers(meta, "GEB")
    assert cands == ["GEB.CL", "GEBSA.CL"]   # primary, alt, dedup of repeated .CL


def test_candidate_adds_plain_cl_when_primary_differs():
    meta = {"yahoo": "FOO.BAR"}
    assert st.candidate_tickers(meta, "FOO") == ["FOO.BAR", "FOO.CL"]


def test_resolve_picks_first_working(monkeypatch):
    # First candidate empty, second has data → resolver returns the second.
    def fake_download(stock, ticker, hk, interval):
        return (_df(), False) if ticker == "BAR.CL" else (pd.DataFrame(), False)
    monkeypatch.setattr(st, "download_history", fake_download)
    meta = {"yahoo": "FOO.CL", "yahoo_alt": ["BAR.CL"]}
    tk, df = st.resolve_history("FOO", meta, {"period": "1y"}, "1d", use_cache=False)
    assert tk == "BAR.CL"
    assert not df.empty


def test_resolve_empty_when_none_work(monkeypatch):
    monkeypatch.setattr(st, "download_history",
                        lambda *a, **k: (pd.DataFrame(), False))
    tk, df = st.resolve_history("X", {"yahoo": "X.CL"}, {"period": "1y"},
                                "1d", use_cache=False)
    assert tk == "X.CL" and df.empty


def test_compare_html_coverage_note_lists_missing():
    idx = pd.bdate_range("2023-01-02", periods=3)
    # Only one real symbol present → all others reported missing.
    closes = pd.DataFrame({"GRUPOSURA": [1.0, 2.0, 3.0]}, index=idx)
    payload = st.build_compare_payload(closes, {})
    html = st.build_compare_html(payload, "2 Years", "1d")
    assert "No Yahoo Finance data for:" in html
    assert "ECOPETROL" in html   # a known-missing symbol is named
