"""Tests des briques Smart Money Concepts (forex/signals/smc.py)."""

from datetime import datetime, timezone

from forex.signals import smc


def _c(ts, o, h, l, c):
    return [ts * 3600_000, o, h, l, c, 0.0]


def _flat(n, price=1.10, start=0):
    """Série plate : aucune structure, aucune inefficience."""
    return [_c(start + i, price, price, price, price) for i in range(n)]


# ── Fair Value Gaps ───────────────────────────────────────

def test_fvg_bullish_detected():
    """Le high de i-2 sous le low de i = trou haussier."""
    candles = _flat(5)
    candles.append(_c(5, 1.10, 1.11, 1.10, 1.11))     # i-2 : high 1.11
    candles.append(_c(6, 1.11, 1.20, 1.11, 1.20))     # impulsion
    candles.append(_c(7, 1.20, 1.21, 1.15, 1.20))     # i : low 1.15 > 1.11
    zones = smc.fair_value_gaps(candles, atr=0.01)
    bull = [z for z in zones if z.direction == "long"]
    assert bull, "un FVG haussier aurait dû être détecté"
    assert bull[-1].bottom == 1.11 and bull[-1].top == 1.15


def test_fvg_bearish_detected():
    candles = _flat(5)
    candles.append(_c(5, 1.20, 1.20, 1.19, 1.19))     # i-2 : low 1.19
    candles.append(_c(6, 1.19, 1.19, 1.10, 1.10))     # impulsion baissière
    candles.append(_c(7, 1.10, 1.15, 1.09, 1.10))     # i : high 1.15 < 1.19
    zones = smc.fair_value_gaps(candles, atr=0.01)
    bear = [z for z in zones if z.direction == "short"]
    assert bear and bear[-1].bottom == 1.15 and bear[-1].top == 1.19


def test_fvg_ignores_gaps_smaller_than_atr_threshold():
    """Un micro-trou est du bruit de cotation, pas une inefficience."""
    candles = _flat(5)
    candles.append(_c(5, 1.10, 1.1000, 1.10, 1.10))
    candles.append(_c(6, 1.10, 1.1010, 1.10, 1.1005))
    candles.append(_c(7, 1.1005, 1.1010, 1.1001, 1.1005))  # trou de 0,1 pip
    assert smc.fair_value_gaps(candles, atr=0.01) == []


def test_no_fvg_on_flat_series():
    assert smc.fair_value_gaps(_flat(30), atr=0.01) == []


# ── Order Blocks ──────────────────────────────────────────

def test_order_block_bullish_is_last_bearish_candle_before_impulse():
    candles = _flat(5)
    candles.append(_c(5, 1.11, 1.115, 1.105, 1.106))   # bougie baissière = OB
    candles.append(_c(6, 1.106, 1.16, 1.106, 1.155))   # impulsion haussière
    zones = smc.order_blocks(candles, atr=0.01, impulse_atr=1.0)
    bull = [z for z in zones if z.direction == "long"]
    assert bull, "un Order Block haussier aurait dû être détecté"
    assert bull[-1].bottom == 1.105 and bull[-1].top == 1.115


def test_order_block_requires_real_impulse():
    """Sans mouvement d'au moins impulse_atr × ATR, aucun Order Block."""
    candles = _flat(5)
    candles.append(_c(5, 1.11, 1.115, 1.105, 1.106))
    candles.append(_c(6, 1.106, 1.108, 1.106, 1.107))  # mouvement minuscule
    assert smc.order_blocks(candles, atr=0.01, impulse_atr=1.0) == []


# ── Structure de marché ───────────────────────────────────

def test_market_structure_detects_bullish_break():
    """Une clôture au-dessus d'un sommet de swing confirmé donne un biais long."""
    candles = _flat(10, 1.10)
    # Sommet marqué puis retour, ensuite cassure franche au-dessus.
    candles += [_c(10, 1.10, 1.10, 1.10, 1.10), _c(11, 1.10, 1.12, 1.10, 1.12)]
    candles += _flat(6, 1.10, start=12)
    candles += [_c(18 + i, 1.10, 1.14, 1.10, 1.13) for i in range(4)]
    st = smc.market_structure(candles)
    assert st.bias == "long"
    assert st.event in {"BOS", "CHoCH"}


def test_market_structure_none_without_swings():
    st = smc.market_structure(_flat(50))
    assert st.bias is None


def test_market_structure_bias_persists_after_the_break():
    """
    Le biais doit rester valable plusieurs bougies APRÈS la cassure : c'est ce
    qui permet à l'entrée d'arriver plus tard, sur le repli dans une zone.
    Exiger la coïncidence des deux événements rendrait le signal muet.
    """
    candles = _flat(10, 1.10)
    candles += [_c(10, 1.10, 1.10, 1.10, 1.10), _c(11, 1.10, 1.12, 1.10, 1.12)]
    candles += _flat(6, 1.10, start=12)
    candles += [_c(18 + i, 1.10, 1.14, 1.10, 1.13) for i in range(4)]
    # Quelques bougies calmes après la cassure : le biais doit tenir.
    candles += _flat(3, 1.125, start=22)
    st = smc.market_structure(candles)
    assert st.bias == "long"
    assert st.bars_ago > 0


# ── Sessions ──────────────────────────────────────────────

def test_sessions_london_and_new_york():
    assert "londres" in smc.active_sessions(datetime(2026, 7, 15, 9, tzinfo=timezone.utc))
    assert "new-york" in smc.active_sessions(datetime(2026, 7, 15, 14, tzinfo=timezone.utc))


def test_asian_session_is_not_liquid_for_smc():
    """La session asiatique est exclue : trop peu de volume institutionnel."""
    asian = datetime(2026, 7, 15, 3, tzinfo=timezone.utc)
    assert smc.active_sessions(asian) == ["tokyo"]
    assert not smc.in_liquid_session(asian)


def test_smc_signal_silent_outside_liquid_sessions():
    # Marché volatil (ATR non nul) pour isoler VRAIMENT le refus de session :
    # sur une série plate, le signal serait déjà rejeté faute d'ATR.
    candles = [_c(i, 1.10 + (i % 5) * 0.002, 1.10 + (i % 5) * 0.002 + 0.003,
                  1.10 + (i % 5) * 0.002 - 0.003, 1.10 + (i % 5) * 0.002 + 0.001)
               for i in range(120)]
    res = smc.smc_signal(candles, datetime(2026, 7, 15, 3, tzinfo=timezone.utc))
    assert res.direction is None
    assert "session" in res.reason.lower()


def test_smc_signal_silent_on_flat_market():
    res = smc.smc_signal(_flat(120), datetime(2026, 7, 15, 14, tzinfo=timezone.utc))
    assert res.direction is None
