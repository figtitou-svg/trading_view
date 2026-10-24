"""
api/aggregator.py — Couche d'agrégation lue par /api/v2 (spec 2026-07-27).

Tout calcul de statistique vit ICI, jamais dans le navigateur : c'est ce qui
rend l'API exposable telle quelle plus tard (signaux payants, vitrine).

Cache : les journaux JSONL de prod font plusieurs Mo et la VM a 1 Go de RAM —
chaque fichier n'est relu que si son mtime a changé (clé de cache (path, mtime),
LRU borné). Les fichiers corrompus/absents dégradent en `available: False`
sans jamais lever.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from forex import config
from forex.learning import verdict as verdict_mod
from forex.paper import reconcile

_INDEX_PATH = os.path.join(config.FOREX_DATA_DIR, "forex_bots.json")


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


@lru_cache(maxsize=64)
def _read_journal_cached(path: str, mtime: float) -> tuple:
    """Le mtime fait partie de la clé : fichier modifié → nouvelle entrée."""
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return tuple(out)


@lru_cache(maxsize=64)
def _read_json_cached(path: str, mtime: float):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def clear_cache() -> None:
    _read_journal_cached.cache_clear()
    _read_json_cached.cache_clear()


def _journal_cache_info():
    return _read_journal_cached.cache_info()._asdict()


def read_trades(bot, source: str | None = None) -> list[dict]:
    """Lit les trades d'un bot depuis le cache, optionnellement filtrés par source.

    Args:
        bot: Objet stratégie avec journal_path
        source: None (tous), "live", ou "backtest"

    Returns:
        Liste de dicts trade, filtrée
    """
    trades = list(_read_journal_cached(bot.journal_path, _mtime(bot.journal_path)))
    if source is None:
        return trades
    return [t for t in trades if t.get("source", "live") == source]


def _basic_stats(trades: list[dict]) -> dict:
    pnls = [t.get("pnl_pct") or 0.0 for t in trades]
    gains = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    pf = (gains / losses) if losses else (float("inf") if gains else 0.0)
    return {
        "n": len(trades),
        "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls) * 100, 1) if pnls else 0.0,
        "expectancy": round(sum(pnls) / len(pnls), 4) if pnls else 0.0,
        "profit_factor": round(pf, 2) if pf != float("inf") else None,
        "total_pnl_pct": round(sum(pnls), 2),
    }


def _daily_curve_live(trades: list[dict], start_equity: float) -> list[list]:
    """Courbe d'equity quotidienne : start + cumul des pnl (€) par jour de clôture."""
    closed = sorted((t for t in trades if t.get("exit_ts")), key=lambda t: t["exit_ts"])
    curve, equity, current_day = [], start_equity, None
    for t in closed:
        day = datetime.fromtimestamp(t["exit_ts"] / 1000, tz=timezone.utc).date().isoformat()
        equity += t.get("pnl") or 0.0
        if day == current_day:
            curve[-1][1] = round(equity, 2)
        else:
            curve.append([day, round(equity, 2)])
            current_day = day
    return curve


def _daily_curve_backtest(trades: list[dict]) -> list[list]:
    """Indice base 100, pnl_pct additif — l'overlay du détail bot (pointillé)."""
    closed = sorted((t for t in trades if t.get("exit_ts")), key=lambda t: t["exit_ts"])
    curve, idx, current_day = [], 100.0, None
    for t in closed:
        day = datetime.fromtimestamp(t["exit_ts"] / 1000, tz=timezone.utc).date().isoformat()
        idx += t.get("pnl_pct") or 0.0
        if day == current_day:
            curve[-1][1] = round(idx, 2)
        else:
            curve.append([day, round(idx, 2)])
            current_day = day
    return curve


def _max_drawdown_pct(curve: list[list]) -> float:
    peak, max_dd = float("-inf"), 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak * 100)
    return round(max_dd, 2)


def _sharpe(curve: list[list]) -> float | None:
    """Sharpe simplifié annualisé (252 j) sur les rendements quotidiens."""
    if len(curve) < 3:
        return None
    rets = [(b[1] / a[1] - 1) for a, b in zip(curve, curve[1:]) if a[1]]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = var ** 0.5
    return round(mean / std * (252 ** 0.5), 2) if std else None


def bot_stats(bot, verdicts: dict | None = None) -> dict:
    """Le bloc complet d'un bot pour l'overview et la page détail."""
    pf_data = _read_json_cached(bot.portfolio_path, _mtime(bot.portfolio_path))
    live = read_trades(bot, source="live")
    backtest = read_trades(bot, source="backtest")
    start_equity = (pf_data or {}).get("start_equity") or config.FOREX_START_EQUITY
    curve_live = _daily_curve_live(live, start_equity)
    if verdicts is None:
        verdicts = verdict_mod.load()
    health = reconcile.check(portfolio_path=bot.portfolio_path,
                             journal_path=bot.journal_path)
    return {
        "available": True,
        "bot": bot.id,
        "label": bot.label,
        "description": getattr(bot, "description", ""),
        "verdict": verdicts.get(bot.id),
        "equity": round((pf_data or {}).get("equity", start_equity), 2),
        "start_equity": start_equity,
        "open_positions": (pf_data or {}).get("positions", {}),
        "live": _basic_stats(live),
        "backtest": _basic_stats(backtest),
        "max_drawdown_pct": _max_drawdown_pct(curve_live),
        "sharpe": _sharpe(curve_live),
        "equity_curve_live": curve_live,
        "equity_curve_backtest": _daily_curve_backtest(backtest),
        "data_health": health,
    }


def overview() -> dict:
    """Tout l'écran d'accueil en un appel (spec §4)."""
    from forex import strategies

    index = _read_json_cached(_INDEX_PATH, _mtime(_INDEX_PATH)) or {}
    runner_active = False
    try:
        updated = datetime.fromisoformat(index["updated_at"])
        runner_active = datetime.now(timezone.utc) - updated < timedelta(minutes=5)
    except (KeyError, ValueError):
        pass

    # Charger les verdicts une fois (évite N lectures du même fichier)
    verdicts = verdict_mod.load()

    bots = []
    for bot in strategies.active():
        try:
            s = bot_stats(bot, verdicts=verdicts)
        except Exception as e:
            print(f"[aggregator] bot_stats({bot.id}) a échoué: {e!r}")
            s = {"available": False, "bot": bot.id, "label": bot.label}
        bots.append(s)

    total_equity = sum(b.get("equity") or 0.0 for b in bots if b.get("available"))
    total_start = sum(b.get("start_equity") or 0.0 for b in bots if b.get("available"))
    agg_curve: dict[str, float] = {}
    for b in bots:
        for day, eq in b.get("equity_curve_live", []):
            agg_curve[day] = agg_curve.get(day, 0.0) + eq
    return {
        "updated_at": index.get("updated_at"),
        "runner_active": runner_active,
        "market_open": index.get("market_open"),
        "total_equity": round(total_equity, 2),
        "total_start_equity": round(total_start, 2),
        "return_pct": round((total_equity / total_start - 1) * 100, 2) if total_start else 0.0,
        "equity_curve": sorted([[d, round(v, 2)] for d, v in agg_curve.items()]),
        "n_validated": sum(1 for b in bots
                           if (b.get("verdict") or {}).get("status") == "validated"),
        "data_consistent": all((b.get("data_health") or {}).get("consistent", True)
                               for b in bots),
        "bots": bots,
    }
