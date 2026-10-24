"""Tests des mécanismes de sortie dynamique (forex/paper/exits.py)."""

import pytest

from forex.paper import exits


# ── trailing_stop ─────────────────────────────────────────

def test_trailing_stop_tightens_long_as_price_advances():
    new_stop = exits.trailing_stop("long", extreme_price=1.1050, atr=0.0010,
                                   atr_stop_mult=2.0, current_stop=1.0980)
    assert new_stop == pytest.approx(1.1030)  # 1.1050 - 2*0.0010


def test_trailing_stop_never_loosens_long():
    # Candidat (1.1010) est PIRE que le stop actuel (1.1030) : on garde 1.1030.
    new_stop = exits.trailing_stop("long", extreme_price=1.1030, atr=0.0010,
                                   atr_stop_mult=2.0, current_stop=1.1030)
    assert new_stop == pytest.approx(1.1030)


def test_trailing_stop_tightens_short_as_price_declines():
    new_stop = exits.trailing_stop("short", extreme_price=1.0950, atr=0.0010,
                                   atr_stop_mult=2.0, current_stop=1.1020)
    assert new_stop == pytest.approx(1.0970)  # 1.0950 + 2*0.0010


# ── breakeven_trailing_stop ────────────────────────────────

def test_breakeven_stays_at_initial_stop_below_1r():
    # Risque initial = 1.1000 - 1.0980 = 0.0020 (1R). Profit actuel = 1.1010-1.1000=0.0010 (<1R).
    new_stop = exits.breakeven_trailing_stop(
        "long", extreme_price=1.1010, atr=0.0010, atr_stop_mult=2.0,
        current_stop=1.0980, entry_price=1.1000, initial_stop=1.0980)
    assert new_stop == pytest.approx(1.0980)


def test_breakeven_jumps_to_entry_at_1r():
    # Profit = 1.1020 - 1.1000 = 0.0020 == 1R : le stop saute à l'entrée.
    new_stop = exits.breakeven_trailing_stop(
        "long", extreme_price=1.1020, atr=0.0010, atr_stop_mult=2.0,
        current_stop=1.0980, entry_price=1.1000, initial_stop=1.0980)
    assert new_stop == pytest.approx(1.1000)


def test_breakeven_trails_further_once_past_1r():
    # extreme 1.1050 : candidat trailing = 1.1050 - 0.0020 = 1.1030, > breakeven (1.1000).
    new_stop = exits.breakeven_trailing_stop(
        "long", extreme_price=1.1050, atr=0.0010, atr_stop_mult=2.0,
        current_stop=1.1000, entry_price=1.1000, initial_stop=1.0980)
    assert new_stop == pytest.approx(1.1030)


# ── chandelier_tp ──────────────────────────────────────────

def test_chandelier_tp_extends_long_as_price_advances():
    new_tp = exits.chandelier_tp("long", extreme_price=1.1100, atr=0.0010,
                                 atr_tp_mult=3.0, current_tp=1.1090)
    assert new_tp == pytest.approx(1.1130)  # 1.1100 + 3*0.0010


def test_chandelier_tp_never_retracts_long():
    new_tp = exits.chandelier_tp("long", extreme_price=1.1050, atr=0.0010,
                                 atr_tp_mult=3.0, current_tp=1.1090)
    assert new_tp == pytest.approx(1.1090)  # candidat (1.1080) < actuel : inchangé


def test_chandelier_tp_extends_short_as_price_declines():
    new_tp = exits.chandelier_tp("short", extreme_price=1.0900, atr=0.0010,
                                 atr_tp_mult=3.0, current_tp=1.0910)
    assert new_tp == pytest.approx(1.0870)  # 1.0900 - 3*0.0010


def test_breakeven_trailing_stop_short_jumps_to_entry_at_1r():
    # Short : entry=1.0950, initial_stop=1.0970 (1R = 0.0020).
    # Profit à 1.0930 = 1.0950 - 1.0930 = 0.0020 == 1R : le stop saute à l'entrée.
    new_stop = exits.breakeven_trailing_stop(
        "short", extreme_price=1.0930, atr=0.0010, atr_stop_mult=2.0,
        current_stop=1.0970, entry_price=1.0950, initial_stop=1.0970)
    assert new_stop == pytest.approx(1.0950)


def test_chandelier_tp_never_retracts_short():
    # Candidat (1.0920) est PIRE (plus haut) que le tp actuel (1.0880) pour un
    # short : on garde 1.0880.
    new_tp = exits.chandelier_tp("short", extreme_price=1.0950, atr=0.0010,
                                 atr_tp_mult=3.0, current_tp=1.0880)
    assert new_tp == pytest.approx(1.0880)
