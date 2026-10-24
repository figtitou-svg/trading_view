"""Tests de l'analyse de performance par combinaison (significativité)."""

import random

from forex.learning import analysis


def _trades(combo, pnl, classif, n):
    random.seed(len(combo) + n)
    return [{"combo": combo, "classification": classif,
             "pnl_pct": pnl + random.gauss(0, 0.1)} for _ in range(n)]


def test_significant_loser_and_winner():
    trades = _trades("tech:long", -1.0, "loss", 25) + _trades("tech+fund:long", 1.5, "win", 25)
    stats = analysis.analyze(trades)
    assert stats["tech:long"].significant_loser
    assert not stats["tech:long"].significant_winner
    assert stats["tech+fund:long"].significant_winner
    assert not stats["tech+fund:long"].significant_loser


def test_insufficient_sample_never_significant():
    # 5 trades perdants : pas assez d'échantillon (MIN_SAMPLE=15) → pas d'action
    stats = analysis.analyze(_trades("tech:short", -1.0, "loss", 5))
    s = stats["tech:short"]
    assert not s.enough_sample
    assert not s.significant_loser


def test_win_rate_and_expectancy():
    trades = ([{"combo": "x", "classification": "win", "pnl_pct": 2.0}] * 3 +
              [{"combo": "x", "classification": "loss", "pnl_pct": -1.0}] * 1)
    s = analysis.analyze(trades)["x"]
    assert s.win_rate == 75.0
    assert round(s.expectancy, 3) == round((2.0 * 3 - 1.0) / 4, 3)
    assert s.profit_factor == 6.0  # gains 6 / pertes 1


def test_n_live_n_backtest_breakdown():
    trades = (
        [{"combo": "x", "classification": "win", "pnl_pct": 1.0, "source": "live"}] * 2
        + [{"combo": "x", "classification": "win", "pnl_pct": 1.0, "source": "backtest"}] * 8
    )
    s = analysis.analyze(trades)["x"]
    assert s.n == 10 and s.n_live == 2 and s.n_backtest == 8


def test_source_missing_defaults_to_live():
    # Entrées sans champ 'source' (anciens trades avant l'ajout du champ)
    # comptent comme "live" — rétro-compatibilité.
    trades = [{"combo": "x", "classification": "win", "pnl_pct": 1.0}] * 3
    s = analysis.analyze(trades)["x"]
    assert s.n_live == 3 and s.n_backtest == 0


def test_historical_trades_can_reach_significance_alone():
    """Les trades historiques ont la même autorité que les vrais : un grand
    échantillon 100% backtest doit pouvoir déclencher significant_loser."""
    trades = _trades("tech:short", -1.0, "loss", 30)
    for t in trades:
        t["source"] = "backtest"
    s = analysis.analyze(trades)["tech:short"]
    assert s.n_live == 0 and s.n_backtest == 30
    assert s.significant_loser
