"""Unit tests for news helpers (sentiment, relevance, date parsing, sources)."""
import sura_tracker as st


def test_classify_bullish():
    assert st.classify_sentiment("Stock rallies as profits surge to record high") == "bullish"


def test_classify_bearish():
    assert st.classify_sentiment("Shares plunge on weak earnings and rising debt") == "bearish"


def test_classify_neutral():
    assert st.classify_sentiment("The company held its annual meeting today") == "neutral"


def test_classify_spanish():
    assert st.classify_sentiment("La acción sube tras fuerte utilidad y dividendo") == "bullish"
    assert st.classify_sentiment("La acción cae por pérdida y riesgo de crisis") == "bearish"


def test_relevance_score_counts_keywords():
    kws = ["gruposura", "suramericana"]
    assert st._relevance_score("GRUPOSURA and Suramericana report", kws) == 2
    assert st._relevance_score("Ecopetrol oil news", kws) == 0


def test_parse_pub_date_rfc2822():
    out = st._parse_pub_date("Wed, 02 Oct 2024 13:00:00 GMT")
    assert out.startswith("2024-10-02")


def test_parse_pub_date_iso():
    assert st._parse_pub_date("2024-10-02T13:00:00Z").startswith("2024-10-02")


def test_parse_pub_date_empty():
    assert st._parse_pub_date("") == ""


def test_load_extra_sources(tmp_path):
    f = tmp_path / "sources.txt"
    f.write_text(
        "# comment\n"
        "https://example.com/rss\n"
        "https://portafolio.co/rss.xml | Portafolio\n"
        "not-a-url\n",
        encoding="utf-8",
    )
    feeds = st.load_extra_sources(str(f))
    assert len(feeds) == 2
    assert feeds[1] == ("https://portafolio.co/rss.xml", "Portafolio")


def test_load_extra_sources_missing_file():
    assert st.load_extra_sources("/nonexistent/path.txt") == []