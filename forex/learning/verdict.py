"""
forex/learning/verdict.py — Portail de validation par bot (spec 2026-07-27).

Statuts, calculés en SÉPARANT les trades `source="live"` et `source="backtest"` :
  incubation : < FOREX_VERDICT_MIN_LIVE_TRADES trades live — pas de preuve.
  watch      : assez de live mais PF < seuil ou espérance ≤ 0 — sous surveillance.
  validated  : assez de live, PF ≥ seuil et espérance > 0.
  kill       : (PF backtest < seuil ET assez de live ET espérance live ≤ 0)
               OU drawdown live > seuil. Jamais sur le seul backtest : tous les
               bots y sont négatifs, le live tranche.

`write_all()` est appelé en fin de `run_learning()` (learning-timer systemd) et
écrit `forex/_cache/verdicts.json`, lu par le runner (sizing) et l'API v2.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from forex import config
from forex.learning import journal

VERDICTS_PATH = os.path.join(config.FOREX_DATA_DIR, "verdicts.json")


def _default_verdicts_path() -> str:
    """
    Résolu à CHAQUE appel (contrairement à `VERDICTS_PATH`, figé à l'import) —
    c'est ce qui permet aux tests d'isoler `config.FOREX_DATA_DIR` (monkeypatch)
    sans que `load()`/`write_all()` n'écrivent dans le vrai cache de prod.
    """
    return os.path.join(config.FOREX_DATA_DIR, "verdicts.json")


def _stats(trades: list[dict]) -> dict:
    pnls = [t.get("pnl_pct") or 0.0 for t in trades]
    gains = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    pf = (gains / losses) if losses else (float("inf") if gains else 0.0)
    return {
        "n": len(trades),
        "expectancy": round(sum(pnls) / len(pnls), 4) if pnls else 0.0,
        # None = PF infini (aucun perdant). À traiter explicitement dans les conditions
        # qui l'utilisent (ex. kill, validated) pour ne pas le transformer en 0.0.
        "profit_factor": round(pf, 2) if pf != float("inf") else None,
        "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls) * 100, 1) if pnls else 0.0,
    }


def _drawdown_pct(portfolio: dict | None) -> float:
    if not portfolio:
        return 0.0
    peak = portfolio.get("peak_equity") or portfolio.get("start_equity") or 0.0
    equity = portfolio.get("equity", peak)
    return round((peak - equity) / peak * 100, 2) if peak else 0.0


def compute(bot_id: str, trades: list[dict], portfolio: dict | None) -> dict:
    """Verdict d'un bot depuis ses trades journalisés et son portefeuille."""
    live = [t for t in trades if t.get("source", "live") == "live"]
    backtest = [t for t in trades if t.get("source") == "backtest"]
    ls, bs = _stats(live), _stats(backtest)
    dd = _drawdown_pct(portfolio)
    min_live = config.FOREX_VERDICT_MIN_LIVE_TRADES

    status, reason = "incubation", f"{ls['n']}/{min_live} trades live — pas encore jugeable"
    if dd > config.FOREX_VERDICT_KILL_DD_PCT:
        status, reason = "kill", f"drawdown live {dd:.1f}% > {config.FOREX_VERDICT_KILL_DD_PCT}%"
    elif (ls["n"] >= config.FOREX_VERDICT_KILL_MIN_LIVE
          and ls["expectancy"] <= 0
          and bs["n"] > 0
          and bs["profit_factor"] is not None
          and bs["profit_factor"] < config.FOREX_VERDICT_KILL_BACKTEST_PF):
        status = "kill"
        reason = (f"PF backtest {bs['profit_factor']} < {config.FOREX_VERDICT_KILL_BACKTEST_PF} "
                  f"et {ls['n']} trades live à espérance {ls['expectancy']:+.3f}%")
    elif ls["n"] >= min_live:
        pf_ok = (ls["profit_factor"] is None
                 or ls["profit_factor"] >= config.FOREX_VERDICT_PF_VALIDATED)
        if pf_ok and ls["expectancy"] > 0:
            status, reason = "validated", (
                f"PF live {ls['profit_factor']} ≥ {config.FOREX_VERDICT_PF_VALIDATED}, "
                f"espérance {ls['expectancy']:+.3f}%")
        else:
            status, reason = "watch", (
                f"PF live {ls['profit_factor']} ou espérance {ls['expectancy']:+.3f}% "
                f"sous les seuils")

    return {
        "bot": bot_id,
        "status": status,
        "reason": reason,
        "risk_mult": config.FOREX_VERDICT_RISK_MULT[status],
        "live": ls,
        "backtest": bs,
        "drawdown_pct": dd,
        "progress": {"live_trades": ls["n"], "needed": min_live},
    }


def load(path: str | None = None) -> dict:
    """{bot_id: verdict} — dict vide si le fichier n'existe pas encore."""
    path = path or _default_verdicts_path()
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("verdicts", {})
    except (OSError, ValueError) as e:
        print(f"[verdict] verdicts.json illisible: {e} — multiplicateurs par défaut")
        return {}


def risk_multiplier(v: dict | None) -> float:
    """Multiplicateur de risque d'un verdict (incubation si bot inconnu → prudence par défaut)."""
    if not v:
        return config.FOREX_VERDICT_RISK_MULT["incubation"]
    return float(v.get("risk_mult", 1.0))


def write_all(bots=None, path: str | None = None) -> dict:
    """Calcule et persiste le verdict de chaque bot actif. Retourne le payload.

    Fusionne avec le contenu existant de verdicts.json plutôt que de l'écraser :
    un appel à bots restreint (ex. le palier-trigger single-bot de
    journal_and_learn) ne doit JAMAIS effacer le verdict des autres bots —
    seuls les bots effectivement recalculés cet appel voient leur entrée
    remplacée. Bug trouvé en revue finale (2026-07-29) : l'ancienne version
    écrasait tout le fichier avec seulement les bots passés en argument.
    """
    from forex import strategies

    path = path or _default_verdicts_path()
    bots = strategies.active() if bots is None else bots

    try:
        with open(path, encoding="utf-8") as f:
            verdicts = json.load(f).get("verdicts", {})
    except (OSError, ValueError):
        verdicts = {}

    computed_this_call = {}
    for bot in bots:
        try:
            trades = journal.read_journal(path=bot.journal_path)
            try:
                with open(bot.portfolio_path, encoding="utf-8") as f:
                    pf_raw = json.load(f)
                    # Robustesse : si le JSON est pas un dict, l'ignorer (données corrompues)
                    pf = pf_raw if isinstance(pf_raw, dict) else None
            except (OSError, ValueError):
                pf = None
            computed_this_call[bot.id] = compute(bot.id, trades, pf)
        except Exception as e:
            print(f"[verdict] {bot.id} — données illisibles ({type(e).__name__}: {e}), omis")
            continue

    verdicts.update(computed_this_call)
    payload = {"updated_at": datetime.now(timezone.utc).isoformat(), "verdicts": verdicts}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

    kills = [b for b, v in computed_this_call.items() if v["status"] == "kill"]
    if kills:
        disabled_path = os.path.join(config.FOREX_DATA_DIR, "disabled_bots.json")
        try:
            with open(disabled_path, encoding="utf-8") as f:
                disabled = json.load(f)
        except (OSError, ValueError):
            disabled = []
        changed = False
        for b in kills:
            if b not in disabled:
                disabled.append(b)
                changed = True
        if changed:
            tmp2 = disabled_path + ".tmp"
            with open(tmp2, "w", encoding="utf-8") as f:
                json.dump(disabled, f, ensure_ascii=False, indent=2)
            os.replace(tmp2, disabled_path)

    return payload
