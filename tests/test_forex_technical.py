"""Tests des indicateurs et du signal technique forex."""

import random

import pytest

import forex.signals.technical as technical_mod
from forex.signals import indicators
from forex.signals.patterns import PatternMatch
from forex.signals.technical import technical_signal


def _candles_from_closes(closes):
    """Bougies OHLCV synthétiques à partir d'une liste de clôtures."""
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        hi = max(prev, c) * 1.0002
        lo = min(prev, c) * 0.9998
        out.append([i * 3600_000, prev, hi, lo, c, 0.0])
        prev = c
    return out


def _walk(seed, drift, n=280):
    """Marche aléatoire avec dérive (uptrend/downtrend réaliste : RSI modéré)."""
    random.seed(seed)
    p = 1.10
    closes = []
    for _ in range(n):
        p *= (1 + drift + random.gauss(0, 0.0015))
        closes.append(p)
    return closes


def test_ema_and_sma_basics():
    assert indicators.sma([1, 2, 3, 4], 2) == pytest.approx(3.5)
    assert indicators.ema([1, 1, 1, 1, 1], 3) == pytest.approx(1.0)
    assert indicators.ema([1, 2], 5) is None  # pas assez de données


def test_rsi_bounds():
    assert indicators.rsi([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]) == 100.0
    assert indicators.rsi([15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]) == 0.0
    assert indicators.rsi([1, 2]) == 50.0  # neutre si trop court


def test_macd_line_sign_on_trends():
    up = [float(x) for x in range(1, 80)]
    down = [float(x) for x in range(80, 1, -1)]
    m_up = indicators.macd(up)
    m_down = indicators.macd(down)
    # la LIGNE MACD (EMA rapide vs lente) est positive en tendance haussière
    assert m_up is not None and m_up[0] > 0
    assert m_down is not None and m_down[0] < 0
    assert indicators.macd([1.0, 2.0, 3.0]) is None  # insuffisant


def test_technical_signal_long_on_uptrend():
    res = technical_signal(_candles_from_closes(_walk(7, 0.0006)))
    assert res.direction == "long"
    assert 0 < res.strength <= 1
    assert res.components["macd_line"] is not None


def test_technical_signal_not_long_on_downtrend():
    res = technical_signal(_candles_from_closes(_walk(7, -0.0006)))
    assert res.direction != "long"  # short ou None, jamais long


def test_technical_signal_none_when_insufficient():
    res = technical_signal(_candles_from_closes([1.1, 1.2, 1.3]))
    assert res.direction is None
    assert res.strength == 0.0


def test_pattern_absent_preserves_legacy_ma_macd_requirement(monkeypatch):
    """Sans figure détectée, le comportement doit être IDENTIQUE à l'ancienne
    règle stricte MA-ET-MACD (non-régression du vote à la majorité)."""
    monkeypatch.setattr(technical_mod.patterns, "detect_patterns", lambda candles: None)
    candles = _candles_from_closes(_walk(7, 0.0006))  # uptrend : MA et MACD haussiers ici
    res = technical_signal(candles)
    assert res.direction == "long"


def test_strong_pattern_breaks_ma_macd_tie(monkeypatch):
    """Une figure chartiste forte peut débloquer une entrée que MA+MACD seuls
    n'auraient pas validée, si l'un des deux s'accorde avec elle."""
    candles = _candles_from_closes(_walk(7, 0.0006))  # MA haussier ; on force MACD baissier

    def fake_macd(closes, fast, slow, signal):
        return (-0.001, -0.0005, -0.0005)  # ligne MACD négative → baissier

    monkeypatch.setattr(technical_mod.indicators, "macd", fake_macd)

    # Sans figure : MA haussier vs MACD baissier → désaccord → pas d'entrée.
    monkeypatch.setattr(technical_mod.patterns, "detect_patterns", lambda c: None)
    assert technical_signal(candles).direction is None

    # Avec une figure haussière forte : MA + figure forment la majorité → long.
    monkeypatch.setattr(
        technical_mod.patterns, "detect_patterns",
        lambda c: PatternMatch("Triangle ascendant", "long", 0.8, "cassure nette"),
    )
    res = technical_signal(candles)
    assert res.direction == "long"
    assert res.components["pattern"] == "Triangle ascendant"
    assert "figure" in res.reason
