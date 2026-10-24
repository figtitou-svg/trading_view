"""
forex/strategies/oil_breakout.py — Bot « Pétrole Breakout ».

Cassure de canal (même brique que `channel_breakout`, cf. forex/strategies/
channel_breakout.py) mais validée uniquement si l'amplitude récente des
bougies dépasse l'amplitude qui précède : le pétrole WTI est sujet à des
cassures brutales sur choc d'offre/stocks hebdo, mais aussi à de nombreuses
fausses cassures en régime calme — ce filtre d'expansion de volatilité
cherche à ne garder que les premières. Amplitude moyenne (vraie plage sur
`_VOL_WINDOW` bougies) plutôt que l'ATR lissé de Wilder : plus sensible aux
toutes dernières bougies, donc plus adapté à détecter un changement de
régime récent qu'une moyenne glissante à décroissance lente.
"""

from __future__ import annotations

from datetime import datetime

from forex import config
from forex.data.calendar import EconEvent
from forex.signals import indicators
from forex.strategies.base import Strategy, StrategyDecision

_VOL_WINDOW = 5


def _true_range(candles: list[list[float]], i: int) -> float:
    """Amplitude réelle (vraie plage) de la bougie `i` : max(H-L, |H-PC|, |L-PC|)."""
    high, low = candles[i][2], candles[i][3]
    prev_close = candles[i - 1][4]
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def _avg_true_range(candles: list[list[float]], start: int, n: int) -> float:
    """Moyenne arithmétique simple de l'amplitude réelle sur `n` bougies à
    partir de `start` (pas de lissage Wilder)."""
    return sum(_true_range(candles, i) for i in range(start, start + n)) / n


def _volatility_expanding(candles: list[list[float]], window: int = _VOL_WINDOW) -> bool:
    """Amplitude moyenne des `window` dernières bougies > celle des `window`
    bougies précédentes : régime de volatilité en expansion.

    La bougie courante (celle qui porte potentiellement la cassure) est
    intentionnellement incluse dans la fenêtre « récente » : l'objectif est
    de détecter une volatilité concomitante à la cassure elle-même, pas
    seulement une volatilité qui la précède strictement."""
    n = len(candles)
    if n < 2 * window + 1:
        return False
    recent = _avg_true_range(candles, n - window, window)
    prior = _avg_true_range(candles, n - 2 * window, window)
    return recent > prior


class OilBreakoutStrategy(Strategy):
    id = "oil_breakout"
    label = "Pétrole Breakout (expansion de volatilité)"
    description = ("Cassure du plus haut/bas des 20 dernières bougies sur le pétrole "
                   "WTI, validée seulement si l'amplitude récente des prix est en "
                   "expansion (filtre les fausses cassures en régime calme).")
    # Resserrés de 1.5/3.0 à 1.0/2.0 après backtest 2024-2026 (+6,8% → +17,1%,
    # Sharpe 0,24 → 0,40, maxDD 28,6% → 19,3%) : optimum local vérifié — un
    # stop encore plus serré (0.75/1.5) fait rechuter la performance, donc ce
    # n'est pas juste "plus serré = mieux" (signature typique de sur-ajustement).
    atr_stop_mult = 1.0
    atr_tp_mult = 2.0
    # canal (20) + 2×fenêtre de volatilité (2×5=10) + marge de sécurité (5)
    min_candles = config.FOREX_CHANNEL_BREAKOUT_BARS + 2 * _VOL_WINDOW + 5
    pairs = ["WTI_USD"]

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

        if not _volatility_expanding(candles):
            components["volatility_expanding"] = False
            return StrategyDecision.no("cassure sans expansion de volatilité", components)
        components["volatility_expanding"] = True

        width = high - low
        breakout_size = (close - high) if direction == "long" else (low - close)
        strength = min(1.0, breakout_size / width) if width > 0 else 0.5
        reason = f"cassure {direction} du canal {period} bougies, volatilité en expansion"

        return StrategyDecision(True, direction, round(strength, 3), [reason], components)
