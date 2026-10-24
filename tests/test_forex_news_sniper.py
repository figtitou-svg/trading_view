# tests/test_forex_news_sniper.py
"""Tests du bot News Sniper (forex/strategies/news_sniper.py)."""

from datetime import datetime, timedelta, timezone

from forex.data.calendar import EconEvent
from forex.strategies.news_sniper import NewsSniperStrategy

NOW = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)


def _event(currency, title, actual, forecast, minutes_ago=10, impact="High"):
    return EconEvent(
        dt=NOW - timedelta(minutes=minutes_ago), currency=currency, title=title,
        impact=impact, actual=actual, forecast=forecast, previous=forecast,
    )


def test_no_entry_without_recent_events():
    bot = NewsSniperStrategy()
    d = bot.evaluate("EUR_USD", NOW, [], [], use_time_filter=False)
    assert not d.enter


def test_enters_long_on_strong_positive_base_surprise():
    events = [_event("EUR", "CPI y/y", actual=3.0, forecast=2.0)]
    bot = NewsSniperStrategy()
    d = bot.evaluate("EUR_USD", NOW, [], events, use_time_filter=False)
    assert d.enter and d.direction == "long"
    assert 0.0 < d.strength <= 1.0


def test_unemployment_surprise_is_inverted():
    """Chômage au-dessus des attentes = mauvais pour la devise (short)."""
    events = [_event("EUR", "Unemployment Rate", actual=8.0, forecast=6.0)]
    bot = NewsSniperStrategy()
    d = bot.evaluate("EUR_USD", NOW, [], events, use_time_filter=False)
    assert d.enter and d.direction == "short"


def test_ignores_events_older_than_60_minutes():
    events = [_event("EUR", "CPI y/y", actual=3.0, forecast=2.0, minutes_ago=90)]
    bot = NewsSniperStrategy()
    d = bot.evaluate("EUR_USD", NOW, [], events, use_time_filter=False)
    assert not d.enter


def test_ignores_micro_surprises_below_5pct():
    events = [_event("EUR", "CPI y/y", actual=2.01, forecast=2.0)]
    bot = NewsSniperStrategy()
    d = bot.evaluate("EUR_USD", NOW, [], events, use_time_filter=False)
    assert not d.enter


def test_strongest_surprise_wins_when_multiple_events():
    events = [
        _event("EUR", "Retail Sales", actual=2.15, forecast=2.0),               # surprise faible, long EUR
        _event("USD", "Non-Farm Employment Change", actual=500.0, forecast=200.0),  # forte surprise USD -> short EUR/USD
    ]
    bot = NewsSniperStrategy()
    d = bot.evaluate("EUR_USD", NOW, [], events, use_time_filter=False)
    assert d.enter and d.direction == "short"
