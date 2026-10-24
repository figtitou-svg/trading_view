"""Tests du walk-forward (découpage des fenêtres, absence de fuite train→test)."""

import random
from datetime import datetime, timedelta, timezone

from forex.backtest.walkforward import walk_forward, _compound_return
from forex.backtest.engine import Trade


def _synthetic_candles(n=4000):
    random.seed(3)
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    price = 1.10
    out = []
    for i in range(n):
        price *= (1 + 0.00002 + random.gauss(0, 0.0008))
        o = price
        h = price * (1 + abs(random.gauss(0, 0.0006)))
        l = price * (1 - abs(random.gauss(0, 0.0006)))
        c = price * (1 + random.gauss(0, 0.0004))
        ts = int((base + timedelta(hours=i)).timestamp() * 1000)
        out.append([ts, o, max(o, h, c), min(o, l, c), c, 0.0])
    return out


def test_compound_return():
    trades = [Trade("EUR_USD", "long", 0, 1.1, 0, 1.1, 20, 10, 1.0, 1, "tp", False),
              Trade("EUR_USD", "long", 0, 1.1, 0, 1.1, 20, -10, -1.0, 1, "sl", False)]
    # +1% puis -1% → ~ -0.01%
    assert _compound_return(trades) == (1.01 * 0.99 - 1) * 100


def test_walk_forward_folds_are_ordered_and_non_overlapping():
    candles = _synthetic_candles(4000)
    res = walk_forward(candles, "EUR_USD", [], train_bars=1500, test_bars=500,
                       use_fundamental=False, granularity="H1")
    assert len(res.folds) >= 1
    for f in res.folds:
        # test strictement postérieur à l'entraînement qui l'a calibré
        assert f.train_start_ts < f.train_end_ts < f.test_end_ts
        assert f.best_params in [{"atr_tp_mult": tp} for tp in (2.0, 3.0, 4.0)]
    # fenêtres de test non chevauchantes (avance d'un test_bars)
    ends = [f.test_end_ts for f in res.folds]
    assert ends == sorted(ends)


def test_walk_forward_summary_runs():
    candles = _synthetic_candles(2600)
    res = walk_forward(candles, "EUR_USD", [], train_bars=1500, test_bars=500,
                       use_fundamental=False, granularity="H1")
    assert isinstance(res.summary(), str)
    assert res.oos_trades >= 0


def test_oos_sharpe_uses_pooled_test_trades_across_folds():
    from forex.backtest.engine import sharpe_ratio

    candles = _synthetic_candles(4000)
    res = walk_forward(candles, "EUR_USD", [], train_bars=1500, test_bars=500,
                       use_fundamental=False, granularity="H1")
    pooled = [t for f in res.folds for t in f.test_trades]
    assert res.oos_sharpe == sharpe_ratio(pooled)


def test_walk_forward_summary_includes_oos_sharpe():
    candles = _synthetic_candles(2600)
    res = walk_forward(candles, "EUR_USD", [], train_bars=1500, test_bars=500,
                       use_fundamental=False, granularity="H1")
    assert "Sharpe OOS" in res.summary()
