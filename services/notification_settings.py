"""
services/notification_settings.py — Réglages de notification partagés
(onglet Paramètres du dashboard).

Un seul fichier JSON (`forex/_cache/notification_settings.json`), écrit
uniquement par l'API du dashboard (`main.py`), relu à chaque cycle par le
runner forex et le runner copy trading — même principe que
`disabled_bots.json`/`follows.json`.
"""

from __future__ import annotations

import json
import os

SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "forex", "_cache", "notification_settings.json"
)

# Préserve exactement le comportement actuel tant que personne n'a touché à
# l'onglet Paramètres (fichier absent ou vide).
DEFAULTS: dict = {
    "forex_mode": "detailed",
    "forex_entries_enabled": True,
    "forex_exits_enabled": True,
    "forex_ranking_enabled": True,
    "copytrading_mode": "detailed",
}


def load_notification_settings() -> dict:
    """Réglages actuels, fusionnés sur les valeurs par défaut. Retourne les
    défauts (copie) si le fichier est absent, corrompu, ou ne contient pas un
    objet JSON (liste, chaîne, null...) — traité comme corrompu."""
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)
    if not isinstance(saved, dict):
        return dict(DEFAULTS)
    return {**DEFAULTS, **saved}
