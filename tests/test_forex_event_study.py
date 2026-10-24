"""Tests de l'event study / CAR (détection d'edge fondamental)."""

from datetime import datetime, timedelta, timezone

from forex.data.calendar import EconEvent
from forex.backtest import event_study as es


def _build(with_edge: bool):
    """
    Construit des bougies H1 + events CPI USD.
    Si with_edge : une surprise USD positive fait BAISSER EUR_USD (USD ↑) sur la
    fenêtre suivante, une négative la fait monter → edge clair et significatif.
    Sinon : le prix ne réagit pas aux surprises → aucun edge.
    """
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    n = 2880  # 120 jours en H1
    closes = [1.10] * n
    events = []
    diffs = [0.3, -0.3, 0.2, -0.2, 0.4, -0.4, 0.15, -0.15]
    window = 6
    for k, hour in enumerate(range(72, n - window - 1, 72)):  # 1 event tous les 3 jours
        diff = diffs[k % len(diffs)]
        events.append((hour, diff))
        if with_edge:
            target = 1.10 * (1 - diff * 0.01)   # diff>0 (USD fort) ⇒ EUR_USD baisse
            for j in range(1, window + 1):
                closes[hour + j] = 1.10 + (target - 1.10) * (j / window)

    candles = []
    for i in range(n):
        ts = int((base + timedelta(hours=i)).timestamp() * 1000)
        c = closes[i]
        candles.append([ts, c, c * 1.0001, c * 0.9999, c, 0.0])

    econ = []
    for hour, diff in events:
        dt = datetime.fromtimestamp(candles[hour][0] / 1000, tz=timezone.utc)
        econ.append(EconEvent(dt=dt, currency="USD", title="CPI y/y", impact="High",
                              actual=3.0 + diff, forecast=3.0, previous=3.0))
    return candles, econ


def test_event_study_detects_real_edge():
    candles, events = _build(with_edge=True)
    res = es.event_study("EUR_USD", events, candles, window_bars=6, min_history=8)
    assert res.n_positive >= 2 and res.n_negative >= 2
    # surprises favorables à l'USD → CAR "en faveur devise" positif > défavorables
    assert res.mean_car_positive > res.mean_car_negative
    assert res.p_value < 0.05
    assert res.significant


def test_event_study_no_edge_not_significant():
    candles, events = _build(with_edge=False)
    res = es.event_study("EUR_USD", events, candles, window_bars=6, min_history=8)
    assert not res.significant  # prix insensible aux surprises → pas d'edge


def test_collect_car_samples_groups():
    candles, events = _build(with_edge=True)
    pos, neg, per_event = es.collect_car_samples("EUR_USD", events, candles,
                                                 window_bars=6, min_history=8)
    assert pos and neg
    assert "CPI" in next(iter(per_event))
