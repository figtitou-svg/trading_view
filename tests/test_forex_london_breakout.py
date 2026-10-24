"""Tests du bot cassure Londres (forex/strategies/london_breakout.py)."""

from datetime import datetime, timedelta, timezone

from forex.strategies.london_breakout import LondonBreakoutStrategy


def _candles_ending_at_london_open(direction="long", breakout_size=0.003, price=1.10,
                                    warmup_bars=40, breakout_hour=8):
    """
    Séquence continue de bougies H1 se terminant par : `warmup_bars` bougies
    plates, puis les bougies de la session Tokyo (00h-08h UTC) du jour
    courant, puis la bougie de cassure à `breakout_hour` UTC. Ancrée sur
    l'heure de cassure plutôt que sur des blocs de jours séparés, pour que les
    bougies précédentes tombent TOUJOURS sur le bon jour, quel que soit
    `warmup_bars`. `breakout_hour` par défaut = 8h (ouverture Londres 7h UTC +
    1h) pour les tests existants ; des tests dédiés couvrent les bornes
    exactes (7h = ouverture, 11h = fin de fenêtre à FOREX_LONDON_BREAKOUT_WINDOW_HOURS=4).
    """
    total_before_breakout = warmup_bars + 8
    london_open = datetime(2026, 7, 16, breakout_hour, tzinfo=timezone.utc)
    start = london_open - timedelta(hours=total_before_breakout)

    out = []
    for i in range(total_before_breakout):
        ts = int((start + timedelta(hours=i)).timestamp() * 1000)
        out.append([ts, price, price + 0.0001, price - 0.0001, price, 0.0])

    breakout_price = price + breakout_size if direction == "long" else price - breakout_size
    breakout_ts = int(london_open.timestamp() * 1000)
    out.append([breakout_ts, price, max(price, breakout_price) + 0.0001,
               min(price, breakout_price) - 0.0001, breakout_price, 0.0])
    return out


def test_long_on_breakout_above_tokyo_range_at_london_open():
    bot = LondonBreakoutStrategy()
    candles = _candles_ending_at_london_open("long")
    now = datetime.fromtimestamp(candles[-1][0] / 1000, tz=timezone.utc)
    d = bot.evaluate("EUR_USD", now, candles, [], use_time_filter=False)
    assert d.enter and d.direction == "long"


def test_short_on_breakout_below_tokyo_range_at_london_open():
    bot = LondonBreakoutStrategy()
    candles = _candles_ending_at_london_open("short")
    now = datetime.fromtimestamp(candles[-1][0] / 1000, tz=timezone.utc)
    d = bot.evaluate("EUR_USD", now, candles, [], use_time_filter=False)
    assert d.enter and d.direction == "short"


def test_no_entry_outside_london_session():
    bot = LondonBreakoutStrategy()
    candles = _candles_ending_at_london_open("long")
    # Décale l'heure d'évaluation en pleine nuit (Tokyo), hors Londres.
    now = datetime.fromtimestamp(candles[-1][0] / 1000, tz=timezone.utc).replace(hour=3)
    d = bot.evaluate("EUR_USD", now, candles, [], use_time_filter=False)
    assert not d.enter


def test_no_entry_outside_the_opening_window():
    bot = LondonBreakoutStrategy()
    candles = _candles_ending_at_london_open("long")
    # Trop tard dans la session Londres (au-delà de la fenêtre d'ouverture).
    now = datetime.fromtimestamp(candles[-1][0] / 1000, tz=timezone.utc).replace(hour=14)
    d = bot.evaluate("EUR_USD", now, candles, [], use_time_filter=False)
    assert not d.enter


def test_enters_exactly_at_london_session_open():
    """Borne exacte : 7h UTC = ouverture Londres (heures_depuis_ouverture=0)."""
    bot = LondonBreakoutStrategy()
    candles = _candles_ending_at_london_open("long", breakout_hour=7)
    now = datetime.fromtimestamp(candles[-1][0] / 1000, tz=timezone.utc)
    d = bot.evaluate("EUR_USD", now, candles, [], use_time_filter=False)
    assert d.enter and d.direction == "long"


def test_enters_at_last_hour_of_opening_window():
    """Borne exacte : 10h UTC = dernière heure valide (FOREX_LONDON_BREAKOUT_WINDOW_HOURS=4 -> 7+3)."""
    bot = LondonBreakoutStrategy()
    candles = _candles_ending_at_london_open("long", breakout_hour=10)
    now = datetime.fromtimestamp(candles[-1][0] / 1000, tz=timezone.utc)
    d = bot.evaluate("EUR_USD", now, candles, [], use_time_filter=False)
    assert d.enter and d.direction == "long"


def test_no_entry_at_first_hour_past_opening_window():
    """Borne exacte : 11h UTC = première heure exclue (heures_depuis_ouverture=4)."""
    bot = LondonBreakoutStrategy()
    candles = _candles_ending_at_london_open("long", breakout_hour=11)
    now = datetime.fromtimestamp(candles[-1][0] / 1000, tz=timezone.utc)
    d = bot.evaluate("EUR_USD", now, candles, [], use_time_filter=False)
    assert not d.enter
