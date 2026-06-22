"""Technical-indicator and risk math — pure functions over pandas/numpy, no I/O."""
import numpy as np
import pandas as pd


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
