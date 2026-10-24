# tests/test_forex_indicators_rolling.py
"""Tests des helpers glissants (forex/signals/indicators.py)."""

import pytest

from forex.signals import indicators


def test_cumulative_return_basic():
    closes = [100.0] * 10 + [110.0]
    assert indicators.cumulative_return(closes, 10) == pytest.approx(0.10)


def test_cumulative_return_none_with_insufficient_history():
    assert indicators.cumulative_return([1.0, 2.0], 5) is None


def test_cumulative_return_none_on_zero_base():
    assert indicators.cumulative_return([0.0, 1.0], 1) is None


def test_rolling_high_excludes_current_bar_by_default():
    candles = [[0, 1, 1.0, 0.9, 1.0, 0], [1, 1, 1.5, 0.9, 1.0, 0], [2, 1, 1.2, 0.9, 1.0, 0]]
    # dernière bougie (high=1.2) exclue -> plus haut des 2 précédentes = 1.5
    assert indicators.rolling_high(candles, 2) == 1.5


def test_rolling_low_excludes_current_bar_by_default():
    candles = [[0, 1, 1.1, 0.8, 1.0, 0], [1, 1, 1.1, 0.95, 1.0, 0], [2, 1, 1.1, 0.5, 1.0, 0]]
    assert indicators.rolling_low(candles, 2) == 0.8


def test_rolling_high_none_with_insufficient_history():
    assert indicators.rolling_high([[0, 1, 1, 1, 1, 0]], 5) is None


def test_rolling_low_none_with_insufficient_history():
    assert indicators.rolling_low([[0, 1, 1, 1, 1, 0]], 5) is None


def test_rolling_high_includes_current_bar_when_exclude_last_false():
    candles = [[0, 1, 1.0, 0.9, 1.0, 0], [1, 1, 1.5, 0.9, 1.0, 0], [2, 1, 1.2, 0.9, 1.0, 0]]
    # avec exclude_last=False, la bougie courante (high=1.2) entre dans la fenêtre
    # -> plus haut des 2 dernières bougies (1.5 et 1.2) = 1.5, mais sur une fenêtre différente
    assert indicators.rolling_high(candles, 2, exclude_last=False) == 1.5
    # fenêtre de 1 bougie : ne contient que la bougie courante -> son propre high
    assert indicators.rolling_high(candles, 1, exclude_last=False) == 1.2


def test_rolling_low_includes_current_bar_when_exclude_last_false():
    candles = [[0, 1, 1.1, 0.8, 1.0, 0], [1, 1, 1.1, 0.95, 1.0, 0], [2, 1, 1.1, 0.5, 1.0, 0]]
    # fenêtre de 1 bougie avec exclude_last=False : ne contient que la bougie courante -> son propre low
    assert indicators.rolling_low(candles, 1, exclude_last=False) == 0.5


def test_rolling_high_none_when_period_zero():
    candles = [[0, 1, 1.0, 0.9, 1.0, 0], [1, 1, 1.5, 0.9, 1.0, 0]]
    assert indicators.rolling_high(candles, 0) is None


def test_rolling_low_none_when_period_zero():
    candles = [[0, 1, 1.0, 0.9, 1.0, 0], [1, 1, 1.5, 0.9, 1.0, 0]]
    assert indicators.rolling_low(candles, 0) is None


def test_cumulative_return_none_when_lookback_zero():
    assert indicators.cumulative_return([1.0, 2.0, 3.0], 0) is None
