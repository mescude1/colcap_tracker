"""
Technical signal scoring → a BUY / SELL verdict.

`evaluate_signals(df)` rates the *current posture* of a price+indicator frame
across several independent checks; `signal_verdict(signals)` aggregates those
into a directional call. Pure functions over a DataFrame produced by
`indicators.calc_indicators` — no I/O.
"""
import pandas as pd

# Verdict thresholds on the net score (bullish signals − bearish signals).
VERDICT_BANDS = [
    (4, "STRONG BUY", "bullish"),
    (2, "BUY", "bullish"),
    (-1, "HOLD", "neutral"),
    (-3, "SELL", "bearish"),
    (-99, "STRONG SELL", "bearish"),
]


def _last_prev(df):
    return df.iloc[-1], df.iloc[-2]


def evaluate_signals(df: pd.DataFrame) -> list:
    """
    Return a list of {name, state, detail} dicts describing the current technical
    posture. `state` is 'bullish' | 'bearish' | 'neutral'. Missing inputs are
    skipped rather than guessed.
    """
    signals = []
    if df is None or df.empty or len(df) < 2:
        return signals
    last, _ = _last_prev(df)
    close = last.get("Close")

    def add(name, state, detail):
        signals.append({"name": name, "state": state, "detail": detail})

    # 1. Long-term trend — price vs SMA200
    sma200 = last.get("SMA_200")
    if pd.notna(sma200) and pd.notna(close):
        add("Long-term trend", "bullish" if close > sma200 else "bearish",
            f"Price {'above' if close > sma200 else 'below'} SMA200")

    # 2. Medium-term trend — price vs SMA50
    sma50 = last.get("SMA_50")
    if pd.notna(sma50) and pd.notna(close):
        add("Medium-term trend", "bullish" if close > sma50 else "bearish",
            f"Price {'above' if close > sma50 else 'below'} SMA50")

    # 3. MA structure — SMA50 vs SMA200 (golden/death)
    if pd.notna(sma50) and pd.notna(sma200):
        add("MA structure", "bullish" if sma50 > sma200 else "bearish",
            f"SMA50 {'>' if sma50 > sma200 else '<'} SMA200")

    # 4. RSI zone
    rsi = last.get("RSI")
    if pd.notna(rsi):
        if rsi < 30:
            add("RSI", "bullish", f"Oversold ({rsi:.0f})")
        elif rsi > 70:
            add("RSI", "bearish", f"Overbought ({rsi:.0f})")
        else:
            add("RSI", "neutral", f"Neutral ({rsi:.0f})")

    # 5. MACD vs signal
    macd, sig = last.get("MACD"), last.get("Signal")
    if pd.notna(macd) and pd.notna(sig):
        add("MACD", "bullish" if macd > sig else "bearish",
            f"MACD {'above' if macd > sig else 'below'} signal")

    # 6. Bollinger position
    bb_u, bb_l = last.get("BB_Upper"), last.get("BB_Lower")
    if pd.notna(bb_u) and pd.notna(bb_l) and pd.notna(close):
        if close < bb_l:
            add("Bollinger", "bullish", "Below lower band (oversold)")
        elif close > bb_u:
            add("Bollinger", "bearish", "Above upper band (overbought)")
        else:
            add("Bollinger", "neutral", "Within bands")

    # 7. Momentum — 20-bar rate of change
    if len(df) > 20 and pd.notna(close):
        ref = df["Close"].iloc[-21]
        if pd.notna(ref) and ref != 0:
            roc = (close / ref - 1) * 100
            add("Momentum (20)", "bullish" if roc >= 0 else "bearish",
                f"{roc:+.1f}% over 20 bars")

    return signals


def signal_verdict(signals: list) -> dict:
    """
    Aggregate signals into {label, state, score, bull, bear, neutral, total}.
    score = (#bullish − #bearish); label per VERDICT_BANDS.
    """
    bull = sum(1 for s in signals if s["state"] == "bullish")
    bear = sum(1 for s in signals if s["state"] == "bearish")
    neutral = sum(1 for s in signals if s["state"] == "neutral")
    score = bull - bear
    label, state = "HOLD", "neutral"
    for threshold, lbl, st in VERDICT_BANDS:
        if score >= threshold:
            label, state = lbl, st
            break
    return {"label": label, "state": state, "score": score,
            "bull": bull, "bear": bear, "neutral": neutral,
            "total": len(signals)}
