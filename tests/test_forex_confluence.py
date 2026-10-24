"""Tests de la règle de confluence + désactivation indépendante des signaux."""

import random
from datetime import datetime, timedelta, timezone

from forex.data.calendar import EconEvent
from forex.signals.confluence import evaluate, is_event_driven

END = datetime(2026, 1, 7, 15, 0, tzinfo=timezone.utc)  # mercredi, marché ouvert
LOOKBACK = 66


def _walk_candles(drift, end_dt=END, seed=7, n=280):
    """Bougies H1 (marche aléatoire à dérive) anticipant END, horodatées à l'heure."""
    random.seed(seed)
    closes, p = [], 1.10
    for _ in range(n):
        p *= (1 + drift + random.gauss(0, 0.0015))
        closes.append(p)
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        ts = int((end_dt - timedelta(hours=(n - 1 - i))).timestamp() * 1000)
        out.append([ts, prev, max(prev, c) * 1.0002, min(prev, c) * 0.9998, c, 0.0])
        prev = c
    return out


def _uptrend_candles(end_dt=END):
    return _walk_candles(0.0006, end_dt)      # → signal technique long


def _downtrend_candles(end_dt=END):
    return _walk_candles(-0.0006, end_dt)


def _events(currency="EUR", actual=5.0, forecast=3.0):
    """10 annonces d'historique + une grosse surprise juste avant END."""
    diffs = [0.0, 0.2, -0.2, 0.4, -0.4, 0.1, -0.1, 0.3, -0.3, 0.0]
    start = datetime(2025, 1, 10, 13, 30, tzinfo=timezone.utc)
    out = [EconEvent(dt=start + timedelta(days=30 * i), currency=currency, title="CPI y/y",
                     impact="High", actual=3.0 + diffs[i], forecast=3.0, previous=3.0)
           for i in range(10)]
    out.append(EconEvent(dt=END - timedelta(minutes=30), currency=currency, title="CPI y/y",
                         impact="High", actual=actual, forecast=forecast, previous=forecast))
    return out


def test_confluence_enters_long_when_both_align():
    # technique haussière (uptrend) + surprise EUR positive → EUR_USD long
    d = evaluate("EUR_USD", END, _uptrend_candles(), _events("EUR"),
                 use_time_filter=False, fundamental_lookback_minutes=LOOKBACK)
    assert d.enter and d.direction == "long"
    # log complet : les deux familles sont présentes dans components
    assert "technical" in d.components and "fundamental" in d.components


def test_disagreement_blocks_entry():
    # technique haussière mais surprise USD positive → USD_USD... EUR_USD short → désaccord
    d = evaluate("EUR_USD", END, _uptrend_candles(), _events("USD"),
                 use_time_filter=False, fundamental_lookback_minutes=LOOKBACK)
    assert not d.enter


def test_technical_only_when_fundamental_disabled():
    d = evaluate("EUR_USD", END, _uptrend_candles(), [],
                 use_technical=True, use_fundamental=False, use_time_filter=False)
    assert d.enter and d.direction == "long"
    assert "fundamental" not in d.components


def test_fundamental_only_when_technical_disabled():
    # pas besoin de tendance technique : seul le fondamental décide
    d = evaluate("EUR_USD", END, _downtrend_candles(), _events("EUR"),
                 use_technical=False, use_fundamental=True, use_time_filter=False,
                 fundamental_lookback_minutes=LOOKBACK)
    assert d.enter and d.direction == "long"
    assert "technical" not in d.components


def test_no_signal_active_never_enters():
    d = evaluate("EUR_USD", END, _uptrend_candles(), _events("EUR"),
                 use_technical=False, use_fundamental=False, use_time_filter=False)
    assert not d.enter


def test_strict_mode_requires_all_active_signals():
    # technique long mais AUCUN event (fondamental neutre) :
    #   - strict → pas d'entrée (le fondamental actif n'a pas tiré)
    #   - any    → entrée (le technique suffit)
    strict = evaluate("EUR_USD", END, _uptrend_candles(), [],
                      use_technical=True, use_fundamental=True, use_time_filter=False,
                      mode="strict", fundamental_lookback_minutes=LOOKBACK)
    assert not strict.enter
    permissive = evaluate("EUR_USD", END, _uptrend_candles(), [],
                          use_technical=True, use_fundamental=True, use_time_filter=False,
                          mode="any", fundamental_lookback_minutes=LOOKBACK)
    assert permissive.enter and permissive.direction == "long"


def test_is_event_driven_only_when_fundamental_fired():
    # Régression du bug « sortie temporelle » : un trade purement technique
    # (fondamental présent mais neutre, direction=None) ne doit PAS être
    # marqué event-driven.
    tech_only = {"technical": {"direction": "long"},
                 "fundamental": {"direction": None, "reason": "aucune surprise"}}
    assert not is_event_driven(tech_only)
    # Fondamental qui a réellement tiré → event-driven.
    with_fund = {"technical": {"direction": "long"},
                 "fundamental": {"direction": "long", "score": 1.2}}
    assert is_event_driven(with_fund)
    # Pas de fondamental du tout → pas event-driven.
    assert not is_event_driven({"technical": {"direction": "short"}})


def test_time_filter_blocks_on_weekend():
    saturday = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
    d = evaluate("EUR_USD", saturday, _uptrend_candles(saturday), _events("EUR"),
                 use_time_filter=True, fundamental_lookback_minutes=LOOKBACK)
    assert not d.enter
    assert "bloqué" in d.reasons[0]
