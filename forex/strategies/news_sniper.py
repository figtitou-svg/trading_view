"""
forex/strategies/news_sniper.py — Bot « News Sniper » (Bot B)

Surveille les annonces économiques récentes à fort impact (High).
Si la donnée réelle (Actual) surpasse largement la prévision (Forecast),
prend instantanément position pour surfer l'impulsion algorithmique,
sans regarder l'analyse technique.
"""

from __future__ import annotations

from datetime import datetime

from forex.data.calendar import EconEvent
from forex.strategies.base import Strategy, StrategyDecision


class NewsSniperStrategy(Strategy):
    id = "news_sniper"
    label = "News Sniper (Volatilité Calendrier)"
    description = ("Surveille les annonces à fort impact : si la donnée réelle "
                   "surprend fortement la prévision, prend position dans "
                   "l'impulsion, sans analyse technique.")
    # Scalping : stop très serré, take profit asymétrique.
    atr_stop_mult = 1.0
    atr_tp_mult = 4.0
    # La logique d'entrée ne dépend d'aucune bougie (uniquement du calendrier) :
    # pas de seuil minimal ici, sinon le bot resterait bloqué tant que le
    # runner n'a pas encore accumulé d'historique de prix pour la paire.
    min_candles = 0

    def decide(
        self,
        pair: str,
        now: datetime,
        candles: list[list[float]],
        events: list[EconEvent],
        context: dict | None = None,
    ) -> StrategyDecision:
        if "_" not in pair:
            return StrategyDecision.no("format de paire invalide", {})

        base, quote = pair.split("_")
        components: dict = {}

        # On cherche une annonce "High" impact dans les 60 dernières minutes
        # sur l'une des devises de la paire.
        recent_surprises = []

        for ev in events:
            age_min = (now - ev.dt).total_seconds() / 60
            if not (0 <= age_min <= 60 and ev.impact == "High" and ev.has_result):
                continue
            if ev.currency not in (base, quote):
                continue

            diff = ev.actual - ev.forecast

            # Normalisation basique : un écart positif = bullish pour la devise.
            # Pour le chômage (Unemployment/Jobless), un diff positif est BÉARISH.
            is_bearish_event = "unemployment" in ev.title.lower() or "jobless" in ev.title.lower()
            if is_bearish_event:
                diff = -diff

            if diff == 0:
                continue

            # Direction pour la paire : bonne surprise sur le base -> achat,
            # bonne surprise sur le quote -> vente (et inversement).
            if diff > 0:
                direction = "long" if ev.currency == base else "short"
            else:
                direction = "short" if ev.currency == base else "long"

            surprise_ratio = abs(diff) / (abs(ev.forecast) or 1.0)
            if surprise_ratio > 0.05:  # filtre les micro-surprises (< 5% d'écart)
                recent_surprises.append((surprise_ratio, direction, ev.title, diff))

        if not recent_surprises:
            return StrategyDecision.no("pas de surprise macro récente", components)

        # La surprise la plus forte l'emporte si plusieurs annonces sont tombées
        # dans la même fenêtre (rare, mais deux devises peuvent publier ensemble).
        surprise_ratio, direction, title, diff = max(recent_surprises, key=lambda s: s[0])
        strength = min(1.0, surprise_ratio)
        reasons = [f"surprise {title} (écart {diff:+.2f}, {surprise_ratio:.0%})"]
        components["surprise_event"] = title
        components["surprise_ratio"] = round(surprise_ratio, 3)

        return StrategyDecision(True, direction, round(strength, 3), reasons, components)
