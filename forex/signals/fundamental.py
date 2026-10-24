"""
forex/signals/fundamental.py — Signal fondamental event-driven (surprise score).

Score de surprise normalisé, **sans look-ahead** :

    surprise = (actual - forecast) / std(surprises passées du même type d'event)

où les « surprises passées » sont calculées **uniquement** sur les annonces
strictement antérieures à l'event courant (garantie anti-look-ahead).

Un |score| au-delà de `FOREX_SURPRISE_THRESHOLD` écarts-types = surprise
significative. La direction sur la *devise* dépend de la polarité de l'event
(une inflation/GDP/emploi supérieurs aux attentes soutiennent la devise ; un
*taux de chômage* supérieur la pénalise). La direction sur la *paire* dépend
ensuite de la position de la devise (base ou quote).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from forex import config
from forex.data.calendar import EconEvent

# Events dont un `actual` SUPÉRIEUR au consensus est BAISSIER pour la devise
# (le reste est haussier par défaut : inflation, croissance, emploi créé…).
_INVERSE_POLARITY_KEYWORDS = (
    "unemployment rate", "jobless", "claims", "misery",
)


def event_polarity(event: EconEvent) -> int:
    """+1 si actual > forecast soutient la devise, -1 si l'inverse."""
    t = event.event_type().lower()
    return -1 if any(k in t for k in _INVERSE_POLARITY_KEYWORDS) else 1


def past_surprises(event: EconEvent, history: list[EconEvent]) -> list[float]:
    """
    Surprises (actual - forecast) des events de MÊME type et devise, survenus
    STRICTEMENT AVANT `event` (anti-look-ahead).
    """
    et = event.event_type().lower()
    out = []
    for e in history:
        if e.currency != event.currency:
            continue
        if e.dt >= event.dt:                 # strictement antérieur
            continue
        if e.event_type().lower() != et:
            continue
        if e.actual is None or e.forecast is None:
            continue
        out.append(e.actual - e.forecast)
    return out


def surprise_score(
    event: EconEvent,
    history: list[EconEvent],
    min_history: int = config.FOREX_MIN_SURPRISE_HISTORY,
) -> float | None:
    """
    Score de surprise normalisé, ou None si résultat manquant ou historique
    insuffisant (l'écart-type ne serait pas fiable).
    """
    if not event.has_result:
        return None
    diffs = past_surprises(event, history)
    if len(diffs) < min_history:
        return None
    std = statistics.pstdev(diffs)
    if std == 0:
        return None
    return (event.actual - event.forecast) / std


@dataclass
class FundamentalResult:
    direction: str | None            # 'long' | 'short' | None (sur la PAIRE)
    strength: float                  # 0.0 → 1.0
    reason: str
    score: float | None = None       # surprise score signé
    event_title: str | None = None
    event_currency: str | None = None
    components: dict = field(default_factory=dict)


def _pair_direction(pair: str, currency: str, currency_bullish: bool) -> str | None:
    base, quote = pair.upper().split("_")
    if currency == base:
        return "long" if currency_bullish else "short"
    if currency == quote:
        return "short" if currency_bullish else "long"
    return None


def fundamental_signal(
    pair: str,
    as_of: datetime,
    events: list[EconEvent],
    *,
    threshold: float = config.FOREX_SURPRISE_THRESHOLD,
    min_history: int = config.FOREX_MIN_SURPRISE_HISTORY,
    lookback_minutes: int = config.EXCLUSION_MIN_AFTER + 30,
) -> FundamentalResult:
    """
    Cherche, dans la fenêtre [as_of - lookback, as_of], l'annonce high-impact la
    plus surprenante touchant la base ou la quote de `pair`, et en déduit une
    direction si le score dépasse le seuil de significativité.

    `events` doit contenir l'historique (pour l'écart-type) ET les events récents.
    """
    base, quote = pair.upper().split("_")
    relevant_ccys = {base, quote}
    window_start = as_of - timedelta(minutes=lookback_minutes)

    best: tuple[float, EconEvent, float] | None = None  # (|score|, event, score)
    for e in events:
        if e.currency not in relevant_ccys:
            continue
        if not (window_start <= e.dt <= as_of):
            continue
        if e.impact.lower() not in {"high", "medium"}:
            continue
        score = surprise_score(e, events, min_history)
        if score is None:
            continue
        if best is None or abs(score) > best[0]:
            best = (abs(score), e, score)

    if best is None:
        return FundamentalResult(None, 0.0, "aucune surprise macro exploitable", None)

    abs_score, event, score = best
    if abs_score < threshold:
        return FundamentalResult(
            None, 0.0,
            f"surprise {score:+.2f}σ < seuil {threshold}σ ({event.event_type()} {event.currency})",
            score, event.title, event.currency,
        )

    pol = event_polarity(event)
    currency_bullish = (score * pol) > 0
    direction = _pair_direction(pair, event.currency, currency_bullish)
    if direction is None:
        return FundamentalResult(None, 0.0, "devise hors paire", score, event.title, event.currency)

    # Force : saturation douce du |score| au-delà de 2σ.
    strength = min(1.0, abs_score / 2.0)
    return FundamentalResult(
        direction, round(strength, 3),
        f"Surprise {event.event_type()} {event.currency} {score:+.2f}σ "
        f"→ {event.currency} {'↑' if currency_bullish else '↓'} → {pair} {direction}",
        round(score, 3), event.title, event.currency,
        components={"impact": event.impact, "actual": event.actual, "forecast": event.forecast},
    )
