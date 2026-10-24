"""Tests des détecteurs de figures chartistes (forex/signals/patterns.py)."""

import random

from forex.signals import patterns
from forex.signals.patterns import SwingPoint


def _closes_to_candles(closes, start_ts=0):
    """
    Bougies OHLCV synthétiques : high/low sont un léger wiggle autour de la
    clôture DE LA MÊME bougie (pas de max/min avec l'open) — sinon un sommet
    « s'échoue » sur la bougie suivante (son high hérite de l'ancien close via
    max(open,close)) et crée de faux doublons de points de swing adjacents.
    """
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        o = prev
        h = c * 1.0002
        l = c * 0.9998
        out.append([start_ts + i * 3600_000, o, h, l, c, 0.0])
        prev = c
    return out


def _seg(a, b, n):
    """Segment linéaire de n points entre a et b (inclus)."""
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def _dummy_candles(n, last_close):
    """Bougies factices : seule la dernière clôture compte (utilisé avec des swings manuels)."""
    out = [[i * 3600_000, 0.0, 0.0, 0.0, 0.0, 0.0] for i in range(n - 1)]
    out.append([(n - 1) * 3600_000, last_close, last_close * 1.001, last_close * 0.999, last_close, 0.0])
    return out


# ── swing_points ──────────────────────────────────────────

def test_swing_points_detects_peaks_and_troughs():
    closes = [1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3, 2]
    candles = _closes_to_candles([float(c) for c in closes])
    swings = patterns.swing_points(candles, left=3, right=3)
    highs = {s.index for s in swings if s.kind == "high"}
    lows = {s.index for s in swings if s.kind == "low"}
    assert 4 in highs and 12 in highs
    assert 8 in lows


# ── Double Top / Double Bottom ───────────────────────────

def test_double_top_confirmed_on_neckline_break():
    atr = 0.01
    swings = [
        SwingPoint(10, 1.20, "high"),
        SwingPoint(15, 1.10, "low"),
        SwingPoint(20, 1.20, "high"),
    ]
    candles = _dummy_candles(25, last_close=1.05)
    m = patterns.detect_double_top(candles, swings, atr)
    assert m is not None and m.direction == "short"


def test_double_top_rejected_without_breakout():
    atr = 0.01
    swings = [
        SwingPoint(10, 1.20, "high"),
        SwingPoint(15, 1.10, "low"),
        SwingPoint(20, 1.20, "high"),
    ]
    candles = _dummy_candles(25, last_close=1.18)  # au-dessus de la ligne de cou
    assert patterns.detect_double_top(candles, swings, atr) is None


def test_double_top_rejected_unequal_peaks():
    atr = 0.01
    swings = [
        SwingPoint(10, 1.20, "high"),
        SwingPoint(15, 1.10, "low"),
        SwingPoint(20, 1.30, "high"),   # trop différent du premier sommet
    ]
    candles = _dummy_candles(25, last_close=1.05)
    assert patterns.detect_double_top(candles, swings, atr) is None


def test_double_bottom_confirmed_on_neckline_break():
    atr = 0.01
    swings = [
        SwingPoint(10, 1.10, "low"),
        SwingPoint(15, 1.20, "high"),
        SwingPoint(20, 1.10, "low"),
    ]
    candles = _dummy_candles(25, last_close=1.25)
    m = patterns.detect_double_bottom(candles, swings, atr)
    assert m is not None and m.direction == "long"


# ── Tête-épaules ──────────────────────────────────────────

def test_head_shoulders_bearish_confirmed():
    atr = 0.01
    swings = [
        SwingPoint(5, 1.15, "high"),    # épaule gauche
        SwingPoint(10, 1.10, "low"),
        SwingPoint(15, 1.25, "high"),   # tête
        SwingPoint(20, 1.11, "low"),
        SwingPoint(25, 1.15, "high"),   # épaule droite
    ]
    candles = _dummy_candles(30, last_close=1.08)  # sous la ligne de cou (~1.105)
    m = patterns.detect_head_shoulders(candles, swings, atr)
    assert m is not None and m.direction == "short"


def test_inverse_head_shoulders_bullish_confirmed():
    atr = 0.01
    swings = [
        SwingPoint(5, 1.15, "low"),     # épaule gauche
        SwingPoint(10, 1.20, "high"),
        SwingPoint(15, 1.05, "low"),    # tête (plus basse)
        SwingPoint(20, 1.19, "high"),
        SwingPoint(25, 1.15, "low"),    # épaule droite
    ]
    candles = _dummy_candles(30, last_close=1.22)  # au-dessus de la ligne de cou (~1.195)
    m = patterns.detect_head_shoulders(candles, swings, atr)
    assert m is not None and m.direction == "long"


def test_head_shoulders_rejected_no_breakout():
    atr = 0.01
    swings = [
        SwingPoint(5, 1.15, "high"), SwingPoint(10, 1.10, "low"),
        SwingPoint(15, 1.25, "high"), SwingPoint(20, 1.11, "low"),
        SwingPoint(25, 1.15, "high"),
    ]
    candles = _dummy_candles(30, last_close=1.14)  # pas de cassure
    assert patterns.detect_head_shoulders(candles, swings, atr) is None


# ── Triangles ─────────────────────────────────────────────

def test_ascending_triangle_breakout_long():
    atr = 0.01
    swings = [
        SwingPoint(8, 1.20, "high"), SwingPoint(18, 1.20, "high"), SwingPoint(28, 1.20, "high"),
        SwingPoint(8, 1.10, "low"), SwingPoint(18, 1.12, "low"), SwingPoint(28, 1.14, "low"),
    ]
    candles = _dummy_candles(35, last_close=1.21)
    m = patterns.detect_triangle(candles, swings, atr)
    assert m is not None and m.direction == "long" and "ascendant" in m.name


def test_descending_triangle_breakout_short():
    atr = 0.01
    swings = [
        SwingPoint(8, 1.25, "high"), SwingPoint(18, 1.20, "high"), SwingPoint(28, 1.15, "high"),
        SwingPoint(8, 1.10, "low"), SwingPoint(18, 1.10, "low"), SwingPoint(28, 1.10, "low"),
    ]
    candles = _dummy_candles(35, last_close=1.09)
    m = patterns.detect_triangle(candles, swings, atr)
    assert m is not None and m.direction == "short" and "descendant" in m.name


def test_symmetric_triangle_breakout_up_and_down():
    atr = 0.01
    swings = [
        SwingPoint(5, 1.30, "high"), SwingPoint(15, 1.25, "high"), SwingPoint(25, 1.20, "high"),
        SwingPoint(5, 1.00, "low"), SwingPoint(15, 1.05, "low"), SwingPoint(25, 1.10, "low"),
    ]
    up = patterns.detect_triangle(_dummy_candles(30, last_close=1.19), swings, atr)
    assert up is not None and up.direction == "long" and "symétrique" in up.name

    down = patterns.detect_triangle(_dummy_candles(30, last_close=1.11), swings, atr)
    assert down is not None and down.direction == "short" and "symétrique" in down.name

    forming = patterns.detect_triangle(_dummy_candles(30, last_close=1.15), swings, atr)
    assert forming is None  # encore entre les deux lignes : pas de cassure


def test_triangle_rejected_insufficient_swings():
    atr = 0.01
    swings = [SwingPoint(8, 1.20, "high"), SwingPoint(8, 1.10, "low")]  # 1 seul de chaque
    candles = _dummy_candles(35, last_close=1.25)
    assert patterns.detect_triangle(candles, swings, atr) is None


# ── Drapeau / fanion ──────────────────────────────────────

def _flag_candles(pole_closes, consol_high_low, breakout_close):
    """pole_closes: 10 valeurs ; consol_high_low: 6 tuples (high,low) ; + 1 bougie de cassure."""
    out = []
    prev = pole_closes[0]
    for i, c in enumerate(pole_closes):
        out.append([i * 3600_000, prev, max(prev, c), min(prev, c), c, 0.0])
        prev = c
    for j, (h, l) in enumerate(consol_high_low):
        c = (h + l) / 2
        out.append([(10 + j) * 3600_000, prev, h, l, c, 0.0])
        prev = c
    out.append([16 * 3600_000, prev, max(prev, breakout_close), min(prev, breakout_close), breakout_close, 0.0])
    return out


def test_bullish_flag_confirmed():
    atr = 0.001
    pole = _seg(1.100, 1.106, 10)          # impulsion +0.006 > 3×atr (0.003)
    consol = [(1.1058, 1.1052)] * 6         # range 0.0006 < 1.5×atr (0.0015)
    candles = _flag_candles(pole, consol, breakout_close=1.108)  # > 1.1058 + marge
    m = patterns.detect_flag(candles, atr)
    assert m is not None and m.direction == "long"


def test_bearish_flag_confirmed():
    atr = 0.001
    pole = _seg(1.100, 1.094, 10)           # impulsion -0.006
    consol = [(1.0948, 1.0942)] * 6
    candles = _flag_candles(pole, consol, breakout_close=1.092)  # < 1.0942 - marge
    m = patterns.detect_flag(candles, atr)
    assert m is not None and m.direction == "short"


def test_flag_rejected_without_pole():
    atr = 0.001
    pole = _seg(1.100, 1.1005, 10)  # mouvement trop faible
    consol = [(1.1007, 1.1003)] * 6
    candles = _flag_candles(pole, consol, breakout_close=1.102)
    assert patterns.detect_flag(candles, atr) is None


def test_flag_rejected_wide_consolidation():
    atr = 0.001
    pole = _seg(1.100, 1.106, 10)
    consol = [(1.110, 1.100)] * 6  # bien trop large (> 1.5×atr)
    candles = _flag_candles(pole, consol, breakout_close=1.112)
    assert patterns.detect_flag(candles, atr) is None


# ── detect_patterns (bout en bout) ────────────────────────

def test_detect_patterns_too_few_candles():
    assert patterns.detect_patterns(_dummy_candles(10, 1.10)) is None


def test_detect_patterns_end_to_end_double_top():
    seg1 = _seg(1.10, 1.20, 20)
    seg2 = _seg(1.20, 1.15, 10)[1:]
    seg3 = _seg(1.15, 1.20, 10)[1:]
    seg4 = _seg(1.20, 1.12, 8)[1:]
    closes = seg1 + seg2 + seg3 + seg4
    candles = _closes_to_candles(closes)
    m = patterns.detect_patterns(candles)
    assert m is not None and m.direction == "short"


def test_detect_patterns_none_on_flat_noise():
    random.seed(0)
    closes = [1.10 + random.gauss(0, 0.00005) for _ in range(60)]
    candles = _closes_to_candles(closes)
    assert patterns.detect_patterns(candles) is None
