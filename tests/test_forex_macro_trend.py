# tests/test_forex_macro_trend.py
"""Tests du bot Macro Confluence (forex/strategies/macro_trend.py)."""

import random
from datetime import datetime, timezone
from unittest.mock import patch

from forex.strategies.macro_trend import MacroTrendStrategy

NOW = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)


def _candles_from_closes(closes):
    """Bougies OHLCV synthétiques à partir d'une liste de clôtures (cf. test_forex_technical.py)."""
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        hi = max(prev, c) * 1.0002
        lo = min(prev, c) * 0.9998
        out.append([i * 3600_000, prev, hi, lo, c, 0.0])
        prev = c
    return out


def _walk(seed, drift, n=280):
    """Marche aléatoire avec dérive (uptrend réaliste : RSI modéré, ne sature pas)."""
    random.seed(seed)
    p = 1.10
    closes = []
    for _ in range(n):
        p *= (1 + drift + random.gauss(0, 0.0015))
        closes.append(p)
    return closes


UPTREND_CANDLES = _candles_from_closes(_walk(7, 0.0006))
# Seed 7 avec une dérive négative sature le RSI en survente (<30, filtré par
# technical_signal — même protection que pour les excès haussiers), ce qui
# empêcherait toute entrée short quel que soit le biais macro. Seed 2 avec
# une dérive plus modeste donne une baisse réaliste (RSI ~41, ne sature pas).
DOWNTREND_CANDLES = _candles_from_closes(_walk(2, -0.0004))


def test_pairs_restricted_to_fred_covered_currencies():
    bot = MacroTrendStrategy()
    assert set(bot.pairs) == {"EUR_USD", "GBP_USD", "USD_JPY", "EUR_GBP", "EUR_JPY", "GBP_JPY"}


def test_no_entry_when_macro_bias_contradicts_uptrend():
    bot = MacroTrendStrategy()
    with patch("forex.strategies.macro_trend.get_pair_macro_bias", return_value=-0.5):
        d = bot.evaluate("EUR_USD", NOW, UPTREND_CANDLES, [], use_time_filter=False)
    assert not d.enter


def test_enters_long_when_trend_and_macro_agree():
    bot = MacroTrendStrategy()
    with patch("forex.strategies.macro_trend.get_pair_macro_bias", return_value=0.6):
        d = bot.evaluate("EUR_USD", NOW, UPTREND_CANDLES, [], use_time_filter=False)
    assert d.enter and d.direction == "long"
    assert 0.0 < d.strength <= 1.0


def test_no_entry_when_macro_bias_neutral():
    bot = MacroTrendStrategy()
    with patch("forex.strategies.macro_trend.get_pair_macro_bias", return_value=0.0):
        d = bot.evaluate("EUR_USD", NOW, UPTREND_CANDLES, [], use_time_filter=False)
    assert not d.enter


def test_enters_short_when_trend_and_macro_agree():
    bot = MacroTrendStrategy()
    with patch("forex.strategies.macro_trend.get_pair_macro_bias", return_value=-0.6):
        d = bot.evaluate("EUR_USD", NOW, DOWNTREND_CANDLES, [], use_time_filter=False)
    assert d.enter and d.direction == "short"
    assert 0.0 < d.strength <= 1.0


def test_no_entry_at_exact_long_boundary():
    """Le seuil est strictement > 0.1 : exactement 0.1 ne doit PAS suffire."""
    bot = MacroTrendStrategy()
    with patch("forex.strategies.macro_trend.get_pair_macro_bias", return_value=0.1):
        d = bot.evaluate("EUR_USD", NOW, UPTREND_CANDLES, [], use_time_filter=False)
    assert not d.enter


def test_no_entry_at_exact_short_boundary():
    """Symétrique : exactement -0.1 ne doit PAS suffire (seuil strictement < -0.1)."""
    bot = MacroTrendStrategy()
    with patch("forex.strategies.macro_trend.get_pair_macro_bias", return_value=-0.1):
        d = bot.evaluate("EUR_USD", NOW, DOWNTREND_CANDLES, [], use_time_filter=False)
    assert not d.enter
