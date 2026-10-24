"""Tests des coûts (commission) du moteur de backtest (forex/backtest/engine.py)."""

import pytest

from forex.backtest.engine import run_backtest
from forex.strategies.base import Strategy, StrategyDecision


class _AlwaysLongStrategy(Strategy):
    """Bot de test : entre long dès que possible, pour isoler l'effet des coûts."""

    id = "always-long-test"
    label = "Bot de test : entre long dès que possible"
    min_candles = 1

    def decide(self, pair, now, candles, events, context=None):
        return StrategyDecision(True, "long", 1.0, ["test"], {"setup": "test"})


def _trending_candles(n=250, start_price=1.10, step=0.0002):
    out = []
    price = start_price
    for i in range(n):
        price += step
        out.append([i * 3600_000, price, price + 0.0005, price - 0.0005, price, 0.0])
    return out


def test_commission_reduces_net_pips_versus_zero_commission():
    candles = _trending_candles()
    common = dict(warmup=1, spread_pips=0.0, slippage_pips=0.0,
                  swap_pips_per_day=0.0, use_time_filter=False,
                  strategy=_AlwaysLongStrategy())
    baseline = run_backtest(candles, "EUR_USD", [], commission_pips=0.0, **common)
    with_commission = run_backtest(candles, "EUR_USD", [], commission_pips=1.0, **common)

    assert baseline.n >= 1
    assert with_commission.n == baseline.n
    for t_base, t_comm in zip(baseline.trades, with_commission.trades):
        assert t_comm.net_pips == pytest.approx(t_base.net_pips - 1.0, abs=0.01)
