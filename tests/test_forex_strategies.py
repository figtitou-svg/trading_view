"""
Tests du framework de bots indépendants (forex/strategies/).

L'enjeu central testé ici : l'ÉTANCHÉITÉ. Chaque bot doit avoir ses propres
fichiers (portefeuille, journal, paramètres appris) pour qu'un bot désactivé ou
coupé par l'apprentissage n'ait aucun effet sur les autres.
"""

from datetime import datetime, timezone

import pytest

from forex import config, strategies
from forex.strategies.base import Strategy, StrategyDecision

NOW = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)


def _flat(n, price=1.10):
    return [[i * 3600_000, price, price, price, price, 0.0] for i in range(n)]


# ── Registre ──────────────────────────────────────────────

def test_registry_exposes_the_four_bots():
    assert {"trend", "chartist", "smc", "macro"}.issubset(set(strategies.REGISTRY))


def test_get_unknown_bot_raises():
    with pytest.raises(KeyError):
        strategies.get("inexistant")


def test_each_bot_has_isolated_paths():
    """Aucun chemin de cache ne doit être partagé entre deux bots."""
    bots = [strategies.get(b) for b in strategies.REGISTRY]
    for attr in ("dir", "portfolio_path", "journal_path", "state_path", "status_path"):
        paths = [getattr(b, attr) for b in bots]
        assert len(set(paths)) == len(paths), f"{attr} partagé entre bots"


def test_bot_ids_are_stable_and_lowercase():
    """L'id sert de nom de dossier et de clé d'API : il ne doit pas surprendre."""
    for bot_id, cls in strategies.REGISTRY.items():
        assert bot_id == bot_id.lower() and " " not in bot_id
        assert cls.id == bot_id


# ── Garde-fous communs ────────────────────────────────────

def test_evaluate_refuses_when_not_enough_candles():
    bot = strategies.get("trend")
    d = bot.evaluate("EUR_USD", NOW, _flat(5), [], use_time_filter=False)
    assert not d.enter
    assert "bougies" in d.summary()


def test_evaluate_blocked_when_market_closed():
    """Le filtre temporel est appliqué en amont, identiquement pour tous les bots."""
    saturday = datetime(2026, 7, 18, 12, tzinfo=timezone.utc)
    for bot_id in strategies.REGISTRY:
        bot = strategies.get(bot_id)
        d = bot.evaluate("EUR_USD", saturday, _flat(400), [], use_time_filter=True)
        assert not d.enter, f"{bot_id} a tenté d'entrer marché fermé"


def test_evaluate_tags_the_deciding_strategy():
    bot = strategies.get("trend")
    d = bot.evaluate("EUR_USD", NOW, _flat(400), [], use_time_filter=False)
    assert d.components.get("strategy") == "trend"


def test_no_bot_enters_on_a_perfectly_flat_market():
    """Aucun signal ne doit être inventé sur un marché sans information."""
    for bot_id in strategies.REGISTRY:
        bot = strategies.get(bot_id)
        d = bot.evaluate("EUR_USD", NOW, _flat(400), [], use_time_filter=False,
                         context={"candles_by_pair": {}, "crossasset": {}})
        assert not d.enter, f"{bot_id} est entré sur un marché plat"


# ── Clé de setup (apprentissage) ──────────────────────────

def test_combo_key_uses_setup_when_present():
    """
    La clé qualifie le setup interne au bot : l'apprentissage peut ainsi couper
    une figure précise (les drapeaux) sans condamner tout le bot chartiste.
    """
    bot = strategies.get("chartist")
    assert bot.combo_key({"setup": "Double Top"}, "short") == "Double Top:short"


def test_combo_key_falls_back_to_direction():
    bot = strategies.get("trend")
    assert bot.combo_key({}, "long") == "long"


# ── Décision ──────────────────────────────────────────────

def test_decision_no_helper_always_carries_a_reason():
    d = StrategyDecision.no("marché plat")
    assert not d.enter and d.direction is None and "marché plat" in d.summary()


def test_base_strategy_requires_decide_implementation():
    with pytest.raises(NotImplementedError):
        Strategy().decide("EUR_USD", NOW, _flat(400), [])


def test_strategy_default_enabled_and_unrestricted_pairs():
    assert Strategy.enabled is True
    assert Strategy.pairs is None


def test_active_runs_all_discovered_bots_when_foreign_bots_empty(monkeypatch):
    monkeypatch.setattr(config, "FOREX_BOTS", [])
    monkeypatch.setattr(config, "FOREX_COMBOS", [])
    monkeypatch.setattr(config, "FOREX_EXIT_VARIANT_BOTS", [])
    ids = [s.id for s in strategies.active()]
    assert set(ids) == set(strategies.BASE_REGISTRY)


def test_active_respects_explicit_foreign_bots_restriction(monkeypatch):
    monkeypatch.setattr(config, "FOREX_BOTS", ["smc", "macro"])
    monkeypatch.setattr(config, "FOREX_COMBOS", [])
    monkeypatch.setattr(config, "FOREX_EXIT_VARIANT_BOTS", [])
    ids = [s.id for s in strategies.active()]
    assert set(ids) == {"smc", "macro"}


def test_active_excludes_the_5_archived_bots():
    """
    channel_breakout, ma_crossover, london_breakout (0% win ou pire retour du
    classement) et les combos trend+chartist / maj-trend+chartist+smc+macro
    ont été archivés (2026-07-23) : ils ne doivent plus tourner par défaut.
    """
    ids = {s.id for s in strategies.active()}
    archived = {"channel_breakout", "ma_crossover", "london_breakout",
                "trend+chartist", "maj-trend+chartist+smc+macro"}
    assert ids.isdisjoint(archived)


def test_strategy_default_exit_mode_is_static():
    assert Strategy.exit_mode == "static"


def test_active_includes_exit_variants_when_enabled(monkeypatch):
    """Vérifie que les variantes d'exit sont générées quand elles sont explicitement listées."""
    # Test 1: défaut vide → aucune variante
    monkeypatch.setattr(config, "FOREX_EXIT_VARIANT_BOTS", [])
    ids_empty = {s.id for s in strategies.active()}
    assert not any("__" in s_id for s_id in ids_empty), "Aucune variante ne doit exister par défaut"

    # Test 2: quand on active quelques bots → variantes générées correctement
    test_bots = ["macro", "smc"]
    test_modes = ["trailing", "trailing_breakeven"]
    monkeypatch.setattr(config, "FOREX_EXIT_VARIANT_BOTS", test_bots)
    monkeypatch.setattr(config, "FOREX_EXIT_VARIANT_MODES", test_modes)
    ids_with_variants = {s.id for s in strategies.active()}

    for bot_id in test_bots:
        for mode in test_modes:
            variant_id = f"{bot_id}__{mode}"
            assert variant_id in ids_with_variants, f"Variante {variant_id} manquante"


def test_exit_variants_carry_the_right_exit_mode_and_preserve_entry_logic(monkeypatch):
    """Variantes d'exit conservent leur mode et la logique d'entrée du bot de base."""
    monkeypatch.setattr(config, "FOREX_EXIT_VARIANT_BOTS", ["macro"])
    monkeypatch.setattr(config, "FOREX_EXIT_VARIANT_MODES", ["trailing", "trailing_breakeven", "chandelier"])

    variants = {s.id: s for s in strategies.active()
                if s.id.startswith("macro__") or s.id == "macro"}
    base = variants["macro"]
    assert any(k.startswith("macro__") for k in variants), "Aucune variante macro__* trouvée"

    for mode in config.FOREX_EXIT_VARIANT_MODES:
        variant = variants[f"macro__{mode}"]
        assert variant.exit_mode == mode
        assert variant.atr_stop_mult == base.atr_stop_mult
        assert variant.atr_tp_mult == base.atr_tp_mult
        assert type(variant) is type(base)


def test_exit_variants_have_fully_isolated_cache_paths(monkeypatch):
    """Variantes d'exit doivent avoir des chemins de cache isolés."""
    monkeypatch.setattr(config, "FOREX_EXIT_VARIANT_BOTS", ["macro"])
    monkeypatch.setattr(config, "FOREX_EXIT_VARIANT_MODES", ["trailing", "trailing_breakeven"])
    bots = strategies.active()
    # Vérifie qu'il y a au moins des variantes pour tester l'isolation
    variant_ids = {b.id for b in bots if "__" in b.id}
    assert len(variant_ids) >= 2, f"Attendait des variantes, trouvé : {variant_ids}"

    for attr in ("dir", "portfolio_path", "journal_path", "state_path", "status_path"):
        paths = [getattr(b, attr) for b in bots]
        assert len(set(paths)) == len(paths), f"{attr} partagé entre bots/variantes"


def test_originals_of_variant_bots_still_run_unmodified(monkeypatch):
    """Quand des variantes sont actives, leurs bots de base tournent aussi inchangés."""
    monkeypatch.setattr(config, "FOREX_EXIT_VARIANT_BOTS", ["macro", "smc"])

    ids = {s.id for s in strategies.active()}
    for bot_id in config.FOREX_EXIT_VARIANT_BOTS:
        assert bot_id in ids


def test_exit_variant_of_a_majority_combo_uses_the_normalized_id(monkeypatch):
    """
    ComboStrategy normalise 'maj:' en 'maj-' (':' est illégal dans un chemin
    Windows) — la variante doit hériter de cet id NORMALISÉ (post-get()), pas
    du texte brut de config, sous peine de chemin de cache invalide.
    """
    monkeypatch.setattr(config, "FOREX_EXIT_VARIANT_BOTS", ["maj:trend+chartist"])
    monkeypatch.setattr(config, "FOREX_EXIT_VARIANT_MODES", ["trailing"])
    variants = [s for s in strategies.active() if s.id.startswith("maj-trend+chartist__")]
    assert len(variants) == 1
    assert variants[0].id == "maj-trend+chartist__trailing"
    assert ":" not in variants[0].id
