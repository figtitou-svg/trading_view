"""
forex/learning/backfill.py — Entraîne le module 7 sur l'historique, PAR BOT.

L'analyse par combinaison de signaux ne lit que le journal des trades ; celui
des vrais trades paper est trop maigre pour juger statistiquement quoi que ce
soit. Ce module rejoue la stratégie d'un bot **telle qu'elle est en vigueur**
sur tout l'historique disponible, avec le MÊME moteur de backtest que le
rapport de validation (mêmes garanties anti-look-ahead, mêmes coûts), et
injecte les trades simulés dans le journal DE CE BOT — étiquetés
`source="backtest"` pour rester distinguables des vrais trades en tout temps.

Chaque bot a son journal : les résultats de `smc` ne diluent jamais ceux de
`trend`, et désactiver un setup chez l'un n'affecte pas l'autre.

Idempotent : relancer le backfill n'ajoute jamais de doublon (déduplication
via (pair, entry_ts, source) déjà présents dans le journal).
"""

from __future__ import annotations

import bisect

from forex import config, strategies
from forex.data import prices, calendar as cal, crossasset
from forex.backtest.engine import run_backtest
from forex.learning import journal, state


def _events_for(pair: str) -> list:
    base, quote = pair.upper().split("_")
    return [e for e in cal.load_events() if e.currency in {base, quote}]


# Cache mémoire des séries de prix, partagé par tout le processus de backfill.
# Un backfill complet rejoue 11 bots × 10 paires sur les MÊMES historiques ;
# sans ce cache, chaque bot (et chaque provider macro) retéléchargerait les
# mêmes séries — des centaines de requêtes yfinance et un rate-limiting assuré.
_SERIES_CACHE: dict[tuple[str, str], list[list[float]]] = {}


def _fetch_cached(pair: str, granularity: str) -> list[list[float]]:
    key = (pair.upper(), granularity)
    if key not in _SERIES_CACHE:
        _SERIES_CACHE[key] = prices.fetch_ohlcv(pair, granularity)
    return _SERIES_CACHE[key]


def clear_cache() -> None:
    """Vide le cache de séries (à appeler entre deux exécutions longues)."""
    _SERIES_CACHE.clear()


def _resolve(strategy):
    """Accepte un bot, un identifiant de bot, ou None (= ancienne confluence)."""
    if strategy is None or not isinstance(strategy, str):
        return strategy
    return strategies.get(strategy)


def _needs_macro_context(strategy) -> bool:
    """
    Vrai si le bot — ou l'un de ses MEMBRES s'il s'agit d'un combo — utilise le
    modèle macro, et a donc besoin de la matrice des paires reconstituée.

    Sans ce test récursif, un combo comme `smc+macro` verrait son membre macro
    calculer la force des devises sur une seule paire (contexte vide), ce qui
    produirait un signal dégradé et fausserait tout son backfill.
    """
    if strategy is None:
        return False
    if strategy.id == "macro":
        return True
    return any(m.id == "macro" for m in getattr(strategy, "members", []))


def _macro_context_provider(granularity: str, exclude: str):
    """
    Fournit au bot macro la matrice des AUTRES paires reconstituée à l'instant
    du passé qu'on rejoue.

    Sans ça, le backfill du bot macro serait faussé par un look-ahead massif :
    la force relative des devises serait calculée avec les prix d'aujourd'hui
    alors qu'on simule une décision d'il y a deux ans. On découpe donc chaque
    série au dernier horodatage ≤ à celui de la bougie rejouée.

    L'instantané cross-asset (VIX, or…) n'est pas historisé : il est volontai-
    rement laissé vide en backfill, ce qui neutralise les composantes risque /
    taux / matières premières. Le backfill macro est donc CONSERVATEUR — il ne
    mesure que la composante « force relative ». Mieux vaut sous-estimer l'edge
    que le fabriquer avec des données du futur.
    """
    series: dict[str, list[list[float]]] = {}
    stamps: dict[str, list[int]] = {}
    for p in config.FOREX_PAIRS:
        if p == exclude:
            continue
        try:
            c = _fetch_cached(p, granularity)
        except Exception:
            continue
        if c:
            series[p] = c
            stamps[p] = [row[0] for row in c]

    bars = config.FOREX_MACRO_STRENGTH_BARS + 2

    def provider(index: int, window: list[list[float]]) -> dict:
        target_ts = window[-1][0]
        by_pair = {exclude: window}
        for p, c in series.items():
            j = bisect.bisect_right(stamps[p], target_ts)
            if j > bars:
                by_pair[p] = c[max(0, j - bars):j]
        return {"candles_by_pair": by_pair, "crossasset": {}}

    return provider


def backfill_pair(
    pair: str,
    strategy=None,
    granularity: str = config.FOREX_GRANULARITY,
    path: str | None = None,
) -> int:
    """
    Rejoue la stratégie d'un bot sur l'historique d'une paire et ajoute au
    journal du bot les trades simulés pas déjà présents. Retourne le nombre
    de trades ajoutés.
    """
    strategy = _resolve(strategy)
    path = path or (strategy.journal_path if strategy else journal.JOURNAL_PATH)
    state_path = strategy.state_path if strategy else state.STATE_PATH

    try:
        candles = _fetch_cached(pair, granularity)
    except Exception as e:
        print(f"[backfill] {pair}: données indisponibles ({e})")
        return 0
    min_needed = strategy.min_candles if strategy else config.MA_SLOW + 5
    if len(candles) < min_needed:
        return 0

    events = _events_for(pair)
    # Rejoue avec les paramètres RÉELLEMENT en vigueur pour cette paire chez ce
    # bot (overrides appris s'il y en a, défauts du bot sinon) — sinon le
    # journal jugerait une stratégie différente de celle qui trade en vrai.
    overrides = state.get_overrides(pair, path=state_path)
    default_stop = strategy.atr_stop_mult if strategy else config.ATR_STOP_MULT
    default_tp = strategy.atr_tp_mult if strategy else config.ATR_TP_MULT

    provider = _macro_context_provider(granularity, pair) if _needs_macro_context(strategy) else None

    result = run_backtest(
        candles, pair, events,
        granularity=granularity,
        strategy=strategy,
        context_provider=provider,
        use_technical=config.USE_TECHNICAL,
        use_fundamental=config.USE_FUNDAMENTAL,
        use_time_filter=config.USE_TIME_FILTER,
        confluence_mode=config.FOREX_CONFLUENCE_MODE,
        atr_stop_mult=overrides.get("atr_stop_mult", default_stop),
        atr_tp_mult=overrides.get("atr_tp_mult", default_tp),
    )

    existing = journal.existing_keys(path)
    added = 0
    bot_id = strategy.id if strategy else None
    for trade in result.trades:
        key = (trade.pair, trade.entry_ts, "backtest")
        if key in existing:
            continue
        combo = (strategy.combo_key(trade.signals or {}, trade.direction)
                 if strategy else None)
        journal.append_trade(trade, path=path, source="backtest",
                             strategy=bot_id, combo=combo)
        existing.add(key)
        added += 1
    return added


def refresh_pair(
    pair: str,
    strategy=None,
    granularity: str = config.FOREX_GRANULARITY,
    path: str | None = None,
) -> int:
    """
    Purge les trades historiques existants d'une paire et les régénère avec
    les réglages ACTUELS (post walk-forward). À appeler juste après que
    l'auto-tuner a changé les paramètres d'une paire, pour que l'analyse par
    combo juge la stratégie réellement en vigueur, pas l'ancienne.
    """
    strategy = _resolve(strategy)
    path = path or (strategy.journal_path if strategy else journal.JOURNAL_PATH)
    journal.purge_source(pair, source="backtest", path=path)
    return backfill_pair(pair, strategy, granularity, path)


def backfill_all(
    pairs: list[str] | None = None,
    strategy=None,
    granularity: str = config.FOREX_GRANULARITY,
    path: str | None = None,
) -> dict[str, int]:
    """Backfill toutes les paires (ou celles fournies). Retourne {paire: n_ajoutés}."""
    pairs = pairs or config.FOREX_PAIRS
    return {pair: backfill_pair(pair, strategy, granularity, path) for pair in pairs}


def _cli() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Backfill du journal d'apprentissage par bot")
    ap.add_argument("--bots", help="Bots à traiter (défaut : FOREX_BOTS)")
    args = ap.parse_args()

    bots = ([strategies.get(b.strip()) for b in args.bots.split(",")]
            if args.bots else strategies.active())
    clear_cache()   # données fraîches au démarrage, puis partagées entre bots
    for bot in bots:
        bot.ensure_dir()
        counts = backfill_all(strategy=bot)
        total = sum(counts.values())
        print(f"[{bot.id}] {total} trade(s) historique(s) ajouté(s)")
        for pair, n in counts.items():
            print(f"    {pair:8} +{n}")


if __name__ == "__main__":
    _cli()
