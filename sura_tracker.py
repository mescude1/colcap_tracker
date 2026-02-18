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

import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio


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
    df["Daily_Return"] = close.pct_change()
    df["Cum_Return"]   = (1 + df["Daily_Return"]).cumprod() - 1
    df["Rolling_Vol"]  = df["Daily_Return"].rolling(vol_window).std() * ann_factor * 100
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


def fig_cumulative(df):
    dates = df.index.strftime("%Y-%m-%d").tolist()
    cum   = (df["Cum_Return"] * 100).round(2).tolist()
    fig = go.Figure(go.Scatter(x=dates, y=cum, name="Cumulative Return",
        line=dict(color=BLUE, width=2),
        fill="tozeroy", fillcolor="rgba(88,166,255,0.1)"))
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


def build_html(df: pd.DataFrame, info: dict, period: str,
               interval: str = "1d", news_items: list = None,
               sym: dict = None) -> str:
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
    interval_label = "Weekly" if interval == "1wk" else "Daily"

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
        "cum":     fig_to_div(fig_cumulative(df),              "chart-cum"),
        "dist":    fig_to_div(fig_distribution(df),            "chart-dist"),
        "vol":     fig_to_div(fig_volatility(df),              "chart-vol"),
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
      <div class="metric-label">Market Cap</div>
      {metric_mktcap}
    </div>
  </div>
</div>

<div class="tabs-bar">
  <button class="tab-btn active" onclick="switchTab(this,'technical')">📈 Technical Analysis</button>
  <button class="tab-btn" onclick="switchTab(this,'returns')">📊 Returns &amp; Risk</button>
  <button class="tab-btn" onclick="switchTab(this,'fundamentals')">🏦 Fundamentals</button>
  <button class="tab-btn" onclick="switchTab(this,'news')">📰 News &amp; Sentiment</button>
</div>

<div id="tab-technical" class="tab-pane active">
  <div class="chart-card">{divs["candle"]}</div>
  <div class="chart-card">{divs["volume"]}</div>
  <div class="chart-card">{divs["rsi"]}</div>
  <div class="chart-card">{divs["macd"]}</div>
</div>

<div id="tab-returns" class="tab-pane">
  <div class="chart-card">{divs["cum"]}</div>
  <div class="chart-row">
    <div class="chart-card">{divs["dist"]}</div>
    <div class="chart-card">{divs["vol"]}</div>
  </div>
  <div class="chart-card">{divs["heatmap"]}</div>
</div>

<div id="tab-fundamentals" class="tab-pane">
  {fund_tab_html}
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
    args = parser.parse_args()

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

    # ── Fetch price data (with multi-tier fallback) ──────────────
    print(f"📡 Fetching price data from Yahoo Finance ({sym['yahoo']})…")
    stock  = yf.Ticker(sym["yahoo"])
    ticker = sym["yahoo"]

    def _normalise_df(raw: pd.DataFrame) -> pd.DataFrame:
        """Flatten MultiIndex columns (yf.download single-ticker) and tz-strip index."""
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        if raw.index.tz is not None:
            raw.index = raw.index.tz_localize(None)
        return raw

    df = pd.DataFrame()

    # ── Attempt 1: stock.history() ─────────────────────────────
    try:
        df = stock.history(**history_kwargs, interval=args.interval)
        if not df.empty:
            print("  ✅ stock.history() succeeded.")
    except (TypeError, KeyError, Exception) as e:
        print(f"  ⚠️  stock.history() failed: {type(e).__name__}: {e}")

    # ── Attempt 2: yf.download() (different code path) ─────────
    if df.empty:
        print("  🔄 Retrying with yf.download()…")
        try:
            dl_kwargs = {**history_kwargs, "interval": args.interval,
                        "progress": False, "auto_adjust": True}
            df = yf.download(ticker, **dl_kwargs)
            if not df.empty:
                df = _normalise_df(df)
                print("  ✅ yf.download() succeeded.")
        except Exception as e:
            print(f"  ⚠️  yf.download() failed: {type(e).__name__}: {e}")

    # ── Attempt 3: native period="2y" fallback ──────────────────
    if df.empty and "start" in history_kwargs:
        print("  🔄 Retrying with native period=2y (ignoring custom start date)…")
        try:
            df = yf.download(ticker, period="2y", interval=args.interval,
                             progress=False, auto_adjust=True)
            if not df.empty:
                df = _normalise_df(df)
                period_label = "2 Years (fallback)"
                print("  ✅ Native period=2y fallback succeeded.")
        except Exception as e:
            print(f"  ⚠️  Native period fallback failed: {type(e).__name__}: {e}")

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
                              sym=sym)

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
