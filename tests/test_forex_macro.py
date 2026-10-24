"""Tests du modèle macro quotidien (forex/signals/macro.py)."""

from datetime import datetime, timezone

from forex.signals import macro


def _series(prices):
    return [[i * 3600_000, p, p, p, p, 0.0] for i, p in enumerate(prices)]


def _rising(n=60, start=1.10, step=0.001):
    return _series([start + i * step for i in range(n)])


def _falling(n=60, start=1.10, step=0.001):
    return _series([start - i * step for i in range(n)])


NOW = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)


# ── Force relative des devises ────────────────────────────

def test_currency_strength_base_up_quote_down():
    """EUR/USD qui monte = EUR fort, USD faible, symétriquement."""
    s = macro.currency_strength({"EUR_USD": _rising()}, bars=48)
    assert s["EUR"] > 0 and s["USD"] < 0
    assert s["EUR"] == -s["USD"]


def test_currency_strength_averages_across_pairs():
    """
    Une devise forte contre TOUTES les autres doit ressortir nettement : c'est
    tout l'intérêt de moyenner sur plusieurs paires plutôt que d'en lire une.
    """
    s = macro.currency_strength({
        "EUR_USD": _rising(),
        "EUR_GBP": _rising(),
        "USD_JPY": _falling(),
    }, bars=48)
    assert s["EUR"] > s["USD"]
    assert s["EUR"] > s["GBP"]


def test_currency_strength_ignores_too_short_series():
    assert macro.currency_strength({"EUR_USD": _rising(10)}, bars=48) == {}


# ── Régime de risque ──────────────────────────────────────

def test_risk_off_when_vix_spikes():
    regime, intensity = macro.risk_regime({"vix": {"change_pct": 25.0},
                                           "gold": {"change_pct": 2.0}})
    assert regime == "risk-off" and intensity > 0


def test_risk_on_when_vix_collapses():
    regime, _ = macro.risk_regime({"vix": {"change_pct": -25.0},
                                   "gold": {"change_pct": -1.0}})
    assert regime == "risk-on"


def test_no_regime_when_vix_calm():
    regime, intensity = macro.risk_regime({"vix": {"change_pct": 1.0}})
    assert regime is None and intensity == 0.0


def test_no_regime_without_vix_data():
    assert macro.risk_regime({}) == (None, 0.0)


def test_risk_off_favours_safe_havens_over_risk_currencies():
    """En stress, le JPY doit être mieux noté que l'AUD, toutes choses égales."""
    scores, detail = macro.currency_scores({}, {"vix": {"change_pct": 30.0},
                                                "gold": {"change_pct": 3.0}})
    assert detail["regime"] == "risk-off"
    assert scores["JPY"] > scores["AUD"]
    assert scores["CHF"] > scores["NZD"]


# ── Signal composite ──────────────────────────────────────

def test_macro_signal_fires_on_significant_spread():
    """Le bot doit avoir un avis tous les jours, sans aucune annonce macro."""
    res = macro.macro_signal("EUR_USD", NOW,
                             {"EUR_USD": _rising(), "EUR_GBP": _rising()},
                             {}, [], threshold=0.05)
    assert res.direction == "long"
    assert res.strength > 0


def test_macro_signal_silent_below_threshold():
    res = macro.macro_signal("EUR_USD", NOW, {"EUR_USD": _rising()}, {}, [],
                             threshold=99.0)
    assert res.direction is None
    assert "seuil" in res.reason


def test_macro_signal_needs_both_currencies():
    res = macro.macro_signal("EUR_USD", NOW, {}, {}, [])
    assert res.direction is None
