"""
forex/strategies/macro_trend.py — Bot « Macro Confluence ».

Combine le suivi de tendance classique (MA+MACD, sans figures chartistes) avec
le score macroéconomique (différentiel de taux directeurs via FRED, cf.
forex.data.macro). Ne prend un trade en tendance que si les fondamentaux
soutiennent la même direction — une confluence technique+fondamentale
indépendante de forex.signals.confluence (qui ne connaît que la surprise
d'annonce, pas le niveau de taux).

Restreint aux paires où les DEUX devises ont une couverture FRED (USD/EUR/
GBP/JPY) : sur les autres (AUD, CAD, CHF, NZD...), get_pair_macro_bias()
renvoie toujours 0.0, ce qui bloquerait systématiquement TOUTE entrée (0.0 ne
dépasse jamais les seuils ±0.1 ci-dessous) — un bot qui ne peut mathématiquement
jamais trader une paire ne doit pas prétendre la couvrir.
"""

from __future__ import annotations

from datetime import datetime

from forex import config
from forex.data.calendar import EconEvent
from forex.data.macro import get_pair_macro_bias
from forex.signals import technical
from forex.strategies.base import Strategy, StrategyDecision


class MacroTrendStrategy(Strategy):
    id = "macro_trend"
    label = "Macro Confluence (Tendance + Taux directeurs)"
    description = ("Combine tendance classique (MA+MACD) et score macro "
                   "(différentiel de taux directeurs) : n'entre en tendance que si "
                   "les fondamentaux sont d'accord.")
    # On laisse respirer le trade car les fondamentaux agissent sur le long terme.
    atr_stop_mult = 3.0
    atr_tp_mult = 5.0
    min_candles = config.MA_SLOW + 5
    pairs = ["EUR_USD", "GBP_USD", "USD_JPY", "EUR_GBP", "EUR_JPY", "GBP_JPY"]

    def decide(
        self,
        pair: str,
        now: datetime,
        candles: list[list[float]],
        events: list[EconEvent],
        context: dict | None = None,
    ) -> StrategyDecision:
        # 1. Évaluer la tendance (MA+MACD+RSI, sans figures : bot séparé).
        tech = technical.technical_signal(candles, use_patterns=False)
        components = tech.components.copy()

        # 2. Récupérer le biais macro (mis en cache en interne, cf. forex.data.macro).
        macro_bias = get_pair_macro_bias(pair)
        components["macro_bias"] = round(macro_bias, 3)

        if tech.direction is None:
            return StrategyDecision.no(tech.reason, components)

        # 3. Filtrage macro : confluence stricte.
        #    - Achat (long) : le biais macro doit être positif (> 0.1 pour être sûr).
        #    - Vente (short) : le biais macro doit être négatif (< -0.1).
        direction = tech.direction
        is_long = direction == "long"

        if is_long and macro_bias <= 0.1:
            return StrategyDecision.no("biais macro insuffisant pour achat", components)
        if not is_long and macro_bias >= -0.1:
            return StrategyDecision.no("biais macro insuffisant pour vente", components)

        # Économie ET graphique d'accord.
        strength = min(1.0, tech.strength + abs(macro_bias))
        reasons = [tech.reason, f"confluence macro ({macro_bias:+.2f})"]

        return StrategyDecision(True, direction, round(strength, 3), reasons, components)
