"""
forex/strategies/ma_crossover.py — Bot « Croisement de moyennes mobiles ».

Signal PUR de croisement EMA rapide/lente (20/100 par défaut) : long si la
rapide est au-dessus de la lente, short sinon — sans MACD ni RSI ni figures,
pour mesurer la contribution du croisement seul, isolément du bot `trend`
(MA 50/200 + MACD + RSI combinés).
"""

from __future__ import annotations

from datetime import datetime

from forex import config
from forex.data.calendar import EconEvent
from forex.signals import indicators
from forex.strategies.base import Strategy, StrategyDecision


class MACrossoverStrategy(Strategy):
    id = "ma_crossover"
    label = "Croisement de moyennes mobiles (EMA rapide vs lente)"
    # Archivé le 2026-07-23 : 0% de win sur 15 trades, pire retour du classement.
    enabled = False
    description = ("Croisement pur de deux moyennes mobiles (EMA rapide/lente), "
                   "sans MACD ni RSI ni figures — mesure la contribution du "
                   "croisement seul.")
    min_candles = config.FOREX_MA_CROSSOVER_SLOW + 5

    def decide(
        self,
        pair: str,
        now: datetime,
        candles: list[list[float]],
        events: list[EconEvent],
        context: dict | None = None,
    ) -> StrategyDecision:
        closes = [c[4] for c in candles]
        ema_fast = indicators.ema(closes, config.FOREX_MA_CROSSOVER_FAST)
        ema_slow = indicators.ema(closes, config.FOREX_MA_CROSSOVER_SLOW)
        components = {
            "ema_fast": round(ema_fast, 6) if ema_fast is not None else None,
            "ema_slow": round(ema_slow, 6) if ema_slow is not None else None,
        }

        if ema_fast is None or ema_slow is None or ema_fast == ema_slow:
            return StrategyDecision.no("moyennes indisponibles ou égales", components)

        direction = "long" if ema_fast > ema_slow else "short"
        # Force proportionnelle à l'écart relatif entre les deux moyennes.
        gap = abs(ema_fast - ema_slow) / ema_slow
        strength = min(1.0, gap / 0.02)  # 2% d'écart = force maximale
        reason = (f"EMA{config.FOREX_MA_CROSSOVER_FAST} "
                 f"{'>' if direction == 'long' else '<'} "
                 f"EMA{config.FOREX_MA_CROSSOVER_SLOW}")

        return StrategyDecision(True, direction, round(strength, 3), [reason], components)
