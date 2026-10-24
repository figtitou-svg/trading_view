"""
forex/signals/sessions.py — Sessions de trading forex (Tokyo/Londres/New York).

Extrait de forex.signals.smc (qui en avait initialement l'usage exclusif) pour
que N'IMPORTE QUEL bot puisse restreindre ou juger sa performance par session,
et non plus seulement SMC. Le conseil « isolez par session » (une stratégie de
réversion vers la moyenne a un edge en session asiatique mais détruit le
capital pendant l'overlap Londres/New York) s'applique à toute stratégie.

Horaires en UTC, volontairement simples (bornes rondes) : une grille plus fine
serait du sur-ajustement déguisé sur des horaires qui varient déjà avec l'heure
d'été/hiver de chaque place.
"""

from __future__ import annotations

from datetime import datetime, timezone

SESSIONS = {
    "londres": (7, 16),
    "new-york": (12, 21),
    "tokyo": (0, 8),
}


def active_sessions(dt: datetime) -> list[str]:
    """Sessions ouvertes à l'instant `dt` (UTC)."""
    h = dt.astimezone(timezone.utc).hour
    return [name for name, (start, end) in SESSIONS.items() if start <= h < end]


def in_liquid_session(dt: datetime, allowed: list[str]) -> bool:
    """
    Vrai si au moins une des sessions `allowed` est active à `dt`.

    Pas de défaut implicite ici (contrairement à l'ancienne version couplée à
    SMC) : ce module est générique, c'est à chaque appelant de dire quelles
    sessions comptent pour LUI.
    """
    return bool(set(active_sessions(dt)) & set(allowed))
