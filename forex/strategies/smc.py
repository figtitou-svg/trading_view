"""
forex/strategies/smc.py — Bot « Smart Money Concepts ».

Exploite les inefficiences de liquidité (`forex.signals.smc`) : biais donné par
la structure de marché (BOS/CHoCH), entrée sur mitigation d'un Fair Value Gap
ou d'un Order Block, uniquement pendant les sessions Londres / New York.

C'est la piste d'edge la plus crédible du lot : elle ne prédit pas le prix, elle
se positionne là où un déséquilibre d'ordres a été laissé. Le stop est plus
serré que celui du bot tendance (la zone elle-même donne l'invalidation : si le
prix la traverse, le setup est faux), ce qui améliore le rapport risque/gain.

⚠️ Aucune promesse de rentabilité : ce bot est mis en concurrence avec les
autres et sera jugé par le même appareil statistique (t-test, walk-forward). Il
sera coupé par l'apprentissage s'il ne prouve rien, exactement comme `trend`.
"""

from __future__ import annotations

from datetime import datetime

from forex import config
from forex.data.calendar import EconEvent
from forex.signals import smc
from forex.strategies.base import Strategy, StrategyDecision


class SMCStrategy(Strategy):
    id = "smc"
    label = "Smart Money (FVG, Order Blocks, BOS/CHoCH, sessions)"
    description = ("Exploite les déséquilibres de liquidité (Smart Money) : entrée "
                   "sur mitigation d'un Fair Value Gap ou d'un Order Block, en "
                   "sessions Londres/New York.")
    # L'invalidation vient de la zone, pas d'une volatilité générique : stop
    # plus serré, objectif plus lointain → rapport risque/gain ~1:3.
    atr_stop_mult = config.FOREX_SMC_ATR_STOP_MULT
    atr_tp_mult = config.FOREX_SMC_ATR_TP_MULT
    min_candles = config.FOREX_SMC_LOOKBACK + config.ATR_PERIOD + 10

    def decide(
        self,
        pair: str,
        now: datetime,
        candles: list[list[float]],
        events: list[EconEvent],
        context: dict | None = None,
    ) -> StrategyDecision:
        res = smc.smc_signal(candles, now)
        components = dict(res.components)
        components.setdefault("setup", None)

        if res.direction is None:
            return StrategyDecision.no(res.reason, components)

        return StrategyDecision(
            True, res.direction, res.strength, [res.reason], components,
        )
