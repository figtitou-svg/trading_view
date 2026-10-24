"""
forex/strategies/tsm.py — Bot « Momentum temporel » (Time-Series Momentum).

Suit le signe du rendement cumulé sur une fenêtre glissante : long si la paire
a monté sur la période, short si elle a baissé — sans lire aucun indicateur de
structure (MA, MACD, RSI), pour mesurer la contribution du momentum PUR,
indépendamment du bot `trend` (qui combine plusieurs signaux).

Inspiré des études académiques sur le momentum devises (le rendement passé
prédit statistiquement le rendement futur sur un horizon de plusieurs
semaines) — recherche externe : QuantInsti EPAT (walk-forward, Sharpe OOS
modeste 0,43-0,78, pas de paramètres pointus). Fenêtre en BOUGIES (pas en
jours) pour rester cohérent avec la granularité configurée.
"""

from __future__ import annotations

from datetime import datetime

from forex import config
from forex.data.calendar import EconEvent
from forex.signals import indicators
from forex.strategies.base import Strategy, StrategyDecision


class TSMStrategy(Strategy):
    id = "tsm"
    label = "Momentum temporel (TSM, signe du rendement cumulé)"
    description = ("Suit le signe du rendement cumulé sur une fenêtre glissante "
                   "(momentum pur), sans indicateur de structure (MA, MACD, RSI).")
    # Momentum de moyen terme : stop/objectif plus larges qu'un bot intrabar.
    atr_stop_mult = 2.5
    atr_tp_mult = 4.0
    min_candles = config.FOREX_TSM_LOOKBACK_BARS + config.ATR_PERIOD + 5

    def decide(
        self,
        pair: str,
        now: datetime,
        candles: list[list[float]],
        events: list[EconEvent],
        context: dict | None = None,
    ) -> StrategyDecision:
        closes = [c[4] for c in candles]
        cumret = indicators.cumulative_return(closes, config.FOREX_TSM_LOOKBACK_BARS)
        components = {"cumulative_return": round(cumret, 5) if cumret is not None else None}

        if cumret is None or cumret == 0:
            return StrategyDecision.no("rendement cumulé indisponible ou nul", components)

        direction = "long" if cumret > 0 else "short"
        # Force proportionnelle à l'ampleur du mouvement : 10% de rendement
        # cumulé sur la fenêtre = force maximale (repère rond, pas calibré).
        strength = min(1.0, abs(cumret) / 0.10)
        reason = (f"momentum {direction} : rendement cumulé {cumret:+.2%} "
                 f"sur {config.FOREX_TSM_LOOKBACK_BARS} bougies")

        return StrategyDecision(True, direction, round(strength, 3), [reason], components)
