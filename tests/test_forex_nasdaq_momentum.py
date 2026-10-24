"""Tests du bot Nasdaq Momentum (forex/strategies/nasdaq_momentum.py)."""

import random
from datetime import datetime, timezone

from forex.strategies.nasdaq_momentum import NasdaqMomentumStrategy

NOW = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)


def _candles_from_closes(closes):
    """Bougies OHLCV synthétiques à partir d'une liste de clôtures."""
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        hi = max(prev, c) * 1.0002
        lo = min(prev, c) * 0.9998
        out.append([i * 3600_000, prev, hi, lo, c, 0.0])
        prev = c
    return out


def _walk(seed, drift, n=280):
    """Marche aléatoire avec dérive (mêmes paramètres que
    tests/test_forex_macro_trend.py, seeds éprouvés pour donner un signal
    technique propre — RSI modéré, ne sature pas)."""
    random.seed(seed)
    p = 1.10
    closes = []
    for _ in range(n):
        p *= (1 + drift + random.gauss(0, 0.0015))
        closes.append(p)
    return closes


UPTREND_CANDLES = _candles_from_closes(_walk(7, 0.0006))
DOWNTREND_CANDLES = _candles_from_closes(_walk(2, -0.0004))

RISK_ON_VIX = {"last": 14.0, "mean": 18.0, "change_pct": -5.0}
RISK_OFF_VIX = {"last": 28.0, "mean": 18.0, "change_pct": 40.0}


def test_pairs_restricted_to_nasdaq():
    bot = NasdaqMomentumStrategy()
    assert bot.pairs == ["NDX_USD"]


def test_enters_long_on_uptrend_when_vix_risk_on():
    bot = NasdaqMomentumStrategy()
    context = {"crossasset": {"vix": RISK_ON_VIX}}
    d = bot.evaluate("NDX_USD", NOW, UPTREND_CANDLES, [], use_time_filter=False, context=context)
    assert d.enter and d.direction == "long"
    assert 0.0 < d.strength <= 1.0


def test_blocks_long_on_uptrend_when_vix_risk_off():
    bot = NasdaqMomentumStrategy()
    context = {"crossasset": {"vix": RISK_OFF_VIX}}
    d = bot.evaluate("NDX_USD", NOW, UPTREND_CANDLES, [], use_time_filter=False, context=context)
    assert not d.enter


def test_enters_short_on_downtrend_regardless_of_vix():
    bot = NasdaqMomentumStrategy()
    context = {"crossasset": {"vix": RISK_OFF_VIX}}
    d = bot.evaluate("NDX_USD", NOW, DOWNTREND_CANDLES, [], use_time_filter=False, context=context)
    assert d.enter and d.direction == "short"
    assert 0.0 < d.strength <= 1.0


def test_no_entry_when_vix_data_missing():
    bot = NasdaqMomentumStrategy()
    d = bot.evaluate("NDX_USD", NOW, UPTREND_CANDLES, [], use_time_filter=False,
                     context={"crossasset": {}})
    assert not d.enter


def test_no_entry_when_vix_values_are_none():
    bot = NasdaqMomentumStrategy()
    context = {"crossasset": {"vix": {"last": None, "mean": None}}}
    d = bot.evaluate("NDX_USD", NOW, UPTREND_CANDLES, [], use_time_filter=False, context=context)
    assert not d.enter


def test_no_entry_when_vix_keys_missing():
    bot = NasdaqMomentumStrategy()
    context = {"crossasset": {"vix": {"other_key": 1}}}
    d = bot.evaluate("NDX_USD", NOW, UPTREND_CANDLES, [], use_time_filter=False, context=context)
    assert not d.enter
