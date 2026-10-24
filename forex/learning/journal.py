"""
forex/learning/journal.py — Journal d'apprentissage (append-only).

Chaque trade clôturé est écrit dans `forex/_cache/trade_journal.jsonl` avec :
  - son résultat NET (pnl, pnl_pct, net_pips) et sa durée ;
  - sa **classification** : win / loss / neutral (sortie temporelle sans mouvement) ;
  - sa **clé de combinaison** de signaux (`tech+fund:long`…) pour l'analyse ;
  - le contexte COMPLET des signaux à l'entrée (déjà porté par PaperTrade.signals) ;
  - sa **source** : `"live"` (vrai trade paper trading) ou `"backtest"` (trade
    simulé sur historique, injecté par `forex.learning.backfill`) — toujours
    distinguable, jamais mélangée de façon invisible.

Le fichier est append-only (JSONL) : il survit aux réinitialisations du
portefeuille et constitue la mémoire d'apprentissage du module 7.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass

from forex import config
from forex.signals.confluence import combo_key

JOURNAL_PATH = os.path.join(config.FOREX_DATA_DIR, "trade_journal.jsonl")


def classify(pnl_pct: float, exit_reason: str) -> str:
    """win / loss / neutral. Une sortie temporelle sans mouvement = neutral."""
    if exit_reason and "temporelle" in exit_reason.lower():
        return "neutral"
    return "win" if pnl_pct > 0 else "loss"


def record_from_trade(trade, source: str = "live", *,
                      strategy: str | None = None, combo: str | None = None) -> dict:
    """
    Construit l'enregistrement de journal à partir d'un PaperTrade/Trade (ou dict).

    `strategy` / `combo` sont fournis par le bot propriétaire du trade : chaque
    bot ayant son propre journal ET sa propre notion de combinaison (une figure
    chartiste pour `chartist`, un type de zone pour `smc`…), la clé ne peut plus
    être déduite ici. À défaut, on retombe sur l'ancienne clé de confluence pour
    rester compatible avec les journaux déjà écrits.
    """
    d = asdict(trade) if is_dataclass(trade) else dict(trade)
    signals = d.get("signals") or {}
    return {
        "strategy": strategy,
        "pair": d.get("pair"),
        "direction": d.get("direction"),
        "entry_ts": d.get("entry_ts"),
        "exit_ts": d.get("exit_ts"),
        "entry_price": d.get("entry_price"),
        "exit_price": d.get("exit_price"),
        "net_pips": d.get("net_pips"),
        "pnl": d.get("pnl"),
        "pnl_pct": d.get("pnl_pct"),
        "exit_reason": d.get("exit_reason"),
        "event_driven": d.get("event_driven", False),
        "classification": classify(d.get("pnl_pct", 0.0), d.get("exit_reason", "")),
        "combo": combo or combo_key(signals, d.get("direction")),
        "signals": signals,
        "source": source,
    }


def append_trade(trade, path: str = JOURNAL_PATH, source: str = "live", *,
                 strategy: str | None = None, combo: str | None = None) -> dict:
    """Ajoute un trade au journal (crée le fichier au besoin). Retourne l'enregistrement."""
    rec = record_from_trade(trade, source=source, strategy=strategy, combo=combo)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def read_journal(path: str = JOURNAL_PATH) -> list[dict]:
    """Relit tout le journal (liste vide si absent)."""
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def count(path: str = JOURNAL_PATH) -> int:
    return len(read_journal(path))


def existing_keys(path: str = JOURNAL_PATH) -> set[tuple]:
    """
    Clés (pair, entry_ts, source) déjà présentes dans le journal — utilisé par
    `forex.learning.backfill` pour rester idempotent (ne jamais dupliquer un
    trade simulé déjà injecté lors d'un backfill précédent).
    """
    return {
        (r.get("pair"), r.get("entry_ts"), r.get("source", "live"))
        for r in read_journal(path)
    }


def purge_source(pair: str, source: str = "backtest", path: str = JOURNAL_PATH) -> int:
    """
    Retire du journal toutes les entrées d'une paire pour une source donnée.

    Utilisé avant un RE-backfill quand l'auto-tuner change les paramètres
    d'une paire : les anciens trades simulés reflètent des réglages qui ne
    sont plus ceux réellement en vigueur, il faut les régénérer plutôt que
    les laisser fausser l'analyse par combo. Retourne le nombre supprimé.
    """
    recs = read_journal(path)
    kept = [r for r in recs if not (r.get("pair") == pair and r.get("source", "live") == source)]
    removed = len(recs) - len(kept)
    if removed:
        with open(path, "w", encoding="utf-8") as f:
            for r in kept:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return removed
