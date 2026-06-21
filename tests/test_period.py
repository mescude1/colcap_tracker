"""Unit tests for flexible period parsing."""
import pytest

import sura_tracker as st


def test_native_period_passthrough():
    kwargs, label = st.parse_period("2y")
    assert kwargs == {"period": "2y"}
    assert label == "2 Years"


def test_ytd_and_max():
    assert st.parse_period("ytd")[0] == {"period": "ytd"}
    assert st.parse_period("max")[0] == {"period": "max"}


def test_custom_weeks_returns_start_date():
    kwargs, label = st.parse_period("26wk")
    assert "start" in kwargs and "period" not in kwargs
    assert label == "26 Weeks"


def test_custom_months_non_native():
    kwargs, label = st.parse_period("4mo")
    assert "start" in kwargs
    assert label == "4 Months"


def test_singular_label():
    assert st.parse_period("1wk")[1] == "1 Week"


def test_case_insensitive():
    assert st.parse_period("2Y")[0] == {"period": "2y"}


@pytest.mark.parametrize("bad", ["", "abc", "0wk", "-3mo", "5days"])
def test_invalid_periods_raise(bad):
    with pytest.raises(ValueError):
        st.parse_period(bad)