"""Tests du gate de l'auto-tuner walk-forward."""

from forex import config
from forex.learning import tuner


def test_gate_rejects_insufficient_folds(monkeypatch):
    # trop peu de folds → refus quelle que soit la perf
    monkeypatch.setattr(tuner, "_fixed_param_oos", lambda *a, **k: [5.0])  # 1 fold
    prop = tuner.propose("EUR_USD", [[0] * 6] * 10, [], {}, train_bars=2, test_bars=2)
    assert not prop.accepted and "folds insuffisants" in prop.reason


def test_gate_accepts_clear_improvement(monkeypatch):
    # base perd, un candidat gagne nettement sur tous les folds
    def fake_oos(candles, pair, events, params, **k):
        if params.get("atr_tp_mult") == config.ATR_TP_MULT and params.get("atr_stop_mult") == config.ATR_STOP_MULT:
            return [0.0, 0.0, 0.0, 0.0]           # base : neutre
        if params == {"atr_stop_mult": 2.0, "atr_tp_mult": 4.0}:
            return [3.0, 2.5, 4.0, 3.5]            # candidat : bien mieux
        return [-1.0, -1.0, -1.0, -1.0]           # autres : pires
    monkeypatch.setattr(tuner, "_fixed_param_oos", fake_oos)
    prop = tuner.propose("EUR_USD", [1] * 5000, [], {})
    assert prop.accepted
    assert prop.changes.get("atr_tp_mult") == 4.0
    assert prop.positive_folds == 4 and prop.n_folds == 4


def test_gate_rejects_small_margin(monkeypatch):
    # candidat à peine meilleur → sous la marge OOS exigée → refus
    def fake_oos(candles, pair, events, params, **k):
        base = params.get("atr_tp_mult") == config.ATR_TP_MULT and params.get("atr_stop_mult") == config.ATR_STOP_MULT
        return [1.0, 1.0, 1.0] if base else [1.1, 1.1, 1.1]
    monkeypatch.setattr(tuner, "_fixed_param_oos", fake_oos)
    prop = tuner.propose("EUR_USD", [1] * 5000, [], {})
    assert not prop.accepted and "gain OOS insuffisant" in prop.reason


def test_gate_rejects_unstable_folds(monkeypatch):
    # gros gain moyen mais folds majoritairement négatifs → instable → refus
    def fake_oos(candles, pair, events, params, **k):
        base = params.get("atr_tp_mult") == config.ATR_TP_MULT and params.get("atr_stop_mult") == config.ATR_STOP_MULT
        return [0.0, 0.0, 0.0, 0.0] if base else [30.0, -5.0, -5.0, -5.0]
    monkeypatch.setattr(tuner, "_fixed_param_oos", fake_oos)
    prop = tuner.propose("EUR_USD", [1] * 5000, [], {})
    assert not prop.accepted and "folds positifs insuffisants" in prop.reason
