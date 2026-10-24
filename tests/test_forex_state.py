"""Tests de l'état appris (overrides, changelog, rollback)."""

from forex.learning import state


def test_apply_param_change_and_read(tmp_path):
    p = str(tmp_path / "learned.json")
    state.apply_param_change("EUR_USD", "atr_tp_mult", 4.0, "walk-forward", 5, path=p)
    assert state.get_overrides("EUR_USD", path=p)["atr_tp_mult"] == 4.0
    cl = state.changelog(path=p)
    assert cl[0]["type"] == "param" and cl[0]["after"] == 4.0 and cl[0]["before"] is None


def test_disable_enable_combo(tmp_path):
    p = str(tmp_path / "learned.json")
    state.disable_combo("tech:short", "perdant", 20, path=p)
    assert "tech:short" in state.get_disabled_combos(path=p)
    # idempotence
    assert state.disable_combo("tech:short", "perdant", 20, path=p) is None
    state.enable_combo("tech:short", "redevenu gagnant", 22, path=p)
    assert "tech:short" not in state.get_disabled_combos(path=p)


def test_rollback_restores(tmp_path):
    p = str(tmp_path / "learned.json")
    state.apply_param_change("EUR_USD", "atr_tp_mult", 4.0, "test", 5, path=p)
    state.disable_combo("tech:short", "test", 20, path=p)
    reverted = state.rollback(2, path=p)
    assert reverted == 2
    assert state.get_overrides("EUR_USD", path=p).get("atr_tp_mult") is None
    assert "tech:short" not in state.get_disabled_combos(path=p)
    # une entrée de rollback est tracée
    assert any(e["type"] == "rollback" for e in state.load(p)["changelog"])


def test_rollback_only_once_per_change(tmp_path):
    p = str(tmp_path / "learned.json")
    state.apply_param_change("EUR_USD", "atr_stop_mult", 2.5, "test", 5, path=p)
    assert state.rollback(5, path=p) == 1   # un seul changement réel à annuler
    assert state.rollback(5, path=p) == 0   # plus rien à annuler
