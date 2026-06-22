#!/usr/bin/env python3
"""
══════════════════════════════════════════════════════════════════════
BVC Stock Analysis Dashboard Generator
Bolsa de Valores de Colombia — Multi-Symbol Edition
══════════════════════════════════════════════════════════════════════

Generates a fully self-contained interactive HTML dashboard with:
  • Candlestick chart + Bollinger Bands + Moving Averages
  • Volume, RSI, MACD charts
  • Cumulative returns, monthly heatmap, rolling volatility
  • Fundamental analysis (embedded for GRUPOSURA FY2022–2024)
  • News feed with bilingual bullish/bearish sentiment classification

Requirements:
    pip install yfinance plotly pandas numpy

Usage:
    python sura_tracker.py                                     # GRUPOSURA, daily, 2y
    python sura_tracker.py --symbol ECOPETROL                  # switch to Ecopetrol
    python sura_tracker.py --symbol BANCOLOMBIA --period 1y    # 1-year Bancolombia
    python sura_tracker.py --sources my_sources.txt            # custom RSS feeds
    python sura_tracker.py --interval 1wk --period 5y          # weekly, 5 years
    python sura_tracker.py --no-news --output dash.html        # offline mode
    python sura_tracker.py --period 26wk --interval 1wk        # 26-week weekly

Supported --symbol values (BVC tickers):
    Financial  : GRUPOSURA (default)  PFGRUPSURA  BANCOLOMBIA  PFBCOLOMBIA
                 BOGOTA  CORFICOLCF  PFAVAL
    Energy     : ECOPETROL  GEB  ISA
    Holding    : GRUPOARGOS  CEMARGOS  NUTRESA
    Retail     : EXITO
    Custom     : any BVC ticker not in the list above is tried as TICKER.CL

--sources file format (one entry per line, # = comment):
    # My custom Colombian finance feeds
    https://www.larepublica.co/rss/economia
    https://www.portafolio.co/rss.xml | Portafolio
    https://www.dinero.com/rss.xml | Dinero

Data source: Yahoo Finance (.CL BVC tickers) + Google News RSS
"""

import argparse
import sys
import html as html_lib
import json
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
import urllib.request
from datetime import datetime
from email.utils import parsedate_to_datetime

# ─── Auto-install if missing ───────────────────────────────────────
def _install(pkg):
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

for _pkg in ["yfinance", "plotly", "pandas", "numpy"]:
    try:
        __import__(_pkg.split("[")[0])
    except ImportError:
        print(f"Installing {_pkg}…")
        _install(_pkg)

import hashlib
import time

import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio


# ══════════════════════════════════════════════════════════════════
# PRICE CACHE  (resilience against Yahoo rate-limits + offline reruns)
# ══════════════════════════════════════════════════════════════════
# A throttled fetch falls back to the last cached frame so the page still
# renders; the next scheduled run refetches once the rate-limit resets.
# Cache files are pandas pickles under .cache/ (gitignored) — no new deps.

CACHE_DIR = ".cache"


def _cache_key(symbol: str, interval: str, history_kwargs: dict) -> str:
    raw = f"{symbol}|{interval}|{sorted(history_kwargs.items())}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.pkl")


def cache_read(path: str, max_age_min):
    """Return the cached frame only if it exists and is younger than max_age_min."""
    if not os.path.exists(path):
        return None
    if max_age_min is not None:
        age_min = (time.time() - os.path.getmtime(path)) / 60
        if age_min > max_age_min:
            return None
    try:
        return pd.read_pickle(path)
    except Exception:
        return None


def cache_read_any(path: str):
    """Return the cached frame regardless of age (stale fallback)."""
    if not os.path.exists(path):
        return None
    try:
        return pd.read_pickle(path)
    except Exception:
        return None


def cache_write(path: str, df: pd.DataFrame) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        df.to_pickle(path)
    except Exception as e:
        print(f"  ⚠️  cache write failed: {e}")


def cached_fetch(key: str, fetch_fn, use_cache: bool = True, max_age_min=60):
    """
    Return data via cache-first strategy:
      1. fresh cache (younger than max_age_min) → return it
      2. otherwise call fetch_fn(); on success cache + return
      3. on failure/empty fetch → fall back to stale cache if present
    Never raises for fetch errors — returns an empty DataFrame as last resort.
    """
    path = _cache_path(key)
    if use_cache:
        fresh = cache_read(path, max_age_min)
        if fresh is not None and not fresh.empty:
            print("  ✅ cache hit (fresh).")
            return fresh
    try:
        df = fetch_fn()
    except Exception as e:
        print(f"  ⚠️  fetch error: {type(e).__name__}: {e}")
        df = None
    if df is not None and not df.empty:
        if use_cache:
            cache_write(path, df)
        return df
    if use_cache:
        stale = cache_read_any(path)
        if stale is not None and not stale.empty:
            print("  ♻️  fetch unavailable — using stale cache.")
            return stale
    return df if df is not None else pd.DataFrame()


def download_history(stock, ticker: str, history_kwargs: dict, interval: str):
    """
    Multi-tier price fetch: stock.history() → yf.download() → native period=2y.
    Returns (df, used_native_fallback). Catches errors internally and returns an
    empty frame so callers (and the cache layer) can decide how to recover.
    """
    def _normalise_df(raw: pd.DataFrame) -> pd.DataFrame:
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        if raw.index.tz is not None:
            raw.index = raw.index.tz_localize(None)
        return raw

    df = pd.DataFrame()
    try:
        df = stock.history(**history_kwargs, interval=interval)
        if not df.empty:
            print("  ✅ stock.history() succeeded.")
    except Exception as e:
        print(f"  ⚠️  stock.history() failed: {type(e).__name__}: {e}")

    if df.empty:
        print("  🔄 Retrying with yf.download()…")
        try:
            df = yf.download(ticker, **history_kwargs, interval=interval,
                             progress=False, auto_adjust=True)
            if not df.empty:
                df = _normalise_df(df)
                print("  ✅ yf.download() succeeded.")
        except Exception as e:
            print(f"  ⚠️  yf.download() failed: {type(e).__name__}: {e}")

    used_native = False
    if df.empty and "start" in history_kwargs:
        print("  🔄 Retrying with native period=2y (ignoring custom start date)…")
        try:
            df = yf.download(ticker, period="2y", interval=interval,
                             progress=False, auto_adjust=True)
            if not df.empty:
                df = _normalise_df(df)
                used_native = True
                print("  ✅ Native period=2y fallback succeeded.")
        except Exception as e:
            print(f"  ⚠️  Native period fallback failed: {type(e).__name__}: {e}")
    return df, used_native


def candidate_tickers(symbol_meta: dict, bvc_symbol: str) -> list:
    """
    Ordered Yahoo ticker candidates for a BVC symbol.

    Tries the registry ticker first, then any curated same-currency alternates
    (``yahoo_alt``), then a plain ``TICKER.CL`` — de-duplicated, order preserved.
    Alternates are intentionally COP/BVC listings only (no foreign ADRs) so the
    dashboard's currency assumptions stay valid.
    """
    cands = [symbol_meta.get("yahoo") or f"{bvc_symbol}.CL"]
    cands += list(symbol_meta.get("yahoo_alt", []))
    cands.append(f"{bvc_symbol}.CL")
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def resolve_history(bvc_symbol: str, symbol_meta: dict, history_kwargs: dict,
                    interval: str, use_cache: bool = True, max_age_min=60):
    """
    Try each candidate ticker (cache-first) until one returns data.

    Returns (resolved_ticker, df). If none yield data, returns the primary
    candidate with an empty frame so the caller can report missing coverage.
    """
    candidates = candidate_tickers(symbol_meta, bvc_symbol)
    for tk in candidates:
        key = _cache_key(tk, interval, history_kwargs)

        def _fetch(t=tk):
            d, _ = download_history(yf.Ticker(t), t, history_kwargs, interval)
            return d

        df = cached_fetch(key, _fetch, use_cache=use_cache, max_age_min=max_age_min)
        if df is not None and not df.empty:
            return tk, df
    return candidates[0], pd.DataFrame()


# ══════════════════════════════════════════════════════════════════
# BVC SYMBOL REGISTRY
# ══════════════════════════════════════════════════════════════════
# Maps BVC tickers → Yahoo Finance tickers (.CL) and dashboard metadata.
# Unknown tickers are tried as TICKER.CL automatically.

BVC_SYMBOLS = {
    # ── Financial Services / Holdings ───────────────────────────
    "GRUPOSURA": {
        "yahoo": "GRUPOSURA.CL", "company": "Grupo de Inversiones Suramericana S.A.",
        "sector": "Financial Services Holding", "has_fundamentals": True,
        # search_name  → used in Google News RSS queries (specific, not generic)
        # keywords     → used to score article relevance; lower-case; partial-match OK
        "search_name": "GRUPOSURA Suramericana",
        "keywords": ["gruposura", "grupo sura", "suramericana", "sura asset",
                     "sura seguros", "inversiones suramericana"],
    },
    "PFGRUPSURA": {
        "yahoo": "PFGRUPSURA.CL", "company": "Grupo SURA — Preferred Shares",
        "sector": "Financial Services Holding", "has_fundamentals": False,
        "search_name": "GRUPOSURA Suramericana preferencial",
        "keywords": ["gruposura", "pfgrupsura", "grupo sura", "suramericana"],
    },
    "BANCOLOMBIA": {
        "yahoo": "BANCOLOMBIA.CL", "company": "Bancolombia S.A.",
        "sector": "Banking", "has_fundamentals": False,
        "search_name": "Bancolombia banco",
        "keywords": ["bancolombia", "grupo bancolombia", "nequi", "banistmo"],
    },
    "PFBCOLOMBIA": {
        "yahoo": "PFBCOLOMBIA.CL", "company": "Bancolombia S.A. — Preferred",
        "sector": "Banking", "has_fundamentals": False,
        "search_name": "Bancolombia preferencial",
        "keywords": ["bancolombia", "pfbcolombia", "grupo bancolombia"],
    },
    "BOGOTA": {
        "yahoo": "BOGOTA.CL", "company": "Banco de Bogotá S.A.",
        "sector": "Banking", "has_fundamentals": False,
        "search_name": "Banco de Bogotá Grupo Aval",
        "keywords": ["banco de bogotá", "banco bogota", "grupo aval"],
    },
    "CORFICOLCF": {
        "yahoo": "CORFICOLCF.CL", "company": "Corporación Financiera Colombiana S.A.",
        "sector": "Financial Services", "has_fundamentals": False,
        "search_name": "Corficolombiana Corficolcf",
        "keywords": ["corficolombiana", "corficolcf", "corporación financiera colombiana"],
    },
    "PFAVAL": {
        "yahoo": "PFAVAL.CL", "company": "Grupo Aval Acciones y Valores S.A.",
        "sector": "Financial Services", "has_fundamentals": False,
        "search_name": "Grupo Aval Pfaval",
        "keywords": ["grupo aval", "pfaval", "aval acciones"],
    },
    # ── Energy / Utilities ──────────────────────────────────────
    "ECOPETROL": {
        "yahoo": "ECOPETROL.CL", "company": "Ecopetrol S.A.",
        "sector": "Oil & Gas", "has_fundamentals": False,
        "search_name": "Ecopetrol petróleo Colombia",
        "keywords": ["ecopetrol", "cenit", "hocol", "savia"],
    },
    "GEB": {
        "yahoo": "GEB.CL", "company": "Grupo Energía Bogotá S.A.",
        "sector": "Utilities", "has_fundamentals": False,
        "search_name": "Grupo Energía Bogotá GEB",
        "keywords": ["grupo energía bogotá", "geb", "gas natural fenosa colombia",
                     "energia bogota"],
    },
    "ISA": {
        "yahoo": "ISA.CL", "company": "Interconexión Eléctrica S.A.",
        "sector": "Utilities", "has_fundamentals": False,
        "search_name": "ISA Interconexión Eléctrica",
        "keywords": ["isa", "interconexión eléctrica", "interconexion electrica",
                     "intercolombia"],
    },
    # ── Diversified / Materials ──────────────────────────────────
    "GRUPOARGOS": {
        "yahoo": "GRUPOARGOS.CL", "company": "Grupo Argos S.A.",
        "sector": "Diversified Holding", "has_fundamentals": False,
        "search_name": "Grupo Argos Cementos",
        "keywords": ["grupo argos", "argos", "cementos argos", "celsia", "compas"],
    },
    "CEMARGOS": {
        "yahoo": "CEMARGOS.CL", "company": "Cementos Argos S.A.",
        "sector": "Materials / Cement", "has_fundamentals": False,
        "search_name": "Cementos Argos cemento Colombia",
        "keywords": ["cementos argos", "cemargos", "argos cemento"],
    },
    "NUTRESA": {
        "yahoo": "NUTRESA.CL", "company": "Grupo Nutresa S.A.",
        "sector": "Consumer Staples", "has_fundamentals": False,
        "search_name": "Grupo Nutresa alimentos Colombia",
        "keywords": ["nutresa", "grupo nutresa", "noel", "colcafe", "zenú", "zenu",
                     "chocolatería luker"],
    },
    # ── Consumer / Retail ───────────────────────────────────────
    "EXITO": {
        "yahoo": "EXITO.CL", "company": "Almacenes Éxito S.A.",
        "sector": "Consumer Discretionary", "has_fundamentals": False,
        "search_name": "Almacenes Éxito supermercado Colombia",
        "keywords": ["almacenes éxito", "almacenes exito", "exito supermercado",
                     "grupo casino colombia", "carulla", "surtimax"],
    },
}

EXCHANGE = "BVC"
CURRENCY = "COP"

# COLCAP index proxy (iShares COLCAP ETF) used as the benchmark for beta /
# relative performance. Resolver-backed, so it degrades gracefully if missing.
BENCHMARK = {"label": "COLCAP", "yahoo": "ICOLCAP.CL",
             "company": "iShares COLCAP (ICOLCAP)"}

# Embedded fundamental data — GRUPOSURA only (official press releases FY2022–2024)
FUNDAMENTAL = {
    "years":      ["2022", "2023", "2024"],
    "revenue":    [None,   35.5,  37.2],    # COP trillion
    "op_income":  [None,    4.6,   9.2],    # COP trillion
    "net_income": [2.1,     2.3,   2.4],    # COP trillion (adjusted)
    "roe":        [None,   10.2,  12.3],    # %
    "dividend":   [1280,   1400,  1500],    # COP / share
    "eps":        [None,   None,  6144],    # COP recurring
}

SUBSIDIARIES = {
    "SURA Asset Management": {
        "Net Income (COP B)": 885,
        "AUM (COP T)": 719,
        "Commission Income (COP T)": 3.9,
        "Operating Income (COP T)": 1.8,
        "ROE Adjusted (%)": 9.0,
        "Clients (M)": 23.4,
    },
    "Suramericana (Insurance)": {
        "Net Income (COP B)": 751,
        "NI Growth (%)": 65,
        "Written Premiums (COP T)": 20.7,
        "Premium Growth (%)": 6.6,
        "ROE Adjusted (%)": 13.1,
        "Clients (M)": 20,
    },
}


# ══════════════════════════════════════════════════════════════════
# TECHNICAL INDICATOR FUNCTIONS
# ══════════════════════════════════════════════════════════════════

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss
    return 100 - (100 / (1 + rs))


def calc_macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast    = series.ewm(span=fast, adjust=False).mean()
    ema_slow    = series.ewm(span=slow, adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_bollinger(series: pd.Series, window=20, num_std=2):
    mid   = series.rolling(window).mean()
    std   = series.rolling(window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range — volatility in price units (Wilder's smoothing via EMA)."""
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    true_range = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False).mean()


def calc_drawdown(close: pd.Series) -> pd.Series:
    """Drawdown from the running peak, as a fraction (0 = at peak, -0.2 = 20% below)."""
    running_max = close.cummax()
    return close / running_max - 1.0


def ann_factor_for(interval: str) -> float:
    """Annualisation factor for return series at the given bar interval."""
    return np.sqrt(52) if interval == "1wk" else np.sqrt(252)


def sharpe_ratio(returns: pd.Series, interval: str = "1d", rf: float = 0.0) -> float:
    """Annualised Sharpe ratio of a periodic-return series (rf = per-period risk-free)."""
    r = returns.dropna()
    if r.empty or r.std() == 0:
        return float("nan")
    return (r.mean() - rf) / r.std() * ann_factor_for(interval)


def sortino_ratio(returns: pd.Series, interval: str = "1d", rf: float = 0.0) -> float:
    """Annualised Sortino ratio — like Sharpe but penalising only downside deviation."""
    r = returns.dropna()
    downside = r[r < rf]
    if r.empty or downside.empty or downside.std() == 0:
        return float("nan")
    return (r.mean() - rf) / downside.std() * ann_factor_for(interval)


def max_drawdown(close: pd.Series) -> float:
    """Maximum peak-to-trough drawdown as a fraction (e.g. -0.34 for -34%)."""
    dd = calc_drawdown(close.dropna())
    return float(dd.min()) if not dd.empty else float("nan")


def calc_beta(stock_ret: pd.Series, index_ret: pd.Series) -> float:
    """Beta = cov(stock, index) / var(index) over aligned (inner-join) returns."""
    joined = pd.concat([stock_ret, index_ret], axis=1).dropna()
    if len(joined) < 2:
        return float("nan")
    var = joined.iloc[:, 1].var()
    if var == 0:
        return float("nan")
    return float(joined.cov().iloc[0, 1] / var)


def tracking_error(stock_ret: pd.Series, index_ret: pd.Series,
                   interval: str = "1d") -> float:
    """Annualised tracking error (%) — std of the active (stock − index) return."""
    diff = (stock_ret - index_ret).dropna()
    if diff.empty:
        return float("nan")
    return float(diff.std() * ann_factor_for(interval) * 100)


def calc_indicators(df: pd.DataFrame, interval: str = "1d") -> pd.DataFrame:
    """Calculate technical indicators, adapting windows and annualisation to interval."""
    if interval == "1wk":
        vol_window = 13       # ~13 weeks ≈ 1 quarter
        ann_factor = np.sqrt(52)
    else:
        vol_window = 21       # ~21 trading days ≈ 1 month
        ann_factor = np.sqrt(252)

    close = df["Close"]
    df["SMA_20"]  = close.rolling(20).mean()
    df["SMA_50"]  = close.rolling(50).mean()
    df["SMA_200"] = close.rolling(200).mean()
    df["RSI"]     = calc_rsi(close)
    df["MACD"], df["Signal"], df["Histogram"] = calc_macd(close)
    df["BB_Upper"], df["BB_Mid"], df["BB_Lower"] = calc_bollinger(close)
    df["ATR"]          = calc_atr(df)
    df["Daily_Return"] = close.pct_change()
    df["Cum_Return"]   = (1 + df["Daily_Return"]).cumprod() - 1
    df["Rolling_Vol"]  = df["Daily_Return"].rolling(vol_window).std() * ann_factor * 100
    df["Drawdown"]     = calc_drawdown(close)
    return df


# ══════════════════════════════════════════════════════════════════
# MONTHLY HEATMAP DATA
# ══════════════════════════════════════════════════════════════════

def monthly_returns(df: pd.DataFrame):
    monthly = df["Close"].resample("ME").last().pct_change() * 100
    monthly = monthly.dropna()
    years   = sorted(monthly.index.year.unique())
    months  = list(range(1, 13))
    z = []
    for yr in years:
        row = []
        for mo in months:
            mask = (monthly.index.year == yr) & (monthly.index.month == mo)
            vals = monthly[mask]
            row.append(round(vals.iloc[0], 2) if len(vals) > 0 else None)
        z.append(row)
    return years, months, z


# ══════════════════════════════════════════════════════════════════
# PLOTLY FIGURE BUILDERS
# ══════════════════════════════════════════════════════════════════

BG     = "#0d1117"
BG2    = "#161b22"
BG3    = "#21262d"
BORDER = "#30363d"
TEXT   = "#e6edf3"
TEXT2  = "#8b949e"
GREEN  = "#3fb950"
RED    = "#f85149"
BLUE   = "#58a6ff"
YELLOW = "#e3b341"
PURPLE = "#bc8cff"
ORANGE = "#ffa657"


def rgba(hex_color: str, alpha: float) -> str:
    """Convert '#rrggbb' + alpha float → 'rgba(r,g,b,alpha)' for Plotly."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


BASE_LAYOUT = dict(
    paper_bgcolor=BG2, plot_bgcolor=BG2,
    font=dict(color=TEXT, family="Segoe UI, system-ui, sans-serif", size=12),
    xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER, showgrid=True),
    yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER, showgrid=True),
    legend=dict(bgcolor=BG2, bordercolor=BORDER, borderwidth=1),
    hovermode="x unified",
    hoverlabel=dict(bgcolor=BG3, bordercolor=BORDER, font=dict(color=TEXT)),
    margin=dict(l=60, r=20, t=30, b=40),
)


def _layout(**overrides):
    """Merge BASE_LAYOUT with per-chart overrides; deep-merge nested dicts."""
    result = dict(**BASE_LAYOUT)
    for k, v in overrides.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = {**result[k], **v}
        else:
            result[k] = v
    return result


def fig_candlestick(df, ticker_label: str = "Stock"):
    dates = df.index.strftime("%Y-%m-%d").tolist()
    close = df["Close"].tolist()
    upper = df["BB_Upper"].tolist()
    mid   = df["BB_Mid"].tolist()
    lower = df["BB_Lower"].tolist()

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates, y=upper, name="BB Upper",
        line=dict(color=TEXT2, width=1, dash="dot")))
    fig.add_trace(go.Scatter(x=dates, y=lower, name="BB Lower",
        line=dict(color=TEXT2, width=1, dash="dot"),
        fill="tonexty", fillcolor="rgba(88,166,255,0.05)"))
    fig.add_trace(go.Scatter(x=dates, y=mid, name="BB Mid / SMA20",
        line=dict(color=ORANGE, width=1)))
    fig.add_trace(go.Scatter(x=dates, y=df["SMA_50"].tolist(), name="SMA 50",
        line=dict(color=BLUE, width=1.5)))
    fig.add_trace(go.Scatter(x=dates, y=df["SMA_200"].tolist(), name="SMA 200",
        line=dict(color=PURPLE, width=1.5)))
    fig.add_trace(go.Candlestick(
        x=dates, open=df["Open"].tolist(), high=df["High"].tolist(),
        low=df["Low"].tolist(), close=close, name=ticker_label,
        increasing=dict(line=dict(color=GREEN), fillcolor=GREEN),
        decreasing=dict(line=dict(color=RED),   fillcolor=RED),
    ))
    fig.update_layout(**_layout(
        title=dict(text="Price · Bollinger Bands · Moving Averages", font=dict(size=13, color=TEXT2)),
        xaxis=dict(rangeslider=dict(visible=False)),
        yaxis=dict(title=f"Price ({CURRENCY})"),
        height=400,
    ))
    return fig


def fig_volume(df):
    dates  = df.index.strftime("%Y-%m-%d").tolist()
    colors = [GREEN if c >= o else RED for c, o in zip(df["Close"], df["Open"])]
    fig = go.Figure(go.Bar(x=dates, y=df["Volume"].tolist(),
                           name="Volume", marker_color=[rgba(c, 0.53) for c in colors]))
    fig.update_layout(**_layout(
        title=dict(text="Volume", font=dict(size=13, color=TEXT2)),
        yaxis=dict(title="Volume"),
        height=160, margin=dict(l=60, r=20, t=30, b=30),
    ))
    return fig


def fig_rsi(df):
    dates = df.index.strftime("%Y-%m-%d").tolist()
    fig = go.Figure()
    fig.add_hline(y=70, line_dash="dash", line_color=RED,   line_width=1, opacity=0.6)
    fig.add_hline(y=30, line_dash="dash", line_color=GREEN, line_width=1, opacity=0.6)
    fig.add_hline(y=50, line_dash="dot",  line_color=TEXT2, line_width=0.5, opacity=0.4)
    fig.add_trace(go.Scatter(x=dates, y=df["RSI"].tolist(), name="RSI(14)",
                             line=dict(color=YELLOW, width=1.5)))
    fig.update_layout(**_layout(
        title=dict(text="RSI (14)", font=dict(size=13, color=TEXT2)),
        yaxis=dict(range=[0, 100], title="RSI"),
        height=190, margin=dict(l=60, r=20, t=30, b=30),
    ))
    return fig


def fig_macd(df):
    dates  = df.index.strftime("%Y-%m-%d").tolist()
    hist   = df["Histogram"].tolist()
    colors = [rgba(GREEN, 0.53) if v >= 0 else rgba(RED, 0.53) for v in hist]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=dates, y=hist, name="Histogram", marker_color=colors))
    fig.add_trace(go.Scatter(x=dates, y=df["MACD"].tolist(),   name="MACD",
                             line=dict(color=BLUE,   width=1.5)))
    fig.add_trace(go.Scatter(x=dates, y=df["Signal"].tolist(), name="Signal",
                             line=dict(color=ORANGE, width=1.5)))
    fig.update_layout(**_layout(
        title=dict(text="MACD (12, 26, 9)", font=dict(size=13, color=TEXT2)),
        yaxis=dict(title=f"MACD ({CURRENCY})"),
        height=210, margin=dict(l=60, r=20, t=30, b=30),
    ))
    return fig


def fig_atr(df):
    dates = df.index.strftime("%Y-%m-%d").tolist()
    fig = go.Figure(go.Scatter(x=dates, y=df["ATR"].round(2).tolist(), name="ATR(14)",
        line=dict(color=PURPLE, width=1.5),
        fill="tozeroy", fillcolor=rgba(PURPLE, 0.09)))
    fig.update_layout(**_layout(
        title=dict(text="Average True Range (14)", font=dict(size=13, color=TEXT2)),
        yaxis=dict(title=f"ATR ({CURRENCY})"),
        height=190, margin=dict(l=60, r=20, t=30, b=30),
    ))
    return fig


def fig_drawdown(df):
    dates = df.index.strftime("%Y-%m-%d").tolist()
    dd    = (df["Drawdown"] * 100).round(2).tolist()
    fig = go.Figure(go.Scatter(x=dates, y=dd, name="Drawdown",
        line=dict(color=RED, width=1.5),
        fill="tozeroy", fillcolor=rgba(RED, 0.12)))
    fig.update_layout(**_layout(
        title=dict(text="Drawdown from Peak (%)", font=dict(size=13, color=TEXT2)),
        yaxis=dict(title="Drawdown (%)", rangemode="tozero"),
        height=250, margin=dict(l=60, r=20, t=30, b=30),
    ))
    return fig


def fig_cumulative(df, bench_cum=None, bench_label="COLCAP"):
    dates = df.index.strftime("%Y-%m-%d").tolist()
    cum   = (df["Cum_Return"] * 100).round(2).tolist()
    fig = go.Figure(go.Scatter(x=dates, y=cum, name="Cumulative Return",
        line=dict(color=BLUE, width=2),
        fill="tozeroy", fillcolor="rgba(88,166,255,0.1)"))
    if bench_cum is not None:
        fig.add_trace(go.Scatter(x=dates, y=(bench_cum * 100).round(2).tolist(),
            name=f"{bench_label} (benchmark)",
            line=dict(color=YELLOW, width=1.5, dash="dot")))
    fig.update_layout(**_layout(
        title=dict(text="Cumulative Returns", font=dict(size=13, color=TEXT2)),
        yaxis=dict(title="Return (%)"),
        height=290,
    ))
    return fig


def fig_distribution(df):
    rets = (df["Daily_Return"].dropna() * 100).round(4).tolist()
    mean = np.mean(rets)
    fig = go.Figure(go.Histogram(x=rets, nbinsx=50, name="Daily Returns",
                                 marker_color=rgba(BLUE, 0.53)))
    fig.add_vline(x=mean, line_dash="dash", line_color=YELLOW,
                  annotation_text=f"Mean: {mean:.3f}%", annotation_position="top right")
    fig.update_layout(**_layout(
        title=dict(text="Daily Return Distribution", font=dict(size=13, color=TEXT2)),
        xaxis=dict(title="Daily Return (%)"),
        yaxis=dict(title="Frequency"),
        height=250, margin=dict(l=60, r=20, t=30, b=30),
    ))
    return fig


def fig_volatility(df):
    dates = df.index.strftime("%Y-%m-%d").tolist()
    vol   = df["Rolling_Vol"].round(2).tolist()
    fig = go.Figure(go.Scatter(x=dates, y=vol, name="Annualised Vol",
        line=dict(color=ORANGE, width=1.5),
        fill="tozeroy", fillcolor=rgba(ORANGE, 0.09)))
    fig.update_layout(**_layout(
        title=dict(text="Rolling 21-Day Annualised Volatility (%)", font=dict(size=13, color=TEXT2)),
        yaxis=dict(title="Volatility (%)"),
        height=250, margin=dict(l=60, r=20, t=30, b=30),
    ))
    return fig


def fig_monthly_heatmap(df):
    years, months, z = monthly_returns(df)
    month_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    text = [[f"{v:.1f}%" if v is not None else "" for v in row] for row in z]
    fig = go.Figure(go.Heatmap(
        z=z, x=month_labels, y=[str(yr) for yr in years],
        colorscale=[[0, RED], [0.35, BG3], [0.5, BG3], [1, GREEN]],
        zmid=0, text=text, texttemplate="%{text}",
        showscale=True,
        colorbar=dict(ticksuffix="%", bgcolor=BG2, bordercolor=BORDER),
    ))
    fig.update_layout(**_layout(
        title=dict(text="Monthly Return Heatmap (%)", font=dict(size=13, color=TEXT2)),
        margin=dict(l=60, r=20, t=30, b=30),
        height=280,
    ))
    return fig


# ── GRUPOSURA fundamental charts (only rendered when has_fundamentals=True) ──

def fig_fund_revenue():
    yrs = FUNDAMENTAL["years"]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=yrs, y=FUNDAMENTAL["revenue"], name="Revenue",
        marker_color=BLUE,
        text=[f"{v}T" if v else "—" for v in FUNDAMENTAL["revenue"]],
        textposition="outside"))
    fig.add_trace(go.Bar(x=yrs, y=FUNDAMENTAL["op_income"], name="Operating Income",
        marker_color=GREEN,
        text=[f"{v}T" if v else "—" for v in FUNDAMENTAL["op_income"]],
        textposition="outside"))
    fig.update_layout(**_layout(
        barmode="group",
        title=dict(text="Revenue & Operating Income (COP Trillion)", font=dict(size=13, color=TEXT2)),
        yaxis=dict(title="COP Trillion"),
        height=280, margin=dict(l=60, r=20, t=30, b=30),
    ))
    return fig


def fig_fund_ni():
    yrs = FUNDAMENTAL["years"]
    ni  = FUNDAMENTAL["net_income"]
    colors = [GREEN if (ni[i] or 0) >= (ni[i-1] or 0) else RED for i in range(len(ni))]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=yrs, y=ni, name="Net Income (Adj.)",
        marker_color=colors,
        text=[f"{v}T" if v else "—" for v in ni],
        textposition="outside"))
    fig.add_trace(go.Scatter(x=yrs, y=ni, mode="lines+markers", name="Trend",
        line=dict(color=YELLOW, width=2, dash="dot"),
        marker=dict(size=8, color=YELLOW)))
    fig.update_layout(**_layout(
        title=dict(text="Net Income Adjusted (COP Trillion)", font=dict(size=13, color=TEXT2)),
        yaxis=dict(title="COP Trillion"),
        height=280, margin=dict(l=60, r=20, t=30, b=30),
    ))
    return fig


def fig_fund_roe():
    yrs = FUNDAMENTAL["years"]
    roe = FUNDAMENTAL["roe"]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=yrs, y=roe, name="ROE Adjusted (%)",
        marker_color=PURPLE,
        text=[f"{v}%" if v else "—" for v in roe],
        textposition="outside"))
    fig.add_trace(go.Scatter(x=yrs, y=roe, mode="lines+markers", name="Trend",
        line=dict(color=YELLOW, width=2, dash="dot"),
        marker=dict(size=8, color=YELLOW)))
    fig.update_layout(**_layout(
        title=dict(text="ROE Adjusted (%)", font=dict(size=13, color=TEXT2)),
        yaxis=dict(range=[0, 16], title="%"),
        height=280, margin=dict(l=60, r=20, t=30, b=30),
    ))
    return fig


def fig_fund_div():
    yrs = FUNDAMENTAL["years"]
    div = FUNDAMENTAL["dividend"]
    fig = go.Figure(go.Bar(x=yrs, y=div, name="Dividend / Share (COP)",
        marker_color=ORANGE,
        text=[f"COP {v:,}" for v in div],
        textposition="outside"))
    fig.update_layout(**_layout(
        title=dict(text="Dividend Per Share (COP)", font=dict(size=13, color=TEXT2)),
        yaxis=dict(range=[0, 1900], title="COP / share"),
        height=280, margin=dict(l=60, r=20, t=30, b=30),
    ))
    return fig


# ── Yahoo Finance fundamentals (any ticker, best-effort) ────────────

def _fin_row(fin, *names):
    """Find a row in a yfinance financials DataFrame by any candidate line-item name."""
    if fin is None or getattr(fin, "empty", True):
        return None
    idx_lower = {str(i).lower(): i for i in fin.index}
    for name in names:                       # pass 1: exact match
        if name.lower() in idx_lower:
            return fin.loc[idx_lower[name.lower()]]
    for name in names:                       # pass 2: substring match
        for key, orig in idx_lower.items():
            if name.lower() in key:
                return fin.loc[orig]
    return None


def fetch_fundamentals(stock) -> dict:
    """
    Pull annual fundamentals from Yahoo Finance (yfinance) into a normalized dict.

    Monetary series are scaled to trillions of the reporting currency; EPS stays raw.
    Tolerant of missing/empty data — BVC '.CL' tickers are often sparse on Yahoo —
    returning {"available": False, …} rather than raising.
    """
    out = {"available": False, "years": [], "revenue": [],
           "op_income": [], "net_income": [], "eps": []}
    try:
        fin = stock.financials
    except Exception:
        fin = None
    if fin is None or getattr(fin, "empty", True):
        return out

    try:
        cols = sorted(fin.columns, key=lambda c: pd.Timestamp(c))
    except Exception:
        cols = list(fin.columns)
    out["years"] = [str(pd.Timestamp(c).year) for c in cols]

    def series(row, scale):
        if row is None:
            return [None] * len(cols)
        vals = []
        for c in cols:
            v = row.get(c)
            vals.append(round(float(v) / scale, 2)
                        if v is not None and pd.notna(v) else None)
        return vals

    out["revenue"]    = series(_fin_row(fin, "Total Revenue", "Revenue", "Operating Revenue"), 1e12)
    out["op_income"]  = series(_fin_row(fin, "Operating Income", "Total Operating Income As Reported"), 1e12)
    out["net_income"] = series(_fin_row(fin, "Net Income", "Net Income Common Stockholders"), 1e12)
    out["eps"]        = series(_fin_row(fin, "Diluted EPS", "Basic EPS"), 1)
    out["available"]  = any(v is not None for v in out["revenue"] + out["net_income"])
    return out


def fig_fund_grouped(years, series_specs, title, yaxis_title, suffix=""):
    """Generic grouped/standalone bar chart. series_specs: list of (name, values, color)."""
    fig = go.Figure()
    for name, vals, color in series_specs:
        fig.add_trace(go.Bar(
            x=years, y=vals, name=name, marker_color=color,
            text=[f"{v}{suffix}" if v is not None else "—" for v in vals],
            textposition="outside"))
    fig.update_layout(**_layout(
        barmode="group",
        title=dict(text=title, font=dict(size=13, color=TEXT2)),
        yaxis=dict(title=yaxis_title),
        height=280, margin=dict(l=60, r=20, t=30, b=30),
    ))
    return fig


def build_yahoo_fund_tab(fund: dict, ticker_bvc: str, ticker_yf: str, currency: str) -> str:
    """Fundamentals-tab HTML built from Yahoo Finance data (non-curated tickers)."""
    years = fund["years"]
    yf_url = f"https://finance.yahoo.com/quote/{ticker_yf}/financials/"
    divs = {
        "rev": fig_to_div(fig_fund_grouped(
            years,
            [("Revenue", fund["revenue"], BLUE),
             ("Operating Income", fund["op_income"], GREEN)],
            f"Revenue & Operating Income ({currency} Trillion)", f"{currency} Trillion",
            suffix="T"), "chart-rev"),
        "ni": fig_to_div(fig_fund_grouped(
            years, [("Net Income", fund["net_income"], PURPLE)],
            f"Net Income ({currency} Trillion)", f"{currency} Trillion",
            suffix="T"), "chart-ni"),
        "eps": fig_to_div(fig_fund_grouped(
            years, [("EPS", fund["eps"], ORANGE)],
            f"Earnings Per Share ({currency})", currency), "chart-eps"),
    }

    def _cell(v, suffix=""):
        return f"{v}{suffix}" if v is not None else "—"

    rows = ""
    table_spec = [("Revenue (T)", fund["revenue"], "T"),
                  ("Operating Income (T)", fund["op_income"], "T"),
                  ("Net Income (T)", fund["net_income"], "T"),
                  ("EPS", fund["eps"], "")]
    for label, vals, suf in table_spec:
        cells = "".join(f"<td>{_cell(v, suf)}</td>" for v in vals)
        rows += f"<tr><td>{label}</td>{cells}</tr>"
    head = "".join(f"<th>FY{y}</th>" for y in years)

    return f"""
  <div class="info-note">
    <strong>Fundamental data</strong> for <strong>{ticker_bvc}</strong> sourced live from
    <a href="{yf_url}" target="_blank">Yahoo Finance</a>. Coverage for BVC tickers can be
    partial — missing values show as “—”. Monetary figures in <strong>{currency} Trillion</strong>.
  </div>
  <div class="chart-row">
    <div class="chart-card">{divs["rev"]}</div>
    <div class="chart-card">{divs["ni"]}</div>
  </div>
  <div class="chart-card">{divs["eps"]}</div>
  <div class="chart-card">
    <div style="font-size:13px;font-weight:600;color:var(--text2);margin-bottom:12px;text-transform:uppercase;letter-spacing:.5px;">Annual Financials — Yahoo Finance</div>
    <table class="fund-table">
      <thead><tr><th>Metric</th>{head}</tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>"""


# ── Dividends & corporate actions (Yahoo, best-effort) ──────────────

def fetch_actions(stock) -> dict:
    """
    Normalize a ticker's dividend and split history into plain lists.

    Returns {"dividends": [(date, per_share), …], "splits": [(date, ratio), …]}.
    Tolerant of missing data / errors — returns empty lists rather than raising.
    """
    out = {"dividends": [], "splits": []}
    for attr, key in (("dividends", "dividends"), ("splits", "splits")):
        try:
            series = getattr(stock, attr)
        except Exception:
            series = None
        if series is not None and len(series):
            for ts, v in series.items():
                try:
                    out[key].append((pd.Timestamp(ts).strftime("%Y-%m-%d"), float(v)))
                except Exception:
                    continue
    return out


def fig_div_history(dividends, currency="COP"):
    dates = [d for d, _ in dividends]
    vals  = [v for _, v in dividends]
    fig = go.Figure(go.Bar(x=dates, y=vals, marker_color=GREEN, name="Dividend",
        text=[f"{v:,.0f}" for v in vals], textposition="outside"))
    fig.update_layout(**_layout(
        title=dict(text=f"Dividend per Share ({currency})", font=dict(size=13, color=TEXT2)),
        yaxis=dict(title=f"{currency} / share"),
        height=300, margin=dict(l=60, r=20, t=30, b=40),
    ))
    return fig


def build_dividends_tab(actions: dict, currency: str = "COP") -> str:
    """Dividends-tab HTML: dividend-history chart + recent dividends & splits tables."""
    divs   = actions.get("dividends", [])
    splits = actions.get("splits", [])
    if not divs and not splits:
        return ('<div style="text-align:center;padding:60px 20px;color:var(--text2);">'
                '<div style="font-size:48px;margin-bottom:16px;">💰</div>'
                '<div style="font-size:16px;font-weight:600;color:var(--text);">'
                'No dividend or split history on Yahoo Finance for this ticker.</div></div>')

    title = ('<div style="font-size:13px;font-weight:600;color:var(--text2);'
             'margin-bottom:12px;text-transform:uppercase;letter-spacing:.5px;">')
    parts = []
    if divs:
        parts.append(f'<div class="chart-card">'
                     f'{fig_to_div(fig_div_history(divs, currency), "chart-divhist")}</div>')
        rows = "".join(f"<tr><td>{d}</td><td>{currency} {v:,.2f}</td></tr>"
                       for d, v in reversed(divs[-12:]))
        parts.append(f'<div class="chart-card">{title}Recent Dividends</div>'
                     f'<table class="fund-table"><thead><tr><th>Ex-Date</th>'
                     f'<th>Per Share</th></tr></thead><tbody>{rows}</tbody></table></div>')
    if splits:
        rows = "".join(f"<tr><td>{d}</td><td>{v:g} : 1</td></tr>"
                       for d, v in reversed(splits))
        parts.append(f'<div class="chart-card">{title}Stock Splits</div>'
                     f'<table class="fund-table"><thead><tr><th>Date</th>'
                     f'<th>Ratio</th></tr></thead><tbody>{rows}</tbody></table></div>')
    return "".join(parts)


# ══════════════════════════════════════════════════════════════════
# NEWS — CUSTOM SOURCE LOADER
# ══════════════════════════════════════════════════════════════════

def load_extra_sources(filepath: str) -> list:
    """
    Parse a .txt file of custom RSS feed sources.

    File format (one entry per line):
        # Lines starting with # are comments
        https://www.larepublica.co/rss/economia
        https://www.portafolio.co/rss.xml | Portafolio
        https://www.dinero.com/rss.xml | Dinero Colombia

    Returns a list of (url, category_label) tuples.
    """
    feeds = []
    if not filepath:
        return feeds
    try:
        with open(filepath, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "|" in line:
                    parts    = line.split("|", 1)
                    url      = parts[0].strip()
                    category = parts[1].strip() or "Custom"
                else:
                    url      = line.strip()
                    parsed   = urllib.parse.urlparse(url)
                    category = parsed.netloc.lstrip("www.") or f"Custom {lineno}"
                if url.startswith("http"):
                    feeds.append((url, category))
                else:
                    print(f"  ⚠️  sources.txt line {lineno}: skipping invalid URL → {url}")
        print(f"  📄 Loaded {len(feeds)} custom source(s) from: {filepath}")
    except FileNotFoundError:
        print(f"  ⚠️  Sources file not found: {filepath}")
    except Exception as e:
        print(f"  ⚠️  Error reading sources file: {e}")
    return feeds


# ══════════════════════════════════════════════════════════════════
# NEWS — SENTIMENT CLASSIFICATION
# ══════════════════════════════════════════════════════════════════

BULLISH_WORDS = {
    # English
    "gain","gains","rise","rises","rose","rally","rallies","surge","surges","soar","soars",
    "grow","growth","profit","profits","beat","beats","exceed","exceeds","record",
    "strong","strength","positive","upgrade","buy","outperform","dividend","recovery",
    "recovers","higher","increase","increases","boost","opportunity","bullish","expansion",
    "improving","improved","acceleration","upside","rebound","inflow","inflows",
    # Spanish
    "sube","subida","alza","alzas","gana","ganancias","crece","crecimiento","utilidad",
    "utilidades","beneficio","beneficios","supera","fuerte","positivo","dividendo",
    "recuperación","recupera","aumenta","incremento","mejora","expansión","oportunidad",
    "rebote","entrada","flujos","alcista","record","máximo",
}

BEARISH_WORDS = {
    # English
    "loss","losses","fall","falls","fell","drop","drops","decline","declines","plunge",
    "miss","misses","weak","weakness","sell","downgrade","underperform","cut","cuts",
    "risk","risks","concern","concerns","debt","default","down","lower","crash","fear",
    "warning","decrease","uncertainty","bearish","contraction","deteriorating","pressure",
    "headwinds","outflow","outflows","deficit","inflation","recession","layoff","layoffs",
    # Spanish
    "baja","bajada","cae","caída","pierde","pérdida","riesgo","deuda","crisis","declive",
    "descenso","disminuye","reducción","preocupación","débil","negativo","incertidumbre",
    "presión","contracción","salida","déficit","inflación","recesión","bajista","mínimo",
    "desempleo","recorte",
}


def classify_sentiment(text: str) -> str:
    """Score a headline+summary as bullish, bearish, or neutral via keyword matching."""
    words      = set(re.findall(r"[a-záéíóúñü]+", text.lower()))
    bull_score = len(words & BULLISH_WORDS)
    bear_score = len(words & BEARISH_WORDS)
    if bull_score > bear_score:
        return "bullish"
    if bear_score > bull_score:
        return "bearish"
    return "neutral"


def _parse_pub_date(raw) -> str:
    """Parse various date formats (Unix timestamp / ISO 8601 / RFC 2822) → YYYY-MM-DD HH:MM."""
    if not raw:
        return ""
    if str(raw).isdigit():
        try:
            return datetime.fromtimestamp(int(raw)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ""
    if "T" in str(raw):
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
    try:
        return parsedate_to_datetime(str(raw)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(raw)[:16]


def _relevance_score(text: str, keywords: list) -> int:
    """Count how many company keywords appear in the given text (case-insensitive)."""
    t = text.lower()
    return sum(1 for kw in keywords if kw in t)


def fetch_news(stock, sym: dict, extra_feeds: list = None) -> list:
    """
    Fetch and classify news from:
      1. yfinance stock.news  (company-specific, tagged 'company')
      2. Targeted Google News RSS feeds for the company (tagged 'company')
      3. Broader BVC / Colombia Macro RSS feeds (tagged 'market')
      4. Any extra feeds loaded from a --sources file (tagged 'custom')

    Each article gets:
      relevance  : int   — count of company keyword hits (0 = not about this company)
      news_type  : str   — 'company' | 'market' | 'custom'
      sentiment  : str   — 'bullish' | 'bearish' | 'neutral'

    Returns list sorted: company articles first (by relevance desc), then market.
    """
    news       = []
    ticker_bvc = sym.get("bvc", "STOCK")
    company    = sym.get("company", ticker_bvc)
    keywords   = sym.get("keywords", [ticker_bvc.lower()])
    search_name = sym.get("search_name", ticker_bvc)   # curated search term, never "Grupo de"

    def _add(article, news_type: str):
        text = article.get("title", "") + " " + article.get("summary", "")
        article["relevance"] = _relevance_score(text, keywords)
        article["news_type"] = news_type
        article["sentiment"] = classify_sentiment(text)
        news.append(article)

    # ── 1. yfinance news (always company-specific) ────────────────
    print("  📰 Fetching yfinance news…")
    try:
        raw_news = stock.news or []
        for item in raw_news:
            content   = item.get("content", item)
            title     = content.get("title", "")
            summary   = content.get("summary", "") or content.get("description", "")
            link      = (content.get("canonicalUrl") or {}).get("url", "") or content.get("link", "")
            publisher = (content.get("provider") or {}).get("displayName", "") or content.get("publisher", "Yahoo Finance")
            pub_date  = content.get("pubDate", "") or content.get("providerPublishTime", "")
            if not title:
                continue
            summary_clean = re.sub(r"<[^>]+>", "", summary).strip()[:220]
            _add({
                "title":     title,
                "summary":   summary_clean,
                "link":      link,
                "publisher": publisher or "Yahoo Finance",
                "date":      _parse_pub_date(pub_date),
                "category":  ticker_bvc,
            }, "company")
    except Exception as e:
        print(f"  ⚠️  yfinance news error: {e}")

    # ── 2. Google News RSS helper ─────────────────────────────────
    def _gnews(query: str) -> str:
        return f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=es-CO&gl=CO&ceid=CO:es"

    # ── 3. Company-targeted RSS feeds ─────────────────────────────
    # Uses search_name (curated) instead of raw company name — avoids "Grupo de" problem.
    # Three distinct queries to maximise recall without flooding generic news.
    company_feeds = [
        (_gnews(f'"{ticker_bvc}"'),                                  ticker_bvc,   "company"),
        (_gnews(f"{search_name} resultados acciones"),               ticker_bvc,   "company"),
        (_gnews(f"{search_name} dividendo utilidades inversión"),    ticker_bvc,   "company"),
    ]

    # ── 4. Market context RSS feeds ───────────────────────────────
    market_feeds = [
        (_gnews("COLCAP BVC bolsa Colombia acciones"),               "BVC / COLCAP", "market"),
        (_gnews("economia Colombia inflacion tasa interés Banrep"),  "Colombia Macro", "market"),
    ]

    # ── 5. Extra feeds from --sources file ────────────────────────
    extra = [(url, cat, "custom") for url, cat in (extra_feeds or [])]

    all_rss = company_feeds + market_feeds + extra
    seen_titles = {n["title"].lower() for n in news}

    for rss_url, category, news_type in all_rss:
        print(f"  📡 RSS [{news_type}]: {category}…")
        try:
            req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            for item in root.findall(".//item")[:12]:
                title      = item.findtext("title", "").strip()
                link       = item.findtext("link", "").strip()
                desc       = item.findtext("description", "")
                pub_date   = item.findtext("pubDate", "")
                source     = item.findtext("source", category)
                desc_clean = re.sub(r"<[^>]+>", "", desc).strip()[:220]
                if not title or title.lower() in seen_titles:
                    continue
                seen_titles.add(title.lower())
                _add({
                    "title":     title,
                    "summary":   desc_clean,
                    "link":      link,
                    "publisher": source,
                    "date":      _parse_pub_date(pub_date),
                    "category":  category,
                }, news_type)
        except Exception as e:
            print(f"  ⚠️  RSS error ({category}): {e}")

    # ── Post-fetch: company feeds that scored 0 get demoted to 'market' ──
    # (e.g., a GRUPOSURA RSS query that returned an unrelated article)
    for n in news:
        if n["news_type"] == "company" and n["relevance"] == 0:
            n["news_type"] = "market"

    # Sort: company articles (relevance desc) first, then market (date desc)
    company_news = sorted([n for n in news if n["news_type"] in ("company","custom")],
                          key=lambda x: (x["relevance"], x["date"] or "0000"), reverse=True)
    market_news  = sorted([n for n in news if n["news_type"] == "market"],
                          key=lambda x: x["date"] or "0000", reverse=True)
    news = company_news + market_news

    n_co   = len(company_news)
    n_mk   = len(market_news)
    n_bull = sum(1 for n in news if n["sentiment"] == "bullish")
    n_bear = sum(1 for n in news if n["sentiment"] == "bearish")
    n_neut = sum(1 for n in news if n["sentiment"] == "neutral")
    print(f"  ✅ {len(news)} articles  |  company: {n_co}  market: {n_mk}  "
          f"|  🟢 {n_bull}  🔴 {n_bear}  ⚪ {n_neut}")
    return news


def render_news_html(news_items: list, ticker_bvc: str = "STOCK") -> str:
    """
    Build the HTML for the News tab.

    Shows two sections: Company News (high-relevance) and Market Context.
    Filter buttons let the user toggle All / Company / Market.
    Each card shows a sentiment badge, relevance dots, source and date.
    """
    if not news_items:
        return ('<div style="text-align:center;padding:40px;color:#8b949e;">'
                '⚠️ No news fetched. Check internet connection or use --no-news.</div>')

    co_news  = [n for n in news_items if n.get("news_type") in ("company", "custom")]
    mk_news  = [n for n in news_items if n.get("news_type") == "market"]

    # Sentiment counts — company news only for the headline pills (more meaningful)
    co_bull = sum(1 for n in co_news if n["sentiment"] == "bullish")
    co_bear = sum(1 for n in co_news if n["sentiment"] == "bearish")
    co_neut = sum(1 for n in co_news if n["sentiment"] == "neutral")

    summary = f"""
<div class="news-topbar">
  <div class="sentiment-summary">
    <div class="sent-pill bullish-pill">🟢 Bullish&nbsp;<strong>{co_bull}</strong></div>
    <div class="sent-pill bearish-pill">🔴 Bearish&nbsp;<strong>{co_bear}</strong></div>
    <div class="sent-pill neutral-pill">⚪ Neutral&nbsp;<strong>{co_neut}</strong></div>
    <div class="sent-pill company-pill">🏢 {ticker_bvc}&nbsp;<strong>{len(co_news)}</strong></div>
    <div class="sent-pill market-pill">🌎 Market&nbsp;<strong>{len(mk_news)}</strong></div>
  </div>
  <div class="news-filters">
    <button class="nf-btn active" onclick="filterNews('all',this)">All</button>
    <button class="nf-btn" onclick="filterNews('company',this)">{ticker_bvc} only</button>
    <button class="nf-btn" onclick="filterNews('market',this)">Market context</button>
  </div>
</div>"""

    def _card(n) -> str:
        sent       = n["sentiment"]
        ntype      = n.get("news_type", "market")
        relevance  = n.get("relevance", 0)
        icon       = "▲" if sent == "bullish" else ("▼" if sent == "bearish" else "→")
        title_esc  = html_lib.escape(n["title"])
        summ_esc   = html_lib.escape(n["summary"]) if n.get("summary") else ""
        pub_esc    = html_lib.escape(n.get("publisher", ""))
        link       = n.get("link", "")
        cat_esc    = html_lib.escape(n.get("category", ""))
        title_html = (f'<a href="{html_lib.escape(link)}" target="_blank" '
                      f'style="color:inherit;text-decoration:none;">{title_esc}</a>'
                      if link else title_esc)
        # Relevance dots: filled dots per keyword hit (max 5 shown)
        dots = min(relevance, 5)
        rel_html = (
            '<span class="rel-dots" title="Company relevance score">'
            + '●' * dots + '○' * (5 - dots)
            + '</span>'
        ) if ntype in ("company", "custom") else ""

        type_badge = (
            f'<span class="ntype-badge ntype-{ntype}">'
            + ("🏢" if ntype == "company" else ("⚙️" if ntype == "custom" else "🌎"))
            + ("</span>")
        )

        return (
            f'<div class="news-card {sent}" data-type="{ntype}">'
            f'  <div class="news-card-header">'
            f'    <span class="news-badge {sent}">{icon} {sent.upper()}</span>'
            f'    <div style="display:flex;gap:4px;align-items:center;">'
            f'      {rel_html}{type_badge}'
            f'      <span class="news-cat">{cat_esc}</span>'
            f'    </div>'
            f'  </div>'
            f'  <div class="news-title">{title_html}</div>'
            + (f'  <div class="news-summary">{summ_esc}</div>' if summ_esc else "")
            + f'  <div class="news-meta"><span class="news-source">{pub_esc}</span>'
            + (f' · {n["date"]}' if n.get("date") else "")
            + '  </div></div>'
        )

    # Company articles first (already sorted by relevance desc from fetch_news),
    # then market articles
    ordered = (
        sorted(co_news, key=lambda x: (x.get("relevance", 0), x.get("date", "")), reverse=True)
        + sorted(mk_news, key=lambda x: x.get("date", ""), reverse=True)
    )
    cards_html = "".join(_card(n) for n in ordered)

    filter_js = """
<script>
function filterNews(type, btn) {
  document.querySelectorAll('.nf-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.news-card').forEach(c => {
    if (type === 'all') { c.style.display = ''; }
    else { c.style.display = (c.dataset.type === type) ? '' : 'none'; }
  });
}
</script>"""

    return summary + f'<div class="news-grid" id="news-grid">{cards_html}</div>' + filter_js


# ══════════════════════════════════════════════════════════════════
# HTML ASSEMBLY
# ══════════════════════════════════════════════════════════════════

def fig_to_div(fig, div_id):
    return pio.to_html(fig, full_html=False, include_plotlyjs=False,
                       div_id=div_id, config={"responsive": True,
                       "modeBarButtonsToRemove": ["lasso2d", "select2d"]})


EXPORT_COLS = ["Open", "High", "Low", "Close", "Volume", "SMA_20", "SMA_50",
               "SMA_200", "RSI", "MACD", "Signal", "Histogram", "ATR",
               "Daily_Return", "Cum_Return", "Rolling_Vol", "Drawdown"]


def export_payload(df: pd.DataFrame) -> dict:
    """Serialise the price + indicator table for client-side CSV/JSON download."""
    cols = [c for c in EXPORT_COLS if c in df.columns]
    rows = []
    for ts, row in df.iterrows():
        r = [ts.strftime("%Y-%m-%d")]
        for c in cols:
            v = row[c]
            r.append(None if pd.isna(v) else round(float(v), 4))
        rows.append(r)
    return {"columns": ["Date"] + cols, "rows": rows}


# Shared client-side export script: turns an embedded {columns, rows} table into
# downloadable CSV/JSON via a Blob — no server, no dependency.
EXPORT_JS = """
function _dl(name, content, mime) {
  const blob = new Blob([content], {type: mime});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(a.href);
}
function _toCSV(tbl) {
  const esc = v => v == null ? '' :
    (/[",\\n]/.test(String(v)) ? '"' + String(v).replace(/"/g,'""') + '"' : v);
  const lines = [tbl.columns.join(',')];
  tbl.rows.forEach(r => lines.push(r.map(esc).join(',')));
  return lines.join('\\n');
}
function exportTable(tbl, base, fmt) {
  if (fmt === 'json') {
    const objs = tbl.rows.map(r =>
      Object.fromEntries(tbl.columns.map((c,i) => [c, r[i]])));
    _dl(base + '.json', JSON.stringify(objs, null, 2), 'application/json');
  } else {
    _dl(base + '.csv', _toCSV(tbl), 'text/csv');
  }
}
"""


def build_html(df: pd.DataFrame, info: dict, period: str,
               interval: str = "1d", news_items: list = None,
               sym: dict = None, fundamentals: dict = None,
               benchmark: dict = None, actions: dict = None) -> str:
    """
    Build a fully self-contained HTML dashboard.

    sym dict keys: bvc, yahoo, company, sector, has_fundamentals, exchange, currency
    """
    # ── Resolve symbol metadata ─────────────────────────────────
    if sym is None:
        sym = BVC_SYMBOLS.get("GRUPOSURA", {})
        sym = {**sym, "bvc": "GRUPOSURA", "exchange": EXCHANGE, "currency": CURRENCY}

    ticker_bvc      = sym.get("bvc", "STOCK")
    ticker_yf       = sym.get("yahoo", f"{ticker_bvc}.CL")
    company         = sym.get("company", ticker_bvc)
    sector          = sym.get("sector", "")
    has_fund        = sym.get("has_fundamentals", False)
    exchange        = sym.get("exchange", EXCHANGE)
    currency        = sym.get("currency", CURRENCY)

    # ── Price / performance stats ────────────────────────────────
    last_close  = df["Close"].iloc[-1]
    prev_close  = df["Close"].iloc[-2]
    chg         = last_close - prev_close
    pct         = chg / prev_close * 100
    last_date   = df.index[-1].strftime("%Y-%m-%d")
    period_ret  = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100
    ann_factor  = np.sqrt(52) if interval == "1wk" else np.sqrt(252)
    ann_vol     = df["Daily_Return"].std() * ann_factor * 100
    sharpe      = sharpe_ratio(df["Daily_Return"], interval)
    max_dd      = max_drawdown(df["Close"]) * 100
    interval_label = "Weekly" if interval == "1wk" else "Daily"

    # ── Benchmark (COLCAP) — beta, excess return, overlay ────────
    beta = excess = None
    bench_cum = None
    bench_label = (benchmark or {}).get("label", "COLCAP")
    if benchmark is not None and benchmark.get("close") is not None:
        bclose = benchmark["close"]
        bret   = bclose.pct_change()
        beta   = calc_beta(df["Daily_Return"], bret)
        bvalid = bclose.dropna()
        if bvalid.size > 1:
            bench_period = (bvalid.iloc[-1] / bvalid.iloc[0] - 1) * 100
            excess = period_ret - bench_period
        bench_cum = (1 + bret).cumprod() - 1

    # ── Yahoo Finance info dict values ──────────────────────────
    pe         = info.get("trailingPE")
    div_yield  = (info.get("dividendYield") or 0) * 100
    mktcap     = info.get("marketCap", 0)
    mktcap_t   = mktcap / 1e12 if mktcap else None
    trailing_eps   = info.get("trailingEps")
    dividend_rate  = info.get("dividendRate")
    trailing_roe   = info.get("returnOnEquity")   # fraction

    chg_color = GREEN if chg >= 0 else RED
    chg_arrow = "▲" if chg >= 0 else "▼"

    # ── Generate Plotly chart divs ────────────────────────────────
    divs = {
        "candle":  fig_to_div(fig_candlestick(df, ticker_bvc), "chart-candle"),
        "volume":  fig_to_div(fig_volume(df),                  "chart-volume"),
        "rsi":     fig_to_div(fig_rsi(df),                     "chart-rsi"),
        "macd":    fig_to_div(fig_macd(df),                    "chart-macd"),
        "atr":     fig_to_div(fig_atr(df),                     "chart-atr"),
        "cum":     fig_to_div(fig_cumulative(df, bench_cum, bench_label), "chart-cum"),
        "dist":    fig_to_div(fig_distribution(df),            "chart-dist"),
        "vol":     fig_to_div(fig_volatility(df),              "chart-vol"),
        "drawdown":fig_to_div(fig_drawdown(df),                "chart-drawdown"),
        "heatmap": fig_to_div(fig_monthly_heatmap(df),         "chart-heatmap"),
    }

    # ── Metric cards (P/E, dividend, ROE, EPS) ──────────────────
    # For GRUPOSURA: use embedded FY2024 data.
    # For other symbols: use Yahoo Finance info dict where available.
    if has_fund:
        metric_pe   = f'<div class="metric-value">{pe:.2f}×</div><div class="metric-sub">Yahoo Finance (TTM)</div>' if pe else '<div class="metric-value">N/A</div>'
        metric_div  = f'<div class="metric-value">{currency} 1,500</div><div class="metric-sub">FY2024 · +7.1% YoY</div>'
        metric_roe  = f'<div class="metric-value" style="color:var(--green)">12.3%</div><div class="metric-sub">FY2024 · +210 bps YoY</div>'
        metric_eps  = f'<div class="metric-value">{currency} 6,144</div><div class="metric-sub">FY2024 · CAGR 18.6% (5yr)</div>'
    else:
        metric_pe   = (f'<div class="metric-value">{pe:.2f}×</div><div class="metric-sub">TTM · Yahoo Finance</div>'
                       if pe else '<div class="metric-value">N/A</div><div class="metric-sub">Yahoo Finance</div>')
        metric_div  = (f'<div class="metric-value">{currency} {dividend_rate:,.0f}</div><div class="metric-sub">Annual · Yahoo Finance</div>'
                       if dividend_rate else '<div class="metric-value">N/A</div><div class="metric-sub">Yahoo Finance</div>')
        metric_roe  = (f'<div class="metric-value">{trailing_roe*100:.1f}%</div><div class="metric-sub">Trailing · Yahoo Finance</div>'
                       if trailing_roe else '<div class="metric-value">N/A</div><div class="metric-sub">Yahoo Finance</div>')
        metric_eps  = (f'<div class="metric-value">{currency} {trailing_eps:,.0f}</div><div class="metric-sub">Trailing EPS · Yahoo Finance</div>'
                       if trailing_eps else '<div class="metric-value">N/A</div><div class="metric-sub">Yahoo Finance</div>')

    metric_divyield = (f'<div class="metric-value">{div_yield:.2f}%</div><div class="metric-sub">Trailing</div>'
                       if div_yield else '<div class="metric-value">N/A</div>')
    metric_mktcap   = (f'<div class="metric-value">{currency} {mktcap_t:.1f}T</div><div class="metric-sub">~{mktcap/1e9:.0f}B {currency} · {exchange}</div>'
                       if mktcap_t else '<div class="metric-value">N/A</div><div class="metric-sub">Yahoo Finance</div>')

    # ── Benchmark cards (rendered only when benchmark data is present) ──
    card_beta = ""
    if beta is not None and not np.isnan(beta):
        card_beta = (
            f'<div class="metric-card"><div class="metric-label">Beta vs {bench_label}</div>'
            f'<div class="metric-value">{beta:.2f}</div>'
            f'<div class="metric-sub">{interval_label} · {bench_label}</div></div>')
    card_excess = ""
    if excess is not None:
        card_excess = (
            f'<div class="metric-card"><div class="metric-label">Excess vs {bench_label}</div>'
            f'<div class="metric-value" style="color:{"var(--green)" if excess>=0 else "var(--red)"}">{excess:+.1f}%</div>'
            f'<div class="metric-sub">{period} · price-based</div></div>')

    # ── Fundamentals tab content ─────────────────────────────────
    if has_fund:
        fund_divs = {
            "rev": fig_to_div(fig_fund_revenue(), "chart-rev"),
            "ni":  fig_to_div(fig_fund_ni(),      "chart-ni"),
            "roe": fig_to_div(fig_fund_roe(),     "chart-roe"),
            "div": fig_to_div(fig_fund_div(),     "chart-div"),
        }
        seg_html = ""
        for seg_name, seg_data in SUBSIDIARIES.items():
            rows = "".join(
                f'<div class="seg-row"><span class="seg-key">{k}</span>'
                f'<span class="seg-val">{v}</span></div>'
                for k, v in seg_data.items()
            )
            seg_html += f'<div class="segment-card"><div class="segment-name">{seg_name}</div>{rows}</div>'

        fund_tab_html = f"""
  <div class="info-note">
    <strong>Fundamental data</strong> sourced from official Grupo SURA press releases (FY2022–FY2024).
    Revenue and income figures in <strong>COP Trillion</strong>.
  </div>
  <div class="chart-row">
    <div class="chart-card">{fund_divs["rev"]}</div>
    <div class="chart-card">{fund_divs["ni"]}</div>
  </div>
  <div class="chart-row">
    <div class="chart-card">{fund_divs["roe"]}</div>
    <div class="chart-card">{fund_divs["div"]}</div>
  </div>
  <div class="chart-card">
    <div style="font-size:13px;font-weight:600;color:var(--text2);margin-bottom:12px;text-transform:uppercase;letter-spacing:.5px;">Annual Performance Summary</div>
    <table class="fund-table">
      <thead><tr><th>Metric</th><th>FY2022</th><th>FY2023</th><th>FY2024</th><th>YoY Δ</th></tr></thead>
      <tbody>
        <tr><td>Revenue (COP T)</td><td>—</td><td>35.5</td><td>37.2</td><td class="pos">+5.4%</td></tr>
        <tr><td>Recurring Revenue (COP T)</td><td>—</td><td>—</td><td>29.3</td><td>—</td></tr>
        <tr><td>Operating Income (COP T)</td><td>—</td><td>4.6 ★</td><td>9.2</td><td class="pos">+100%</td></tr>
        <tr><td>Net Income Adjusted (COP T)</td><td>2.1</td><td>2.3</td><td>2.4</td><td class="pos">+4.3%</td></tr>
        <tr><td>Net Income Reported (COP T)</td><td>—</td><td>1.5</td><td>6.1</td><td class="pos">+294.5%</td></tr>
        <tr><td>ROE Adjusted (%)</td><td>—</td><td>10.2%</td><td>12.3%</td><td class="pos">+210 bps</td></tr>
        <tr><td>EPS Recurring (COP)</td><td>—</td><td>—</td><td>6,144</td><td>—</td></tr>
        <tr><td>Dividend / Share (COP)</td><td>~1,280</td><td>1,400</td><td>1,500</td><td class="pos">+7.1%</td></tr>
        <tr><td>Total Clients (M)</td><td>—</td><td>—</td><td>76.5</td><td>—</td></tr>
      </tbody>
    </table>
  </div>
  <div class="chart-card">
    <div style="font-size:13px;font-weight:600;color:var(--text2);margin-bottom:12px;text-transform:uppercase;letter-spacing:.5px;">Subsidiary Performance — FY2024</div>
    <div class="segment-grid">{seg_html}</div>
  </div>"""
    elif fundamentals and fundamentals.get("available"):
        fund_tab_html = build_yahoo_fund_tab(fundamentals, ticker_bvc, ticker_yf, currency)
    else:
        yf_url = f"https://finance.yahoo.com/quote/{ticker_yf}/financials/"
        fund_tab_html = f"""
  <div class="info-note">
    <strong>Fundamental data</strong> for <strong>{ticker_bvc}</strong> is not embedded in this dashboard.
    Only GRUPOSURA has hand-curated fundamental data (FY2022–2024).
    For {ticker_bvc} financials, visit:
    <a href="{yf_url}" target="_blank">Yahoo Finance — {ticker_bvc} Financials</a>
  </div>
  <div style="text-align:center;padding:60px 20px;color:var(--text2);">
    <div style="font-size:48px;margin-bottom:16px;">📊</div>
    <div style="font-size:16px;font-weight:600;color:var(--text);margin-bottom:8px;">No embedded fundamental data for {ticker_bvc}</div>
    <div style="font-size:13px;max-width:500px;margin:0 auto;">
      Price analytics, technical indicators, returns and news are fully functional above.
      Fundamental data for this ticker can be viewed at Yahoo Finance.
    </div>
    <div style="margin-top:20px;">
      <a href="{yf_url}" target="_blank"
         style="background:var(--blue);color:#000;padding:10px 20px;border-radius:6px;
                text-decoration:none;font-weight:700;font-size:13px;">
        View on Yahoo Finance →
      </a>
    </div>
  </div>"""

    # ── Dividends / corporate-actions tab ────────────────────────
    dividends_html = build_dividends_tab(actions or {}, currency)

    # ── Export data (CSV/JSON download) ──────────────────────────
    export_json = json.dumps(export_payload(df)).replace("</", "<\\/")
    export_base = f"{ticker_bvc.lower()}_{interval}"

    # ── News tab ─────────────────────────────────────────────────
    news_html = render_news_html(news_items or [], ticker_bvc)

    # ── Assemble full HTML ────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{ticker_bvc} — {exchange} Analysis Dashboard</title>
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <style>
    :root {{
      --bg:#0d1117;--bg2:#161b22;--bg3:#21262d;--border:#30363d;
      --text:#e6edf3;--text2:#8b949e;--blue:#58a6ff;--green:#3fb950;
      --red:#f85149;--yellow:#e3b341;--purple:#bc8cff;--orange:#ffa657;--radius:8px;
    }}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    body{{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;font-size:14px;}}
    .header{{background:var(--bg2);border-bottom:1px solid var(--border);padding:18px 24px;
      display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;}}
    .ticker-badge{{background:var(--blue);color:#000;font-weight:700;font-size:11px;
      padding:3px 8px;border-radius:4px;letter-spacing:.5px;}}
    .company-name{{font-size:18px;font-weight:700;}}
    .exchange-tag{{font-size:11px;color:var(--text2);margin-top:2px;}}
    .live-price-wrap{{text-align:right;}}
    .live-price{{font-size:28px;font-weight:700;}}
    .price-change{{font-size:14px;margin-top:2px;color:{chg_color};}}
    .price-date{{font-size:11px;color:var(--text2);margin-top:2px;}}
    .metrics-section{{padding:16px 24px;}}
    .metrics-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:10px;}}
    .metric-card{{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:14px;}}
    .metric-label{{font-size:11px;color:var(--text2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px;}}
    .metric-value{{font-size:18px;font-weight:700;}}
    .metric-sub{{font-size:11px;color:var(--text2);margin-top:3px;}}
    .tabs-bar{{border-bottom:1px solid var(--border);display:flex;padding:0 24px;background:var(--bg2);overflow-x:auto;}}
    .tab-btn{{padding:12px 20px;border:none;background:none;color:var(--text2);font-size:14px;
      cursor:pointer;border-bottom:2px solid transparent;transition:color .2s;margin-bottom:-1px;white-space:nowrap;}}
    .tab-btn:hover{{color:var(--text);}}
    .tab-btn.active{{color:var(--blue);border-bottom-color:var(--blue);font-weight:600;}}
    .tab-pane{{display:none;padding:20px 24px;}}
    .tab-pane.active{{display:block;}}
    .chart-card{{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);
      padding:16px;margin-bottom:14px;}}
    .chart-row{{display:grid;grid-template-columns:1fr 1fr;gap:14px;}}
    @media(max-width:900px){{.chart-row{{grid-template-columns:1fr;}}}}
    .info-note{{background:var(--bg3);border-left:3px solid var(--blue);padding:10px 14px;
      border-radius:0 var(--radius) var(--radius) 0;font-size:12px;color:var(--text2);margin-bottom:14px;}}
    .info-note strong{{color:var(--text);}} .info-note a{{color:var(--blue);}}
    .fund-table{{width:100%;border-collapse:collapse;font-size:13px;}}
    .fund-table th{{text-align:left;padding:8px 12px;color:var(--text2);font-weight:600;
      border-bottom:1px solid var(--border);font-size:11px;}}
    .fund-table td{{padding:8px 12px;border-bottom:1px solid var(--border);}}
    .fund-table tr:last-child td{{border-bottom:none;}}
    .pos{{color:var(--green);}} .neg{{color:var(--red);}}
    .segment-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px;}}
    @media(max-width:700px){{.segment-grid{{grid-template-columns:1fr;}}}}
    .segment-card{{background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);padding:16px;}}
    .segment-name{{font-size:14px;font-weight:700;margin-bottom:10px;color:var(--blue);}}
    .seg-row{{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);}}
    .seg-row:last-child{{border-bottom:none;}}
    .seg-key{{color:var(--text2);font-size:12px;}} .seg-val{{font-weight:600;font-size:12px;}}
    /* ── News ── */
    .news-topbar{{margin-bottom:18px;}}
    .sentiment-summary{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;}}
    .sent-pill{{padding:6px 14px;border-radius:20px;font-size:13px;font-weight:600;}}
    .bullish-pill{{background:rgba(63,185,80,0.15);color:#3fb950;}}
    .bearish-pill{{background:rgba(248,81,73,0.15);color:#f85149;}}
    .neutral-pill{{background:rgba(139,148,158,0.15);color:#8b949e;}}
    .company-pill{{background:rgba(88,166,255,0.15);color:#58a6ff;}}
    .market-pill{{background:rgba(227,179,65,0.15);color:#e3b341;}}
    .news-filters{{display:flex;gap:6px;flex-wrap:wrap;}}
    .nf-btn{{background:var(--bg3);border:1px solid var(--border);color:var(--text2);
      padding:5px 14px;border-radius:20px;font-size:12px;cursor:pointer;transition:all .15s;}}
    .nf-btn:hover{{color:var(--text);border-color:var(--text2);}}
    .nf-btn.active{{background:var(--blue);color:#000;border-color:var(--blue);font-weight:600;}}
    .news-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px;}}
    .news-card{{background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);
      padding:14px;border-left-width:3px;border-left-style:solid;}}
    .news-card.bullish{{border-left-color:#3fb950;}}
    .news-card.bearish{{border-left-color:#f85149;}}
    .news-card.neutral{{border-left-color:#30363d;}}
    .news-card-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;}}
    .news-badge{{font-size:10px;font-weight:700;padding:2px 7px;border-radius:3px;text-transform:uppercase;letter-spacing:.4px;}}
    .news-badge.bullish{{background:rgba(63,185,80,0.15);color:#3fb950;}}
    .news-badge.bearish{{background:rgba(248,81,73,0.15);color:#f85149;}}
    .news-badge.neutral{{background:rgba(139,148,158,0.15);color:#8b949e;}}
    .news-cat{{font-size:10px;color:var(--text2);background:var(--bg2);padding:2px 6px;border-radius:3px;}}
    .news-title{{font-size:13px;font-weight:600;line-height:1.45;margin-bottom:6px;}}
    .news-summary{{font-size:12px;color:var(--text2);line-height:1.4;margin-bottom:6px;
      display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}}
    .news-meta{{font-size:11px;color:var(--text2);margin-top:4px;}}
    .news-source{{font-weight:600;color:var(--blue);}}
    .rel-dots{{font-size:9px;color:var(--blue);letter-spacing:1px;opacity:.8;}}
    .ntype-badge{{font-size:11px;padding:1px 4px;}}
    footer{{border-top:1px solid var(--border);padding:16px 24px;color:var(--text2);font-size:11px;text-align:center;}}
    footer a{{color:var(--blue);text-decoration:none;}}
  </style>
</head>
<body>

<div class="header">
  <div style="display:flex;align-items:center;gap:16px;">
    <span class="ticker-badge">{ticker_bvc}</span>
    <div>
      <div class="company-name">{company}</div>
      <div class="exchange-tag">{exchange} · Colombia · {currency} · {sector} · {interval_label} · {period}</div>
    </div>
  </div>
  <div class="live-price-wrap">
    <div class="live-price">{currency} {last_close:,.0f}</div>
    <div class="price-change">{chg_arrow} {abs(chg):,.0f} ({abs(pct):.2f}%) vs prev close</div>
    <div class="price-date">Last trade: {last_date} · Yahoo Finance</div>
  </div>
</div>

<div class="metrics-section">
  <div class="metrics-grid">
    <div class="metric-card">
      <div class="metric-label">P/E Ratio (TTM)</div>
      {metric_pe}
    </div>
    <div class="metric-card">
      <div class="metric-label">Dividend / Share</div>
      {metric_div}
    </div>
    <div class="metric-card">
      <div class="metric-label">Dividend Yield</div>
      {metric_divyield}
    </div>
    <div class="metric-card">
      <div class="metric-label">ROE</div>
      {metric_roe}
    </div>
    <div class="metric-card">
      <div class="metric-label">EPS</div>
      {metric_eps}
    </div>
    <div class="metric-card">
      <div class="metric-label">{period} Return</div>
      <div class="metric-value" style="color:{'var(--green)' if period_ret>=0 else 'var(--red)'}">{period_ret:+.1f}%</div>
      <div class="metric-sub">Price-based · Yahoo Finance</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Annualised Volatility</div>
      <div class="metric-value">{ann_vol:.1f}%</div>
      <div class="metric-sub">Historical · √{252 if interval=='1d' else 52}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Sharpe Ratio</div>
      <div class="metric-value" style="color:{'var(--green)' if sharpe>=1 else ('var(--text)' if sharpe>=0 else 'var(--red)')}">{sharpe:.2f}</div>
      <div class="metric-sub">Annualised · rf=0</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Max Drawdown</div>
      <div class="metric-value" style="color:var(--red)">{max_dd:.1f}%</div>
      <div class="metric-sub">Peak-to-trough · {interval_label}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Market Cap</div>
      {metric_mktcap}
    </div>
    {card_beta}
    {card_excess}
  </div>
</div>

<div style="padding:0 24px 12px;display:flex;gap:8px;align-items:center;">
  <span style="font-size:11px;color:var(--text2);text-transform:uppercase;letter-spacing:.5px;">Export data</span>
  <button class="nf-btn" onclick="exportTable(EXPORT_DATA,'{export_base}','csv')">⬇ CSV</button>
  <button class="nf-btn" onclick="exportTable(EXPORT_DATA,'{export_base}','json')">⬇ JSON</button>
</div>

<div class="tabs-bar">
  <button class="tab-btn active" onclick="switchTab(this,'technical')">📈 Technical Analysis</button>
  <button class="tab-btn" onclick="switchTab(this,'returns')">📊 Returns &amp; Risk</button>
  <button class="tab-btn" onclick="switchTab(this,'fundamentals')">🏦 Fundamentals</button>
  <button class="tab-btn" onclick="switchTab(this,'dividends')">💰 Dividends</button>
  <button class="tab-btn" onclick="switchTab(this,'news')">📰 News &amp; Sentiment</button>
</div>

<div id="tab-technical" class="tab-pane active">
  <div class="chart-card">{divs["candle"]}</div>
  <div class="chart-card">{divs["volume"]}</div>
  <div class="chart-card">{divs["rsi"]}</div>
  <div class="chart-card">{divs["macd"]}</div>
  <div class="chart-card">{divs["atr"]}</div>
</div>

<div id="tab-returns" class="tab-pane">
  <div class="chart-card">{divs["cum"]}</div>
  <div class="chart-card">{divs["drawdown"]}</div>
  <div class="chart-row">
    <div class="chart-card">{divs["dist"]}</div>
    <div class="chart-card">{divs["vol"]}</div>
  </div>
  <div class="chart-card">{divs["heatmap"]}</div>
</div>

<div id="tab-fundamentals" class="tab-pane">
  {fund_tab_html}
</div>

<div id="tab-dividends" class="tab-pane">
  {dividends_html}
</div>

<div id="tab-news" class="tab-pane">
  <div class="info-note">
    <strong>News &amp; Sentiment</strong> — {ticker_bvc} · BVC · Colombia Macro.
    Sentiment classified with bilingual keyword matching (English + Spanish).
    Always verify before acting on any headline.
  </div>
  {news_html}
</div>

<footer>
  Generated by <strong>sura_tracker.py</strong> on {datetime.now().strftime('%Y-%m-%d %H:%M')} ·
  Ticker: <a href="https://finance.yahoo.com/quote/{ticker_yf}/" target="_blank">{ticker_yf} on Yahoo Finance</a> ·
  <a href="https://www.gruposura.com/en/investor-relations/" target="_blank">Grupo SURA IR</a>
</footer>

<script>
const EXPORT_DATA = {export_json};
{EXPORT_JS}
function switchTab(btn, name) {{
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  btn.classList.add('active');
  window.dispatchEvent(new Event('resize'));
}}
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════
# MULTI-SYMBOL COMPARE  (interactive, client-side)
# ══════════════════════════════════════════════════════════════════

def fetch_multi(history_kwargs: dict, interval: str,
                use_cache: bool = True, max_age_min=60):
    """
    Fetch Close history for every BVC_SYMBOLS ticker, per-symbol through the cache.

    Going symbol-by-symbol (instead of one batch) means a partially rate-limited
    run still renders from whatever is cached; symbols that fail with no cache are
    skipped and refetched on the next run once the limit resets.

    Returns (close_df, companies) — BVC symbols as columns (registry order),
    tz-naive DatetimeIndex (outer-joined across symbols).
    """
    companies = {bvc: meta["company"] for bvc, meta in BVC_SYMBOLS.items()}
    cols = {}
    for bvc, meta in BVC_SYMBOLS.items():
        _, df = resolve_history(bvc, meta, history_kwargs, interval,
                                use_cache=use_cache, max_age_min=max_age_min)
        if df is not None and not df.empty and "Close" in df.columns:
            s = df["Close"]
            if s.index.tz is not None:
                s.index = s.index.tz_localize(None)
            cols[bvc] = s

    if not cols:
        return pd.DataFrame(), companies
    close = pd.DataFrame(cols).sort_index()
    ordered = [b for b in BVC_SYMBOLS if b in close.columns]   # registry order
    return close[ordered], companies


def build_compare_payload(closes: pd.DataFrame, companies: dict) -> dict:
    """Turn an aligned Close DataFrame into a JSON-serialisable payload for the page."""
    closes = closes.dropna(axis=1, how="all").sort_index()
    series = {
        sym: {
            "name":  companies.get(sym, sym),
            "close": [None if pd.isna(v) else round(float(v), 4) for v in closes[sym]],
        }
        for sym in closes.columns
    }
    return {
        "dates":   [d.strftime("%Y-%m-%d") for d in closes.index],
        "symbols": list(closes.columns),
        "series":  series,
    }


COMPARE_COLORS = [BLUE, GREEN, ORANGE, PURPLE, YELLOW, RED, "#2dd4bf",
                  "#f472b6", "#a3e635", "#60a5fa", "#fb923c", "#c084fc",
                  "#34d399", "#facc15"]


def build_compare_html(payload: dict, period_label: str, interval: str,
                       default_n: int = 4) -> str:
    """
    Build a self-contained interactive COLCAP comparison page.

    All symbols' price series are embedded as JSON; the browser recomputes the
    rebased-return overlay, correlation heatmap and stats table whenever the
    selection of symbols changes — no server, GitHub-Pages friendly.
    """
    ann_factor   = 52 if interval == "1wk" else 252
    interval_lbl = "Weekly" if interval == "1wk" else "Daily"
    symbols      = payload["symbols"]
    default_syms = symbols[:default_n]
    missing      = [s for s in BVC_SYMBOLS if s not in symbols]
    coverage_note = (
        f'<p style="color:#e3b341;font-size:12px;margin-top:6px;">⚠️ '
        f'No Yahoo Finance data for: {", ".join(missing)} '
        f'(will be retried on the next run).</p>'
        if missing else
        f'<p style="color:#3fb950;font-size:12px;margin-top:6px;">'
        f'✅ Coverage: all {len(symbols)} symbols.</p>'
    )

    data_json  = json.dumps(payload).replace("</", "<\\/")
    colors_json = json.dumps(COMPARE_COLORS)
    default_json = json.dumps(default_syms)

    chips = "".join(
        f'<button class="chip" data-sym="{s}" onclick="toggleSym(this)">{s}</button>'
        for s in symbols
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>COLCAP Compare — {EXCHANGE}</title>
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <style>
    :root {{
      --bg:#0d1117;--bg2:#161b22;--bg3:#21262d;--border:#30363d;
      --text:#e6edf3;--text2:#8b949e;--blue:#58a6ff;--green:#3fb950;--red:#f85149;--radius:8px;
    }}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    body{{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;font-size:14px;}}
    .header{{background:var(--bg2);border-bottom:1px solid var(--border);padding:18px 24px;}}
    .header h1{{font-size:20px;}}
    .header p{{color:var(--text2);font-size:12px;margin-top:4px;}}
    .controls{{padding:16px 24px;border-bottom:1px solid var(--border);background:var(--bg2);}}
    .controls-label{{font-size:11px;color:var(--text2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px;}}
    .chips{{display:flex;flex-wrap:wrap;gap:8px;}}
    .chip{{background:var(--bg3);border:1px solid var(--border);color:var(--text2);
      padding:6px 12px;border-radius:20px;font-size:12px;font-weight:600;cursor:pointer;transition:all .15s;}}
    .chip:hover{{border-color:var(--text2);color:var(--text);}}
    .chip.active{{background:var(--blue);color:#000;border-color:var(--blue);}}
    .chip-actions{{margin-top:10px;display:flex;gap:8px;}}
    .chip-actions button{{background:none;border:1px solid var(--border);color:var(--text2);
      padding:4px 10px;border-radius:6px;font-size:11px;cursor:pointer;}}
    .chip-actions button:hover{{color:var(--text);border-color:var(--text2);}}
    .section{{padding:20px 24px;}}
    .chart-card{{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:16px;}}
    .chart-row{{display:grid;grid-template-columns:1fr 1fr;gap:16px;}}
    @media(max-width:900px){{.chart-row{{grid-template-columns:1fr;}}}}
    table.cmp{{width:100%;border-collapse:collapse;font-size:13px;}}
    table.cmp th{{text-align:right;padding:8px 12px;color:var(--text2);font-weight:600;font-size:11px;border-bottom:1px solid var(--border);}}
    table.cmp th:first-child,table.cmp td:first-child{{text-align:left;}}
    table.cmp td{{padding:8px 12px;border-bottom:1px solid var(--border);}}
    table.cmp tr:last-child td{{border-bottom:none;}}
    .pos{{color:var(--green);}} .neg{{color:var(--red);}}
    .swatch{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:middle;}}
    .empty{{text-align:center;color:var(--text2);padding:40px;}}
    footer{{border-top:1px solid var(--border);padding:16px 24px;color:var(--text2);font-size:11px;text-align:center;}}
    .card-title{{font-size:13px;font-weight:600;color:var(--text2);margin-bottom:12px;text-transform:uppercase;letter-spacing:.5px;}}
  </style>
</head>
<body>

<div class="header">
  <h1>📊 COLCAP Compare</h1>
  <p>{EXCHANGE} · Colombia · {CURRENCY} · {interval_lbl} · {period_label} · all data precalculated · select symbols below</p>
  {coverage_note}
</div>

<div class="controls">
  <div class="controls-label">Symbols ({len(symbols)} available)</div>
  <div class="chips" id="chips">{chips}</div>
  <div class="chip-actions">
    <button onclick="selectAll()">Select all</button>
    <button onclick="clearAll()">Clear</button>
    <button onclick="exportCompare('csv')">⬇ CSV</button>
    <button onclick="exportCompare('json')">⬇ JSON</button>
  </div>
</div>

<div class="section">
  <div class="chart-card"><div id="overlay" style="height:420px;"></div></div>
  <div class="chart-card"><div class="card-title">Drawdown from Peak (%)</div><div id="ddown" style="height:300px;"></div></div>
  <div class="chart-row">
    <div class="chart-card"><div class="card-title">Return Correlation</div><div id="corr" style="height:360px;"></div></div>
    <div class="chart-card"><div class="card-title">Summary</div><div id="stats"></div></div>
  </div>
  <div class="chart-card">
    <div class="card-title">Rolling Correlation
      <select id="rollwin" onchange="renderRollCorr()" style="background:var(--bg3);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:2px 6px;margin-left:8px;">
        <option value="20">20</option><option value="30" selected>30</option>
        <option value="60">60</option><option value="90">90</option>
      </select> bars · pick exactly two symbols
    </div>
    <div id="rollcorr" style="height:300px;"></div>
  </div>
</div>

<footer>
  Generated by <strong>sura_tracker.py --compare</strong> on {datetime.now().strftime('%Y-%m-%d %H:%M')} ·
  Rebased to 100 at the first common date · Sharpe rf=0 · √{ann_factor} annualisation.
</footer>

<script>
const DATA = {data_json};
const COLORS = {colors_json};
const ANN = Math.sqrt({ann_factor});
const CUR = "{CURRENCY}";
let selected = {default_json};

const PLOT_CFG = {{responsive:true, displayModeBar:false}};
const AXIS = {{gridcolor:'#30363d', zerolinecolor:'#30363d', color:'#8b949e'}};
const LAYOUT_BASE = {{
  paper_bgcolor:'#161b22', plot_bgcolor:'#161b22',
  font:{{color:'#e6edf3', family:'Segoe UI, system-ui, sans-serif', size:12}},
  margin:{{l:55,r:20,t:30,b:40}}, legend:{{bgcolor:'#161b22', bordercolor:'#30363d'}},
  hovermode:'x unified'
}};

function colorFor(sym) {{ return COLORS[DATA.symbols.indexOf(sym) % COLORS.length]; }}
function mean(a) {{ return a.reduce((x,y)=>x+y,0)/a.length; }}
function std(a) {{ const m=mean(a); return Math.sqrt(a.reduce((s,v)=>s+(v-m)*(v-m),0)/(a.length-1)); }}

function pearson(a, b) {{
  const ma=mean(a), mb=mean(b); let num=0, da=0, db=0;
  for (let i=0;i<a.length;i++) {{ const x=a[i]-ma, y=b[i]-mb; num+=x*y; da+=x*x; db+=y*y; }}
  return (da===0||db===0) ? 0 : num/Math.sqrt(da*db);
}}

// Indices where every selected symbol has a non-null close (common window).
function commonMask(syms) {{
  const out=[];
  for (let i=0;i<DATA.dates.length;i++) {{
    if (syms.every(s => DATA.series[s].close[i] != null)) out.push(i);
  }}
  return out;
}}

function rets(closes) {{
  const r=[]; for (let i=1;i<closes.length;i++) r.push(closes[i]/closes[i-1]-1); return r;
}}

function render() {{
  document.querySelectorAll('.chip').forEach(c =>
    c.classList.toggle('active', selected.includes(c.dataset.sym)));

  updateHash();

  if (selected.length === 0) {{
    Plotly.purge('overlay'); Plotly.purge('corr'); Plotly.purge('ddown');
    Plotly.purge('rollcorr');
    document.getElementById('overlay').innerHTML =
      '<div class="empty">Select one or more symbols to compare.</div>';
    document.getElementById('corr').innerHTML = '';
    document.getElementById('stats').innerHTML = '';
    document.getElementById('rollcorr').innerHTML = '';
    return;
  }}

  const mask = commonMask(selected);
  const dates = mask.map(i => DATA.dates[i]);

  // ── Rebased overlay (=100 at first common date) ──
  const traces = selected.map(s => {{
    const c = mask.map(i => DATA.series[s].close[i]);
    const base = c[0];
    return {{x:dates, y:c.map(v => v/base*100), name:s, mode:'lines',
             line:{{color:colorFor(s), width:1.8}}}};
  }});
  Plotly.react('overlay', traces, Object.assign({{}}, LAYOUT_BASE, {{
    title:{{text:'Rebased Price (=100 at first common date)', font:{{size:13,color:'#8b949e'}}}},
    xaxis:Object.assign({{}},AXIS), yaxis:Object.assign({{title:'Index'}},AXIS)
  }}), PLOT_CFG);

  // ── Drawdown overlay (peak-to-trough %, per symbol over common window) ──
  const ddTraces = selected.map(s => {{
    const c = mask.map(i => DATA.series[s].close[i]);
    let peak = -Infinity;
    const dd = c.map(v => {{ peak = Math.max(peak, v); return (v/peak - 1)*100; }});
    return {{x:dates, y:dd, name:s, mode:'lines', line:{{color:colorFor(s), width:1.5}}}};
  }});
  Plotly.react('ddown', ddTraces, Object.assign({{}}, LAYOUT_BASE, {{
    xaxis:Object.assign({{}},AXIS), yaxis:Object.assign({{title:'Drawdown (%)', rangemode:'tozero'}},AXIS)
  }}), PLOT_CFG);

  // ── Correlation heatmap of returns ──
  const retMap = {{}};
  selected.forEach(s => retMap[s] = rets(mask.map(i => DATA.series[s].close[i])));
  const z = selected.map(a => selected.map(b => +pearson(retMap[a], retMap[b]).toFixed(2)));
  Plotly.react('corr', [{{
    z:z, x:selected, y:selected, type:'heatmap', zmin:-1, zmax:1,
    colorscale:[[0,'#f85149'],[0.5,'#21262d'],[1,'#3fb950']],
    text:z, texttemplate:'%{{text}}', showscale:true
  }}], Object.assign({{}}, LAYOUT_BASE, {{
    xaxis:Object.assign({{}},AXIS), yaxis:Object.assign({{autorange:'reversed'}},AXIS)
  }}), PLOT_CFG);

  // ── Stats table ──
  let rows = '';
  selected.forEach(s => {{
    const c = mask.map(i => DATA.series[s].close[i]);
    const r = retMap[s];
    const periodRet = (c[c.length-1]/c[0]-1)*100;
    const vol = std(r)*ANN*100;
    const sharpe = std(r)===0 ? NaN : mean(r)/std(r)*ANN;
    const cls = periodRet>=0 ? 'pos' : 'neg';
    rows += `<tr>
      <td><span class="swatch" style="background:${{colorFor(s)}}"></span>${{s}}</td>
      <td class="${{cls}}">${{periodRet>=0?'+':''}}${{periodRet.toFixed(1)}}%</td>
      <td>${{vol.toFixed(1)}}%</td>
      <td>${{isNaN(sharpe)?'—':sharpe.toFixed(2)}}</td>
      <td>${{CUR}} ${{Math.round(c[c.length-1]).toLocaleString()}}</td>
    </tr>`;
  }});
  document.getElementById('stats').innerHTML = `
    <div style="font-size:11px;color:#8b949e;margin-bottom:8px;">Common window: ${{dates.length}} bars` +
    (dates.length ? ` · ${{dates[0]}} → ${{dates[dates.length-1]}}` : '') + `</div>
    <table class="cmp"><thead><tr>
      <th>Symbol</th><th>Return</th><th>Ann. Vol</th><th>Sharpe</th><th>Last</th>
    </tr></thead><tbody>${{rows}}</tbody></table>`;

  renderRollCorr();
}}

function renderRollCorr() {{
  const el = document.getElementById('rollcorr');
  if (selected.length !== 2) {{
    Plotly.purge('rollcorr');
    el.innerHTML = '<div class="empty">Select exactly two symbols to see their rolling correlation.</div>';
    return;
  }}
  el.innerHTML = '';
  const win = parseInt(document.getElementById('rollwin').value, 10);
  const mask = commonMask(selected);
  const [a, b] = selected;
  const ra = rets(mask.map(i => DATA.series[a].close[i]));
  const rb = rets(mask.map(i => DATA.series[b].close[i]));
  if (ra.length < win) {{
    el.innerHTML = '<div class="empty">Not enough common history for this window.</div>';
    return;
  }}
  const y = rollingCorr2(ra, rb, win);
  const x = mask.slice(win).map(i => DATA.dates[i]);
  Plotly.react('rollcorr', [{{x:x, y:y, mode:'lines', name:`${{a}} vs ${{b}}`,
    line:{{color:'#58a6ff', width:1.8}}}}], Object.assign({{}}, LAYOUT_BASE, {{
    title:{{text:`${{a}} vs ${{b}} · ${{win}}-bar rolling correlation`, font:{{size:13,color:'#8b949e'}}}},
    xaxis:Object.assign({{}},AXIS), yaxis:Object.assign({{range:[-1,1]}},AXIS)
  }}), PLOT_CFG);
}}

function rollingCorr2(a, b, win) {{
  const out = [];
  for (let i = win; i <= a.length; i++) out.push(+pearson(a.slice(i-win, i), b.slice(i-win, i)).toFixed(3));
  return out;
}}

function applyHash() {{
  const h = decodeURIComponent(location.hash.replace(/^#/, '')).trim();
  if (!h) return false;
  const want = h.split(',').map(s => s.trim().toUpperCase()).filter(s => DATA.symbols.includes(s));
  if (want.length) {{ selected = want; return true; }}
  return false;
}}

function updateHash() {{
  const target = '#' + selected.join(',');
  if (location.hash !== target) history.replaceState(null, '', selected.length ? target : location.pathname);
}}

function toggleSym(btn) {{
  const s = btn.dataset.sym;
  selected = selected.includes(s) ? selected.filter(x=>x!==s) : [...selected, s];
  render();
}}
function selectAll() {{ selected = [...DATA.symbols]; render(); }}
function clearAll() {{ selected = []; render(); }}

{EXPORT_JS}
function exportCompare(fmt) {{
  if (!selected.length) return;
  const mask = commonMask(selected);
  const cols = ['Date', ...selected];
  const rows = mask.map(i => [DATA.dates[i], ...selected.map(s => DATA.series[s].close[i])]);
  exportTable({{columns: cols, rows: rows}}, 'colcap_compare', fmt);
}}

applyHash();           // restore a shared selection from the URL, if present
render();
window.addEventListener('hashchange', () => {{ if (applyHash()) render(); }});
window.addEventListener('resize', () => {{
  ['overlay','corr','ddown','rollcorr'].forEach(id => {{ try {{ Plotly.Plots.resize(id); }} catch(e) {{}} }});
}});
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════
# PERIOD PARSING
# ══════════════════════════════════════════════════════════════════

_NATIVE_PERIODS = {"1d","5d","1mo","3mo","6mo","1y","2y","3y","5y","10y","ytd","max"}

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
            "1d":"1 Day","5d":"5 Days","1mo":"1 Month","3mo":"3 Months",
            "6mo":"6 Months","1y":"1 Year","2y":"2 Years","3y":"3 Years",
            "5y":"5 Years","10y":"10 Years","ytd":"YTD","max":"Max",
        }
        return {"period": s}, label_map.get(s, s.upper())

    # Custom weeks: Xwk
    m = re.fullmatch(r"(\d+)wk", s)
    if m:
        weeks = int(m.group(1))
        if weeks < 1:
            raise ValueError("Weeks must be ≥ 1")
        from datetime import timedelta
        start = (datetime.now() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
        return {"start": start}, f"{weeks} Week{'s' if weeks > 1 else ''}"

    # Custom months: Xmo (non-native)
    m = re.fullmatch(r"(\d+)mo", s)
    if m:
        months = int(m.group(1))
        if months < 1:
            raise ValueError("Months must be ≥ 1")
        from datetime import timedelta
        start = (datetime.now() - timedelta(days=round(months * 30.44))).strftime("%Y-%m-%d")
        return {"start": start}, f"{months} Month{'s' if months > 1 else ''}"

    raise ValueError(
        f"Unrecognised period '{period_str}'.\n"
        "  Weeks  : 1wk, 2wk, 4wk, 6wk, 8wk, 12wk, 26wk, 52wk …\n"
        "  Months : 1mo, 2mo, 3mo, 6mo, 9mo, 12mo, 18mo …\n"
        "  Years  : 1y, 2y, 3y, 5y, 10y\n"
        "  Other  : 1d, 5d, ytd, max"
    )


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

def run_compare(args):
    """Fetch every COLCAP symbol and write the interactive comparison page."""
    try:
        history_kwargs, period_label = parse_period(args.period)
    except ValueError as e:
        print(f"\n❌ Invalid --period: {e}")
        sys.exit(1)

    output_file    = args.output or "compare.html"
    interval_label = "Weekly" if args.interval == "1wk" else "Daily"

    print(f"\n{'═'*62}")
    print(f"  COLCAP Compare — {len(BVC_SYMBOLS)} symbols")
    print(f"  Period   : {args.period} ({period_label})  |  Interval: {args.interval} ({interval_label})")
    print(f"  Output   : {output_file}")
    print(f"{'═'*62}\n")

    print("📡 Downloading all COLCAP symbols from Yahoo Finance…")
    closes, companies = fetch_multi(history_kwargs, args.interval,
                                    use_cache=not args.no_cache,
                                    max_age_min=args.cache_ttl)
    got = [c for c in closes.columns if closes[c].notna().any()]
    print(f"  ✅ Data for {len(got)}/{len(BVC_SYMBOLS)} symbols: {'  '.join(got)}")
    if not got:
        print("\n❌ No price data returned for any symbol. Try again later.")
        sys.exit(1)

    payload = build_compare_payload(closes, companies)
    html_content = build_compare_html(payload, period_label, args.interval)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    size_kb = os.path.getsize(output_file) / 1024
    print(f"\n✅ Comparison page saved: {output_file}  ({size_kb:.0f} KB)")
    print(f"\n  Open in browser: file://{os.path.abspath(output_file)}\n")


def main():
    # Build the list of available symbols for the help text
    sym_list = "  ".join(sorted(BVC_SYMBOLS.keys()))

    parser = argparse.ArgumentParser(
        description="Generate a BVC stock analysis dashboard (HTML)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            f"Available --symbol values:\n  {sym_list}\n"
            "  (any other BVC ticker is tried as TICKER.CL on Yahoo Finance)\n\n"
            "Period examples:\n"
            "  Weeks  : 1wk  2wk  4wk  6wk  8wk  12wk  26wk  52wk\n"
            "  Months : 1mo  2mo  3mo  6mo  9mo  12mo  18mo\n"
            "  Years  : 1y  2y  3y  5y  10y\n"
            "  Other  : 1d  5d  ytd  max\n\n"
            "sources.txt format:\n"
            "  # comment\n"
            "  https://www.larepublica.co/rss/economia\n"
            "  https://www.portafolio.co/rss.xml | Portafolio\n\n"
            "Examples:\n"
            "  python sura_tracker.py\n"
            "  python sura_tracker.py --symbol ECOPETROL --period 1y\n"
            "  python sura_tracker.py --symbol BANCOLOMBIA --interval 1wk --period 2y\n"
            "  python sura_tracker.py --sources my_feeds.txt --period 6mo\n"
            "  python sura_tracker.py --symbol GRUPOSURA --period 5y --interval 1wk --no-news\n"
        )
    )
    parser.add_argument(
        "--symbol", default="GRUPOSURA", metavar="TICKER",
        help="BVC ticker symbol. Default: GRUPOSURA. Use --help for full list."
    )
    parser.add_argument(
        "--period", default="2y",
        help="Data range (4wk / 6mo / 2y / ytd / max …). Default: 2y"
    )
    parser.add_argument(
        "--interval", default="1d", choices=["1d", "1wk"],
        help="Candle interval: daily (1d) or weekly (1wk). Default: 1d"
    )
    parser.add_argument(
        "--output", default=None,
        help="Output HTML filename. Default: {SYMBOL}_dashboard.html"
    )
    parser.add_argument(
        "--sources", default=None, metavar="FILE",
        help="Path to .txt file with custom RSS news sources"
    )
    parser.add_argument(
        "--no-news", action="store_true",
        help="Skip news fetching (faster, offline-friendly)"
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="Generate the interactive COLCAP comparison page (all symbols)"
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Bypass the local price cache (always fetch fresh from Yahoo)"
    )
    parser.add_argument(
        "--no-benchmark", action="store_true",
        help="Skip the COLCAP benchmark fetch (no beta / excess-return cards)"
    )
    parser.add_argument(
        "--cache-ttl", type=int, default=60, metavar="MIN",
        help="Cache freshness window in minutes (default: 60). Older entries refetch."
    )
    args = parser.parse_args()

    # ── Compare mode: build the all-symbols comparison page and exit ──
    if args.compare:
        run_compare(args)
        return

    # ── Resolve symbol ──────────────────────────────────────────
    sym_key = args.symbol.upper().strip()
    if sym_key in BVC_SYMBOLS:
        sym = {**BVC_SYMBOLS[sym_key], "bvc": sym_key,
               "exchange": EXCHANGE, "currency": CURRENCY}
    else:
        print(f"  ⚠️  '{sym_key}' not in BVC_SYMBOLS registry.")
        print(f"  ℹ️  Attempting {sym_key}.CL on Yahoo Finance…")
        sym = {
            "bvc":              sym_key,
            "yahoo":            f"{sym_key}.CL",
            "company":          sym_key,
            "sector":           "Unknown",
            "has_fundamentals": False,
            "exchange":         EXCHANGE,
            "currency":         CURRENCY,
        }

    # ── Default output filename ─────────────────────────────────
    output_file = args.output or f"{sym_key.lower()}_dashboard.html"

    # ── Parse and validate period ───────────────────────────────
    try:
        history_kwargs, period_label = parse_period(args.period)
    except ValueError as e:
        print(f"\n❌ Invalid --period: {e}")
        sys.exit(1)

    interval_label = "Weekly" if args.interval == "1wk" else "Daily"

    print(f"\n{'═'*62}")
    print(f"  BVC Dashboard Generator")
    print(f"  Symbol   : {sym_key}  ({sym['yahoo']})  —  {sym['company']}")
    print(f"  Sector   : {sym['sector']}")
    print(f"  Period   : {args.period} ({period_label})  |  Interval: {args.interval} ({interval_label})")
    print(f"  Output   : {output_file}")
    if args.sources:
        print(f"  Sources  : {args.sources}")
    print(f"{'═'*62}\n")

    # ── Load extra news sources ─────────────────────────────────
    extra_feeds = []
    if args.sources:
        print("📄 Loading custom news sources…")
        extra_feeds = load_extra_sources(args.sources)

    # ── Fetch price data (resolver + cache-first, multi-tier) ────
    print(f"📡 Fetching price data from Yahoo Finance ({sym['yahoo']})…")
    ticker, df = resolve_history(sym["bvc"], sym, history_kwargs, args.interval,
                                 use_cache=not args.no_cache, max_age_min=args.cache_ttl)
    if ticker != sym["yahoo"]:
        print(f"  ℹ️  Resolved {sym['yahoo']} → {ticker}")
        sym["yahoo"] = ticker
    stock = yf.Ticker(ticker)

    if df.empty:
        print(f"\n❌ All fetch attempts failed for {ticker}.")
        print("   Possible causes:")
        print("   • Invalid ticker — check that it trades on BVC (.CL suffix on Yahoo Finance)")
        print("   • Yahoo Finance API rate-limited or down — try again in a few minutes")
        print("   • Upgrade yfinance:  pip install --upgrade yfinance")
        sys.exit(1)

    # Ensure timezone-naive index
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    bars = "bars" if args.interval == "1wk" else "trading days"
    print(f"✅ Downloaded {len(df)} {bars} ({df.index[0].date()} → {df.index[-1].date()})")

    # ── Technical indicators ────────────────────────────────────
    print("🔢 Calculating technical indicators…")
    df = calc_indicators(df, interval=args.interval)

    # ── Quote info ──────────────────────────────────────────────
    print("📊 Fetching quote info…")
    try:
        info = stock.info
    except Exception:
        info = {}
        print("⚠️  Could not fetch info dict — using defaults.")

    # ── Fundamentals (Yahoo) — skip for curated GRUPOSURA ────────
    fundamentals = None
    if not sym.get("has_fundamentals"):
        print("🏦 Fetching fundamentals from Yahoo Finance…")
        fundamentals = fetch_fundamentals(stock)
        if fundamentals.get("available"):
            print(f"  ✅ Fundamentals for {len(fundamentals['years'])} fiscal year(s).")
        else:
            print("  ℹ️  No fundamentals available on Yahoo for this ticker.")

    # ── Benchmark (COLCAP) ───────────────────────────────────────
    benchmark = None
    if not args.no_benchmark and sym["bvc"] != BENCHMARK["label"]:
        print("📉 Fetching COLCAP benchmark…")
        _, bdf = resolve_history("ICOLCAP", BENCHMARK, history_kwargs, args.interval,
                                 use_cache=not args.no_cache, max_age_min=args.cache_ttl)
        if not bdf.empty and "Close" in bdf.columns:
            bclose = bdf["Close"]
            if bclose.index.tz is not None:
                bclose.index = bclose.index.tz_localize(None)
            benchmark = {"label": BENCHMARK["label"],
                         "close": bclose.reindex(df.index).ffill()}
            print("  ✅ Benchmark loaded.")
        else:
            print("  ℹ️  COLCAP benchmark unavailable — skipping beta/excess.")

    # ── Dividends & corporate actions ────────────────────────────
    print("💰 Fetching dividends & splits…")
    actions = fetch_actions(stock)
    print(f"  ✅ {len(actions['dividends'])} dividend(s), {len(actions['splits'])} split(s).")

    # ── News ────────────────────────────────────────────────────
    news_items = []
    if not args.no_news:
        print("📰 Fetching news & classifying sentiment…")
        news_items = fetch_news(stock, sym, extra_feeds)
    else:
        print("⏭️  Skipping news (--no-news)")

    # ── Build HTML ──────────────────────────────────────────────
    print("🎨 Building Plotly charts…")
    html_content = build_html(df, info, period_label,
                              interval=args.interval,
                              news_items=news_items,
                              sym=sym, fundamentals=fundamentals,
                              benchmark=benchmark, actions=actions)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    size_kb = os.path.getsize(output_file) / 1024
    print(f"\n✅ Dashboard saved: {output_file}  ({size_kb:.0f} KB)")

    # ── Quick stats ─────────────────────────────────────────────
    print(f"\n{'─'*62}")
    print(f"  Quick stats — {sym_key}")
    print(f"  Period      : {period_label}  |  Interval: {args.interval} ({interval_label})")
    print(f"  Last close  : {CURRENCY} {df['Close'].iloc[-1]:,.0f}")
    print(f"  Period ret  : {(df['Close'].iloc[-1]/df['Close'].iloc[0]-1)*100:+.1f}%")
    ann_f = np.sqrt(52) if args.interval == "1wk" else np.sqrt(252)
    print(f"  Ann. vol    : {df['Daily_Return'].std()*ann_f*100:.1f}%")
    print(f"  Sharpe      : {sharpe_ratio(df['Daily_Return'], args.interval):.2f}")
    print(f"  Max drawdown: {max_drawdown(df['Close'])*100:.1f}%")
    last_rsi  = df["RSI"].dropna().iloc[-1]
    rsi_note  = "Overbought" if last_rsi > 70 else ("Oversold" if last_rsi < 30 else "Neutral")
    print(f"  RSI (14)    : {last_rsi:.1f} → {rsi_note}")
    last_macd = df["MACD"].dropna().iloc[-1]
    last_sig  = df["Signal"].dropna().iloc[-1]
    print(f"  MACD signal : {'Bullish ▲' if last_macd > last_sig else 'Bearish ▼'} "
          f"(MACD={last_macd:.1f}, Signal={last_sig:.1f})")
    print(f"{'─'*62}")
    print(f"\n  Open in browser: file://{os.path.abspath(output_file)}\n")


if __name__ == "__main__":
    main()
