"""
forex/data/crossasset.py — Contexte macro cross-asset (yfinance, sans credentials).

Le bot macro historique ne pouvait s'exprimer que dans les ~35 minutes suivant
une annonce économique, et seulement si ≥ 8 surprises passées du même type
étaient déjà connues. Comme le flux Forex Factory ne donne que la semaine
courante, cette condition n'était quasiment jamais remplie : le bot restait
muet. Ce module fournit les données macro **disponibles à chaque barre**, pour
qu'il ait un avis tous les jours.

Instruments suivis (tous publics, aucun compte requis) :
  - `^VIX`   : volatilité implicite S&P 500 → appétit pour le risque ;
  - `GC=F`   : or → valeur refuge (monte quand le marché a peur) ;
  - `CL=F`   : pétrole WTI → corrélé au CAD (Canada exportateur net) ;
  - `^TNX`   : rendement du 10 ans US → différentiel de taux, moteur n°1 du USD.

Le cache disque évite de retélécharger à chaque cycle de polling (les données
macro bougent à l'échelle de la journée, pas de la minute) et rend le module
utilisable hors-ligne : en cas d'échec réseau, on renvoie le dernier instantané
connu plutôt que de faire tomber tout le bot.
"""

from __future__ import annotations

import json
import os
import time

from forex import config

CACHE_PATH = os.path.join(config.FOREX_DATA_DIR, "crossasset.json")

# Ticker yfinance → nom interne.
TICKERS = {
    "^VIX": "vix",
    "GC=F": "gold",
    "CL=F": "oil",
    "^TNX": "us10y",
}


def _fetch_series(ticker: str, lookback_days: int) -> list[float] | None:
    """Clôtures journalières d'un instrument (None si indisponible)."""
    try:
        import yfinance as yf

        df = yf.download(ticker, period=f"{lookback_days}d", interval="1d",
                         auto_adjust=False, progress=False, threads=False)
        if df is None or len(df) == 0:
            return None
        import pandas as pd

        if isinstance(df.columns, pd.MultiIndex):
            df = df.copy()
            df.columns = df.columns.get_level_values(0)
        closes = [float(v) for v in df["Close"].tolist() if v == v]  # filtre NaN
        return closes or None
    except Exception as e:
        print(f"[forex] cross-asset {ticker} indisponible : {e}")
        return None


def _load_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_cache(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError as e:
        print(f"[forex] écriture du cache cross-asset échouée : {e}")


def snapshot(
    *,
    lookback_days: int = config.FOREX_MACRO_LOOKBACK_DAYS,
    max_age_seconds: int = config.FOREX_MACRO_CACHE_SECONDS,
    force: bool = False,
) -> dict:
    """
    Instantané macro : pour chaque instrument, sa dernière valeur et sa
    variation en % sur la fenêtre.

    Renvoie le cache si celui-ci est plus récent que `max_age_seconds` — et
    aussi, en secours, si le réseau échoue (mieux vaut un contexte macro de la
    veille que pas de contexte du tout).
    """
    cache = _load_cache()
    fresh = cache and (time.time() - cache.get("fetched_at", 0)) < max_age_seconds
    if fresh and not force:
        return cache

    out: dict = {"fetched_at": time.time()}
    got_any = False
    for ticker, name in TICKERS.items():
        closes = _fetch_series(ticker, lookback_days)
        if not closes or len(closes) < 2:
            # Conserve la valeur précédemment connue si on l'a.
            if name in cache:
                out[name] = cache[name]
            continue
        got_any = True
        last, first = closes[-1], closes[0]
        out[name] = {
            "last": round(last, 4),
            "change_pct": round((last / first - 1) * 100, 3) if first else 0.0,
            "mean": round(sum(closes) / len(closes), 4),
        }

    if not got_any and cache:
        return cache          # réseau totalement indisponible → dernier connu
    _save_cache(out)
    return out
