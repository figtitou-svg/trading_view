"""
forex/strategies/macro.py — Bot « macro » (refondu).

Ne dépend plus d'une annonce économique pour avoir un avis : il note chaque
devise tous les jours (force relative, régime de risque, taux, matières
premières — cf. `forex.signals.macro`) et prend position sur les paires dont
l'écart de score est significatif.

Horizon plus long que les autres bots : un déséquilibre macro se corrige en
jours, pas en heures. Stop et objectif sont donc plus larges.
"""

from __future__ import annotations

from datetime import datetime

from forex import config
from forex.data.calendar import EconEvent
from forex.signals import macro
from forex.strategies.base import Strategy, StrategyDecision


class MacroStrategy(Strategy):
    id = "macro"
    label = "Macro (force des devises, risk-on/off, taux, matières premières)"
    description = ("Note chaque devise chaque jour (force relative, risk-on/off, "
                   "taux, matières premières) et prend position sur les écarts "
                   "significatifs. Horizon de plusieurs jours.")
    atr_stop_mult = config.FOREX_MACRO_ATR_STOP_MULT
    atr_tp_mult = config.FOREX_MACRO_ATR_TP_MULT
    # Il faut de quoi mesurer la performance récente sur la fenêtre de force.
    min_candles = config.FOREX_MACRO_STRENGTH_BARS + config.ATR_PERIOD + 5

    def decide(
        self,
        pair: str,
        now: datetime,
        candles: list[list[float]],
        events: list[EconEvent],
        context: dict | None = None,
    ) -> StrategyDecision:
        context = context or {}
        candles_by_pair = context.get("candles_by_pair") or {pair: candles}
        cross = context.get("crossasset") or {}

        res = macro.macro_signal(pair, now, candles_by_pair, cross, events)
        components = dict(res.components)
        components["macro_score"] = res.score

        if res.direction is None:
            return StrategyDecision.no(res.reason, components)

        return StrategyDecision(
            True, res.direction, res.strength, [res.reason], components,
        )
