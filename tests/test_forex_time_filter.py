"""Tests du filtre de risque temporel (horaires 24/5 + fenêtres d'annonce)."""

from datetime import datetime, timedelta, timezone

from forex.data.calendar import EconEvent
from forex.signals import time_filter


def _dt(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def test_market_open_weekday():
    # mercredi 15h UTC → ouvert
    assert time_filter.is_market_open(_dt(2026, 1, 7, 15))


def test_market_closed_saturday():
    assert not time_filter.is_market_open(_dt(2026, 1, 10, 12))  # samedi


def test_market_closed_friday_evening():
    assert not time_filter.is_market_open(_dt(2026, 1, 9, 22))   # vendredi 22h
    assert time_filter.is_market_open(_dt(2026, 1, 9, 20))       # vendredi 20h encore ouvert


def test_market_closed_sunday_before_open():
    assert not time_filter.is_market_open(_dt(2026, 1, 11, 20))  # dimanche 20h
    assert time_filter.is_market_open(_dt(2026, 1, 11, 22))      # dimanche 22h → ouvert


def test_exclusion_window_blocks_around_event():
    event_dt = _dt(2026, 1, 7, 13, 30)
    events = [EconEvent(dt=event_dt, currency="USD", title="CPI y/y", impact="High",
                        actual=None, forecast=3.0, previous=3.0)]
    # 10 min avant (< 15 min before) → bloqué
    gate = time_filter.in_exclusion_window("EUR_USD", event_dt - timedelta(minutes=10), events)
    assert not gate.can_open
    # 1 h avant → OK
    gate2 = time_filter.in_exclusion_window("EUR_USD", event_dt - timedelta(hours=1), events)
    assert gate2.can_open


def test_exclusion_ignores_other_currencies():
    event_dt = _dt(2026, 1, 7, 13, 30)
    events = [EconEvent(dt=event_dt, currency="AUD", title="CPI y/y", impact="High",
                        actual=None, forecast=3.0, previous=3.0)]
    gate = time_filter.in_exclusion_window("EUR_USD", event_dt, events)
    assert gate.can_open  # AUD ne concerne pas EUR_USD


def test_spread_multiplier_widens_post_event():
    event_dt = _dt(2026, 1, 7, 13, 30)
    events = [EconEvent(dt=event_dt, currency="USD", title="NFP", impact="High",
                        actual=250.0, forecast=200.0, previous=180.0)]
    assert time_filter.spread_multiplier("EUR_USD", event_dt + timedelta(minutes=2), events) > 1.0
    assert time_filter.spread_multiplier("EUR_USD", event_dt + timedelta(hours=2), events) == 1.0


def test_should_time_exit():
    entry = _dt(2026, 1, 7, 10)
    # 3h plus tard, pas de mouvement → sortie forcée (max 120 min)
    assert time_filter.should_time_exit(entry, entry + timedelta(hours=3), moved_enough=False,
                                        max_minutes=120)
    # mais si ça a bougé, on garde
    assert not time_filter.should_time_exit(entry, entry + timedelta(hours=3), moved_enough=True,
                                            max_minutes=120)


def test_weekend_gap_risk():
    assert time_filter.weekend_gap_risk(_dt(2026, 1, 9, 19)).at_risk        # vendredi 19h
    assert not time_filter.weekend_gap_risk(_dt(2026, 1, 7, 12)).at_risk    # mercredi
