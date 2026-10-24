"""Tests du moteur de backtest (forex/backtest/engine.py) — métriques dérivées."""

from datetime import datetime, timedelta, timezone

from forex.backtest.engine import BacktestResult, Trade, sharpe_by_session, sharpe_ratio


def _trade(entry_dt, exit_dt, pnl_pct):
    return Trade(
        pair="EUR_USD", direction="long",
        entry_ts=int(entry_dt.timestamp() * 1000), entry_price=1.10,
        exit_ts=int(exit_dt.timestamp() * 1000), exit_price=1.10,
        stop_pips=20, net_pips=pnl_pct * 20, pnl_pct=pnl_pct,
        bars_held=1, exit_reason="take-profit", event_driven=False,
    )


def test_sharpe_ratio_is_zero_with_fewer_than_two_trades():
    assert sharpe_ratio([]) == 0.0
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert sharpe_ratio([_trade(start, start + timedelta(hours=1), 1.0)]) == 0.0


def test_sharpe_ratio_is_zero_when_returns_have_no_variance():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trades = [_trade(start + timedelta(days=i), start + timedelta(days=i, hours=1), 1.0)
              for i in range(5)]
    assert sharpe_ratio(trades) == 0.0


def test_sharpe_ratio_positive_for_consistently_winning_trades():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trades = [_trade(start + timedelta(days=i), start + timedelta(days=i, hours=1),
                     1.0 if i % 2 == 0 else 0.5)
              for i in range(10)]
    assert sharpe_ratio(trades) > 0


def test_sharpe_by_session_buckets_by_entry_hour():
    tokyo_entry = datetime(2026, 7, 15, 3, tzinfo=timezone.utc)
    london_entry = datetime(2026, 7, 16, 9, tzinfo=timezone.utc)
    trades = [
        _trade(tokyo_entry, tokyo_entry + timedelta(hours=1), 1.0),
        _trade(tokyo_entry + timedelta(days=1), tokyo_entry + timedelta(days=1, hours=1), -0.5),
        _trade(london_entry, london_entry + timedelta(hours=1), 1.0),
        _trade(london_entry + timedelta(days=1), london_entry + timedelta(days=1, hours=1), 0.5),
    ]
    by_session = sharpe_by_session(trades)
    assert set(by_session) == {"tokyo", "londres"}


def test_backtest_result_sharpe_methods_match_module_functions():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trades = [_trade(start + timedelta(days=i), start + timedelta(days=i, hours=1),
                     1.0 if i % 2 == 0 else -0.3)
              for i in range(8)]
    result = BacktestResult(pair="EUR_USD", trades=trades, equity_curve=[1000.0], start_equity=1000.0)
    assert result.sharpe_ratio() == sharpe_ratio(trades)
    assert result.sharpe_by_session() == sharpe_by_session(trades)
