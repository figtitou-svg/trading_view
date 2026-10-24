"""Tests du signal fondamental (surprise score, look-ahead, polarité, direction)."""

from datetime import datetime, timedelta, timezone

import pytest

from forex.data.calendar import EconEvent
from forex.signals import fundamental


def _evt(dt, ccy, title, actual, forecast, impact="High"):
    return EconEvent(dt=dt, currency=ccy, title=title, impact=impact,
                     actual=actual, forecast=forecast, previous=forecast)


def _history(ccy="USD", title="CPI y/y", n=10, start=None):
    """n annonces mensuelles avec des surprises variées (écart-type non nul)."""
    start = start or datetime(2025, 1, 10, 13, 30, tzinfo=timezone.utc)
    diffs = [0.0, 0.2, -0.2, 0.4, -0.4, 0.1, -0.1, 0.3, -0.3, 0.0]
    out = []
    for i in range(n):
        out.append(_evt(start + timedelta(days=30 * i), ccy, title,
                        3.0 + diffs[i % len(diffs)], 3.0))
    return out


def test_event_polarity():
    assert fundamental.event_polarity(_evt(datetime.now(timezone.utc), "USD", "CPI y/y", 3, 3)) == 1
    assert fundamental.event_polarity(
        _evt(datetime.now(timezone.utc), "USD", "Unemployment Rate", 4, 4)) == -1


def test_surprise_score_needs_min_history():
    hist = _history(n=5)
    target = _evt(hist[-1].dt + timedelta(days=30), "USD", "CPI y/y", 4.0, 3.0)
    # seulement 5 antérieurs < min_history=8 → None
    assert fundamental.surprise_score(target, hist + [target], min_history=8) is None


def test_surprise_score_value():
    import statistics
    hist = _history(n=10)
    target = _evt(hist[-1].dt + timedelta(days=30), "USD", "CPI y/y", 3.5, 3.0)
    diffs = [e.actual - e.forecast for e in hist]
    expected = (3.5 - 3.0) / statistics.pstdev(diffs)
    got = fundamental.surprise_score(target, hist + [target], min_history=8)
    assert got == pytest.approx(expected)


def test_no_look_ahead():
    """La surprise d'un event ne doit dépendre que d'annonces STRICTEMENT antérieures."""
    hist = _history(n=10)
    mid = hist[5]
    # un event postérieur avec une énorme surprise ne doit pas changer le score de `mid`
    future = _evt(hist[-1].dt + timedelta(days=60), "USD", "CPI y/y", 99.0, 3.0)
    s1 = fundamental.surprise_score(mid, hist, min_history=3)
    s2 = fundamental.surprise_score(mid, hist + [future], min_history=3)
    assert s1 == s2


def test_fundamental_signal_pair_direction():
    hist = _history(n=10)
    # forte surprise positive USD (actual >> forecast) → USD ↑
    t = hist[-1].dt + timedelta(days=30)
    big = _evt(t, "USD", "CPI y/y", 5.0, 3.0)  # +2.0 vs std ~0.25 → score énorme
    events = hist + [big]
    as_of = t + timedelta(minutes=5)

    # EUR_USD : USD est la quote → USD ↑ ⇒ EUR_USD short
    r = fundamental.fundamental_signal("EUR_USD", as_of, events, lookback_minutes=30)
    assert r.direction == "short"
    # USD_JPY : USD est la base → USD ↑ ⇒ USD_JPY long
    r2 = fundamental.fundamental_signal("USD_JPY", as_of, events, lookback_minutes=30)
    assert r2.direction == "long"


def test_fundamental_signal_below_threshold_is_none():
    hist = _history(n=10)
    t = hist[-1].dt + timedelta(days=30)
    tiny = _evt(t, "USD", "CPI y/y", 3.02, 3.0)  # surprise minuscule
    events = hist + [tiny]
    r = fundamental.fundamental_signal("EUR_USD", t + timedelta(minutes=5), events,
                                       threshold=0.5, lookback_minutes=30)
    assert r.direction is None


def test_fundamental_signal_no_event_in_window():
    hist = _history(n=10)
    # as_of loin de toute annonce
    r = fundamental.fundamental_signal(
        "EUR_USD", datetime(2030, 1, 1, tzinfo=timezone.utc), hist, lookback_minutes=30)
    assert r.direction is None
