# Colcap Tracker — BVC Stock Dashboard

Interactive HTML dashboards for stocks on the **Bolsa de Valores de Colombia (BVC)**, generated with Python + Plotly and served via GitHub Pages.

---

## ⚡ Quick start — GitHub Actions

### 1 · Push this folder to a GitHub repo

```bash
cd "Colcap Tracker"
git init
git add sura_tracker.py sources_example.txt .github/
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

### 2 · Enable GitHub Pages

Go to your repo → **Settings → Pages**

| Setting | Value |
|---------|-------|
| Source | **Deploy from a branch** |
| Branch | **gh-pages** / root |

Click **Save**. (The `gh-pages` branch is created automatically on the first workflow run.)

### 3 · Run the workflow

Go to **Actions → BVC Dashboard Generator → Run workflow**

Pick your inputs:

| Input | Options | Default |
|-------|---------|---------|
| Symbol | GRUPOSURA, ECOPETROL, BANCOLOMBIA, … | GRUPOSURA |
| Period | 2y, 1y, 6mo, 3mo, ytd, max, 26wk … | 2y |
| Interval | 1d (daily), 1wk (weekly) | 1d |
| Skip news | true / false | false |

### 4 · Get the shareable link

After the run completes (~2 min), the link appears in the **job summary** (the ✅ box in the Actions UI):

```
https://YOUR_USERNAME.github.io/YOUR_REPO/gruposura_2y_1d.html
```

An **index page** listing all generated dashboards is also kept at:
```
https://YOUR_USERNAME.github.io/YOUR_REPO/index.html
```

> Dashboards accumulate — each symbol/period/interval combination gets its own file.
> Re-running with the same inputs overwrites that file with fresh data.

---

## 🖥 Run locally

```bash
# Create and activate a virtual environment (optional but recommended)
python -m venv colcap
source colcap/bin/activate          # macOS/Linux
# colcap\Scripts\activate           # Windows

# Install dependencies
pip install yfinance plotly pandas numpy

# Run (defaults: GRUPOSURA, 2-year, daily candles)
python sura_tracker.py

# Examples
python sura_tracker.py --symbol ECOPETROL --period 1y
python sura_tracker.py --symbol BANCOLOMBIA --interval 1wk --period 2y
python sura_tracker.py --symbol GRUPOSURA --period 6mo --no-news
python sura_tracker.py --sources sources_example.txt

# Interactive comparison of ALL COLCAP symbols in one page
python sura_tracker.py --compare
python sura_tracker.py --compare --period 1y --interval 1wk --output compare.html

# Signal scan across all COLCAP symbols → alerts.html
python sura_tracker.py --alerts

# Weighted portfolio page (editable weights, blended risk/return) → portfolio.html
python sura_tracker.py --portfolio "GRUPOSURA:0.4,ECOPETROL:0.3,ISA:0.3"

# Cache controls (resilient to Yahoo rate-limits) and benchmark toggle
python sura_tracker.py --symbol ISA --cache-ttl 120
python sura_tracker.py --symbol ISA --no-cache --no-benchmark
```

The generated HTML file opens in any browser — no server needed.

---

## 📊 Compare mode (interactive)

`--compare` builds a single self-contained `compare.html` with **every COLCAP
symbol precalculated and embedded**. Open it and pick symbols from the selector —
the browser recomputes everything client-side (no server):

- **Rebased price overlay** — all selected symbols indexed to 100 at the first common date
- **Return-correlation heatmap** — pairwise Pearson correlation of daily/weekly returns
- **Summary table** — period return, annualised volatility, Sharpe ratio and last price

Symbols with no Yahoo Finance data for the chosen period are skipped automatically.

---

## 🔔 Alerts & 📦 Portfolio

- **`--alerts`** scans every COLCAP symbol and writes a **Buy/Sell board**: each
  symbol gets a **BUY / SELL / HOLD verdict** (from trend, RSI, MACD, Bollinger and
  momentum) plus any fresh events, sorted by conviction. Wired into the hourly workflow.
- **`--portfolio "SYM:weight,…"`** builds an interactive page where you edit weights
  in the browser and see blended cumulative return, annualised volatility, Sharpe,
  and covariance-based **contribution-to-risk** recompute live.

## 📈 Per-symbol analytics

Each dashboard includes candlesticks + Bollinger/MAs, volume, RSI, MACD, **ATR(14)**,
cumulative returns (with a **COLCAP benchmark overlay** + **beta** / excess-return
cards), **drawdown-from-peak**, return distribution, rolling volatility and a monthly
heatmap. A sticky **signals sidebar** shows a **BUY/SELL verdict** with the per-signal
posture (trend, RSI, MACD, Bollinger, momentum). Header metric cards include
**Sharpe ratio** and **max drawdown**. There are
**Fundamentals** and **Dividends** tabs pulled live from Yahoo Finance (GRUPOSURA keeps
its hand-curated FY2022–2024 data), and a **CSV/JSON export** button.

A local price **cache** (`.cache/`) makes reruns fast and tolerates Yahoo rate-limits:
a throttled run renders from cached data and the next run refetches what's missing.

## 🗂 Code layout

Pure building blocks live in the **`bvc/`** package (`indicators`, `period`,
`sentiment`); fetch/cache/resolver, Plotly rendering, and the CLI stay in
`sura_tracker.py`, which re-exports the package API so the entry point is unchanged.

---

## 🧪 Tests

```bash
pip install -r requirements-dev.txt
pytest                 # 115 offline unit + functional tests, no network needed
```

---

## 📰 Custom news sources

Create a `.txt` file following the format in `sources_example.txt`:

```
# Lines starting with # are ignored
https://www.larepublica.co/rss/economia
https://www.portafolio.co/rss.xml | Portafolio
https://www.dinero.com/rss.xml    | Dinero
```

Pass it with `--sources my_sources.txt`.
To use it in GitHub Actions, commit the file to the repo and add `--sources my_sources.txt` to the `python sura_tracker.py` command in the workflow.

---

## 📊 Supported BVC tickers

| Symbol | Company |
|--------|---------|
| GRUPOSURA | Grupo de Inversiones Suramericana S.A. |
| PFGRUPSURA | Grupo SURA — Preferred |
| ECOPETROL | Ecopetrol S.A. |
| BANCOLOMBIA | Bancolombia S.A. |
| PFBCOLOMBIA | Bancolombia — Preferred |
| BOGOTA | Banco de Bogotá S.A. |
| CORFICOLCF | Corporación Financiera Colombiana |
| PFAVAL | Grupo Aval |
| GEB | Grupo Energía Bogotá |
| ISA | Interconexión Eléctrica |
| GRUPOARGOS | Grupo Argos S.A. |
| CEMARGOS | Cementos Argos S.A. |
| NUTRESA | Grupo Nutresa S.A. |
| EXITO | Almacenes Éxito S.A. |

Any other BVC ticker is tried automatically as `TICKER.CL` on Yahoo Finance.

---

## 🗂 File structure

```
Colcap Tracker/
├── sura_tracker.py          # main dashboard + compare generator
├── sources_example.txt      # custom RSS feed template
├── requirements.txt         # runtime deps
├── requirements-dev.txt     # + pytest for tests
├── tests/                   # offline unit + functional tests
├── README.md
└── .github/
    └── workflows/
        └── bvc_dashboard.yml   # GitHub Actions workflow (hourly 8am–4pm COT)
```

> **Schedule:** the workflow runs hourly from **8 am–4 pm Bogotá time**
> (`0 13-21 * * *`, UTC-5) and regenerates `compare.html` on every run.
