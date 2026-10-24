"""Endpoints copy trading (miroir Hyperliquid) — déplacés de main.py à l'identique (spec 2026-07-27)."""
import json as _json
import os as _os
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from utils.logger import logger

router = APIRouter()

_COPY_CACHE = _os.path.join(_os.path.dirname(_os.path.dirname(
    _os.path.dirname(_os.path.abspath(__file__)))), "copytrading", "_cache")
# ⚠️ Adresse fournie par requête HTTP : validée par regex stricte, jamais
# interpolée dans un chemin de fichier (même précaution que _forex_bot).
_COPY_ADDR_RE = re.compile(r"^0x[a-f0-9]{40}$")


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return _json.load(f)
    except (OSError, ValueError):
        return None


def _copy_read(name: str):
    return _read_json(_os.path.join(_COPY_CACHE, name))


@router.get("/api/copytrading/status")
async def copytrading_status():
    """Statut du runner, candidats présélectionnés et traders suivis."""
    cand = _copy_read("candidates.json") or {}
    follows = (_copy_read("follows.json") or {}).get("follows", [])
    pf = _copy_read("portfolio.json")

    # Runner actif si le portefeuille a été réécrit il y a moins de 10 min
    # (poll 180 s + timeouts éventuels : 5 min donnerait des faux négatifs).
    active = False
    if pf:
        try:
            updated = datetime.fromisoformat(pf["updated_at"])
            active = datetime.now(timezone.utc) - updated < timedelta(minutes=10)
        except (KeyError, ValueError):
            pass

    candidates = cand.get("candidates", [])
    for c in candidates:
        c["followed"] = c.get("address") in follows
    return {
        "available": pf is not None or bool(candidates),
        "runner_active": active,
        "follows": follows,
        "candidates": candidates,
        "candidates_updated_at": cand.get("updated_at"),
    }


@router.get("/api/copytrading/portfolio")
async def copytrading_portfolio():
    """Portefeuille miroir : equity, positions ouvertes, historique."""
    pf = _copy_read("portfolio.json")
    if pf is None:
        return {"available": False, "equity": None, "positions": [],
                "trades": [], "equity_history": []}
    start = pf.get("start_equity", 0) or 0
    eq = pf.get("equity", start)
    return {
        "available": True,
        "equity": eq,
        "start_equity": start,
        "return_pct": round((eq / start - 1) * 100, 2) if start else 0.0,
        "positions": pf.get("positions", []),
        "trades": list(reversed(pf.get("trades", [])))[:50],
        "equity_history": pf.get("equity_history", []),
        "updated_at": pf.get("updated_at"),
    }


def _copy_set_follow(address: str, add: bool) -> dict:
    addr = address.strip().lower()
    if not _COPY_ADDR_RE.fullmatch(addr):
        raise HTTPException(status_code=400, detail="Adresse invalide")
    _os.makedirs(_COPY_CACHE, exist_ok=True)
    path = _os.path.join(_COPY_CACHE, "follows.json")
    data = _read_json(path) or {"follows": []}
    follows = [f for f in data.get("follows", []) if f != addr]
    if add:
        follows.append(addr)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump({"follows": follows}, f, ensure_ascii=False, indent=2)
    _os.replace(tmp, path)
    logger.info(f"📋 Copy trading : {'suivi' if add else 'désuivi'} de {addr}")
    return {"follows": follows}


@router.post("/api/copytrading/follow/{address}")
async def copytrading_follow(address: str):
    """Active la copie d'un trader (pris en compte au prochain poll du runner)."""
    return _copy_set_follow(address, add=True)


@router.post("/api/copytrading/unfollow/{address}")
async def copytrading_unfollow(address: str):
    """Désactive la copie ; le runner clôture ses positions miroir au prochain poll."""
    return _copy_set_follow(address, add=False)
