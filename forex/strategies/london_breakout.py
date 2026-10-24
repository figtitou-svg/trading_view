"""
forex/strategies/london_breakout.py — Bot « Cassure Londres ».

Marque le plus haut/bas de la session Tokyo (00h-08h UTC), puis cherche une
cassure de ce range une fois la session Londres ouverte — logique reprise
d'une implémentation Python publique (github.com/je-suis-tm/quant-trading,
« London Breakout »), avec deux corrections délibérées par rapport à la
source :
  1. Le ratio risque/gain original (stop 100bp / TP 50bp, soit 1:0,5) exige
     plus de 66% de trades gagnants pour être rentable, même sans coûts. On
     utilise ici les multiples ATR standards du bot (stop resserré, objectif
     ~1,7x plus large), cohérents avec les autres cassures du projet (SMC,
     canal).
  2. Le backtest de la source ne modélise aucun coût (spread/slippage/
     commission) — ce bot est validé exclusivement via le moteur du projet,
     qui les inclut tous.

N'entre QUE dans les `FOREX_LONDON_BREAKOUT_WINDOW_HOURS` premières heures de
la session Londres (l'essentiel du mouvement de transition Tokyo->Londres se
joue à l'ouverture, pas n'importe quand pendant la session).
"""

from __future__ import annotations

from datetime import datetime, timezone

from forex import config
from forex.data.calendar import EconEvent
from forex.signals import sessions
from forex.strategies.base import Strategy, StrategyDecision

_LONDON_OPEN_HOUR = sessions.SESSIONS["londres"][0]


class LondonBreakoutStrategy(Strategy):
    id = "london_breakout"
    label = "Cassure Londres (range Tokyo -> ouverture Londres)"
    # Archivé le 2026-07-23 : 0% de win sur 15 trades, pire retour du classement.
    enabled = False
    description = ("Marque le range de la session Tokyo puis cherche une cassure "
                   "de ce range à l'ouverture de la session Londres.")
    atr_stop_mult = 1.5
    atr_tp_mult = 2.5
    # Une journée complète (couvre la session Tokyo) + marge de warmup.
    min_candles = 24 + config.ATR_PERIOD + 5

    def decide(
        self,
        pair: str,
        now: datetime,
        candles: list[list[float]],
        events: list[EconEvent],
        context: dict | None = None,
    ) -> StrategyDecision:
        now_utc = now.astimezone(timezone.utc)
        components = {"sessions": sessions.active_sessions(now_utc)}

        if "londres" not in components["sessions"]:
            return StrategyDecision.no("hors session Londres", components)

        hours_since_open = now_utc.hour - _LONDON_OPEN_HOUR
        if hours_since_open < 0 or hours_since_open >= config.FOREX_LONDON_BREAKOUT_WINDOW_HOURS:
            return StrategyDecision.no("hors fenêtre d'ouverture Londres", components)

        # Range Tokyo : bougies dont l'horodatage tombe dans la session Tokyo
        # (00h-08h UTC) du jour courant, hors la bougie en cours. Tokyo (0-8)
        # et l'ouverture Londres (7h) se chevauchent d'une heure : évaluer à
        # 7h (ouverture pile) ne voit que 7 bougies Tokyo (0-6, la 7e étant la
        # bougie courante exclue), évaluer à 8h ou plus tard en voit 8 (0-7).
        # Comportement intentionnel (couvert par les tests aux heures 7/8/10),
        # pas un bug : le range se stabilise dès la 2e bougie de la fenêtre.
        tokyo_start, tokyo_end = sessions.SESSIONS["tokyo"]
        tokyo_bars = []
        for c in candles[:-1]:
            dt = datetime.fromtimestamp(c[0] / 1000, tz=timezone.utc)
            if tokyo_start <= dt.hour < tokyo_end and dt.date() == now_utc.date():
                tokyo_bars.append(c)

        if not tokyo_bars:
            return StrategyDecision.no("range Tokyo introuvable", components)

        tokyo_high = max(c[2] for c in tokyo_bars)
        tokyo_low = min(c[3] for c in tokyo_bars)
        close = candles[-1][4]
        components.update(tokyo_high=tokyo_high, tokyo_low=tokyo_low, close=close)

        if close > tokyo_high:
            direction = "long"
        elif close < tokyo_low:
            direction = "short"
        else:
            return StrategyDecision.no("dans le range Tokyo, pas de cassure", components)

        width = tokyo_high - tokyo_low
        breakout_size = (close - tokyo_high) if direction == "long" else (tokyo_low - close)
        strength = min(1.0, breakout_size / width) if width > 0 else 0.5
        reason = (f"cassure {direction} du range Tokyo ({tokyo_low:.5f}-{tokyo_high:.5f}) "
                 "à l'ouverture Londres")

        return StrategyDecision(True, direction, round(strength, 3), [reason], components)
