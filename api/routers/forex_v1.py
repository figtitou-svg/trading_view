"""Endpoints forex v1 — déplacés de main.py à l'identique (spec 2026-07-27)."""
import json as _json
import os as _os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from utils.logger import logger

router = APIRouter()

_FOREX_CACHE = _os.path.join(_os.path.dirname(_os.path.dirname(
    _os.path.dirname(_os.path.abspath(__file__)))), "forex", "_cache")
_FOREX_CANDLES = _os.path.join(_FOREX_CACHE, "forex_candles.json")
_FOREX_INDEX = _os.path.join(_FOREX_CACHE, "forex_bots.json")


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return _json.load(f)
    except (OSError, ValueError):
        return None


def _forex_bot(bot_id: str | None):
    """
    Résout un bot depuis un paramètre de requête, ou le premier bot actif.

    ⚠️ `bot_id` vient d'une requête HTTP et sert à construire des chemins de
    fichiers : on le valide contre la LISTE BLANCHE des bots connus au lieu de
    l'interpoler dans un chemin (sinon `?bot=../../etc` lirait n'importe quoi).
    Retourne None si l'identifiant est inconnu.
    """
    try:
        from forex import strategies as _strat
        active = _strat.active()
        if not active:
            return None
        if not bot_id:
            return active[0]
        wanted = bot_id.strip().lower()
        return next((b for b in active if b.id == wanted), None)
    except Exception as e:
        logger.warning(f"Bots forex indisponibles: {e}")
        return None


@router.get("/api/forex/bots")
async def forex_bots():
    """
    Tableau comparatif des bots : equity, trades, win rate. C'est la vue qui
    permet de dire lequel a un edge — l'intérêt même du découpage en bots
    indépendants.
    """
    index = _read_json(_FOREX_INDEX)
    if index is None:
        return {"available": False, "bots": []}
    active = False
    try:
        updated = datetime.fromisoformat(index["updated_at"])
        active = datetime.now(timezone.utc) - updated < timedelta(minutes=5)
    except (KeyError, ValueError):
        pass
    index["available"] = True
    index["runner_active"] = active
    return index


@router.get("/api/forex/status")
async def forex_status(bot: str | None = None):
    """Instantané des signaux par paire pour un bot (écrit par forex.paper.runner)."""
    b = _forex_bot(bot)
    if b is None:
        return {"available": False}
    data = _read_json(b.status_path)
    if data is None:
        return {"available": False, "bot": b.id}

    # Runner considéré actif si le statut a moins de 5 minutes.
    active = False
    try:
        updated = datetime.fromisoformat(data["updated_at"])
        active = datetime.now(timezone.utc) - updated < timedelta(minutes=5)
    except (KeyError, ValueError):
        pass
    data["available"] = True
    data["runner_active"] = active
    return data


@router.get("/api/forex/portfolio")
async def forex_portfolio(bot: str | None = None):
    """Portefeuille virtuel d'un bot : equity, positions ouvertes, derniers trades."""
    b = _forex_bot(bot)
    if b is None:
        return {"available": False, "equity": None, "trades": []}
    data = _read_json(b.portfolio_path)
    if data is None:
        # Portefeuille pas encore écrit : le bot n'a simplement jamais tradé.
        return {"available": True, "bot": b.id, "equity": None, "trades": [],
                "open_positions": {}, "n_trades": 0, "win_rate": 0.0}
    start = data.get("start_equity", 0) or 0
    equity = data.get("equity", start)
    trades = data.get("trades", [])
    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    return {
        "available": True,
        "bot": b.id,
        "equity": round(equity, 2),
        "start_equity": start,
        "return_pct": round((equity / start - 1) * 100, 2) if start else 0.0,
        "peak_equity": data.get("peak_equity", equity),
        "open_positions": data.get("positions", {}),
        "trades": list(reversed(trades))[:50],   # plus récents d'abord
        "n_trades": len(trades),
        "win_rate": round(wins / len(trades) * 100, 1) if trades else 0.0,
    }


@router.get("/api/forex/candles")
async def forex_candles(pair: str | None = None):
    """
    Bougies récentes par paire (cache écrit par le runner), pour les graphiques
    du dashboard. Format par bougie : [ts_ms, o, h, l, c]. Filtrable par `pair`
    (une paire, ou plusieurs séparées par des virgules) pour éviter de
    transférer tout le cache quand seules quelques paires sont affichées.
    """
    data = _read_json(_FOREX_CANDLES) or {}
    if pair:
        wanted = [p.strip().upper() for p in pair.split(",") if p.strip()]
        return {p: data.get(p, []) for p in wanted}
    return data


@router.get("/api/forex/calendar")
async def forex_calendar(limit: int = 15):
    """
    Prochaines annonces macro high/medium impact (depuis le cache calendrier),
    enrichies d'un score d'importance 0→5, d'une explication en langage simple
    et des paires suivies concernées par la devise de l'annonce.
    """
    try:
        from forex import config as forex_config
        from forex.data import calendar as _cal
        now = datetime.now(timezone.utc)
        upcoming = [
            e for e in _cal.load_events()
            if e.dt >= now and e.impact.lower() in {"high", "medium"}
        ]
        upcoming.sort(key=lambda e: e.dt)
        return [
            {"dt": e.dt.isoformat(), "currency": e.currency, "title": e.title,
             "impact": e.impact, "forecast": e.forecast, "previous": e.previous,
             "importance": _cal.importance_score(e.impact),
             "explanation": _cal.explain_event(e.title),
             "pairs": [p for p in forex_config.FOREX_PAIRS
                       if e.currency.upper() in p.upper().split("_")]}
            for e in upcoming[:limit]
        ]
    except Exception as e:
        logger.warning(f"Calendrier forex indisponible: {e}")
        return []


@router.get("/api/forex/macro")
async def forex_macro():
    """Biais macro (différentiel de taux directeurs) par paire suivie."""
    try:
        from forex import config as forex_config
        from forex.data import macro as _macro
        details = [_macro.get_pair_macro_detail(p) for p in forex_config.FOREX_PAIRS]
        return {
            "available": True,
            "biases": {d["pair"]: d["bias"] for d in details},
            "details": details,
        }
    except Exception as e:
        logger.warning(f"Biais macro indisponible: {e}")
        return {"available": False, "biases": {}, "details": []}


@router.get("/api/forex/learning")
async def forex_learning(bot: str | None = None):
    """Apprentissage d'un bot : réglages appris, setups désactivés, perf, changelog."""
    b = _forex_bot(bot)
    if b is None:
        return {"available": False}
    try:
        from forex.learning import state as _state, journal as _journal, analysis as _analysis
        trades = _journal.read_journal(path=b.journal_path)
        stats = _analysis.analyze(trades)
        st = _state.load(b.state_path)
        return {
            "available": True,
            "bot": b.id,
            "label": b.label,
            "n_trades": len(trades),
            "params": st.get("params", {}),
            "disabled_combos": st.get("disabled_combos", []),
            "combos": [s.to_dict() for s in
                       sorted(stats.values(), key=lambda x: x.expectancy)],
            "changelog": _state.changelog(15, path=b.state_path),
        }
    except Exception as e:
        logger.warning(f"Apprentissage forex indisponible: {e}")
        return {"available": False}


def _forex_set_disabled(bot_id: str) -> dict:
    """Supprime un bot depuis le dashboard : le runner clôturera sa position
    ouverte (silencieusement) et archivera son cache au prochain poll."""
    bot = _forex_bot(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot inconnu")
    _os.makedirs(_FOREX_CACHE, exist_ok=True)
    path = _os.path.join(_FOREX_CACHE, "disabled_bots.json")
    disabled = _read_json(path) or []
    if bot.id not in disabled:
        disabled.append(bot.id)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(disabled, f, ensure_ascii=False, indent=2)
    _os.replace(tmp, path)
    logger.info(f"🗑️ Bot forex supprimé depuis le dashboard : {bot.id}")
    return {"disabled": disabled}


@router.post("/api/forex/bots/{bot_id}/disable")
async def forex_disable_bot(bot_id: str):
    """Supprime un bot depuis le dashboard (pris en compte au prochain poll du runner)."""
    return _forex_set_disabled(bot_id)
