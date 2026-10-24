"""
forex/learning/state.py — Mémoire des réglages APPRIS (source de vérité).

Persiste dans `forex/_cache/learned_params.json` :
  - `params`          : overrides numériques par paire (multiples ATR, seuil surprise…) ;
  - `disabled_combos` : combinaisons de signaux temporairement désactivées ;
  - `changelog`       : historique horodaté de CHAQUE changement (avant/après,
                        raison, échantillon) — traçabilité + base du rollback.

Le runner lit `get_overrides(pair)` et `get_disabled_combos()` ; le module
d'apprentissage écrit via `apply_param_change` / `disable_combo` /
`enable_combo`. `rollback()` annule les derniers changements.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from forex import config

STATE_PATH = os.path.join(config.FOREX_DATA_DIR, "learned_params.json")

_DEFAULT = {"version": 0, "params": {}, "disabled_combos": [], "changelog": []}


def load(path: str = STATE_PATH) -> dict:
    if not os.path.exists(path):
        return json.loads(json.dumps(_DEFAULT))
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return json.loads(json.dumps(_DEFAULT))
    for k, v in _DEFAULT.items():
        data.setdefault(k, json.loads(json.dumps(v)))
    return data


def save(state: dict, path: str = STATE_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Lecture (utilisée par le runner / backtest) ──────────

def get_overrides(pair: str, path: str = STATE_PATH) -> dict:
    """Overrides numériques appris pour une paire ({} si aucun)."""
    return load(path).get("params", {}).get(pair.upper(), {})


def get_disabled_combos(path: str = STATE_PATH) -> set[str]:
    return set(load(path).get("disabled_combos", []))


def changelog(limit: int = 20, path: str = STATE_PATH) -> list[dict]:
    return load(path).get("changelog", [])[-limit:][::-1]


# ── Écriture (utilisée par le module d'apprentissage) ────

def apply_param_change(pair: str, field: str, after, reason: str,
                       sample: int, path: str = STATE_PATH) -> dict:
    """Change un paramètre appris pour une paire et journalise l'opération."""
    state = load(path)
    pair = pair.upper()
    before = state["params"].get(pair, {}).get(field)
    state["params"].setdefault(pair, {})[field] = after
    entry = {"ts": _now(), "type": "param", "pair": pair, "field": field,
             "before": before, "after": after, "reason": reason, "sample": sample,
             "rolled_back": False}
    state["changelog"].append(entry)
    state["version"] += 1
    save(state, path)
    return entry


def disable_combo(combo: str, reason: str, sample: int, path: str = STATE_PATH) -> dict | None:
    """Désactive une combinaison de signaux (no-op si déjà désactivée)."""
    state = load(path)
    if combo in state["disabled_combos"]:
        return None
    state["disabled_combos"].append(combo)
    entry = {"ts": _now(), "type": "combo_disable", "combo": combo,
             "reason": reason, "sample": sample, "rolled_back": False}
    state["changelog"].append(entry)
    state["version"] += 1
    save(state, path)
    return entry


def enable_combo(combo: str, reason: str, sample: int, path: str = STATE_PATH) -> dict | None:
    """Réactive une combinaison précédemment désactivée (no-op sinon)."""
    state = load(path)
    if combo not in state["disabled_combos"]:
        return None
    state["disabled_combos"].remove(combo)
    entry = {"ts": _now(), "type": "combo_enable", "combo": combo,
             "reason": reason, "sample": sample, "rolled_back": False}
    state["changelog"].append(entry)
    state["version"] += 1
    save(state, path)
    return entry


def _invert(state: dict, entry: dict) -> None:
    """Annule l'effet d'une entrée de changelog sur l'état."""
    t = entry["type"]
    if t == "param":
        pair, field, before = entry["pair"], entry["field"], entry["before"]
        if before is None:
            state["params"].get(pair, {}).pop(field, None)
        else:
            state["params"].setdefault(pair, {})[field] = before
    elif t == "combo_disable":
        if entry["combo"] in state["disabled_combos"]:
            state["disabled_combos"].remove(entry["combo"])
    elif t == "combo_enable":
        if entry["combo"] not in state["disabled_combos"]:
            state["disabled_combos"].append(entry["combo"])


def rollback(steps: int = 1, path: str = STATE_PATH) -> int:
    """
    Annule les `steps` derniers changements non déjà annulés (hors entrées de
    rollback). Retourne le nombre de changements effectivement annulés.
    """
    state = load(path)
    reverted = 0
    for entry in reversed(state["changelog"]):
        if reverted >= steps:
            break
        if entry.get("rolled_back") or entry.get("type") == "rollback":
            continue
        _invert(state, entry)
        entry["rolled_back"] = True
        reverted += 1
    if reverted:
        state["changelog"].append({"ts": _now(), "type": "rollback", "reverted": reverted})
        state["version"] += 1
        save(state, path)
    return reverted
