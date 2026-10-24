"""
forex/strategies/registry.py — Auto-découverte des bots de base.

Chaque fichier de forex/strategies/ (hors base.py, combo.py, registry.py et
remove.py) qui définit une sous-classe de Strategy avec `enabled = True` est
automatiquement enregistré. Ajouter un bot = ajouter un fichier ; le retirer =
repasser `enabled = False` (ou supprimer le fichier). Aucune autre édition
(ni __init__.py, ni .env) n'est nécessaire.
"""

from __future__ import annotations

import importlib
import inspect
import os
import pkgutil

from forex.strategies.base import Strategy

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_EXCLUDED_MODULES = {"base", "combo", "registry", "remove"}


def discover_base_strategies() -> dict[str, type[Strategy]]:
    """
    Scanne forex/strategies/ et retourne {id: classe} pour chaque sous-classe
    de Strategy (hors ComboStrategy, qui vit dans combo.py — exclu du scan)
    définie DANS ce module (pas un simple import réexporté) avec
    `enabled = True`. Triées par nom de fichier pour un ordre stable.
    """
    found: dict[str, type[Strategy]] = {}
    module_names = sorted(
        name for _, name, is_pkg in pkgutil.iter_modules([_PKG_DIR])
        if not is_pkg and name not in _EXCLUDED_MODULES
    )
    for name in module_names:
        module = importlib.import_module(f"forex.strategies.{name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, Strategy)
                and obj is not Strategy
                and obj.__module__ == module.__name__
                and getattr(obj, "enabled", True)
            ):
                found[obj.id] = obj
    return found
