"""Tests du bot cassure de canal (forex/strategies/channel_breakout.py)."""

from datetime import datetime, timezone

from forex import config
from forex.strategies.channel_breakout import ChannelBreakoutStrategy

NOW = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)


def _flat_then_breakout(period, direction="long", price=1.10, breakout_size=0.002):
    """Canal plat sur `period` bougies puis une cassure nette sur la dernière."""
    out = [[i * 3600_000, price, price + 0.0001, price - 0.0001, price, 0.0]
          for i in range(period + config.ATR_PERIOD + 5)]
    last_ts = out[-1][0] + 3600_000
    breakout_price = price + breakout_size if direction == "long" else price - breakout_size
    out.append([last_ts, price, max(price, breakout_price) + 0.0001,
               min(price, breakout_price) - 0.0001, breakout_price, 0.0])
    return out


def test_long_on_upside_breakout():
    bot = ChannelBreakoutStrategy()
    candles = _flat_then_breakout(config.FOREX_CHANNEL_BREAKOUT_BARS, "long")
    d = bot.evaluate("EUR_USD", NOW, candles, [], use_time_filter=False)
    assert d.enter and d.direction == "long"


def test_short_on_downside_breakout():
    bot = ChannelBreakoutStrategy()
    candles = _flat_then_breakout(config.FOREX_CHANNEL_BREAKOUT_BARS, "short")
    d = bot.evaluate("EUR_USD", NOW, candles, [], use_time_filter=False)
    assert d.enter and d.direction == "short"


def test_no_entry_when_price_stays_inside_channel():
    bot = ChannelBreakoutStrategy()
    candles = _flat_then_breakout(config.FOREX_CHANNEL_BREAKOUT_BARS, "long", breakout_size=0.0)
    d = bot.evaluate("EUR_USD", NOW, candles, [], use_time_filter=False)
    assert not d.enter


def test_strength_capped_at_one_on_large_breakout():
    bot = ChannelBreakoutStrategy()
    # Cassure très large par rapport au canal (0.0002 de large) : force saturée.
    candles = _flat_then_breakout(config.FOREX_CHANNEL_BREAKOUT_BARS, "long", breakout_size=0.01)
    d = bot.evaluate("EUR_USD", NOW, candles, [], use_time_filter=False)
    assert d.enter and d.strength == 1.0


def test_strength_scales_with_breakout_size_when_not_capped():
    bot = ChannelBreakoutStrategy()
    # Cassure fine (juste au-dessus du canal) : force proportionnelle, non saturée.
    candles = _flat_then_breakout(config.FOREX_CHANNEL_BREAKOUT_BARS, "long", breakout_size=0.00015)
    d = bot.evaluate("EUR_USD", NOW, candles, [], use_time_filter=False)
    assert d.enter and 0.0 < d.strength < 1.0
