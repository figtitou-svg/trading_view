"""Tests du bot Pétrole Breakout (forex/strategies/oil_breakout.py)."""

from datetime import datetime, timezone

from forex.strategies import oil_breakout
from forex.strategies.oil_breakout import OilBreakoutStrategy

NOW = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)


def _flat(n, price=80.0, wobble=0.05):
    return [[i * 3600_000, price, price + wobble, price - wobble, price, 0.0]
           for i in range(n)]


def _flat_then_breakout(direction="long", price=80.0, breakout_size=1.5, prefix=40):
    out = _flat(prefix, price=price, wobble=0.02)
    last_ts = out[-1][0] + 3600_000
    breakout_price = price + breakout_size if direction == "long" else price - breakout_size
    out.append([last_ts, price, max(price, breakout_price) + 0.02,
               min(price, breakout_price) - 0.02, breakout_price, 0.0])
    return out


def test_pairs_restricted_to_oil():
    bot = OilBreakoutStrategy()
    assert bot.pairs == ["WTI_USD"]


def test_volatility_expanding_true_when_recent_ranges_are_wider():
    candles = _flat(15, wobble=0.05)
    for i in range(-5, 0):
        c = candles[i]
        candles[i] = [c[0], c[1], c[1] + 0.5, c[1] - 0.5, c[4], 0.0]
    assert oil_breakout._volatility_expanding(candles) is True


def test_volatility_expanding_false_when_range_is_constant():
    candles = _flat(15, wobble=0.05)
    assert oil_breakout._volatility_expanding(candles) is False


def test_long_on_upside_breakout_with_volatility_expansion():
    bot = OilBreakoutStrategy()
    candles = _flat_then_breakout("long")
    d = bot.evaluate("WTI_USD", NOW, candles, [], use_time_filter=False)
    assert d.enter and d.direction == "long"


def test_short_on_downside_breakout_with_volatility_expansion():
    bot = OilBreakoutStrategy()
    candles = _flat_then_breakout("short")
    d = bot.evaluate("WTI_USD", NOW, candles, [], use_time_filter=False)
    assert d.enter and d.direction == "short"


def test_no_entry_when_price_stays_inside_channel():
    bot = OilBreakoutStrategy()
    candles = _flat_then_breakout("long", breakout_size=0.0)
    d = bot.evaluate("WTI_USD", NOW, candles, [], use_time_filter=False)
    assert not d.enter


def test_no_entry_on_breakout_when_volatility_not_expanding(monkeypatch):
    """La cassure seule ne suffit pas : si _volatility_expanding renvoie False,
    aucune entrée n'est prise même sur une cassure franche du canal."""
    monkeypatch.setattr(oil_breakout, "_volatility_expanding", lambda candles, window=oil_breakout._VOL_WINDOW: False)
    bot = OilBreakoutStrategy()
    candles = _flat_then_breakout("long")
    d = bot.evaluate("WTI_USD", NOW, candles, [], use_time_filter=False)
    assert not d.enter
