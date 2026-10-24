"""
forex/strategies/trend.py — Bot « suivi de tendance » (baseline).

Reprend TELLE QUELLE la logique technique historique du bot forex :
MA50/200 + signe de la ligne MACD (les deux doivent s'accorder), RSI en filtre
d'invalidation des extrêmes.

Rôle : **référence de comparaison**. On sait déjà (backfill de 7619 trades sur
10 paires) que cette approche seule est un perdant statistiquement significatif
après coûts ; elle reste en place pour que les nouveaux bots soient jugés
contre une baseline connue plutôt que dans le vide. Si un bot ne bat pas
`trend`, il n'apporte rien.
"""

from __future__ import annotations

from datetime import datetime

from forex import config
from forex.data.calendar import EconEvent
from forex.signals.technical import technical_signal
from forex.strategies.base import Strategy, StrategyDecision


class TrendStrategy(Strategy):
    id = "trend"
    label = "Tendance (MA50/200 + MACD + RSI)"
    description = ("Suit la tendance : MA50/200 et MACD doivent s'accorder, RSI en "
                   "filtre. Sert de référence pour juger les autres bots.")
    min_candles = config.MA_SLOW + 5

    def decide(
        self,
        pair: str,
        now: datetime,
        candles: list[list[float]],
        events: list[EconEvent],
        context: dict | None = None,
    ) -> StrategyDecision:
        # use_patterns=False : les figures chartistes sont un bot séparé.
        tech = technical_signal(candles, use_patterns=False)
        components = {"setup": "trend", **tech.components}

        if tech.direction is None:
            return StrategyDecision.no(f"tendance neutre : {tech.reason}", components)

        return StrategyDecision(
            True, tech.direction, tech.strength,
            [f"tendance {tech.direction} ({tech.reason})"], components,
        )
