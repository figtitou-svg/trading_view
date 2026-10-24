"""
forex/signals/time_filter.py — Filtre de risque temporel.

Trois rôles (module 4 du spec) :
  1. **Horaires de marché** : le forex est 24/5 — fermé du vendredi 21:00 UTC
     au dimanche 21:00 UTC. Aucune ouverture le week-end.
  2. **Fenêtre d'exclusion** autour des annonces high-impact : pas de NOUVELLE
     position dans les N minutes avant / M minutes après (spread élargi,
     volatilité erratique).
  3. **Sortie forcée** : un trade event-driven qui n'a pas « payé » après
     X minutes est coupé (on ne reste pas exposé sans edge).

Le spread post-annonce élargi est exposé via `spread_multiplier`, utilisé par
le backtest et le broker simulé pour des coûts réalistes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from forex import config
from forex.data.calendar import EconEvent

# Marché forex : ouvre dimanche 21:00 UTC, ferme vendredi 21:00 UTC.
_OPEN_HOUR_UTC = 21


def is_market_open(dt: datetime) -> bool:
    """Vrai si le marché forex est ouvert à l'instant `dt` (UTC)."""
    dt = dt.astimezone(timezone.utc)
    wd = dt.weekday()  # Mon=0 … Sun=6
    if wd == 5:                                   # samedi : fermé
        return False
    if wd == 4 and dt.hour >= _OPEN_HOUR_UTC:     # vendredi soir : fermé
        return False
    if wd == 6 and dt.hour < _OPEN_HOUR_UTC:      # dimanche matin : fermé
        return False
    return True


def _pair_events(pair: str, events: list[EconEvent], impacts={"high"}) -> list[EconEvent]:
    base, quote = pair.upper().split("_")
    ccys = {base, quote}
    return [e for e in events if e.currency in ccys and e.impact.lower() in impacts]


@dataclass
class TimeGate:
    can_open: bool
    reason: str
    blocking_event: str | None = None


def in_exclusion_window(
    pair: str,
    now: datetime,
    events: list[EconEvent],
    *,
    min_before: int = config.EXCLUSION_MIN_BEFORE,
    min_after: int = config.EXCLUSION_MIN_AFTER,
) -> TimeGate:
    """Bloque l'ouverture si `now` tombe autour d'une annonce high-impact de la paire."""
    now = now.astimezone(timezone.utc)
    for e in _pair_events(pair, events):
        start = e.dt - timedelta(minutes=min_before)
        end = e.dt + timedelta(minutes=min_after)
        if start <= now <= end:
            delta = (e.dt - now).total_seconds() / 60
            when = f"dans {delta:.0f} min" if delta >= 0 else f"il y a {-delta:.0f} min"
            return TimeGate(False, f"annonce {e.currency} {e.event_type()} {when}", e.title)
    return TimeGate(True, "hors fenêtre d'annonce")


def can_trade(
    pair: str,
    now: datetime,
    events: list[EconEvent],
    **kwargs,
) -> TimeGate:
    """Combine horaires de marché + fenêtre d'exclusion."""
    if not is_market_open(now):
        return TimeGate(False, "marché fermé (week-end)")
    return in_exclusion_window(pair, now, events, **kwargs)


def spread_multiplier(
    pair: str,
    now: datetime,
    events: list[EconEvent],
    *,
    min_after: int = config.EXCLUSION_MIN_AFTER,
    mult: float = config.POST_EVENT_SPREAD_MULT,
) -> float:
    """Facteur d'élargissement du spread juste après une annonce high-impact."""
    now = now.astimezone(timezone.utc)
    for e in _pair_events(pair, events):
        if e.dt <= now <= e.dt + timedelta(minutes=min_after):
            return mult
    return 1.0


def should_time_exit(
    entry_dt: datetime,
    now: datetime,
    moved_enough: bool,
    *,
    max_minutes: int = config.EVENT_TRADE_MAX_MIN,
) -> bool:
    """
    Sortie forcée : position ouverte depuis > max_minutes SANS mouvement utile.
    `moved_enough` = True si le prix a déjà bougé significativement (à l'appelant
    de le déterminer, p.ex. via l'ATR).
    """
    if moved_enough:
        return False
    held = (now.astimezone(timezone.utc) - entry_dt.astimezone(timezone.utc))
    return held >= timedelta(minutes=max_minutes)


@dataclass
class WeekendGap:
    at_risk: bool
    message: str


def weekend_gap_risk(now: datetime, warn_hours: int = 4) -> WeekendGap:
    """Alerte si une position ouverte approche de la fermeture du vendredi (gap risk)."""
    now = now.astimezone(timezone.utc)
    if now.weekday() == 4 and now.hour >= _OPEN_HOUR_UTC - warn_hours:
        return WeekendGap(True, f"fermeture vendredi {_OPEN_HOUR_UTC}:00 UTC proche — risque de gap week-end")
    return WeekendGap(False, "pas de risque de gap immédiat")
