"""Tests de l'auto-découverte des bots (forex/strategies/registry.py)."""

from forex.strategies import registry
from forex.strategies.base import Strategy


def test_discover_finds_the_four_known_bots():
    found = registry.discover_base_strategies()
    assert {"trend", "chartist", "smc", "macro"}.issubset(set(found))


def test_discover_returns_strategy_subclasses():
    found = registry.discover_base_strategies()
    for cls in found.values():
        assert issubclass(cls, Strategy) and cls is not Strategy


def test_discover_ignores_disabled_strategies(monkeypatch):
    from forex.strategies import trend

    monkeypatch.setattr(trend.TrendStrategy, "enabled", False)
    found = registry.discover_base_strategies()
    assert "trend" not in found


def test_discover_ignores_combo_and_base_modules():
    """combo.py/base.py/registry.py ne définissent pas de bot à découvrir."""
    found = registry.discover_base_strategies()
    assert "combo" not in found and "base" not in found and "registry" not in found


def test_no_exit_variants_by_default(monkeypatch):
    """Les variantes d'exit (expérience 2026-07) ne tournent plus par défaut."""
    import importlib
    from forex import config as fconfig
    import forex.strategies as strategies

    # Save original state to restore after test
    original_exit_variant_bots = fconfig.FOREX_EXIT_VARIANT_BOTS[:]

    try:
        monkeypatch.delenv("FOREX_EXIT_VARIANT_BOTS", raising=False)
        importlib.reload(fconfig)
        importlib.reload(strategies)
        ids = [b.id for b in strategies.active()]
        assert not [i for i in ids if "__" in i], f"variantes encore actives : {ids}"
    finally:
        # Restore original config and strategies modules to avoid pollution
        monkeypatch.setenv("FOREX_EXIT_VARIANT_BOTS",
                          ",".join(original_exit_variant_bots) if original_exit_variant_bots else "")
        importlib.reload(fconfig)
        importlib.reload(strategies)
