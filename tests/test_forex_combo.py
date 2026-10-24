"""Tests des bots de combinaison (forex/strategies/combo.py)."""

from datetime import datetime, timezone

import pytest

from forex import strategies
from forex.strategies.base import Strategy, StrategyDecision
from forex.strategies.combo import ComboStrategy

NOW = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)


def _flat(n=300, price=1.10):
    return [[i * 3600_000, price, price, price, price, 0.0] for i in range(n)]


class FakeBot(Strategy):
    """Bot factice à décision fixe, pour piloter les cas de combinaison."""

    min_candles = 1

    def __init__(self, bot_id, direction=None, strength=0.5):
        self.id = bot_id
        self.label = f"Faux bot {bot_id}"
        self.atr_stop_mult = 2.0
        self.atr_tp_mult = 3.0
        self._direction = direction
        self._strength = strength
        self.calls = 0

    def decide(self, pair, now, candles, events, context=None):
        self.calls += 1
        if self._direction is None:
            return StrategyDecision.no("neutre", {"setup": None})
        return StrategyDecision(True, self._direction, self._strength,
                                ["signal factice"], {"setup": self.id})


# ── Règles de vote ────────────────────────────────────────

def test_unanimity_enters_when_all_agree():
    combo = ComboStrategy([FakeBot("a", "long"), FakeBot("b", "long")], "all")
    d = combo.evaluate("EUR_USD", NOW, _flat(), [], use_time_filter=False)
    assert d.enter and d.direction == "long"


def test_unanimity_refuses_when_one_abstains():
    combo = ComboStrategy([FakeBot("a", "long"), FakeBot("b", None)], "all")
    d = combo.evaluate("EUR_USD", NOW, _flat(), [], use_time_filter=False)
    assert not d.enter


def test_opposite_directions_always_refused():
    """Deux bots qui se contredisent ne diversifient rien : on s'abstient."""
    for mode in ("all", "majority"):
        combo = ComboStrategy([FakeBot("a", "long"), FakeBot("b", "short")], mode)
        d = combo.evaluate("EUR_USD", NOW, _flat(), [], use_time_filter=False)
        assert not d.enter
        assert "désaccord" in d.summary()


def test_majority_enters_with_half_the_members():
    combo = ComboStrategy(
        [FakeBot("a", "long"), FakeBot("b", "long"), FakeBot("c", None), FakeBot("d", None)],
        "majority")
    d = combo.evaluate("EUR_USD", NOW, _flat(), [], use_time_filter=False)
    assert d.enter and d.direction == "long"


def test_majority_refuses_below_threshold():
    combo = ComboStrategy(
        [FakeBot("a", "long"), FakeBot("b", None), FakeBot("c", None), FakeBot("d", None)],
        "majority")
    d = combo.evaluate("EUR_USD", NOW, _flat(), [], use_time_filter=False)
    assert not d.enter


def test_combo_is_at_least_as_selective_as_its_members():
    """Un combo unanime ne peut jamais entrer si un membre s'abstient."""
    member_fires = FakeBot("a", "long")
    combo = ComboStrategy([member_fires, FakeBot("b", None)], "all")
    solo = member_fires.evaluate("EUR_USD", NOW, _flat(), [], use_time_filter=False)
    both = combo.evaluate("EUR_USD", NOW, _flat(), [], use_time_filter=False)
    assert solo.enter and not both.enter


# ── Traçabilité ───────────────────────────────────────────

def test_setup_names_the_agreeing_members():
    """L'apprentissage doit pouvoir distinguer QUELS membres ont déclenché."""
    combo = ComboStrategy(
        [FakeBot("a", "long"), FakeBot("b", "long"), FakeBot("c", None)], "majority")
    d = combo.evaluate("EUR_USD", NOW, _flat(), [], use_time_filter=False)
    assert d.components["setup"] == "a+b"
    assert combo.combo_key(d.components, d.direction) == "a+b:long"


def test_members_decisions_are_logged():
    combo = ComboStrategy([FakeBot("a", "long"), FakeBot("b", None)], "all")
    d = combo.evaluate("EUR_USD", NOW, _flat(), [], use_time_filter=False)
    assert set(d.components["members"]) == {"a", "b"}


# ── Mémoïsation (coût de calcul) ──────────────────────────

def test_member_decisions_are_memoized_across_combos():
    """
    Un membre partagé par plusieurs combos ne doit être évalué QU'UNE FOIS par
    bougie : sans ça, chaque combo relancerait la détection de figures et de
    swing points, et le cycle exploserait avec le nombre de combinaisons.
    """
    shared = FakeBot("shared", "long")
    combo1 = ComboStrategy([shared, FakeBot("x", "long")], "all")
    combo2 = ComboStrategy([shared, FakeBot("y", "long")], "all")
    context = {}
    candles = _flat()

    combo1.evaluate("EUR_USD", NOW, candles, [], use_time_filter=False, context=context)
    combo2.evaluate("EUR_USD", NOW, candles, [], use_time_filter=False, context=context)

    assert shared.calls == 1


def test_memoization_does_not_leak_across_pairs():
    shared = FakeBot("shared", "long")
    combo = ComboStrategy([shared, FakeBot("x", "long")], "all")
    context = {}
    combo.evaluate("EUR_USD", NOW, _flat(), [], use_time_filter=False, context=context)
    combo.evaluate("GBP_USD", NOW, _flat(), [], use_time_filter=False, context=context)
    assert shared.calls == 2


# ── Construction & registre ───────────────────────────────

def test_parse_combo_unanimous():
    combo = strategies.parse_combo("smc+macro")
    assert combo.id == "smc+macro" and combo.mode == "all"
    assert [m.id for m in combo.members] == ["smc", "macro"]


def test_parse_combo_majority_uses_filesystem_safe_id():
    """':' est illégal dans un chemin Windows, et l'id est un nom de dossier."""
    combo = strategies.parse_combo("maj:trend+smc")
    assert combo.mode == "majority"
    import os

    assert ":" not in combo.id
    assert ":" not in os.path.basename(combo.dir)


def test_combo_needs_at_least_two_members():
    with pytest.raises(ValueError):
        ComboStrategy([FakeBot("a")], "all")


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        ComboStrategy([FakeBot("a"), FakeBot("b")], "consensus-mou")


def test_combo_inherits_strictest_warmup_and_mean_multipliers():
    a, b = FakeBot("a"), FakeBot("b")
    a.min_candles, b.min_candles = 50, 200
    a.atr_stop_mult, b.atr_stop_mult = 1.0, 3.0
    combo = ComboStrategy([a, b], "all")
    assert combo.min_candles == 200      # le plus exigeant, sinon membre muet
    assert combo.atr_stop_mult == 2.0    # moyenne


def test_combos_have_isolated_paths_from_their_members():
    """Un combo est un bot à part entière : portefeuille et journal séparés."""
    combo = strategies.get("smc+macro")
    smc = strategies.get("smc")
    assert combo.portfolio_path != smc.portfolio_path
    assert combo.journal_path != smc.journal_path


def test_active_includes_bases_then_combos():
    """
    Ordre parmi les bots "originaux" (hors variantes SL/TP dynamique
    `<bot>__<mode>`, ajoutées après coup et donc hors de cette invariante
    d'ordre — cf. forex/strategies/__init__.py::active()).
    """
    ids = [s.id for s in strategies.active()]
    original_ids = [i for i in ids if "__" not in i]
    base_ids = [i for i in original_ids if "+" not in i]
    combo_ids = [i for i in original_ids if "+" in i]
    assert {"trend", "chartist", "smc", "macro"}.issubset(set(base_ids))
    assert "smc+macro" in combo_ids
    # tous les bots de base précèdent tous les combos
    if combo_ids:
        assert ids.index(base_ids[-1]) < ids.index(combo_ids[0])
    assert len(set(ids)) == len(ids)      # aucun doublon d'identifiant
