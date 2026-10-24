"""Tests du bot Or Macro (forex/strategies/gold_macro.py)."""

from datetime import datetime, timezone

from forex import config
from forex.strategies.gold_macro import GoldMacroStrategy

NOW = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)

_PREFIX = config.MA_SLOW + config.ATR_PERIOD + 5


def _flat_then_move(price=100.0, move=0.0, wobble=0.05):
    """`_PREFIX` bougies plates (pas de tendance de fond, SMA200 ≈ prix) puis
    une bougie qui déplace la clôture de `move`."""
    out = [[i * 3600_000, price, price + wobble, price - wobble, price, 0.0]
          for i in range(_PREFIX)]
    last_ts = out[-1][0] + 3600_000
    new_price = price + move
    out.append([last_ts, price, max(price, new_price) + wobble,
               min(price, new_price) - wobble, new_price, 0.0])
    return out


def _trend_then_move(trend_start, trend_end, flat_price, move, n_trend=150, wobble=0.05):
    """Tendance de fond (linéaire sur `n_trend` bougies, de `trend_start` à
    `trend_end`) puis un plateau à `flat_price` (stabilise SMA50/ATR) puis une
    bougie qui déplace la clôture de `move` — pour tester le retour à la
    moyenne EN ACCORD avec la tendance de fond (SMA200)."""
    out = []
    ts = 0
    for i in range(n_trend):
        p = trend_start + (trend_end - trend_start) * i / max(1, n_trend - 1)
        out.append([ts, p, p + wobble, p - wobble, p, 0.0])
        ts += 3600_000
    n_flat = _PREFIX - n_trend
    for _ in range(n_flat):
        out.append([ts, flat_price, flat_price + wobble, flat_price - wobble, flat_price, 0.0])
        ts += 3600_000
    new_price = flat_price + move
    out.append([ts, flat_price, max(flat_price, new_price) + wobble,
               min(flat_price, new_price) - wobble, new_price, 0.0])
    return out


FALLING_YIELD = {"last": 4.1, "mean": 4.3, "change_pct": -3.0}
RISING_YIELD = {"last": 4.5, "mean": 4.3, "change_pct": 3.0}


def test_pairs_restricted_to_gold():
    bot = GoldMacroStrategy()
    assert bot.pairs == ["XAU_USD"]


def test_enters_long_below_band_when_yield_falling_and_uptrend():
    """Retour à la moyenne EN ACCORD avec la tendance de fond (SMA200 sous le
    prix courant, cf. valeurs vérifiées empiriquement : close=95, trend200≈94.3)."""
    bot = GoldMacroStrategy()
    candles = _trend_then_move(80, 100, 100, move=-5.0)
    context = {"crossasset": {"us10y": FALLING_YIELD}}
    d = bot.evaluate("XAU_USD", NOW, candles, [], use_time_filter=False, context=context)
    assert d.enter and d.direction == "long"


def test_enters_short_above_band_when_yield_rising_and_downtrend():
    """Symétrique : SMA200 au-dessus du prix courant (close=105, trend200≈105.7)."""
    bot = GoldMacroStrategy()
    candles = _trend_then_move(120, 100, 100, move=5.0)
    context = {"crossasset": {"us10y": RISING_YIELD}}
    d = bot.evaluate("XAU_USD", NOW, candles, [], use_time_filter=False, context=context)
    assert d.enter and d.direction == "short"


def test_no_entry_when_long_setup_contradicts_long_term_trend():
    """Le fix : bande + taux valideraient un long (comme avant), mais sans
    tendance de fond haussière (historique plat, SMA200 ≈ prix, donc
    close < trend200 après la baisse) l'entrée est maintenant bloquée —
    c'est exactement le biais qui perdait -13,5% en backtest (222 shorts
    contre 128 longs pendant un marché haussier)."""
    bot = GoldMacroStrategy()
    candles = _flat_then_move(move=-5.0)
    context = {"crossasset": {"us10y": FALLING_YIELD}}
    d = bot.evaluate("XAU_USD", NOW, candles, [], use_time_filter=False, context=context)
    assert not d.enter


def test_no_entry_below_band_when_yield_not_falling():
    bot = GoldMacroStrategy()
    candles = _flat_then_move(move=-5.0)
    context = {"crossasset": {"us10y": RISING_YIELD}}
    d = bot.evaluate("XAU_USD", NOW, candles, [], use_time_filter=False, context=context)
    assert not d.enter


def test_no_entry_when_price_stays_near_mean():
    bot = GoldMacroStrategy()
    candles = _flat_then_move(move=0.0)
    context = {"crossasset": {"us10y": FALLING_YIELD}}
    d = bot.evaluate("XAU_USD", NOW, candles, [], use_time_filter=False, context=context)
    assert not d.enter


def test_no_entry_when_us10y_missing():
    bot = GoldMacroStrategy()
    candles = _flat_then_move(move=-5.0)
    d = bot.evaluate("XAU_USD", NOW, candles, [], use_time_filter=False,
                     context={"crossasset": {}})
    assert not d.enter
