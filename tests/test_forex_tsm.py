# tests/test_forex_tsm.py
"""Tests du bot TSM (forex/strategies/tsm.py)."""

from datetime import datetime, timezone

from forex import config
from forex.strategies.tsm import TSMStrategy

NOW = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)


def _candles(n, start=1.10, step=0.0):
    out, price = [], start
    for i in range(n):
        price += step
        out.append([i * 3600_000, price, price + 0.0003, price - 0.0003, price, 0.0])
    return out


def test_long_on_positive_cumulative_return():
    bot = TSMStrategy()
    n = config.FOREX_TSM_LOOKBACK_BARS + config.ATR_PERIOD + 10
    d = bot.evaluate("EUR_USD", NOW, _candles(n, step=0.0002), [], use_time_filter=False)
    assert d.enter and d.direction == "long"


def test_short_on_negative_cumulative_return():
    bot = TSMStrategy()
    n = config.FOREX_TSM_LOOKBACK_BARS + config.ATR_PERIOD + 10
    d = bot.evaluate("EUR_USD", NOW, _candles(n, step=-0.0002), [], use_time_filter=False)
    assert d.enter and d.direction == "short"


def test_no_entry_on_flat_market():
    bot = TSMStrategy()
    n = config.FOREX_TSM_LOOKBACK_BARS + config.ATR_PERIOD + 10
    d = bot.evaluate("EUR_USD", NOW, _candles(n, step=0.0), [], use_time_filter=False)
    assert not d.enter


def test_strength_capped_at_one():
    bot = TSMStrategy()
    n = config.FOREX_TSM_LOOKBACK_BARS + config.ATR_PERIOD + 10
    d = bot.evaluate("EUR_USD", NOW, _candles(n, step=0.005), [], use_time_filter=False)
    assert d.enter and d.strength == 1.0
