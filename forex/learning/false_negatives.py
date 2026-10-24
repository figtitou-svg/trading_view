"""
forex/learning/false_negatives.py — Analyse des opportunités manquées.

Rejoue la règle de confluence sur l'historique. À chaque barre où l'on N'entre
PAS, on regarde si un mouvement significatif (≥ `tp_mult` × ATR) s'est produit
dans les `window` barres suivantes : si oui, c'était un trade gagnant potentiel
manqué, et on **impute le filtre responsable** (technique neutre/contraire,
fondamental manquant, filtre temporel, désaccord…).

But : détecter si certains filtres sont **trop restrictifs** et font rater des
gains — sans jamais les assouplir automatiquement (informational uniquement ;
tout assouplissement passerait par la même validation que le reste).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from forex import config
from forex.data.calendar import EconEvent
from forex.signals import indicators
from forex.signals.confluence import evaluate

_GRAN_MIN = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D": 1440}


@dataclass
class FalseNegativeReport:
    pair: str
    notable_moves: int              # gros mouvements survenus en position flat
    captured: int                   # ceux où l'on ÉTAIT effectivement entré
    missed: int                     # gros mouvements ratés
    by_blocker: dict = field(default_factory=dict)

    @property
    def capture_rate(self) -> float:
        tot = self.notable_moves
        return (self.captured / tot * 100) if tot else 0.0

    def summary(self) -> str:
        lines = [
            f"[{self.pair}] opportunités : {self.notable_moves} gros mouvements · "
            f"captés {self.captured} ({self.capture_rate:.0f}%) · ratés {self.missed}",
        ]
        for blocker, n in sorted(self.by_blocker.items(), key=lambda x: -x[1]):
            lines.append(f"    ratés par {blocker} : {n}")
        return "\n".join(lines)


def _blocker(components: dict, move_dir: str, entered: bool) -> str | None:
    """Impute le filtre qui a empêché de prendre le mouvement `move_dir`."""
    if entered:
        return None
    # Le gate bloquant commence par "annonce …" ou contient "fermé" ; la raison
    # de PASSAGE est "hors fenêtre d'annonce" (ne doit pas être imputée).
    gate = components.get("time_gate", "")
    if isinstance(gate, str) and (gate.startswith("annonce") or "fermé" in gate):
        return "filtre temporel"
    tech = components.get("technical") or {}
    fund = components.get("fundamental") or {}
    tdir = tech.get("direction")
    fdir = fund.get("direction")
    if tech and tdir is None:
        return "technique neutre"
    if tech and tdir and tdir != move_dir:
        return "technique à contre-sens"
    if fund and fdir is None:
        return "fondamental manquant"
    if tdir and fdir and tdir != fdir:
        return "désaccord des signaux"
    return "autre"


def analyze(
    candles: list[list[float]],
    pair: str,
    events: list[EconEvent] | None = None,
    *,
    window: int = 6,
    tp_mult: float = config.ATR_TP_MULT,
    granularity: str = config.FOREX_GRANULARITY,
) -> FalseNegativeReport:
    """Rejoue les décisions et impute les gros mouvements manqués."""
    events = events or []
    bar_min = _GRAN_MIN.get(granularity.upper(), 60)
    warmup = max(config.MA_SLOW, config.MACD_SLOW + config.MACD_SIGNAL, config.ATR_PERIOD) + 5

    notable = captured = missed = 0
    blockers: Counter = Counter()

    for i in range(warmup, len(candles) - window):
        atr = indicators.atr(candles[max(0, i - (config.ATR_PERIOD + 1) * 3): i + 1],
                             config.ATR_PERIOD)
        if atr <= 0:
            continue
        entry_close = candles[i][4]
        future_close = candles[i + window][4]
        move = future_close - entry_close
        if abs(move) < tp_mult * atr:           # pas un « gros » mouvement
            continue
        notable += 1
        move_dir = "long" if move > 0 else "short"

        now = datetime.fromtimestamp(candles[i][0] / 1000, tz=timezone.utc)
        decision = evaluate(
            pair, now, candles[: i + 1], events,
            fundamental_lookback_minutes=bar_min + config.EXCLUSION_MIN_AFTER + 1,
        )
        entered = decision.enter and decision.direction == move_dir
        if entered:
            captured += 1
            continue
        missed += 1
        blockers[_blocker(decision.components, move_dir, entered)] += 1

    return FalseNegativeReport(pair, notable, captured, missed, dict(blockers))
