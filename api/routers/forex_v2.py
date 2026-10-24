"""
api/routers/forex_v2.py — API v2 (spec 2026-07-27).

Contrat : le front ne calcule RIEN. /overview sert l'écran d'accueil complet
en une requête (pollée toutes les 30 s) ; le reste est à la demande.
"""

from __future__ import annotations

import json
import os
from typing import Literal
from fastapi import APIRouter, HTTPException, Query

from api import aggregator
from forex import config

router = APIRouter(prefix="/api/v2")

_CANDLES_PATH = os.path.join(config.FOREX_DATA_DIR, "forex_candles.json")


def _bot_or_404(bot_id: str):
    """Liste blanche des bots actifs — jamais d'id interpolé dans un chemin."""
    from forex import strategies
    wanted = bot_id.strip().lower()
    bot = next((b for b in strategies.active() if b.id == wanted), None)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot inconnu")
    return bot


@router.get("/overview")
async def overview():
    return aggregator.overview()


@router.get("/bots/{bot_id}")
async def bot_detail(bot_id: str):
    return aggregator.bot_stats(_bot_or_404(bot_id))


@router.get("/bots/{bot_id}/trades")
async def bot_trades(bot_id: str, page: int = Query(1, ge=1),
                     page_size: int = Query(50, ge=1, le=200),
                     source: Literal["live", "backtest"] = Query("live")):
    bot = _bot_or_404(bot_id)
    trades = aggregator.read_trades(bot, source=source)
    trades = sorted(trades, key=lambda t: t.get("exit_ts") or 0, reverse=True)
    start = (page - 1) * page_size
    return {"total": len(trades), "page": page, "page_size": page_size,
            "trades": trades[start:start + page_size]}


@router.get("/candles")
async def candles(pair: str | None = None, from_ts: int | None = None):
    try:
        with open(_CANDLES_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if pair:
        wanted = [p.strip().upper() for p in pair.split(",") if p.strip()]
        data = {p: data.get(p, []) for p in wanted}
    if from_ts:
        # Défense : ignore les bougies malformées (listes vides, pas d'index 0)
        filtered = {}
        for p, cs in data.items():
            try:
                filtered[p] = [c for c in cs if isinstance(c, (list, tuple)) and len(c) > 0 and c[0] >= from_ts]
            except (TypeError, IndexError):
                filtered[p] = []
        data = filtered
    return data


@router.get("/calendar")
async def calendar(limit: int = 15):
    from api.routers.forex_v1 import forex_calendar
    return await forex_calendar(limit=limit)


@router.get("/macro")
async def macro():
    from api.routers.forex_v1 import forex_macro
    return await forex_macro()
