"""
copytrading/api.py — Client des API publiques Hyperliquid (sans clé).

Deux familles de fonctions :
  - les fetchers (réseau) : fetch_leaderboard, fetch_positions, fetch_mids ;
  - les parseurs (purs) : parse_leaderboard_row, parse_positions — c'est eux
    qui portent la logique et qui sont testés, sur des payloads enregistrés.
"""

from __future__ import annotations

import httpx

LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
INFO_URL = "https://api.hyperliquid.xyz/info"
_TIMEOUT = 20.0


def fetch_leaderboard() -> list[dict]:
    """Classement complet (payload volumineux : à ne rafraîchir qu'1×/jour)."""
    resp = httpx.get(LEADERBOARD_URL, timeout=60.0)
    resp.raise_for_status()
    return resp.json().get("leaderboardRows", [])


def _info(payload: dict):
    resp = httpx.post(INFO_URL, json=payload, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_positions(address: str) -> dict:
    """État de marge + positions ouvertes d'un trader (clearinghouseState)."""
    return _info({"type": "clearinghouseState", "user": address})


def fetch_mids() -> dict[str, float]:
    """Prix mid actuels par coin. Les clés '@N' (paires spot) sont ignorées."""
    out: dict[str, float] = {}
    for coin, px in _info({"type": "allMids"}).items():
        if coin.startswith("@"):
            continue
        try:
            out[coin] = float(px)
        except (TypeError, ValueError):
            continue
    return out


def parse_leaderboard_row(row: dict) -> dict | None:
    """Ligne du leaderboard → dict plat, ou None si malformée."""
    try:
        perf = {w: v for w, v in row.get("windowPerformances", [])}
        week = perf.get("week", {})
        month = perf.get("month", {})
        return {
            "address": row["ethAddress"].lower(),
            "display_name": row.get("displayName"),
            "account_value": float(row["accountValue"]),
            "roi_week": float(week.get("roi", 0)),
            "roi_month": float(month.get("roi", 0)),
            "pnl_week": float(week.get("pnl", 0)),
            "pnl_month": float(month.get("pnl", 0)),
            "volume_week": float(week.get("vlm", 0)),
        }
    except (KeyError, TypeError, ValueError):
        return None


def parse_positions(state: dict) -> tuple[float, dict[str, dict]]:
    """
    clearinghouseState → (account_value, {coin: {"direction", "frac"}}).

    `frac` = part du compte du trader engagée sur ce coin (positionValue /
    accountValue), PLAFONNÉE à 1.0 : on copie la fraction de compte, jamais
    l'exposition levier — le miroir ne peut pas perdre plus que sa poche.
    """
    try:
        account_value = float(state.get("marginSummary", {}).get("accountValue", 0) or 0)
    except (TypeError, ValueError):
        return 0.0, {}
    if account_value <= 0:
        return 0.0, {}
    target: dict[str, dict] = {}
    for ap in state.get("assetPositions", []):
        pos = ap.get("position", {})
        try:
            szi = float(pos["szi"])
            value = abs(float(pos["positionValue"]))
        except (KeyError, TypeError, ValueError):
            continue
        if szi == 0 or value <= 0:
            continue
        target[pos.get("coin", "?")] = {
            "direction": "long" if szi > 0 else "short",
            "frac": min(value / account_value, 1.0),
        }
    return account_value, target
