"""Tests du module générique de sessions de trading (forex/signals/sessions.py)."""

from datetime import datetime, timezone

from forex.signals import sessions


def test_active_sessions_london_and_new_york_overlap():
    dt = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)
    assert set(sessions.active_sessions(dt)) == {"londres", "new-york"}


def test_active_sessions_tokyo_only_at_night_utc():
    dt = datetime(2026, 7, 15, 3, tzinfo=timezone.utc)
    assert sessions.active_sessions(dt) == ["tokyo"]


def test_in_liquid_session_true_when_one_allowed_session_active():
    dt = datetime(2026, 7, 15, 9, tzinfo=timezone.utc)  # londres seule
    assert sessions.in_liquid_session(dt, ["londres", "new-york"])


def test_in_liquid_session_false_when_no_allowed_session_active():
    dt = datetime(2026, 7, 15, 3, tzinfo=timezone.utc)  # tokyo seule
    assert not sessions.in_liquid_session(dt, ["londres", "new-york"])


def test_in_liquid_session_requires_explicit_allowed_list():
    """Pas de défaut implicite : générique, chaque appelant précise ses sessions."""
    dt = datetime(2026, 7, 15, 9, tzinfo=timezone.utc)
    assert not sessions.in_liquid_session(dt, [])
