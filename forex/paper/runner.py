"""
forex/paper/runner.py — Boucle de paper trading forex MULTI-BOTS (100 % simulé).

Fait tourner côte à côte plusieurs bots **indépendants** (cf.
`forex.strategies`) : chacun a sa stratégie, son portefeuille virtuel, son
journal de trades, ses paramètres appris et ses garde-fous de risque. Un bot
qui se plante, se fait couper par l'apprentissage ou est désactivé n'a aucun
effet sur les autres — c'est ce qui permet de mesurer l'edge de chaque approche
séparément au lieu d'un agrégat illisible.

Ce qui est MUTUALISÉ, et pourquoi :
  - **les bougies** : téléchargées une seule fois par paire et par cycle, puis
    passées à tous les bots. Sans ça, 10 paires × 4 bots = 40 requêtes yfinance
    par cycle → rate-limiting garanti ;
  - **le calendrier économique** et **l'instantané cross-asset** (VIX, or,
    pétrole, taux), pour la même raison ;
  - **le filtre temporel** et les contrôles de levier : ce sont des règles de
    sécurité, pas des stratégies.

Aucun ordre réel n'est possible : tout fill est un calcul local.

Lancer :
    python -m forex.paper.runner            # boucle continue
    python -m forex.paper.runner --once     # une seule itération (cron/test)
    python -m forex.paper.runner --bots smc # restreint aux bots donnés
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Créneaux de notification (07:30/13:00/18:00/22:00) pensés en heure de Paris ;
# le serveur de prod tourne en UTC, donc `datetime.now()` nu donnerait un
# décalage de 1h/2h (hiver/été) — on fixe explicitement le fuseau.
_PARIS_TZ = ZoneInfo("Europe/Paris")

from forex import config, strategies
from forex.data import prices, calendar as cal, crossasset
from forex.signals import indicators
from forex.signals.time_filter import is_market_open
from forex.risk.manager import RiskManager, check_leverage
from forex.risk.sizing import units_from_risk
from forex.paper.broker import PaperBroker
from forex.strategies import remove
from forex.learning import journal, state, loop as learning_loop
from forex.learning import verdict as verdict_mod
from services.notification_settings import load_notification_settings, DEFAULTS as _NOTIF_DEFAULTS

_GRAN_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D": 1440}
_CALENDAR_REFRESH_SECONDS = 3600
# Nombre de bougies récentes mises en cache par paire pour les graphiques du
# dashboard (lecture disque → aucun appel réseau côté API). Aligné sur `need`
# dans _fetch_candles (~300 bougies H1, soit ~12 jours) pour couvrir l'horizon
# pluri-journalier des bots macro sans jamais sortir de la fenêtre en cache.
_CHART_CANDLES = 300

CANDLES_PATH = os.path.join(config.FOREX_DATA_DIR, "forex_candles.json")
# Index global : la liste des bots actifs et leur résumé, pour que le dashboard
# sache quoi afficher sans connaître la configuration.
INDEX_PATH = os.path.join(config.FOREX_DATA_DIR, "forex_bots.json")
# Bots supprimés depuis le dashboard : relu à chaque cycle par iterate(), même
# principe que follows.json (copy trading) et disabled_combos (apprentissage).
DISABLED_BOTS_PATH = os.path.join(config.FOREX_DATA_DIR, "disabled_bots.json")


def load_disabled_bots() -> set[str]:
    """Ids des bots supprimés depuis le dashboard. Set vide si le fichier est absent/corrompu."""
    try:
        with open(DISABLED_BOTS_PATH, encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, json.JSONDecodeError):
        return set()


def _exclude_disabled(active: list, disabled_ids: set[str]) -> list:
    """
    Exclut les bots supprimés depuis le dashboard AVANT de construire leurs
    BotRuntime : sinon un redémarrage du service recréerait un dossier de
    cache vide (et un portefeuille neuf) pour un bot déjà archivé.
    """
    return [s for s in active if s.id not in disabled_ids]


def _retire_orphaned_disabled_bots(active: list, disabled_ids: set[str],
                                   candles_by_pair: dict) -> None:
    """
    Un bot supprimé pendant que le processus était ARRÊTÉ n'a jamais été
    clôturé/archivé par iterate() (qui ne tourne que pendant que le
    processus vit). Si son dossier de cache existe encore (donc pas encore
    retiré), on le clôture au prix courant et on l'archive maintenant, une
    fois, au démarrage — sinon sa position ouverte resterait orpheline pour
    toujours et son historique jamais archivé. Si le dossier n'existe plus
    (déjà archivé lors d'un run précédent), on ne touche à rien.
    """
    for s in active:
        if s.id in disabled_ids and os.path.isdir(s.dir):
            _retire_bot(BotRuntime(s), candles_by_pair)


def _notify(title: str, body: str) -> None:
    """Envoie une alerte Telegram (import paresseux → tests sans .env crypto)."""
    try:
        from services.notifier import notifier  # noqa: PLC0415
        # Le notifier envoie en Markdown : les '_' des noms de paires (EUR_USD)
        # cassent le parsing (italique non fermé). On les remplace par '/'
        # (plus lisible) pour éviter les 400 Bad Request.
        msg = f"*{title}*\n{body}".replace("_", "/")
        asyncio.run(notifier.send_telegram_text(msg))
    except Exception as e:  # pas de Telegram configuré / offline : on continue
        print(f"[forex] notification ignorée : {e}")


_RANK_MEDALS = ["🥇", "🥈", "🥉"]

# Créneaux de notification, en heure de Paris (HHMM). Deux jeux INDÉPENDANTS :
# le classement (mode détaillé) garde ses horaires historiques ; le récap
# (mode daily_recap) a les siens — changer l'un ne doit jamais affecter l'autre.
_RANKING_SLOTS = [730, 1300, 1800, 2200]
_DAILY_RECAP_SLOTS = [730, 1200, 2000]


def _slot_action(current_time_val: int, forex_mode: str, forex_ranking_enabled: bool,
                  last_notified_slot: int, just_started: bool) -> tuple[str | None, int, bool]:
    """
    Détermine si un créneau de notification vient d'être franchi et lequel,
    et fait progresser l'état (last_notified_slot, just_started).

    Retourne (action, nouveau last_notified_slot, nouveau just_started) où
    action vaut "ranking", "daily_recap" ou None (rien à faire ce cycle).

    `just_started` supprime uniquement la toute première notification après
    le lancement du script (pour ne pas notifier rétroactivement un créneau
    déjà passé si le script démarre en cours de journée) — c'est un
    mécanisme distinct du reset quotidien de `last_notified_slot`. Avant ce
    correctif, les deux partageaient la même sentinelle -1 : le reset
    remettait last_notified_slot à -1 juste avant le premier créneau du
    jour, et la condition de suppression (`last_notified_slot != -1`)
    redevenait vraie à ce moment précis — la notif du premier créneau ne
    partait donc JAMAIS, chaque jour, pas seulement au lancement du script.
    """
    active_slots = _DAILY_RECAP_SLOTS if forex_mode == "daily_recap" else _RANKING_SLOTS

    triggered_slot = -1
    for slot in active_slots:
        if current_time_val >= slot:
            triggered_slot = slot

    action = None
    if triggered_slot != -1 and triggered_slot != last_notified_slot:
        if not just_started:
            if forex_mode == "detailed" and forex_ranking_enabled:
                action = "ranking"
            elif forex_mode == "daily_recap":
                action = "daily_recap"
        just_started = False
        last_notified_slot = triggered_slot

    if current_time_val < active_slots[0] and last_notified_slot != -1:
        last_notified_slot = -1

    return action, last_notified_slot, just_started


def _build_ranking_message(entries: list[dict], now_local: datetime) -> str:
    """
    Classement condensé des bots pour la notif périodique : top 5 par
    retour %, sans détail technique (pas de win rate ni nb de trades —
    trop d'infos pour une notif, le dashboard reste la source détaillée).
    """
    ranked = sorted(entries, key=lambda e: e["ret"], reverse=True)[:5]
    lines = []
    for i, e in enumerate(ranked):
        ret_str = f"+{e['ret']:.2f}" if e["ret"] >= 0 else f"{e['ret']:.2f}"
        rank_label = _RANK_MEDALS[i] if i < len(_RANK_MEDALS) else f"{i + 1}."
        lines.append(f"{rank_label} *{e['bot']}* : {ret_str}%")
    header = f"🏆 *Top {len(ranked)} bots forex ({now_local.strftime('%H:%M')})*\n\n"
    return header + "\n".join(lines)


def _build_daily_recap_message(runtimes: list[BotRuntime], since: datetime, until: datetime,
                               now_local: datetime) -> tuple[str, str]:
    """
    Récap enrichi (mode notification 'daily_recap', 3 fois par jour à
    7h30/12h/20h — cf. _DAILY_RECAP_SLOTS) : nombre d'entrées/sorties
    (gains/pertes) et P&L cumulé depuis le dernier récap, tous bots
    confondus, plus le classement top 5 par retour % — condensé au lieu
    d'une notif par trade.
    """
    since_ms = int(since.timestamp() * 1000)
    until_ms = int(until.timestamp() * 1000)
    n_entries = 0
    n_wins = 0
    n_losses = 0
    pnl_total = 0.0
    for rt in runtimes:
        for pos in rt.broker.positions.values():
            if since_ms < pos.entry_ts <= until_ms:
                n_entries += 1
        for trade in rt.broker.trades:
            if since_ms < trade.entry_ts <= until_ms:
                n_entries += 1
            if since_ms < trade.exit_ts <= until_ms:
                if trade.pnl > 0:
                    n_wins += 1
                else:
                    n_losses += 1
                pnl_total += trade.pnl

    ranking_entries = [{"bot": rt.id, "ret": rt.broker.stats().get("return_pct", 0)}
                       for rt in runtimes]
    ranking = _build_ranking_message(ranking_entries, now_local)

    title = f"📅 Récap Forex ({now_local.strftime('%H:%M')})"
    body = (f"🔵 {n_entries} entrée(s) · ✅ {n_wins} gain(s) · ❌ {n_losses} perte(s)\n"
            f"P&L cumulé {pnl_total:+.2f}\n\n" + ranking)
    return title, body


def _build_entry_message(bot_id: str, direction: str, pair: str, *,
                         entry: float, stop: float, tp: float, strength: float) -> tuple[str, str]:
    title = f"🔵 {bot_id.upper()} ENTRÉE {direction.upper()} {pair}"
    body = f"@ {entry:.5f} · stop {stop:.5f} · TP {tp:.5f} · force {strength:.2f}"
    return title, body


def _build_exit_message(bot_id: str, pair: str, trade, equity: float) -> tuple[str, str]:
    emoji = "🟢" if trade.pnl > 0 else "🔴"
    title = f"{emoji} {bot_id.upper()} SORTIE {pair}"
    if trade.adjusted:
        label = ("SL ajusté" if trade.exit_reason == "stop-loss"
                 else "TP ajusté" if trade.exit_reason == "take-profit"
                 else "ajusté")
        note = f" ({label})"
    else:
        note = ""
    body = (f"{trade.exit_reason}{note} @ {trade.exit_price:.5f}\n"
            f"P&L {trade.pnl:+.2f} ({trade.pnl_pct:+.2f}%) · equity {equity:.2f}")
    return title, body


def _load_events() -> list:
    ccys = set()
    for p in config.FOREX_PAIRS:
        b, q = p.split("_")
        ccys |= {b, q}
    return [e for e in cal.load_events() if e.currency in ccys]


def _write_json(path: str, payload) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"[forex] écriture de {os.path.basename(path)} échouée : {e}")


class BotRuntime:
    """
    État d'exécution d'un bot : sa stratégie + son portefeuille + son risque.

    Tout est adressé par les chemins de la stratégie (`_cache/bots/<id>/`), ce
    qui garantit l'étanchéité entre bots sans que le reste du code ait à s'en
    soucier.
    """

    def __init__(self, strategy):
        self.strategy = strategy
        strategy.ensure_dir()
        self.broker = PaperBroker(path=strategy.portfolio_path)
        self.rm = RiskManager(
            capital=self.broker.equity,
            daily_loss_limit_pct=config.FOREX_DAILY_LOSS_LIMIT_PCT,
            weekly_loss_limit_pct=config.FOREX_WEEKLY_LOSS_LIMIT_PCT,
            trailing_drawdown_pct=config.FOREX_TRAILING_DD_PCT,
        )
        self.rm.start_day(self.broker.equity)
        self.retired = False  # True une fois clôturé+archivé suite à une suppression dashboard

    @property
    def id(self) -> str:
        return self.strategy.id

    def journal_and_learn(self, trade, combo: str) -> None:
        """Journalise un trade clôturé puis déclenche l'analyse au palier.

        Deux try SÉPARÉS : la journalisation est la source de vérité de
        l'apprentissage et du dashboard — un échec de l'analyse (scipy absent,
        état corrompu…) ne doit jamais empêcher d'écrire le trade, sinon
        portefeuille et journal divergent (cf. forex/paper/reconcile.py).
        """
        try:
            journal.append_trade(trade, path=self.strategy.journal_path,
                                 strategy=self.id, combo=combo)
        except Exception as e:
            print(f"[forex/{self.id}] ÉCHEC JOURNALISATION ({e}) — "
                  f"lancer `python -m forex.paper.reconcile --bot {self.id} --fix`")
            return
        try:
            total = journal.count(path=self.strategy.journal_path)
            if total and total % config.FOREX_LEARN_TRADE_PALIER == 0:
                learning_loop.run_learning(
                    reason=f"palier {total} trades", do_tune=False, bots=[self.id])
        except Exception as e:
            print(f"[forex/{self.id}] apprentissage échoué : {e}")

    def write_status(self, snapshot: dict, now: datetime) -> dict:
        """Persiste l'instantané du bot et retourne son résumé (pour l'index)."""
        can, why = self.rm.can_open_trade()
        stats = self.broker.stats()
        payload = {
            "bot": self.id,
            "label": self.strategy.label,
            "description": self.strategy.description,
            "updated_at": now.isoformat(),
            "granularity": config.FOREX_GRANULARITY,
            "market_open": is_market_open(now),
            "atr_stop_mult": self.strategy.atr_stop_mult,
            "atr_tp_mult": self.strategy.atr_tp_mult,
            "risk": {
                "daily_loss_pct": round(self.rm.daily_loss_pct(), 2),
                "drawdown_pct": round(self.rm.drawdown_pct(), 2),
                "can_trade": can, "reason": why,
            },
            "portfolio": stats,
            "pairs": list(snapshot.values()),
        }
        _write_json(self.strategy.status_path, payload)
        return {"bot": self.id, "label": self.strategy.label,
                "description": self.strategy.description, **stats}


def _fetch_candles(gran: str) -> dict[str, list]:
    """
    Télécharge les bougies de toutes les paires forex ET des instruments
    cross-asset (Nasdaq, or, pétrole) UNE SEULE FOIS par cycle. Le résultat
    est partagé par tous les bots (et sert de contexte au bot macro, qui a
    besoin de la matrice complète pour calculer la force des devises) — les
    bots forex non restreints (pairs=None) restent cependant cantonnés à
    FOREX_PAIRS par _run_bot ci-dessous, malgré la présence des instruments
    cross-asset dans ce même dictionnaire.
    """
    need = max(config.MA_SLOW + 60, 300)
    out: dict[str, list] = {}
    for pair in config.FOREX_PAIRS + config.CROSSASSET_INSTRUMENTS:
        try:
            out[pair] = prices.fetch_ohlcv(pair, gran, count=need)
        except Exception as e:
            print(f"[forex] {pair}: données indisponibles ({e})")
    return out


def _retire_bot(rt: BotRuntime, candles_by_pair: dict) -> None:
    """
    Clôture silencieusement les positions ouvertes d'un bot supprimé depuis le
    dashboard, archive son cache, puis le marque comme retiré. Aucune
    notification Telegram : la suppression est une action déclenchée par
    l'utilisateur lui-même (même principe que le suivi/désuivi en copy
    trading).
    """
    for pair, pos in list(rt.broker.positions.items()):
        candles = candles_by_pair.get(pair)
        price = candles[-1][4] if candles else pos.entry_price
        trade = rt.broker.force_close(pair, price, "bot supprimé")
        if trade is not None:
            rt.journal_and_learn(trade, rt.strategy.combo_key(pos.signals or {}, pos.direction))
    try:
        remove.purge(rt.id, archive=True)
    except OSError as e:
        print(f"[forex] {rt.id} : archivage du cache échoué ({e}) — bot tout de même retiré.")
    rt.retired = True
    print(f"[forex] {rt.id} supprimé depuis le dashboard : positions clôturées, cache archivé.")


def iterate(runtimes: list[BotRuntime], events: list, *, verbose: bool = True) -> None:
    """Un cycle complet : bougies mutualisées, puis chaque bot joue sa partition."""
    now = datetime.now(timezone.utc)
    gran = config.FOREX_GRANULARITY
    bar_min = _GRAN_MINUTES.get(gran, 60)

    candles_by_pair = _fetch_candles(gran)
    if not candles_by_pair:
        print("[forex] aucune donnée disponible ce cycle")
        return

    context = {"candles_by_pair": candles_by_pair, "crossasset": crossasset.snapshot()}

    # Cache des bougies pour les graphiques du dashboard (commun aux bots).
    _write_json(CANDLES_PATH, {
        p: [[c[0], round(c[1], 5), round(c[2], 5), round(c[3], 5), round(c[4], 5)]
            for c in candles[-_CHART_CANDLES:]]
        for p, candles in candles_by_pair.items()
    })

    disabled_ids = load_disabled_bots()
    verdicts = verdict_mod.load()
    settings = load_notification_settings()
    summaries = []
    for rt in runtimes:
        if rt.id in disabled_ids:
            if not rt.retired:
                _retire_bot(rt, candles_by_pair)
            continue
        snapshot = _run_bot(rt, candles_by_pair, events, context, now, bar_min, verbose, settings,
                            verdicts)
        summaries.append(rt.write_status(snapshot, now))

    _write_json(INDEX_PATH, {"updated_at": now.isoformat(),
                             "market_open": is_market_open(now),
                             "bots": summaries})


def _run_bot(rt: BotRuntime, candles_by_pair: dict, events: list, context: dict,
             now: datetime, bar_min: int, verbose: bool,
             settings: dict | None = None, verdicts: dict | None = None) -> dict:
    """Gestion des sorties puis des entrées, pour toutes les paires d'un bot."""
    settings = settings if settings is not None else _NOTIF_DEFAULTS
    strat = rt.strategy
    snapshot: dict[str, dict] = {}

    # pairs=None signifie « tout FOREX_PAIRS », PAS « tout candles_by_pair » :
    # depuis l'ajout des instruments cross-asset (Nasdaq/or/pétrole), ce dict
    # contient aussi des paires que les bots forex non restreints ne doivent
    # jamais évaluer.
    allowed_pairs = strat.pairs if strat.pairs is not None else config.FOREX_PAIRS
    for pair, candles in candles_by_pair.items():
        # Univers restreint (ex. carry JPY-only, ou bot cross-asset
        # mono-instrument) : les autres paires n'existent simplement pas pour
        # ce bot, ni dans ses stats ni sur le dashboard.
        if pair not in allowed_pairs:
            continue
        rec = {"pair": pair, "price": None, "status": "?", "detail": ""}
        snapshot[pair] = rec
        if not candles:
            rec.update(status="no_data", detail="aucune bougie disponible")
            continue
        if len(candles) < strat.min_candles:
            rec.update(status="warmup", detail=f"{len(candles)} bougies")
            continue

        last = candles[-1]
        _, _, high, low, close, *_ = last
        ts = last[0]
        rec["price"] = round(close, 5)

        # ── Gestion d'une position ouverte ────────────────
        pos = rt.broker.position(pair)
        if pos is not None:
            if _manage_open(rt, pair, pos, high, low, close, ts, now, bar_min, rec, verbose, settings):
                continue
            continue

        # ── Recherche d'entrée ────────────────────────────
        decision = strat.evaluate(pair, now, candles, events, context=context)
        rec["reasons"] = decision.reasons
        rec["setup"] = decision.components.get("setup")
        if verbose:
            print(f"[{now:%H:%M}] {strat.id}/{pair} {close:.5f} — {decision.summary()[:80]}")
        if not decision.enter:
            rec.update(status="flat", detail=decision.summary()[:110])
            continue

        # Veto d'un setup désactivé par l'apprentissage DE CE BOT.
        combo = strat.combo_key(decision.components, decision.direction)
        if combo in state.get_disabled_combos(path=strat.state_path):
            rec.update(status="combo_disabled", detail=f"setup {combo} désactivé (apprentissage)")
            continue

        can, why = rt.rm.can_open_trade()
        if not can:
            rec.update(status="risk_block", detail=why)
            continue

        atr = indicators.atr(candles[-(config.ATR_PERIOD + 1) * 3:], config.ATR_PERIOD)
        if atr <= 0:
            rec.update(status="flat", detail="ATR nul")
            continue

        # Multiples ATR : défauts du bot, éventuellement remplacés par ceux
        # appris pour cette paire PAR CE BOT.
        ov = state.get_overrides(pair, path=strat.state_path)
        stop_mult = ov.get("atr_stop_mult", strat.atr_stop_mult)
        tp_mult = ov.get("atr_tp_mult", strat.atr_tp_mult)

        # Verdict de l'apprentissage : un bot en statut kill n'ouvre plus rien,
        # les autres statuts modulent le risque (watch = prudence, validated = normal).
        risk_mult = verdict_mod.risk_multiplier((verdicts or {}).get(strat.id))
        if risk_mult <= 0:
            rec.update(status="verdict_kill", detail="bot en statut kill — entrée refusée")
            continue
        eff_risk_pct = config.FOREX_RISK_PCT * risk_mult

        # Contrôle de levier ESMA (informationnel). Le pip est valorisé dans la
        # devise QUOTE pour éviter d'avoir besoin d'un taux croisé.
        quote_ccy = pair.split("_")[1]
        stop_pips = (stop_mult * atr) / (0.01 if pair.endswith("JPY") else 0.0001)
        units = units_from_risk(rt.broker.equity, eff_risk_pct, stop_pips,
                                pair, quote_ccy, close)
        lev = check_leverage(pair, units, close, rt.broker.equity)
        if not lev.allowed:
            rec.update(status="lev_block", detail=lev.message)
            continue

        pos = rt.broker.open_position(
            pair, decision.direction, close, atr,
            risk_pct=eff_risk_pct,
            atr_stop_mult=stop_mult, atr_tp_mult=tp_mult,
            ts=ts, event_driven=False, signals=decision.components,
            exit_mode=strat.exit_mode,
        )
        rt.rm.update_equity(rt.broker.equity, now)
        if settings["forex_mode"] == "detailed" and settings["forex_entries_enabled"]:
            _notify(*_build_entry_message(strat.id, decision.direction, pair,
                                          entry=pos.entry_price, stop=pos.stop,
                                          tp=pos.tp, strength=decision.strength))
        rec.update(status="entered", direction=decision.direction,
                   detail=f"{decision.direction} @ {pos.entry_price:.5f}",
                   position={"direction": pos.direction, "entry": round(pos.entry_price, 5),
                             "stop": round(pos.stop, 5), "tp": round(pos.tp, 5),
                             "unreal_pips": 0.0})
        if verbose:
            print(f"[{now:%H:%M}] {strat.id}/{pair} ENTRÉE {decision.direction} @ {pos.entry_price:.5f}")

    return snapshot


def _manage_open(rt: BotRuntime, pair: str, pos, high: float, low: float, close: float,
                 ts: int, now: datetime, bar_min: int, rec: dict, verbose: bool,
                 settings: dict | None = None) -> bool:
    """Gère une position ouverte. Retourne True si elle a été clôturée."""
    settings = settings if settings is not None else _NOTIF_DEFAULTS
    strat = rt.strategy
    combo = strat.combo_key(pos.signals or {}, pos.direction)

    rt.broker.update_exit_levels(pair, high, low)
    trade = rt.broker.on_bar(pair, high, low, close, ts)
    if trade is not None:
        rt.rm.update_equity(rt.broker.equity, now)
        rt.journal_and_learn(trade, combo)
        if settings["forex_mode"] == "detailed" and settings["forex_exits_enabled"]:
            _notify(*_build_exit_message(strat.id, pair, trade, rt.broker.equity))
        rec.update(status="closed", detail=f"{trade.exit_reason} · P&L {trade.pnl_pct:+.2f}%")
        if verbose:
            print(f"[{now:%H:%M}] {strat.id}/{pair} SORTIE {trade.exit_reason} "
                  f"P&L {trade.pnl_pct:+.2f}%")
        return True

    # Filet de sécurité : détention absolue maximale, pour éviter qu'une
    # position stagne indéfiniment sans toucher stop ni TP.
    held_bars = (ts - pos.entry_ts) / 1000 / 60 / max(bar_min, 1)
    if held_bars >= config.MAX_HOLD_BARS:
        trade = rt.broker.force_close(pair, close, "détention max", ts)
        rt.rm.update_equity(rt.broker.equity, now)
        rt.journal_and_learn(trade, combo)
        if settings["forex_mode"] == "detailed" and settings["forex_exits_enabled"]:
            _notify(*_build_exit_message(strat.id, pair, trade, rt.broker.equity))
        rec.update(status="closed", detail=f"détention max · P&L {trade.pnl_pct:+.2f}%")
        return True

    unreal_pips = ((close - pos.entry_price) / (0.01 if pair.endswith("JPY") else 0.0001)
                   * (1 if pos.direction == "long" else -1))
    rec.update(status="in_position", direction=pos.direction,
               detail=f"{pos.direction} @ {pos.entry_price:.5f} · {unreal_pips:+.1f} pips",
               position={"direction": pos.direction, "entry": round(pos.entry_price, 5),
                         "stop": round(pos.stop, 5), "tp": round(pos.tp, 5),
                         "unreal_pips": round(unreal_pips, 1)})
    return False


def run(once: bool = False, bots: list[str] | None = None) -> None:
    active = [strategies.get(b) for b in bots] if bots else strategies.active()
    disabled_ids = load_disabled_bots()
    if disabled_ids:
        _retire_orphaned_disabled_bots(active, disabled_ids, _fetch_candles(config.FOREX_GRANULARITY))
    active = _exclude_disabled(active, disabled_ids)
    if not active:
        print("[forex] aucun bot actif (FOREX_BOTS vide) — rien à faire.")
        return
    runtimes = [BotRuntime(s) for s in active]

    print("=" * 60)
    print("  💱 FOREX PAPER TRADING MULTI-BOTS (100 % simulé)")
    print("=" * 60)
    print("  " + config.summary())
    for rt in runtimes:
        print(f"  · {rt.id:9} {rt.strategy.label}")
        print(f"    {rt.broker.stats()}")
    print("=" * 60)
    _notify("💱 FOREX paper trading démarré",
            config.summary() + "\nBots : " + ", ".join(rt.id for rt in runtimes))

    try:
        n = cal.refresh()
        print(f"  Calendrier : {n} event(s) mis à jour")
    except Exception as e:
        print(f"  Calendrier : refresh échoué ({e})")

    last_cal_refresh = time.time()
    events = _load_events()

    # Heures de notification : cf. _RANKING_SLOTS (mode détaillé, 4x/jour) et
    # _DAILY_RECAP_SLOTS (mode récap, 3x/jour : 7h30/12h/20h).
    last_notified_slot = -1
    just_started = True
    last_daily_recap_time = datetime.now(timezone.utc)

    while True:
        try:
            if time.time() - last_cal_refresh > _CALENDAR_REFRESH_SECONDS:
                try:
                    cal.refresh()
                    events = _load_events()
                except Exception as e:
                    print(f"[forex] refresh calendrier échoué : {e}")
                last_cal_refresh = time.time()

            iterate(runtimes, events)

            # --- Notification périodique : classement (mode détaillé) ou récap ---
            settings = load_notification_settings()
            now_local = datetime.now(_PARIS_TZ)
            current_time_val = now_local.hour * 100 + now_local.minute

            action, last_notified_slot, just_started = _slot_action(
                current_time_val, settings["forex_mode"], settings["forex_ranking_enabled"],
                last_notified_slot, just_started,
            )
            if action == "ranking":
                entries = [
                    {"bot": rt.id, "ret": rt.broker.stats().get("return_pct", 0)}
                    for rt in runtimes
                ]
                _notify("📊 Point de marché Forex", _build_ranking_message(entries, now_local))
            elif action == "daily_recap":
                now_utc = datetime.now(timezone.utc)
                _notify(*_build_daily_recap_message(runtimes, last_daily_recap_time,
                                                    now_utc, now_local))
                last_daily_recap_time = now_utc
            # ----------------------------------------------

        except KeyboardInterrupt:
            print("\n👋 Runner forex arrêté.")
            break
        except Exception as e:
            print(f"[forex] erreur boucle : {e}")

        if once:
            break
        time.sleep(config.FOREX_POLL_SECONDS)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Paper trading forex multi-bots (simulé)")
    ap.add_argument("--once", action="store_true", help="Une seule itération puis sortie")
    ap.add_argument("--bots", help="Liste de bots à lancer (défaut : FOREX_BOTS)")
    args = ap.parse_args()
    run(once=args.once,
        bots=[b.strip() for b in args.bots.split(",")] if args.bots else None)
