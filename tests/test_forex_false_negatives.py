"""Tests de l'analyse des opportunités manquées (faux négatifs)."""

import random
from datetime import datetime, timezone, timedelta

from forex.learning import false_negatives


def _candles(n=1200, seed=5):
    random.seed(seed)
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    p, out = 1.10, []
    for i in range(n):
        p *= (1 + random.gauss(0, 0.0015))
        o = p
        h = p * (1 + abs(random.gauss(0, 0.0008)))
        l = p * (1 - abs(random.gauss(0, 0.0008)))
        c = p * (1 + random.gauss(0, 0.0005))
        out.append([int((base + timedelta(hours=i)).timestamp() * 1000),
                    o, max(o, h, c), min(o, l, c), c, 0.0])
    return out


def test_accounting_invariants():
    rep = false_negatives.analyze(_candles(), "EUR_USD", [], window=6, granularity="H1")
    # des mouvements notables existent sur une marche aléatoire volatile
    assert rep.notable_moves > 0
    # cohérence comptable : captés + ratés = notables
    assert rep.captured + rep.missed == rep.notable_moves
    # chaque raté est imputé à exactement un filtre
    assert sum(rep.by_blocker.values()) == rep.missed
    assert 0 <= rep.capture_rate <= 100


def test_summary_runs():
    rep = false_negatives.analyze(_candles(600), "EUR_USD", [], granularity="H1")
    assert "EUR_USD" in rep.summary()
