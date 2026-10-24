"""Tests du texte de rapport de validation (forex/backtest/report.py)."""

from datetime import datetime, timedelta, timezone

from forex.backtest.engine import BacktestResult, Trade
from forex.backtest.report import ValidationReport


def _trade(entry_dt, pnl_pct):
    return Trade(
        pair="EUR_USD", direction="long",
        entry_ts=int(entry_dt.timestamp() * 1000), entry_price=1.10,
        exit_ts=int((entry_dt + timedelta(hours=1)).timestamp() * 1000), exit_price=1.10,
        stop_pips=20, net_pips=pnl_pct * 20, pnl_pct=pnl_pct,
        bars_held=1, exit_reason="take-profit", event_driven=False,
    )


def _result(trades):
    return BacktestResult(pair="EUR_USD", trades=trades,
                          equity_curve=[1000.0] * (len(trades) + 1), start_equity=1000.0)


def _report(confluence, technical_only):
    return ValidationReport(
        pair="EUR_USD", n_candles=1000, n_events=0,
        confluence=confluence, technical_only=technical_only,
        buy_hold_pct=0.0, study=None, walk=None,
    )


def test_report_flags_suspiciously_high_sharpe():
    start = datetime(2026, 1, 1, 9, tzinfo=timezone.utc)  # londres
    trades = [_trade(start + timedelta(days=i), 1.0 + (0.01 if i % 2 == 0 else -0.01))
              for i in range(10)]
    report = _report(_result(trades), _result([]))
    assert "suspect" in report.text()


def test_report_flags_weak_sharpe():
    start = datetime(2026, 1, 1, 9, tzinfo=timezone.utc)
    trades = [_trade(start + timedelta(days=i), 0.2 if i % 2 == 0 else -0.198)
              for i in range(10)]
    report = _report(_result(trades), _result([]))
    text = report.text()
    assert "faible" in text or "nul" in text


def test_report_shows_sharpe_by_session():
    start = datetime(2026, 1, 1, 9, tzinfo=timezone.utc)  # londres
    trades = [_trade(start + timedelta(days=i), 0.5 if i % 2 == 0 else -0.4) for i in range(6)]
    report = _report(_result(trades), _result([]))
    text = report.text()
    assert "Sharpe par session" in text
    assert "londres" in text
