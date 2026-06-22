"""Registry integrity + per-symbol currency handling (offline)."""
import sura_tracker as st


REQUIRED_KEYS = {"yahoo", "company", "sector", "has_fundamentals",
                 "search_name", "keywords"}


def test_registry_entries_have_required_keys():
    for sym, meta in st.BVC_SYMBOLS.items():
        missing = REQUIRED_KEYS - set(meta)
        assert not missing, f"{sym} missing {missing}"
        assert isinstance(meta["keywords"], list) and meta["keywords"]


def test_registry_expanded_coverage():
    # Phase 10 additions should all be present.
    for sym in ("DAVIVIENDA", "CELSIA", "PROMIGAS", "TERPEL", "CANACOL",
                "MINEROS", "GRUPOAVAL", "PFGRUPOARG", "PFCEMARGOS",
                "CONCONCRETO", "ENKA", "FABRICATO", "ETB", "BVC"):
        assert sym in st.BVC_SYMBOLS
    assert len(st.BVC_SYMBOLS) >= 26


def test_bancolombia_is_usd_adr():
    meta = st.BVC_SYMBOLS["BANCOLOMBIA"]
    assert meta["yahoo"] == "CIB"
    assert meta["currency"] == "USD"


def test_default_currency_is_cop():
    # Symbols without an explicit currency default to COP.
    assert "currency" not in st.BVC_SYMBOLS["GRUPOSURA"]
    assert st.CURRENCY == "COP"
