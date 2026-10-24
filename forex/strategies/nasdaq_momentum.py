"""
forex/strategies/nasdaq_momentum.py — Bot « Nasdaq Momentum ».

Suit la tendance du Nasdaq 100 (MA+MACD, sans figure chartiste — même brique
que le bot `trend`) mais n'autorise un achat que si le VIX est sous sa
moyenne récente (régime risk-on) : un indice actions casse le plus souvent à
la baisse quand la volatilité implicite s'envole, un suivi de tendance pur
achèterait alors des creux dans un marché qui continue de chuter. Aucune
restriction symétrique sur les ventes : un régime risk-off ne dément pas un
signal de vente, il le renforce plutôt.
"""

from __future__ import annotations

from datetime import datetime

from forex.data.calendar import EconEvent
from forex.signals import technical
from forex.strategies.base import Strategy, StrategyDecision


class NasdaqMomentumStrategy(Strategy):
    id = "nasdaq_momentum"
    label = "Nasdaq Momentum (filtre VIX)"
    description = ("Suivi de tendance (MA+MACD) sur le Nasdaq 100, qui n'autorise un "
                   "achat que si le VIX est sous sa moyenne récente (régime risk-on).")
    # Resserrés de 2.5/4.0 à 1.5/3.0 après backtest 2023-2026 (+41,9% → +104,3%,
    # Sharpe 1,43 → 1,99) : des stops plus serrés laissent plus de trades tourner
    # sur ce marché, chaque essai raté coûtant moins cher. Un stop encore plus
    # serré (1.0/2.0) testait mieux (Sharpe 2,31) mais dépasse la zone crédible
    # 0,5-2 documentée par sharpe_ratio() — signe de sur-optimisation, pas gardé.
    atr_stop_mult = 1.5
    atr_tp_mult = 3.0
    pairs = ["NDX_USD"]

    def decide(
        self,
        pair: str,
        now: datetime,
        candles: list[list[float]],
        events: list[EconEvent],
        context: dict | None = None,
    ) -> StrategyDecision:
        tech = technical.technical_signal(candles, use_patterns=False)
        components = tech.components.copy()

        if tech.direction is None:
            return StrategyDecision.no(tech.reason, components)

        vix = ((context or {}).get("crossasset") or {}).get("vix") or {}
        vix_last, vix_mean = vix.get("last"), vix.get("mean")
        if vix_last is None or vix_mean is None:
            return StrategyDecision.no("VIX indisponible", components)

        components["vix_last"] = vix_last
        components["vix_mean"] = vix_mean

        if tech.direction == "long" and vix_last >= vix_mean:
            return StrategyDecision.no("VIX en pic — régime risk-off", components)

        reason = f"{tech.reason} ; VIX {vix_last:.1f} vs moy {vix_mean:.1f}"
        return StrategyDecision(True, tech.direction, tech.strength, [reason], components)
