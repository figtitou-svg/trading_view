"""
forex/strategies/gold_macro.py — Bot « Or Macro ».

L'or est piloté par les taux réels : il monte quand le rendement du 10 ans US
baisse (le coût d'opportunité de détenir un actif sans rendement diminue) et
inversement. Contrairement à un suivi de tendance, l'or oscille plus qu'il ne
tend hors période de crise : le bot combine donc un retour à la moyenne
(bandes ATR autour d'une moyenne mobile) avec ce biais macro directionnel,
au lieu du suivi de tendance pur utilisé par les bots forex existants.

Garde-fou de tendance long terme (SMA 200) : le backtest 2024-2026 a montré
un retour à la moyenne SANS filtre de tendance perdant -13,5% pendant que
l'or doublait (222 shorts contre 128 longs) — le mean-reversion pariait sans
cesse contre un marché structurellement haussier. Le bot n'autorise donc
plus un short que si le prix est déjà sous sa SMA200 (tendance de fond
baissière), et un long que s'il est au-dessus (tendance de fond haussière) :
la confluence bande+taux reste nécessaire mais n'est plus suffisante seule.
"""

from __future__ import annotations

from datetime import datetime

from forex import config
from forex.data.calendar import EconEvent
from forex.signals import indicators
from forex.strategies.base import Strategy, StrategyDecision

_BAND_MULT = 1.5


class GoldMacroStrategy(Strategy):
    id = "gold_macro"
    label = "Or Macro (retour à la moyenne + taux réels)"
    description = ("Retour à la moyenne (bandes ATR) sur l'or, activé seulement quand "
                   "le rendement du 10 ans US confirme la direction (taux en baisse "
                   "pour un achat, en hausse pour une vente).")
    # Resserré/asymétrisé de 2.0/3.0 à 1.5/4.0 après balayage sur 2024-2026
    # (-1,2% → +9,7%, Sharpe -0,03 → 0,42) : la largeur de bande (1.5) et le
    # filtre de tendance restent ceux d'origine, seul le ratio stop/tp change.
    # Environ 20 variantes testées (stop/tp, largeur de bande, avec/sans
    # chaque filtre) ; un cran plus serré (1.25/4.0) testait encore un peu
    # mieux mais le gain marginal ne justifiait pas de pousser plus loin le
    # risque de sur-ajustement à cette fenêtre précise.
    atr_stop_mult = 1.5
    atr_tp_mult = 4.0
    # SMA200 (filtre de tendance) est la contrainte la plus longue désormais.
    min_candles = config.MA_SLOW + config.ATR_PERIOD + 5
    pairs = ["XAU_USD"]

    def decide(
        self,
        pair: str,
        now: datetime,
        candles: list[list[float]],
        events: list[EconEvent],
        context: dict | None = None,
    ) -> StrategyDecision:
        closes = [c[4] for c in candles]
        mean = indicators.sma(closes, config.MA_FAST)
        trend = indicators.sma(closes, config.MA_SLOW)
        atr_val = indicators.atr(candles, config.ATR_PERIOD)
        close = closes[-1]
        components = {"mean": mean, "trend_sma200": trend, "atr": atr_val, "close": close}

        if mean is None or trend is None or atr_val <= 0:
            return StrategyDecision.no("indicateurs indisponibles", components)

        upper = mean + _BAND_MULT * atr_val
        lower = mean - _BAND_MULT * atr_val
        components.update(band_upper=round(upper, 3), band_lower=round(lower, 3))

        us10y = ((context or {}).get("crossasset") or {}).get("us10y")
        if not us10y:
            return StrategyDecision.no("taux 10 ans indisponible", components)

        yield_change = us10y.get("change_pct", 0.0)
        components["us10y_change_pct"] = yield_change

        if close <= lower and yield_change < 0 and close > trend:
            direction = "long"
        elif close >= upper and yield_change > 0 and close < trend:
            direction = "short"
        else:
            return StrategyDecision.no("hors bande, taux non confirmé, ou contre la tendance de fond",
                                       components)

        width = upper - lower
        dist = (lower - close) if direction == "long" else (close - upper)
        strength = min(1.0, 0.3 + dist / width) if width > 0 else 0.5
        reason = f"retour à la moyenne {direction}, 10y {yield_change:+.2f}%"

        return StrategyDecision(True, direction, round(strength, 3), [reason], components)
