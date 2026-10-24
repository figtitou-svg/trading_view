"""
forex/strategies/ — Registre des BOTS forex indépendants.

Deux familles :
  - **bots de base** (auto-découverts, cf. `registry.py`) : chacun une logique
    d'entrée propre ;
  - **bots de combinaison** (`smc+macro`, `maj:trend+chartist+smc+macro`…) :
    plusieurs bots de base doivent s'accorder pour entrer (cf. `combo.py`).

Tous vivent leur vie : portefeuille, journal, paramètres appris et statistiques
séparés (cf. `base.py`). Le runner les fait tourner côte à côte sur les mêmes
bougies, et l'apprentissage les juge un par un.

Ajouter/retirer un bot de base : cf. `registry.py` (un fichier + `enabled`,
rien d'autre à éditer). Combinaisons par `.env` :
    FOREX_COMBOS=trend+macro,chartist+macro,smc+macro,trend+smc,maj:trend+chartist+smc+macro
"""

from __future__ import annotations

from forex import config
from forex.strategies.base import Strategy, StrategyDecision, BOTS_DIR
from forex.strategies.combo import ComboStrategy
from forex.strategies import registry

# Bots de base, auto-découverts. Ajouter un bot = déposer un fichier avec une
# classe Strategy dans ce dossier ; le retirer = repasser `enabled = False`
# dans sa classe. Aucune autre édition n'est nécessaire.
BASE_REGISTRY: dict[str, type[Strategy]] = registry.discover_base_strategies()

# Rétro-compatibilité : `REGISTRY` désigne les bots de base.
REGISTRY = BASE_REGISTRY


def parse_combo(spec: str) -> ComboStrategy:
    """
    Construit un combo depuis sa spécification textuelle.

        "smc+macro"                       → unanimité des deux
        "maj-trend+chartist+smc+macro"    → majorité des quatre

    (`maj:` est accepté en entrée par commodité, mais l'id retenu utilise
    `maj-` : il sert de nom de dossier et ':' est illégal sous Windows.)
    """
    spec = spec.strip().lower()
    mode = "all"
    for prefix in ("maj-", "maj:"):
        if spec.startswith(prefix):
            mode, spec = "majority", spec[len(prefix):]
            break
    members = [get(part) for part in spec.split("+") if part.strip()]
    return ComboStrategy(members, mode)


def get(bot_id: str) -> Strategy:
    """Instancie un bot (de base ou de combinaison) par son identifiant."""
    key = bot_id.strip().lower()
    if key in BASE_REGISTRY:
        return BASE_REGISTRY[key]()
    if "+" in key:
        return parse_combo(key)
    raise KeyError(f"bot inconnu : {bot_id!r} "
                   f"(bases connues : {', '.join(sorted(BASE_REGISTRY))})")


def _exit_mode_label(mode: str) -> str:
    return {"trailing": "trailing", "trailing_breakeven": "breakeven+trailing",
            "chandelier": "chandelier"}.get(mode, mode)


def _build_exit_variants() -> list[Strategy]:
    """
    Décline chaque bot de FOREX_EXIT_VARIANT_BOTS en une variante par mode de
    FOREX_EXIT_VARIANT_MODES : même logique d'entrée (ré-instanciée via get(),
    marche pour un bot de base comme pour un combo), seul exit_mode change.
    L'id devient `<bot>__<mode>`, ce qui isole automatiquement son cache
    (dir/portfolio_path/... dérivent tous de self.id, cf. base.py).
    """
    variants: list[Strategy] = []
    for bot_id in config.FOREX_EXIT_VARIANT_BOTS:
        for mode in config.FOREX_EXIT_VARIANT_MODES:
            try:
                variant = get(bot_id)
            except (KeyError, ValueError) as e:
                print(f"[forex] variante ignorée — {e}")
                continue
            variant.id = f"{variant.id}__{mode}"
            variant.label = f"{variant.label} [{_exit_mode_label(mode)}]"
            variant.exit_mode = mode
            variants.append(variant)
    return variants


def active() -> list[Strategy]:
    """
    Bots actifs : tous les bots de base découverts (enabled=True) sauf
    restriction explicite via FOREX_BOTS, puis les combinaisons de FOREX_COMBOS,
    puis les variantes SL/TP dynamique de FOREX_EXIT_VARIANT_BOTS.

    FOREX_BOTS vide (défaut) = tous les bots découverts tournent : c'est ce qui
    permet d'ajouter un bot sans toucher à .env. Le lister explicitement
    restreint aux seuls ids donnés.
    """
    base_ids = ([b for b in config.FOREX_BOTS if b in BASE_REGISTRY]
                if config.FOREX_BOTS else list(BASE_REGISTRY))
    out: list[Strategy] = [BASE_REGISTRY[b]() for b in base_ids]
    for combo_id in config.FOREX_COMBOS:
        try:
            out.append(get(combo_id))
        except (KeyError, ValueError) as e:
            print(f"[forex] bot ignoré — {e}")
    out.extend(_build_exit_variants())
    return out


__all__ = ["Strategy", "StrategyDecision", "ComboStrategy", "REGISTRY",
           "BASE_REGISTRY", "BOTS_DIR", "get", "active", "parse_combo"]
