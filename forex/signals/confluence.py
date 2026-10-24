"""
forex/signals/confluence.py — Règle d'entrée par confluence.

Une position n'est ouverte QUE si tous les signaux ACTIFS s'alignent :

    (fondamental significatif dans une direction)
      ET (technique alignée dans la MÊME direction)
      ET (hors fenêtre d'exclusion temporelle + marché ouvert)

Pondération (documentée, volontairement simple pour éviter l'overfitting) :
  - Le désaccord *interne* au signal technique (MA vs MACD) est déjà tranché en
    amont : il renvoie alors direction=None (pas de vote).
  - Entre familles, on exige un **accord strict de direction** — pas de score
    pondéré qui « rachèterait » un désaccord. La force combinée est la moyenne
    des forces des signaux actifs (chacun ∈ [0,1]).

Chaque famille est désactivable indépendamment (flags de config) pour mesurer
sa contribution marginale : avec un seul signal actif, la confluence se réduit
à ce signal ; avec zéro signal actif, aucune entrée n'est jamais émise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from forex import config
from forex.data.calendar import EconEvent
from forex.signals.fundamental import fundamental_signal
from forex.signals.technical import technical_signal
from forex.signals import time_filter


@dataclass
class ConfluenceDecision:
    enter: bool
    direction: str | None                 # 'long' | 'short' | None
    strength: float                       # 0.0 → 1.0
    reasons: list[str] = field(default_factory=list)
    components: dict = field(default_factory=dict)  # TOUS les signaux (log complet)

    def summary(self) -> str:
        head = "ENTRÉE" if self.enter else "pas d'entrée"
        if self.direction:
            head += f" {self.direction} (force {self.strength:.2f})"
        return head + " · " + " ; ".join(self.reasons)


def combo_key(components: dict, direction: str | None = None) -> str:
    """
    Clé identifiant la COMBINAISON de signaux qui a produit une entrée, pour
    l'analyse de performance et l'activation/désactivation par le module
    d'apprentissage. Ex. 'tech+fund:long', 'tech:short', 'fund:long'.

    On se base sur les familles ayant réellement tiré (direction non None) dans
    `components` (le log complet d'une décision).
    """
    fired = []
    tech = (components or {}).get("technical")
    fund = (components or {}).get("fundamental")
    if tech and tech.get("direction"):
        fired.append("tech")
    if fund and fund.get("direction"):
        fired.append("fund")
    families = "+".join(fired) if fired else "none"
    if direction is None:
        direction = (tech or {}).get("direction") or (fund or {}).get("direction")
    return f"{families}:{direction or '?'}"


def is_event_driven(components: dict) -> bool:
    """
    Vrai UNIQUEMENT si le signal fondamental (surprise macro) a réellement
    contribué une direction à la décision.

    ⚠️ Ne PAS utiliser `bool(components.get("fundamental"))` : le dict
    `fundamental` est toujours présent dès que le signal fondamental est actif
    (même neutre, direction=None) — ce qui marquerait à tort TOUS les trades
    comme event-driven et les soumettrait à la sortie forcée après quelques
    heures. Seul un trade réellement déclenché/confirmé par une surprise macro
    doit être coupé s'il ne « paie » pas rapidement.
    """
    fund = (components or {}).get("fundamental")
    return bool(fund and fund.get("direction"))


def evaluate(
    pair: str,
    now: datetime,
    candles: list[list[float]],
    events: list[EconEvent] | None = None,
    *,
    use_technical: bool = config.USE_TECHNICAL,
    use_fundamental: bool = config.USE_FUNDAMENTAL,
    use_time_filter: bool = config.USE_TIME_FILTER,
    fundamental_lookback_minutes: int | None = None,
    mode: str = config.FOREX_CONFLUENCE_MODE,
) -> ConfluenceDecision:
    """Applique la règle de confluence et retourne une décision traçable."""
    events = events or []
    reasons: list[str] = []
    components: dict = {}

    # ── Filtre temporel (peut bloquer d'emblée) ───────────
    if use_time_filter:
        gate = time_filter.can_trade(pair, now, events)
        components["time_gate"] = gate.reason
        if not gate.can_open:
            return ConfluenceDecision(False, None, 0.0, [f"bloqué : {gate.reason}"], components)
        reasons.append(gate.reason)

    # Chaque signal actif est évalué ; on collecte ceux qui « tirent » (direction
    # non None). `n_active` sert à distinguer les modes strict/any.
    n_active = 0
    fired_directions: list[str] = []
    fired_strengths: list[float] = []
    neutral_reasons: list[str] = []

    # ── Signal technique ──────────────────────────────────
    if use_technical:
        n_active += 1
        tech = technical_signal(candles)
        components["technical"] = {"direction": tech.direction, "strength": tech.strength,
                                   "reason": tech.reason, **tech.components}
        if tech.direction is None:
            neutral_reasons.append(f"technique neutre : {tech.reason}")
        else:
            fired_directions.append(tech.direction)
            fired_strengths.append(tech.strength)
            reasons.append(f"technique {tech.direction} ({tech.reason})")

    # ── Signal fondamental ────────────────────────────────
    if use_fundamental:
        n_active += 1
        fund_kwargs = {}
        if fundamental_lookback_minutes is not None:
            fund_kwargs["lookback_minutes"] = fundamental_lookback_minutes
        fund = fundamental_signal(pair, now, events, **fund_kwargs)
        components["fundamental"] = {"direction": fund.direction, "strength": fund.strength,
                                     "reason": fund.reason, "score": fund.score}
        if fund.direction is None:
            neutral_reasons.append(f"fondamental neutre : {fund.reason}")
        else:
            fired_directions.append(fund.direction)
            fired_strengths.append(fund.strength)
            reasons.append(f"fondamental {fund.direction} ({fund.reason})")

    # ── Aucun signal actif → jamais d'entrée ─────────────
    if n_active == 0:
        return ConfluenceDecision(False, None, 0.0, reasons + ["aucun signal actif"], components)

    # ── Aucun signal n'a tiré ─────────────────────────────
    if not fired_directions:
        return ConfluenceDecision(False, None, 0.0, reasons + neutral_reasons, components)

    # Mode STRICT : tous les signaux actifs doivent avoir tiré (aucun neutre).
    if mode == "strict" and len(fired_directions) < n_active:
        return ConfluenceDecision(False, None, 0.0, reasons + neutral_reasons, components)

    # Les signaux qui ont tiré doivent s'accorder en direction (dans les 2 modes).
    if len(set(fired_directions)) > 1:
        return ConfluenceDecision(False, None, 0.0,
                                  reasons + [f"désaccord de direction {fired_directions}"], components)

    direction = fired_directions[0]
    strength = sum(fired_strengths) / len(fired_strengths)
    label = "CONFLUENCE" if len(fired_directions) > 1 else "signal"
    return ConfluenceDecision(True, direction, round(strength, 3),
                              reasons + [f"{label} {direction} confirmé ({mode})"], components)
