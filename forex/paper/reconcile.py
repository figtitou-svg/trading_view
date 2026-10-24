"""
forex/paper/reconcile.py — Réconciliation portefeuille ↔ journal.

Le portefeuille (`paper_portfolio.json`, écrit par PaperBroker) et le journal
(`trade_journal.jsonl`, append-only) doivent raconter la même histoire pour les
trades LIVE : `equity == start_equity + Σ pnl(journal live)` et chaque trade du
portefeuille doit exister dans le journal (clé (pair, entry_ts, "live")).

`check()` mesure l'écart ; `fix()` réinjecte dans le journal les trades du
portefeuille qui en sont absents (le portefeuille est la référence : c'est lui
qui a encaissé le pnl). Ne touche JAMAIS aux entrées `source="backtest"`.

CLI :
    python -m forex.paper.reconcile           # rapport tous bots
    python -m forex.paper.reconcile --fix     # répare tous bots
    python -m forex.paper.reconcile --bot macro --fix
"""

from __future__ import annotations

import argparse
import json

from forex.learning import journal

EPSILON = 0.01  # tolérance d'arrondi en devise de compte


def _load_portfolio(portfolio_path: str) -> dict | None:
    try:
        with open(portfolio_path, encoding="utf-8") as f:
            data = json.load(f)
            # JSON valide mais pas un dict (ex. liste) → invalide
            if not isinstance(data, dict):
                return None
            return data
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def check(*, portfolio_path: str, journal_path: str) -> dict:
    """
    Compare portefeuille et journal live. Ne modifie rien.

    Détecte deux cas de divergence :
    1. `missing_in_journal` : trades du portefeuille absents du journal live.
       → Réparable par `fix()` (réinjecte dans le journal).
    2. `extra_in_journal` : trades live du journal absents du portefeuille.
       → Cas d'un reset : le journal n'est jamais réinitialisé (append-only),
         mais le portefeuille l'est (fichier nouveau). Ne se répare PAS par
         `fix()` — intervention manuelle requise (purge du journal ou reset).

    Le calcul de `consistent` exige que AUCUNE divergence n'existe (missing_in_journal
    ET extra_in_journal doivent être 0, ET l'equity gap doit être < EPSILON).
    """
    pf = _load_portfolio(portfolio_path)
    if pf is None:
        return {"available": False, "consistent": True, "missing_in_journal": 0,
                "extra_in_journal": 0, "equity_gap": 0.0}
    live = [r for r in journal.read_journal(path=journal_path)
            if r.get("source", "live") == "live"]
    portfolio_keys = {(t.get("pair"), t.get("entry_ts")) for t in pf.get("trades", [])}
    journal_keys = {(r.get("pair"), r.get("entry_ts")) for r in live}

    missing = [t for t in pf.get("trades", [])
               if (t.get("pair"), t.get("entry_ts")) not in journal_keys]
    extra = [r for r in live
             if (r.get("pair"), r.get("entry_ts")) not in portfolio_keys]

    expected_equity = pf.get("start_equity", 0.0) + sum(
        r.get("pnl") or 0.0 for r in live)
    gap = pf.get("equity", 0.0) - expected_equity
    return {
        "available": True,
        "consistent": not missing and not extra and abs(gap) < EPSILON,
        "missing_in_journal": len(missing),
        "extra_in_journal": len(extra),
        "equity_gap": round(gap, 2),
        "n_portfolio_trades": len(pf.get("trades", [])),
        "n_journal_live": len(live),
    }


def fix(*, portfolio_path: str, journal_path: str, strategy_id: str) -> int:
    """Réinjecte dans le journal les trades du portefeuille absents. Retourne le nombre ajouté."""
    pf = _load_portfolio(portfolio_path)
    if pf is None:
        return 0
    existing = journal.existing_keys(path=journal_path)
    added = 0
    for t in pf.get("trades", []):
        if (t.get("pair"), t.get("entry_ts"), "live") in existing:
            continue
        journal.append_trade(t, path=journal_path, source="live",
                             strategy=strategy_id)
        added += 1
    return added


def _cli() -> None:
    from forex import strategies

    ap = argparse.ArgumentParser(description="Réconciliation portefeuille ↔ journal")
    ap.add_argument("--fix", action="store_true", help="Répare au lieu de seulement rapporter")
    ap.add_argument("--bot", help="Un seul bot (défaut : tous les bots actifs)")
    args = ap.parse_args()

    try:
        bots = [strategies.get(args.bot)] if args.bot else strategies.active()
    except KeyError:
        print(f"Erreur : bot '{args.bot}' introuvable.")
        raise SystemExit(1)

    for bot in bots:
        report = check(portfolio_path=bot.portfolio_path, journal_path=bot.journal_path)
        flag = "OK " if report["consistent"] else "DIVERGENT"
        status_line = f"[{flag}] {bot.id}:"
        if report["missing_in_journal"] > 0:
            status_line += f" {report['missing_in_journal']} manquant(s) au journal"
        if report["extra_in_journal"] > 0:
            status_line += f" {report['extra_in_journal']} surplus au journal (manual fix)"
        if report["equity_gap"] != 0.0:
            status_line += f" equity_gap={report['equity_gap']:+.2f}"
        print(status_line)
        if args.fix and not report["consistent"] and report["missing_in_journal"] > 0:
            n = fix(portfolio_path=bot.portfolio_path, journal_path=bot.journal_path,
                    strategy_id=bot.id)
            print(f"        → {n} trade(s) réinjecté(s) dans le journal")
        if report["extra_in_journal"] > 0 and args.fix:
            print(f"        ⚠ {report['extra_in_journal']} trade(s) en surplus du journal"
                  f" (reset détecté) — nettoyage manuel requis")


if __name__ == "__main__":
    _cli()
