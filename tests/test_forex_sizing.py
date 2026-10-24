"""Tests du dimensionnement forex (pip / units / stops ATR)."""

import pytest

from forex.risk import sizing


def test_pip_size_jpy_vs_others():
    assert sizing.pip_size("EUR_USD") == 0.0001
    assert sizing.pip_size("GBP_USD") == 0.0001
    assert sizing.pip_size("USD_JPY") == 0.01


def test_parse_instrument():
    assert sizing.parse_instrument("EUR_USD") == ("EUR", "USD")


def test_price_distance_to_pips():
    assert sizing.price_distance_to_pips("EUR_USD", 0.0020) == pytest.approx(20)
    assert sizing.price_distance_to_pips("USD_JPY", 0.20) == pytest.approx(20)


def test_pip_value_quote_is_account():
    # EUR_USD, compte en USD → 1 pip = pip_size par unit
    assert sizing.pip_value_per_unit("EUR_USD", "USD", 1.10) == pytest.approx(0.0001)


def test_pip_value_base_is_account():
    # EUR_USD, compte en EUR → 1 pip = pip_size / prix
    assert sizing.pip_value_per_unit("EUR_USD", "EUR", 1.10) == pytest.approx(0.0001 / 1.10)


def test_pip_value_cross_requires_rate():
    with pytest.raises(ValueError):
        sizing.pip_value_per_unit("GBP_USD", "EUR", 1.25)  # ni base ni quote = EUR
    # avec le taux fourni, ça passe
    val = sizing.pip_value_per_unit("GBP_USD", "EUR", 1.25, quote_to_account_rate=0.92)
    assert val == pytest.approx(0.0001 * 0.92)


def test_units_from_risk_never_exceeds_risk():
    # 10 000 de capital, 1% risque = 100 ; stop 20 pips ; compte USD, EUR_USD @1.10
    units = sizing.units_from_risk(10_000, 1.0, 20, "EUR_USD", "USD", 1.10)
    # perte au stop = units * 20 * 0.0001 ≤ 100
    assert units * 20 * 0.0001 <= 100 + 1e-9
    assert units == 50_000  # 100 / (20*0.0001)


def test_units_from_risk_degenerate_returns_zero():
    assert sizing.units_from_risk(0, 1.0, 20, "EUR_USD", "USD", 1.10) == 0
    assert sizing.units_from_risk(10_000, 1.0, 0, "EUR_USD", "USD", 1.10) == 0
    assert sizing.units_from_risk(10_000, 0, 20, "EUR_USD", "USD", 1.10) == 0


def test_atr_stops_long_and_short():
    stop, tp = sizing.atr_stops(1.1000, 0.0010, "long", 2.0, 3.0)
    assert stop == pytest.approx(1.0980)
    assert tp == pytest.approx(1.1030)
    stop, tp = sizing.atr_stops(1.1000, 0.0010, "short", 2.0, 3.0)
    assert stop == pytest.approx(1.1020)
    assert tp == pytest.approx(1.0970)


def test_atr_stops_invalid_direction():
    with pytest.raises(ValueError):
        sizing.atr_stops(1.10, 0.001, "sideways", 2.0, 3.0)
