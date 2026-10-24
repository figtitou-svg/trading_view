"""
forex/signals/indicators.py — Indicateurs techniques purs (aucune dépendance).

Fonctions pures sur des listes de prix / bougies OHLCV `[ts, o, h, l, c, v]`,
volontairement dupliquées depuis la logique éprouvée de `scanner.py` (RSI/EMA/ATR)
pour garder le module forex **découplé** du bot crypto — importer `scanner`
déclencherait sa validation `.env`, l'import de ccxt et la reconfiguration stdout.
On y ajoute le MACD, absent côté crypto.
"""

from __future__ import annotations


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def ema_series(values: list[float], period: int) -> list[float]:
    """EMA en série. Amorçage par la SMA de la première fenêtre (comme scanner.py)."""
    if len(values) < period or period <= 0:
        return list(values)
    k = 2 / (period + 1)
    out = [sum(values[:period]) / period]
    for price in values[period:]:
        out.append(price * k + out[-1] * (1 - k))
    return out


def ema(values: list[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    return ema_series(values, period)[-1]


def rsi(closes: list[float], period: int = 14) -> float:
    """RSI avec lissage de Wilder (identique à scanner.calculate_rsi)."""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    avg_gain = sum(d for d in deltas[:period] if d > 0) / period
    avg_loss = sum(-d for d in deltas[:period] if d < 0) / period
    for d in deltas[period:]:
        gain = d if d > 0 else 0.0
        loss = -d if d < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def atr(candles: list[list[float]], period: int = 14) -> float:
    """ATR (Wilder) sur des bougies OHLCV (identique à scanner.calculate_atr)."""
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        high, low = candles[i][2], candles[i][3]
        prev_close = candles[i - 1][4]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    val = sum(trs[:period]) / period
    for tr in trs[period:]:
        val = (val * (period - 1) + tr) / period
    return val


def macd(
    closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[float, float, float] | None:
    """
    MACD (Moving Average Convergence Divergence).

    Returns:
        (macd_line, signal_line, histogram) sur la dernière bougie, ou None si
        pas assez de données. histogram = macd_line - signal_line ; son signe et
        sa pente donnent le momentum.
    """
    if len(closes) < slow + signal:
        return None
    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)
    n = min(len(ema_fast), len(ema_slow))
    if n < signal + 1:
        return None
    macd_line = [ema_fast[-n + i] - ema_slow[-n + i] for i in range(n)]
    signal_line = ema_series(macd_line, signal)
    if not signal_line:
        return None
    m = macd_line[-1]
    s = signal_line[-1]
    return (m, s, m - s)


def cumulative_return(closes: list[float], lookback: int) -> float | None:
    """Rendement cumulé entre closes[-1-lookback] et closes[-1]. None si pas assez de données."""
    if len(closes) < lookback + 1 or lookback <= 0:
        return None
    base = closes[-1 - lookback]
    if base == 0:
        return None
    return (closes[-1] / base) - 1


def rolling_high(candles: list[list[float]], period: int, *, exclude_last: bool = True) -> float | None:
    """
    Plus haut sur les `period` bougies précédentes.

    Exclut la bougie courante par défaut pour éviter le look-ahead : tant qu'elle
    n'est pas clôturée, son high n'est pas définitif et l'utiliser reviendrait à
    tricher avec une information du futur. Passer exclude_last=False seulement
    pour une analyse a posteriori sur des données déjà figées.
    """
    window = candles[:-1] if exclude_last else candles
    if len(window) < period or period <= 0:
        return None
    return max(c[2] for c in window[-period:])


def rolling_low(candles: list[list[float]], period: int, *, exclude_last: bool = True) -> float | None:
    """
    Plus bas sur les `period` bougies précédentes.

    Exclut la bougie courante par défaut pour éviter le look-ahead (bougie en
    cours, pas encore clôturée) — même raisonnement que `rolling_high`.
    """
    window = candles[:-1] if exclude_last else candles
    if len(window) < period or period <= 0:
        return None
    return min(c[3] for c in window[-period:])
