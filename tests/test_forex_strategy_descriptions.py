"""
Tests des descriptions de stratégie (forex/strategies/*.py), affichées sur la
page dédiée d'un bot dans le dashboard. Une description vide passerait
inaperçue en code review mais se verrait immédiatement sur la page — ce test
la fige en même temps que la découverte des bots.
"""

from forex.strategies import BASE_REGISTRY, parse_combo
from forex.strategies.base import Strategy


def test_base_strategy_default_description_is_empty():
    assert Strategy.description == ""


def test_every_base_strategy_has_a_description():
    for bot_id, cls in BASE_REGISTRY.items():
        instance = cls()
        assert instance.description, f"{bot_id} n'a pas de description"
        assert len(instance.description) > 10, f"{bot_id} : description trop courte"


def test_combo_strategy_generates_a_description():
    combo = parse_combo("trend+macro")
    assert "trend" in combo.description
    assert "macro" in combo.description
    assert combo.description
