"""
forex/strategies/channel_breakout.py — Bot « Cassure de canal ».

Entre sur la cassure du plus haut/bas des N dernières bougies (canal de
Donchian simplifié) — logique de suivi de tendance la plus simple qui soit,
sans aucun indicateur lissé. Stop plus serré que la moyenne (le canal lui-même
donne l'invalidation : repasser dedans annule le setup), comme SMC.
"""

from __future__ import annotations

from datetime import datetime

from forex import config
from forex.data.calendar import EconEvent
from forex.signals import indicators
from forex.strategies.base import Strategy, StrategyDecision


class ChannelBreakoutStrategy(Strategy):
    id = "channel_breakout"
    label = "Cassure de canal (plus haut/bas glissant)"
    # Archivé le 2026-07-23 : 0% de win sur 15 trades, pire retour du classement.
    enabled = False
    description = ("Entre sur la cassure du plus haut/bas des N dernières bougies "
                   "(canal de Donchian simplifié), sans indicateur lissé.")
    atr_stop_mult = 1.5
    atr_tp_mult = 3.0
    min_candles = config.FOREX_CHANNEL_BREAKOUT_BARS + config.ATR_PERIOD + 5

    def decide(
        self,
        pair: str,
        now: datetime,
        candles: list[list[float]],
        events: list[EconEvent],
        context: dict | None = None,
    ) -> StrategyDecision:
        period = config.FOREX_CHANNEL_BREAKOUT_BARS
        high = indicators.rolling_high(candles, period)
        low = indicators.rolling_low(candles, period)
        close = candles[-1][4]
        components = {"channel_high": high, "channel_low": low, "close": close}

        if high is None or low is None:
            return StrategyDecision.no("canal indisponible", components)

        if close > high:
            direction = "long"
        elif close < low:
            direction = "short"
        else:
            return StrategyDecision.no("dans le canal, pas de cassure", components)

        # Force proportionnelle à l'ampleur de la cassure relative à la largeur du canal.
        width = high - low
        breakout_size = (close - high) if direction == "long" else (low - close)
        strength = min(1.0, breakout_size / width) if width > 0 else 0.5
        reason = f"cassure {direction} du canal {period} bougies ({low:.5f}-{high:.5f})"

        return StrategyDecision(True, direction, round(strength, 3), [reason], components)
