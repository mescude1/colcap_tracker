"""Flexible --period string parsing (native yfinance periods, custom weeks/months)."""
import re
from datetime import datetime, timedelta

_NATIVE_PERIODS = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "3y", "5y", "10y", "ytd", "max"}


def parse_period(period_str: str):
    """
    Parse a flexible period string → (history_kwargs, display_label).

    Accepted formats
    ────────────────
    Native yfinance  →  1d  5d  1mo  3mo  6mo  1y  2y  3y  5y  10y  ytd  max
    Weeks (custom)   →  1wk  2wk  4wk  6wk  8wk  12wk  26wk  52wk  …
    Months (custom)  →  any Xmo not in native list  (2mo  4mo  9mo  18mo  …)
    """
    s = period_str.strip().lower()

    if s in _NATIVE_PERIODS:
        label_map = {
            "1d": "1 Day", "5d": "5 Days", "1mo": "1 Month", "3mo": "3 Months",
            "6mo": "6 Months", "1y": "1 Year", "2y": "2 Years", "3y": "3 Years",
            "5y": "5 Years", "10y": "10 Years", "ytd": "YTD", "max": "Max",
        }
        return {"period": s}, label_map.get(s, s.upper())

    # Custom weeks: Xwk
    m = re.fullmatch(r"(\d+)wk", s)
    if m:
        weeks = int(m.group(1))
        if weeks < 1:
            raise ValueError("Weeks must be ≥ 1")
        start = (datetime.now() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
        return {"start": start}, f"{weeks} Week{'s' if weeks > 1 else ''}"

    # Custom months: Xmo (non-native)
    m = re.fullmatch(r"(\d+)mo", s)
    if m:
        months = int(m.group(1))
        if months < 1:
            raise ValueError("Months must be ≥ 1")
        start = (datetime.now() - timedelta(days=round(months * 30.44))).strftime("%Y-%m-%d")
        return {"start": start}, f"{months} Month{'s' if months > 1 else ''}"

    raise ValueError(
        f"Unrecognised period '{period_str}'.\n"
        "  Weeks  : 1wk, 2wk, 4wk, 6wk, 8wk, 12wk, 26wk, 52wk …\n"
        "  Months : 1mo, 2mo, 3mo, 6mo, 9mo, 12mo, 18mo …\n"
        "  Years  : 1y, 2y, 3y, 5y, 10y\n"
        "  Other  : 1d, 5d, ytd, max"
    )
