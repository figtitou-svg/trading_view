"""Tests des garde-fous de risque forex (levier ESMA + kill-switch)."""

from datetime import datetime, timezone

import pytest

from forex.risk import manager


def test_major_vs_minor_pair():
    assert manager.is_major_pair("EUR_USD")
    assert not manager.is_major_pair("EUR_TRY")


def test_max_leverage_caps():
    assert manager.max_leverage("EUR_USD") == 30.0     # majeure
    assert manager.max_leverage("EUR_TRY") == 20.0     # mineure
    assert manager.max_leverage("XAU_USD") == 20.0     # or


def test_check_leverage_allows_within_cap():
    # 30 000 notionnel / 10 000 capital = 3:1 ≤ 30:1
    chk = manager.check_leverage("EUR_USD", 30_000, 1.0, 10_000)
    assert chk.allowed and chk.leverage == pytest.approx(3.0)


def test_check_leverage_rejects_above_cap():
    # 400 000 notionnel / 10 000 = 40:1 > 30:1
    chk = manager.check_leverage("EUR_USD", 400_000, 1.0, 10_000)
    assert not chk.allowed


def test_daily_loss_kill_switch():
    rm = manager.RiskManager(10_000, daily_loss_limit_pct=3.0)
    d = datetime(2026, 1, 5, tzinfo=timezone.utc)
    rm.start_day(10_000, d)
    rm.update_equity(9_800, d)   # -2% → OK
    assert rm.can_open_trade()[0]
    rm.update_equity(9_650, d)   # -3.5% → coupé
    ok, why = rm.can_open_trade()
    assert not ok and "jour" in why


def test_weekly_loss_kill_switch():
    rm = manager.RiskManager(10_000, daily_loss_limit_pct=50, weekly_loss_limit_pct=6.0)
    d = datetime(2026, 1, 5, tzinfo=timezone.utc)
    rm.start_day(10_000, d)
    rm.start_week(10_000)
    rm.update_equity(9_300, d)   # -7% semaine
    ok, why = rm.can_open_trade()
    assert not ok and "semaine" in why


def test_trailing_drawdown_kill_switch():
    rm = manager.RiskManager(10_000, daily_loss_limit_pct=100, weekly_loss_limit_pct=100,
                             trailing_drawdown_pct=10.0)
    d = datetime(2026, 1, 5, tzinfo=timezone.utc)
    rm.start_day(10_000, d)
    rm.update_equity(12_000, d)  # nouveau pic
    # nouveau jour : perte du jour repart de 0, mais le drawdown depuis le pic reste
    d2 = datetime(2026, 1, 6, tzinfo=timezone.utc)
    rm.update_equity(10_700, d2)  # -10.8% depuis pic 12 000
    assert rm.daily_loss_pct() == pytest.approx(0.0)
    ok, why = rm.can_open_trade()
    assert not ok and "drawdown" in why
