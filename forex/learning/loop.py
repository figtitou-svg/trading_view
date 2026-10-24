"""
forex/learning/loop.py — Orchestrateur du module 7.

`run_learning()` :
  1. **Combos** : analyse le journal ; désactive une combinaison
     statistiquement perdante (échantillon suffisant), réactive une
     combinaison redevenue gagnante. (rapide → appelé aussi par le runner à
     chaque palier de N trades.)
  2. **Paramètres** (`do_tune=True`, cycle hebdomadaire) : pour chaque paire,
     l'auto-tuner walk-forward propose un meilleur réglage ; s'il passe le gate,
     il est appliqué et journalisé.

Tout changement est tracé (state.changelog) et notifié sur Telegram.

CLI :
    python -m forex.learning.loop              # analyse combos (rapide)
    python -m forex.learning.loop --backfill   # entraîne le journal sur l'historique
    python -m forex.learning.loop --tune       # backfill + analyse + auto-tuning walk-forward
    python -m forex.learning.loop --report     # rapport (combos + faux négatifs)
    python -m forex.learning.loop --rollback [N]   # annule les N derniers changements
"""

from __future__ import annotations

import argparse
import asyncio

from forex import config, strategies
from forex.data import prices, calendar as cal
from forex.learning import analysis, backfill, journal, state, tuner, false_negatives, verdict


def _notify(title: str, body: str) -> None:
    try:
        from services.notifier import notifier  # noqa: PLC0415
        asyncio.run(notifier.send_telegram_text(f"*{title}*\n{body}".replace("_", "/")))
    except Exception as e:
        print(f"[learning] notification ignorée : {e}")


def _events_for(pair: str) -> list:
    b, q = pair.split("_")
    return [e for e in cal.load_events() if e.currency in {b, q}]


def _review_combos(bot) -> list[str]:
    """
    Désactive/réactive des setups selon la significativité, dans le périmètre
    d'UN bot (son journal, son état). Retourne les changements.
    """
    trades = journal.read_journal(path=bot.journal_path)
    stats = analysis.analyze(trades)
    disabled = state.get_disabled_combos(path=bot.state_path)
    changes: list[str] = []

    for combo, s in stats.items():
        if s.significant_loser and combo not in disabled:
            entry = state.disable_combo(
                combo, f"perdant significatif (expectancy {s.expectancy:+.3f}%, p={s.p_value:.3f})",
                s.n, path=bot.state_path)
            if entry:
                changes.append(f"❌ [{bot.id}] setup {combo} désactivé (n={s.n}, exp {s.expectancy:+.3f}%)")
        elif s.significant_winner and combo in disabled:
            entry = state.enable_combo(
                combo, f"redevenu gagnant (expectancy {s.expectancy:+.3f}%, p={s.p_value:.3f})",
                s.n, path=bot.state_path)
            if entry:
                changes.append(f"✅ [{bot.id}] setup {combo} réactivé (n={s.n}, exp {s.expectancy:+.3f}%)")
    return changes


def _tune_params(bot) -> tuple[list[str], list[str]]:
    """
    Auto-tuning walk-forward par paire, pour UN bot. Retourne (changements
    affichés, paires dont les paramètres ont réellement changé — à rafraîchir
    dans le journal historique avant de juger les setups sur des données à jour).
    """
    changes: list[str] = []
    changed_pairs: list[str] = []
    defaults = {"atr_stop_mult": bot.atr_stop_mult, "atr_tp_mult": bot.atr_tp_mult}

    for pair in config.FOREX_PAIRS:
        try:
            candles = prices.fetch_ohlcv(pair, config.FOREX_GRANULARITY)
        except Exception as e:
            print(f"[learning/{bot.id}] {pair}: données indisponibles ({e})")
            continue
        events = _events_for(pair)
        current = state.get_overrides(pair, path=bot.state_path)
        proposal = tuner.propose(
            pair, candles, events, current,
            defaults=defaults,
            strategy=bot,
            granularity=config.FOREX_GRANULARITY,
            use_time_filter=config.USE_TIME_FILTER,
        )
        print(f"  [{bot.id}] " + proposal.summary())
        if proposal.accepted:
            for field_, after in proposal.changes.items():
                state.apply_param_change(
                    pair, field_, after,
                    f"walk-forward OOS {proposal.oos_before:+.1f}%→{proposal.oos_after:+.1f}% "
                    f"({proposal.positive_folds}/{proposal.n_folds} folds+)",
                    proposal.n_folds, path=bot.state_path,
                )
            changes.append(f"[{bot.id}] " + proposal.summary())
            changed_pairs.append(pair)
    return changes, changed_pairs


def _bots(bots: list[str] | None):
    return [strategies.get(b) for b in bots] if bots else strategies.active()


def run_learning(reason: str = "palier", do_tune: bool = False, notify: bool = True,
                 bots: list[str] | None = None) -> list[str]:
    """
    Exécute un cycle d'apprentissage, bot par bot. Retourne les changements.

    Chaque bot est jugé sur SON journal et modifie SON état : un bot coupé
    n'entraîne jamais l'arrêt d'un autre.

    Ordre (important) : le tuning des PARAMÈTRES passe avant l'analyse des
    SETUPS. Si l'auto-tuner améliore les multiples ATR d'une paire, son
    historique simulé est régénéré avec les nouveaux réglages avant que
    l'analyse ne juge sa rentabilité — sinon on jugerait une stratégie qui
    n'est déjà plus celle réellement en vigueur.
    """
    changes: list[str] = []
    # Données fraîches au début du cycle, puis mises en cache et partagées par
    # tous les bots : ils doivent être jugés sur EXACTEMENT le même historique.
    backfill.clear_cache()
    for bot in _bots(bots):
        bot.ensure_dir()
        if do_tune:
            tune_changes, changed_pairs = _tune_params(bot)
            changes += tune_changes
            for pair in changed_pairs:
                n = backfill.refresh_pair(pair, bot)
                print(f"[learning/{bot.id}] {pair} : historique régénéré ({n} trades)")
            # Backfill idempotent des autres paires : peu coûteux (n'ajoute que
            # les nouvelles bougies écoulées pour celles non tunées).
            counts = backfill.backfill_all(strategy=bot)
            added = sum(counts.values())
            if added:
                print(f"[learning/{bot.id}] backfill : +{added} trade(s) historique(s)")

        changes += _review_combos(bot)

    # Verdicts recalculés à chaque cycle, même sans changement de combo : c'est
    # le portail que le runner (sizing) et l'API v2 lisent.
    try:
        this_cycle_bots = _bots(bots)
        payload = verdict.write_all(bots=this_cycle_bots)
        this_cycle_ids = {b.id for b in this_cycle_bots}
        kills = [b for b, v in payload["verdicts"].items()
                 if b in this_cycle_ids and v["status"] == "kill"]
        if kills:
            changes.append(f"💀 verdict kill : {', '.join(kills)}")
    except Exception as e:
        print(f"[learning] écriture des verdicts échouée : {e}")

    if changes and notify:
        _notify(f"🧠 FOREX apprentissage ({reason})", "\n".join(changes))
    if not changes:
        print(f"[learning] ({reason}) aucun changement (échantillon/gate insuffisants).")
    return changes


def _report(bots: list[str] | None = None) -> None:
    for bot in _bots(bots):
        trades = journal.read_journal(path=bot.journal_path)
        n_live = sum(1 for t in trades if t.get("source", "live") == "live")
        n_backtest = len(trades) - n_live
        print(f"\n{'=' * 60}")
        print(f"=== {bot.id.upper()} — {bot.label}")
        print(f"=== Journal : {len(trades)} trades ({n_live} live · {n_backtest} historique)")
        print("=" * 60)
        print(analysis.summary(analysis.analyze(trades)))
        st = state.load(bot.state_path)
        print("  Réglages appris :")
        print(f"    params : {st.get('params', {})}")
        print(f"    setups désactivés : {st.get('disabled_combos', [])}")
        for c in state.changelog(5, path=bot.state_path):
            print(f"    {c}")


def _cli() -> None:
    ap = argparse.ArgumentParser(description="Boucle d'apprentissage forex (module 7)")
    ap.add_argument("--backfill", action="store_true",
                    help="Entraîne le journal sur l'historique (trades simulés, idempotent)")
    ap.add_argument("--tune", action="store_true", help="Backfill + auto-tuning walk-forward")
    ap.add_argument("--report", action="store_true", help="Rapport (combos + faux négatifs)")
    ap.add_argument("--rollback", nargs="?", const=1, type=int, metavar="N",
                    help="Annule les N derniers changements (défaut 1)")
    ap.add_argument("--bots", help="Bots concernés (défaut : FOREX_BOTS)")
    args = ap.parse_args()

    bots = [b.strip() for b in args.bots.split(",")] if args.bots else None

    if args.rollback is not None:
        for bot in _bots(bots):
            n = state.rollback(args.rollback, path=bot.state_path)
            print(f"[{bot.id}] {n} changement(s) annulé(s).")
        return
    if args.backfill:
        for bot in _bots(bots):
            bot.ensure_dir()
            counts = backfill.backfill_all(strategy=bot)
            total = sum(counts.values())
            print(f"[{bot.id}] backfill : {total} trade(s) historique(s) ajouté(s).")
            for pair, n in counts.items():
                print(f"    {pair:8} +{n}")
        return
    if args.report:
        _report(bots)
        return
    changes = run_learning(reason="hebdomadaire" if args.tune else "manuel",
                           do_tune=args.tune, bots=bots)
    for c in changes:
        print("  " + c)


if __name__ == "__main__":
    _cli()
