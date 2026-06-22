"""Functional test: full HTML dashboard assembly, offline, no network."""
import sura_tracker as st


def _sym(has_fund=False):
    return {
        "bvc": "TESTCO", "yahoo": "TESTCO.CL", "company": "Test Company S.A.",
        "sector": "Testing", "has_fundamentals": has_fund,
        "exchange": "BVC", "currency": "COP",
        "keywords": ["testco"], "search_name": "Testco",
    }


def test_build_html_self_contained(df_with_indicators):
    html = st.build_html(df_with_indicators, info={}, period="2 Years",
                         interval="1d", news_items=[], sym=_sym())
    assert html.startswith("<!DOCTYPE html>")
    # Tabs present
    for tab in ("technical", "returns", "fundamentals", "news"):
        assert f"tab-{tab}" in html
    # Chart divs rendered (incl. Phase 1 additions)
    for div in ("chart-candle", "chart-rsi", "chart-macd", "chart-atr",
                "chart-drawdown", "chart-heatmap"):
        assert div in html
    # Phase 1 metric cards
    assert "Sharpe Ratio" in html
    assert "Max Drawdown" in html
    # Signals sidebar with a BUY/SELL verdict
    assert 'class="sidebar"' in html
    assert "Signal Summary" in html
    assert "verdict-badge" in html
    assert any(v in html for v in ("STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"))
    # Loads Plotly from CDN (github-pages friendly, no bundling)
    assert "cdn.plot.ly" in html
    # Company metadata surfaced
    assert "Test Company S.A." in html


def test_build_html_with_news(df_with_indicators):
    news = [{
        "title": "Testco profits surge", "summary": "Strong quarter",
        "link": "https://example.com", "publisher": "Test Wire",
        "date": "2024-10-02 10:00", "category": "TESTCO",
        "relevance": 1, "news_type": "company", "sentiment": "bullish",
    }]
    html = st.build_html(df_with_indicators, info={}, period="2 Years",
                         interval="1d", news_items=news, sym=_sym())
    assert "Testco profits surge" in html
    assert "BULLISH" in html


def test_render_news_empty():
    out = st.render_news_html([], "TESTCO")
    assert "No news" in out