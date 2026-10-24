"""Tests du broker simulé (fills, comptabilité, persistance)."""

import pytest

from forex.paper.broker import PaperBroker


def _broker(tmp_path):
    return PaperBroker(path=str(tmp_path / "pf.json"), start_equity=10_000)


def test_take_profit_gains_expected_risk_multiple(tmp_path):
    b = _broker(tmp_path)
    # long, ATR 10 pips, stop_mult 2 (=20 pips), tp_mult 3 (=30 pips), risque 1%
    pos = b.open_position("EUR_USD", "long", 1.1000, 0.0010, risk_pct=1.0,
                          spread_pips=0.0, slippage_pips=0.0)
    assert pos.stop_pips == pytest.approx(20, abs=0.1)
    trade = b.on_bar("EUR_USD", high=pos.tp + 1e-5, low=1.1005, close=pos.tp,
                     ts=pos.entry_ts + 3_600_000, spread_pips=0.0, swap_pips_per_day=0.0,
                     commission_pips=0.0)
    assert trade.exit_reason == "take-profit"
    # +30 pips sur un stop de 20 pips à 1% de risque = +1.5% de l'equity
    assert trade.pnl_pct == pytest.approx(1.5, abs=0.05)
    assert b.equity == pytest.approx(10_150, abs=5)


def test_stop_loss_costs_one_risk_unit(tmp_path):
    b = _broker(tmp_path)
    pos = b.open_position("EUR_USD", "long", 1.1000, 0.0010, risk_pct=1.0,
                          spread_pips=0.0, slippage_pips=0.0)
    trade = b.on_bar("EUR_USD", high=1.1005, low=pos.stop - 1e-5, close=pos.stop,
                     ts=pos.entry_ts + 3_600_000, spread_pips=0.0, swap_pips_per_day=0.0,
                     commission_pips=0.0)
    assert trade.exit_reason == "stop-loss"
    assert trade.pnl_pct == pytest.approx(-1.0, abs=0.05)  # perd ~1 unité de risque
    assert b.equity < 10_000


def test_short_take_profit(tmp_path):
    b = _broker(tmp_path)
    pos = b.open_position("EUR_USD", "short", 1.1000, 0.0010, risk_pct=1.0,
                          spread_pips=0.0, slippage_pips=0.0)
    assert pos.tp < pos.entry_price < pos.stop
    trade = b.on_bar("EUR_USD", high=1.0995, low=pos.tp - 1e-5, close=pos.tp,
                     ts=pos.entry_ts + 3_600_000, spread_pips=0.0, swap_pips_per_day=0.0)
    assert trade.exit_reason == "take-profit"
    assert trade.pnl_pct > 0


def test_no_exit_when_price_between_stop_and_tp(tmp_path):
    b = _broker(tmp_path)
    pos = b.open_position("EUR_USD", "long", 1.1000, 0.0010)
    assert b.on_bar("EUR_USD", high=1.1010, low=1.0995, close=1.1005, ts=pos.entry_ts + 1) is None
    assert b.has_position("EUR_USD")


def test_double_open_raises(tmp_path):
    b = _broker(tmp_path)
    b.open_position("EUR_USD", "long", 1.1000, 0.0010)
    with pytest.raises(ValueError):
        b.open_position("EUR_USD", "long", 1.1000, 0.0010)


def test_force_close(tmp_path):
    b = _broker(tmp_path)
    pos = b.open_position("EUR_USD", "long", 1.1000, 0.0010)
    trade = b.force_close("EUR_USD", 1.1000, "manuel", pos.entry_ts + 1)
    assert trade is not None and trade.exit_reason == "manuel"
    assert not b.has_position("EUR_USD")


def test_persistence_roundtrip(tmp_path):
    path = str(tmp_path / "pf.json")
    b = PaperBroker(path=path, start_equity=10_000)
    pos = b.open_position("EUR_USD", "long", 1.1000, 0.0010, spread_pips=0.0, slippage_pips=0.0)
    b.on_bar("EUR_USD", high=pos.tp + 1e-5, low=1.10, close=pos.tp,
             ts=pos.entry_ts + 3_600_000, spread_pips=0.0, swap_pips_per_day=0.0)
    eq = b.equity
    b2 = PaperBroker(path=path)
    assert b2.equity == pytest.approx(eq)
    assert len(b2.trades) == 1
    assert b2.stats()["trades"] == 1


def test_commission_reduces_pnl_at_exit(tmp_path):
    b = _broker(tmp_path)
    pos = b.open_position("EUR_USD", "long", 1.1000, 0.0010, risk_pct=1.0,
                          spread_pips=0.0, slippage_pips=0.0)
    trade = b.on_bar("EUR_USD", high=pos.tp + 1e-5, low=1.1005, close=pos.tp,
                     ts=pos.entry_ts + 3_600_000, spread_pips=0.0, swap_pips_per_day=0.0,
                     commission_pips=0.6)
    # 30 pips brutes - 0,6 pip de commission, sur un stop de 20 pips à 1% de risque
    assert trade.pnl_pct == pytest.approx((30 - 0.6) / 20 * 1.0, abs=0.01)


def test_open_position_sets_dynamic_exit_fields_with_static_default(tmp_path):
    b = _broker(tmp_path)
    pos = b.open_position("EUR_USD", "long", 1.1000, 0.0010, risk_pct=1.0,
                          atr_stop_mult=2.0, atr_tp_mult=3.0,
                          spread_pips=0.0, slippage_pips=0.0)
    assert pos.exit_mode == "static"
    assert pos.adjusted is False
    assert pos.atr == 0.0010
    assert pos.atr_stop_mult == 2.0 and pos.atr_tp_mult == 3.0
    assert pos.extreme_price == pos.entry_price
    assert pos.initial_stop == pos.stop
    assert pos.initial_tp == pos.tp


def test_open_position_accepts_explicit_exit_mode(tmp_path):
    b = _broker(tmp_path)
    pos = b.open_position("EUR_USD", "long", 1.1000, 0.0010, exit_mode="trailing")
    assert pos.exit_mode == "trailing"


def test_closed_trade_carries_adjusted_flag_default_false(tmp_path):
    b = _broker(tmp_path)
    pos = b.open_position("EUR_USD", "long", 1.1000, 0.0010, spread_pips=0.0, slippage_pips=0.0)
    trade = b.on_bar("EUR_USD", high=pos.tp + 1e-5, low=1.1005, close=pos.tp,
                     ts=pos.entry_ts + 3_600_000, spread_pips=0.0, swap_pips_per_day=0.0)
    assert trade.adjusted is False


def test_update_exit_levels_is_noop_for_static(tmp_path):
    b = _broker(tmp_path)
    pos = b.open_position("EUR_USD", "long", 1.1000, 0.0010, atr_stop_mult=2.0,
                          spread_pips=0.0, slippage_pips=0.0)
    stop_before = pos.stop
    b.update_exit_levels("EUR_USD", high=1.1100, low=1.0990)
    assert b.position("EUR_USD").stop == stop_before
    assert b.position("EUR_USD").adjusted is False


def test_update_exit_levels_trailing_tightens_stop_only(tmp_path):
    b = _broker(tmp_path)
    pos = b.open_position("EUR_USD", "long", 1.1000, 0.0010, atr_stop_mult=2.0,
                          atr_tp_mult=3.0, exit_mode="trailing",
                          spread_pips=0.0, slippage_pips=0.0)
    tp_before = pos.tp
    b.update_exit_levels("EUR_USD", high=1.1050, low=1.0995)
    updated = b.position("EUR_USD")
    assert updated.stop == pytest.approx(1.1030)  # 1.1050 - 2*0.0010
    assert updated.tp == tp_before                # tp inchangé en mode trailing
    assert updated.adjusted is True


def test_update_exit_levels_chandelier_extends_both(tmp_path):
    b = _broker(tmp_path)
    pos = b.open_position("EUR_USD", "long", 1.1000, 0.0010, atr_stop_mult=2.0,
                          atr_tp_mult=3.0, exit_mode="chandelier",
                          spread_pips=0.0, slippage_pips=0.0)
    tp_before = pos.tp
    b.update_exit_levels("EUR_USD", high=1.1200, low=1.0995)
    updated = b.position("EUR_USD")
    assert updated.stop == pytest.approx(1.1180)  # 1.1200 - 2*0.0010
    assert updated.tp == pytest.approx(1.1230)    # 1.1200 + 3*0.0010
    assert updated.tp > tp_before
    assert updated.adjusted is True


def test_closed_trade_reports_adjusted_true_when_stop_moved(tmp_path):
    b = _broker(tmp_path)
    pos = b.open_position("EUR_USD", "long", 1.1000, 0.0010, atr_stop_mult=2.0,
                          exit_mode="trailing", spread_pips=0.0, slippage_pips=0.0)
    b.update_exit_levels("EUR_USD", high=1.1050, low=1.0995)  # stop trails to 1.1030
    updated_stop = b.position("EUR_USD").stop
    trade = b.on_bar("EUR_USD", high=1.1055, low=updated_stop - 1e-5, close=updated_stop,
                     ts=pos.entry_ts + 3_600_000, spread_pips=0.0, swap_pips_per_day=0.0)
    assert trade is not None
    assert trade.adjusted is True
