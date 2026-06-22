"""Bilingual (EN/ES) news sentiment classification + relevance/date helpers."""
import re
from datetime import datetime
from email.utils import parsedate_to_datetime

BULLISH_WORDS = {
    # English
    "gain", "gains", "rise", "rises", "rose", "rally", "rallies", "surge", "surges", "soar", "soars",
    "grow", "growth", "profit", "profits", "beat", "beats", "exceed", "exceeds", "record",
    "strong", "strength", "positive", "upgrade", "buy", "outperform", "dividend", "recovery",
    "recovers", "higher", "increase", "increases", "boost", "opportunity", "bullish", "expansion",
    "improving", "improved", "acceleration", "upside", "rebound", "inflow", "inflows",
    # Spanish
    "sube", "subida", "alza", "alzas", "gana", "ganancias", "crece", "crecimiento", "utilidad",
    "utilidades", "beneficio", "beneficios", "supera", "fuerte", "positivo", "dividendo",
    "recuperación", "recupera", "aumenta", "incremento", "mejora", "expansión", "oportunidad",
    "rebote", "entrada", "flujos", "alcista", "record", "máximo",
}

BEARISH_WORDS = {
    # English
    "loss", "losses", "fall", "falls", "fell", "drop", "drops", "decline", "declines", "plunge",
    "miss", "misses", "weak", "weakness", "sell", "downgrade", "underperform", "cut", "cuts",
    "risk", "risks", "concern", "concerns", "debt", "default", "down", "lower", "crash", "fear",
    "warning", "decrease", "uncertainty", "bearish", "contraction", "deteriorating", "pressure",
    "headwinds", "outflow", "outflows", "deficit", "inflation", "recession", "layoff", "layoffs",
    # Spanish
    "baja", "bajada", "cae", "caída", "pierde", "pérdida", "riesgo", "deuda", "crisis", "declive",
    "descenso", "disminuye", "reducción", "preocupación", "débil", "negativo", "incertidumbre",
    "presión", "contracción", "salida", "déficit", "inflación", "recesión", "bajista", "mínimo",
    "desempleo", "recorte",
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
