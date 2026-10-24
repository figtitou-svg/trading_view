"""
forex/strategies/chartist.py — Bot « figures chartistes ».

Utilise les détecteurs déjà écrits et testés (`forex.signals.patterns`) —
double top/bottom, tête-épaules (+ inversée), triangles, drapeaux/fanions —
mais comme **source d'entrée autonome** au lieu d'un simple votant noyé dans
le signal technique.

Le nom de la figure est exposé en `setup` : la clé de combo devient donc
`double-top:short`, `triangle-ascendant:long`, etc. L'apprentissage peut ainsi
désactiver une figure précise qui ne paie pas (les drapeaux, par exemple) sans
condamner toutes les autres — impossible tant que les figures votaient en bloc.

(Le module s'appelle `chartist` et non `patterns` pour ne pas entrer en
collision d'import avec `forex.signals.patterns`, dont il dépend.)
"""

from __future__ import annotations

from datetime import datetime

from forex import config
from forex.data.calendar import EconEvent
from forex.signals import indicators, patterns
from forex.strategies.base import Strategy, StrategyDecision


class ChartistStrategy(Strategy):
    id = "chartist"
    label = "Figures chartistes (double top, tête-épaules, triangles, drapeaux)"
    description = ("Entre sur des figures chartistes détectées automatiquement "
                   "(double top/bottom, tête-épaules, triangles, drapeaux).")
    # Les figures se jouent sur la cassure : pas besoin des 200 bougies de la
    # MA lente, seulement de la fenêtre de détection + de quoi calculer l'ATR.
    min_candles = config.FOREX_PATTERN_LOOKBACK + config.ATR_PERIOD + 5

    def decide(
        self,
        pair: str,
        now: datetime,
        candles: list[list[float]],
        events: list[EconEvent],
        context: dict | None = None,
    ) -> StrategyDecision:
        pattern = patterns.detect_patterns(candles)
        if pattern is None:
            return StrategyDecision.no("aucune figure détectée", {"setup": None})

        rsi_v = indicators.rsi([c[4] for c in candles], config.RSI_PERIOD)
        components = {
            "setup": pattern.name,
            "pattern": pattern.name,
            "pattern_reason": pattern.reason,
            "pattern_strength": pattern.strength,
            "rsi": rsi_v,
        }

        # Même filtre d'invalidation que le bot tendance : on n'achète pas une
        # cassure haussière en plein surachat (le mouvement est déjà consommé).
        if pattern.direction == "long" and rsi_v >= config.RSI_OVERBOUGHT:
            return StrategyDecision.no(
                f"figure {pattern.name} ignorée — RSI {rsi_v} (surachat)", components)
        if pattern.direction == "short" and rsi_v <= config.RSI_OVERSOLD:
            return StrategyDecision.no(
                f"figure {pattern.name} ignorée — RSI {rsi_v} (survente)", components)

        return StrategyDecision(
            True, pattern.direction, pattern.strength,
            [f"figure {pattern.name} {pattern.direction} ({pattern.reason})"],
            components,
        )
