"""Tests du runner de paper trading (forex/paper/runner.py) — filtrage par bot."""

import json
import os
from datetime import datetime, timezone

import pytest

from forex.paper.runner import BotRuntime, _build_ranking_message, _run_bot
from forex.paper import runner
from forex.strategies.base import Strategy, StrategyDecision
from services import notification_settings as ns


class _JpyOnlyBot(Strategy):
    """Bot factice restreint aux paires JPY, pour tester le filtrage runner."""

    id = "jpy-only-test-bot"
    label = "Bot de test JPY-only"
    min_candles = 1
    pairs = ["USD_JPY"]

    def decide(self, pair, now, candles, events, context=None):
        return StrategyDecision.no("bot de test — jamais d'entrée")


def _flat(n=5, price=1.10):
    return [[i * 3600_000, price, price, price, price, 0.0] for i in range(n)]


def test_run_bot_only_evaluates_its_restricted_pairs(tmp_path, monkeypatch):
    from forex.strategies import base as strategies_base

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))
    strat = _JpyOnlyBot()
    rt = BotRuntime(strat)
    candles_by_pair = {"EUR_USD": _flat(), "USD_JPY": _flat()}
    now = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)

    snapshot = _run_bot(rt, candles_by_pair, [], {}, now, 60, verbose=False)

    assert set(snapshot) == {"USD_JPY"}


def test_run_bot_evaluates_all_pairs_when_unrestricted(tmp_path, monkeypatch):
    from forex.strategies import base as strategies_base

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))

    class _AnyPairBot(_JpyOnlyBot):
        id = "any-pair-test-bot"
        pairs = None

    strat = _AnyPairBot()
    rt = BotRuntime(strat)
    candles_by_pair = {"EUR_USD": _flat(), "USD_JPY": _flat()}
    now = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)

    snapshot = _run_bot(rt, candles_by_pair, [], {}, now, 60, verbose=False)

    assert set(snapshot) == {"EUR_USD", "USD_JPY"}


def test_run_bot_unrestricted_bot_ignores_crossasset_instruments(tmp_path, monkeypatch):
    """
    Régression : ajouter des instruments cross-asset (Nasdaq/or/pétrole) à
    candles_by_pair ne doit PAS faire évaluer un bot forex non restreint
    (pairs=None) sur ces instruments — seuls les bots qui les nomment
    explicitement dans `pairs` doivent les voir.
    """
    from forex.strategies import base as strategies_base

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))

    class _AnyPairBot(_JpyOnlyBot):
        id = "any-pair-crossasset-test-bot"
        pairs = None

    strat = _AnyPairBot()
    rt = BotRuntime(strat)
    candles_by_pair = {"EUR_USD": _flat(), "USD_JPY": _flat(), "NDX_USD": _flat()}
    now = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)

    snapshot = _run_bot(rt, candles_by_pair, [], {}, now, 60, verbose=False)

    assert set(snapshot) == {"EUR_USD", "USD_JPY"}


def test_run_bot_evaluates_its_restricted_crossasset_pair(tmp_path, monkeypatch):
    """
    Symétrique du test d'isolation ci-dessus : un bot restreint à un
    instrument cross-asset (ex. XAU_USD) doit bien l'évaluer quand il est
    présent dans candles_by_pair.
    """
    from forex.strategies import base as strategies_base

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))

    class _GoldOnlyBot(_JpyOnlyBot):
        id = "gold-only-test-bot"
        pairs = ["XAU_USD"]

    strat = _GoldOnlyBot()
    rt = BotRuntime(strat)
    candles_by_pair = {"EUR_USD": _flat(), "USD_JPY": _flat(), "XAU_USD": _flat()}
    now = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)

    snapshot = _run_bot(rt, candles_by_pair, [], {}, now, 60, verbose=False)

    assert set(snapshot) == {"XAU_USD"}


def test_run_bot_handles_empty_candle_list_without_crashing(tmp_path, monkeypatch):
    """
    Un bot avec min_candles=0 (ex. News Sniper, qui n'a pas besoin d'historique
    de prix) ne doit pas planter si prices.fetch_ohlcv renvoie [] pour une paire
    (trou de données / rate-limit) : `len([]) < 0` est toujours False, donc le
    garde-fou warmup seul ne suffit pas — il faut un garde-fou "pas de bougies"
    explicite avant tout accès à candles[-1].
    """
    from forex.strategies import base as strategies_base

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))

    class _ZeroCandlesBot(_JpyOnlyBot):
        id = "zero-candles-test-bot"
        min_candles = 0
        pairs = None

    strat = _ZeroCandlesBot()
    rt = BotRuntime(strat)
    candles_by_pair = {"EUR_USD": [], "USD_JPY": _flat()}
    now = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)

    snapshot = _run_bot(rt, candles_by_pair, [], {}, now, 60, verbose=False)

    assert snapshot["EUR_USD"]["status"] == "no_data"
    assert snapshot["EUR_USD"]["price"] is None
    assert snapshot["USD_JPY"]["status"] != "no_data"


def test_build_ranking_message_keeps_only_top_5_sorted_desc():
    entries = [
        {"bot": "a", "ret": 1.0},
        {"bot": "b", "ret": 5.0},
        {"bot": "c", "ret": -2.0},
        {"bot": "d", "ret": 3.0},
        {"bot": "e", "ret": 0.5},
        {"bot": "f", "ret": 4.0},
    ]
    now_local = datetime(2026, 7, 21, 18, 0)

    msg = _build_ranking_message(entries, now_local)

    order = [line.split("*")[1] for line in msg.splitlines() if "*" in line and "Top" not in line]
    assert order == ["b", "f", "d", "a", "e"]
    assert "c" not in msg  # 6e bot (pire retour) exclu du top 5


def test_build_ranking_message_uses_medals_for_top_3_and_no_technical_detail():
    entries = [
        {"bot": "gold", "ret": 5.0},
        {"bot": "silver", "ret": 3.0},
        {"bot": "bronze", "ret": 1.0},
        {"bot": "fourth", "ret": -1.0},
    ]
    now_local = datetime(2026, 7, 21, 13, 0)

    msg = _build_ranking_message(entries, now_local)

    assert "🥇 *gold* : +5.00%" in msg
    assert "🥈 *silver* : +3.00%" in msg
    assert "🥉 *bronze* : +1.00%" in msg
    assert "4. *fourth* : -1.00%" in msg
    assert "Top 4 bots forex (13:00)" in msg
    # Pas de détails techniques : ni win rate, ni nombre de trades, ni equity
    assert "Win" not in msg
    assert "trades" not in msg
    assert "€" not in msg


from forex.paper.runner import _build_entry_message, _build_exit_message
from forex.paper.broker import PaperTrade


def test_build_entry_message_has_no_reasons():
    title, body = _build_entry_message("trend", "long", "EUR_USD",
                                       entry=1.10500, stop=1.10000, tp=1.11500, strength=0.72)
    assert title == "🔵 TREND ENTRÉE LONG EUR_USD"
    assert body == "@ 1.10500 · stop 1.10000 · TP 1.11500 · force 0.72"


def _trade(pnl, exit_reason, adjusted=False):
    return PaperTrade(pair="EUR_USD", direction="long", entry_ts=0, exit_ts=1,
                      entry_price=1.1000, exit_price=1.1100, net_pips=30.0,
                      pnl=pnl, pnl_pct=1.5, exit_reason=exit_reason,
                      event_driven=False, adjusted=adjusted)


def test_build_exit_message_green_on_profit():
    title, body = _build_exit_message("trend", "EUR_USD", _trade(50.0, "take-profit"), equity=10050.0)
    assert title.startswith("🟢")
    assert "(ajusté)" not in body


def test_build_exit_message_red_on_loss():
    title, _ = _build_exit_message("trend", "EUR_USD", _trade(-30.0, "stop-loss"), equity=9970.0)
    assert title.startswith("🔴")


def test_build_exit_message_notes_sl_adjusted():
    title, body = _build_exit_message("trend", "EUR_USD", _trade(20.0, "stop-loss", adjusted=True), equity=10020.0)
    assert title == "🟢 TREND SORTIE EUR_USD"
    assert body == "stop-loss (SL ajusté) @ 1.11000\nP&L +20.00 (+1.50%) · equity 10020.00"


def test_build_exit_message_notes_tp_adjusted():
    _, body = _build_exit_message("trend", "EUR_USD", _trade(50.0, "take-profit", adjusted=True), equity=10050.0)
    assert "(TP ajusté)" in body


def test_run_bot_threads_strategy_exit_mode_into_opened_position(tmp_path, monkeypatch):
    """
    exit_mode=strat.exit_mode doit être transmis à open_position() — sans ça,
    les variantes SL/TP dynamique (macro__trailing, etc.) tradent silencieusement
    en mode "static" malgré leur exit_mode déclaré.
    """
    from forex.strategies import base as strategies_base

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))

    class _AlwaysEnterBot(Strategy):
        id = "always-enter-test-bot"
        label = "Bot de test qui entre toujours"
        min_candles = 1
        exit_mode = "trailing"

        def decide(self, pair, now, candles, events, context=None):
            return StrategyDecision(True, "long", 0.9, ["test"], {})

    strat = _AlwaysEnterBot()
    rt = BotRuntime(strat)
    # _flat() a un ATR nul (bougies identiques) : `_run_bot` refuse alors toute
    # entrée ("ATR nul") avant même d'atteindre `open_position`, ce qui ne
    # permettrait pas de vérifier le câblage de `exit_mode`. On donne donc un
    # léger mouvement de prix pour obtenir un ATR strictement positif.
    candles_by_pair = {"EUR_USD": [
        [i * 3600_000, 1.10 + (i % 5) * 0.0002, 1.10 + (i % 5) * 0.0002 + 0.0003,
         1.10 + (i % 5) * 0.0002 - 0.0003, 1.10 + (i % 5) * 0.0002, 0.0]
        for i in range(400)
    ]}
    now = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)

    _run_bot(rt, candles_by_pair, [], {"candles_by_pair": candles_by_pair, "crossasset": {}},
            now, 60, verbose=False)

    pos = rt.broker.position("EUR_USD")
    assert pos is not None
    assert pos.exit_mode == "trailing"


# ── Verdict de l'apprentissage : modulation du sizing / veto kill ──────

class _AlwaysEnterBot(Strategy):
    id = "always-enter-verdict-test-bot"
    label = "Bot de test qui entre toujours (verdict)"
    min_candles = 1

    def decide(self, pair, now, candles, events, context=None):
        return StrategyDecision(True, "long", 0.9, ["test"], {})


def _moving_candles(n=400):
    # ATR nul avec _flat() empêcherait toute entrée avant même le sizing.
    return [
        [i * 3600_000, 1.10 + (i % 5) * 0.0002, 1.10 + (i % 5) * 0.0002 + 0.0003,
         1.10 + (i % 5) * 0.0002 - 0.0003, 1.10 + (i % 5) * 0.0002, 0.0]
        for i in range(n)
    ]


def test_run_bot_applies_watch_risk_multiplier_to_sizing(tmp_path, monkeypatch):
    """Un bot en statut 'watch' (risk_mult 0.5) ouvre une position à risque réduit."""
    from forex.strategies import base as strategies_base
    from forex import config

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))
    strat = _AlwaysEnterBot()
    rt = BotRuntime(strat)
    candles_by_pair = {"EUR_USD": _moving_candles()}
    now = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)
    verdicts = {strat.id: {"status": "watch", "risk_mult": 0.5}}

    _run_bot(rt, candles_by_pair, [], {"candles_by_pair": candles_by_pair, "crossasset": {}},
            now, 60, verbose=False, verdicts=verdicts)

    pos = rt.broker.position("EUR_USD")
    assert pos is not None
    assert pos.risk_pct == pytest.approx(config.FOREX_RISK_PCT * 0.5)


def test_run_bot_never_opens_when_verdict_kill(tmp_path, monkeypatch):
    """Un bot en statut 'kill' (risk_mult 0) n'ouvre jamais de position."""
    from forex.strategies import base as strategies_base

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))
    strat = _AlwaysEnterBot()
    rt = BotRuntime(strat)
    candles_by_pair = {"EUR_USD": _moving_candles()}
    now = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)
    verdicts = {strat.id: {"status": "kill", "risk_mult": 0.0}}

    snapshot = _run_bot(rt, candles_by_pair, [], {"candles_by_pair": candles_by_pair, "crossasset": {}},
                        now, 60, verbose=False, verdicts=verdicts)

    assert rt.broker.position("EUR_USD") is None
    assert snapshot["EUR_USD"]["status"] == "verdict_kill"


# ── Suppression d'un bot depuis le dashboard ──────────────

def test_load_disabled_bots_reads_existing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "DISABLED_BOTS_PATH", str(tmp_path / "disabled_bots.json"))
    with open(runner.DISABLED_BOTS_PATH, "w", encoding="utf-8") as f:
        json.dump(["macro__trailing", "channel_breakout"], f)
    assert runner.load_disabled_bots() == {"macro__trailing", "channel_breakout"}


def test_load_disabled_bots_returns_empty_set_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "DISABLED_BOTS_PATH", str(tmp_path / "does_not_exist.json"))
    assert runner.load_disabled_bots() == set()


def test_exclude_disabled_filters_by_id():
    class _Fake:
        def __init__(self, id_):
            self.id = id_

    active = [_Fake("a"), _Fake("b"), _Fake("c")]
    result = runner._exclude_disabled(active, {"b"})
    assert [s.id for s in result] == ["a", "c"]


def test_retire_bot_closes_position_silently_and_archives(tmp_path, monkeypatch):
    from forex.strategies import base as strategies_base
    import forex.strategies.remove as remove_module

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))

    notified = []
    monkeypatch.setattr(runner, "_notify", lambda *a, **k: notified.append((a, k)))
    purged = []
    monkeypatch.setattr(remove_module, "purge",
                        lambda bot_id, archive=False: purged.append((bot_id, archive)))

    strat = _JpyOnlyBot()
    rt = runner.BotRuntime(strat)
    rt.broker.open_position("USD_JPY", "long", 150.00, 0.10, spread_pips=0.0, slippage_pips=0.0)
    assert rt.broker.has_position("USD_JPY")

    candles_by_pair = {"USD_JPY": _flat(5, price=151.00)}
    runner._retire_bot(rt, candles_by_pair)

    assert not rt.broker.has_position("USD_JPY")
    assert rt.retired is True
    assert notified == []
    assert purged == [(strat.id, True)]


def test_retire_bot_with_no_open_position_still_archives(tmp_path, monkeypatch):
    from forex.strategies import base as strategies_base
    import forex.strategies.remove as remove_module

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))
    purged = []
    monkeypatch.setattr(remove_module, "purge",
                        lambda bot_id, archive=False: purged.append((bot_id, archive)))

    strat = _JpyOnlyBot()
    rt = runner.BotRuntime(strat)

    runner._retire_bot(rt, {})

    assert rt.retired is True
    assert purged == [(strat.id, True)]


def test_iterate_excludes_disabled_bot_from_index_and_retires_once(tmp_path, monkeypatch):
    from forex.strategies import base as strategies_base
    import forex.strategies.remove as remove_module

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))
    monkeypatch.setattr(runner, "CANDLES_PATH", str(tmp_path / "candles.json"))
    monkeypatch.setattr(runner, "INDEX_PATH", str(tmp_path / "index.json"))
    monkeypatch.setattr(runner, "DISABLED_BOTS_PATH", str(tmp_path / "disabled_bots.json"))
    monkeypatch.setattr(runner, "_fetch_candles",
                        lambda gran: {"USD_JPY": _flat(400, price=151.0)})
    monkeypatch.setattr(runner.crossasset, "snapshot", lambda: {})
    purged = []
    monkeypatch.setattr(remove_module, "purge",
                        lambda bot_id, archive=False: purged.append(bot_id))

    strat = _JpyOnlyBot()
    rt = runner.BotRuntime(strat)
    with open(runner.DISABLED_BOTS_PATH, "w", encoding="utf-8") as f:
        json.dump([strat.id], f)

    runner.iterate([rt], [], verbose=False)

    assert rt.retired is True
    assert purged == [strat.id]
    with open(runner.INDEX_PATH, encoding="utf-8") as f:
        index = json.load(f)
    assert index["bots"] == []          # le bot supprimé n'apparaît plus

    # Second cycle : ne doit pas re-tenter l'archivage.
    runner.iterate([rt], [], verbose=False)
    assert purged == [strat.id]


def test_retire_bot_sets_retired_even_if_archive_fails(tmp_path, monkeypatch):
    from forex.strategies import base as strategies_base
    import forex.strategies.remove as remove_module

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))

    def _boom(bot_id, archive=False):
        raise OSError("dossier verrouillé (simulation)")

    monkeypatch.setattr(remove_module, "purge", _boom)

    strat = _JpyOnlyBot()
    rt = runner.BotRuntime(strat)

    runner._retire_bot(rt, {})

    assert rt.retired is True   # le bot est quand même marqué retiré malgré l'échec d'archivage


def test_retire_orphaned_disabled_bots_archives_not_yet_retired_bot(tmp_path, monkeypatch):
    from forex.strategies import base as strategies_base
    import forex.strategies.remove as remove_module

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))
    purged = []
    monkeypatch.setattr(remove_module, "purge",
                        lambda bot_id, archive=False: purged.append(bot_id))

    strat = _JpyOnlyBot()
    strat.ensure_dir()  # simule un dossier de cache déjà existant (jamais archivé)

    runner._retire_orphaned_disabled_bots([strat], {strat.id}, {})

    assert purged == [strat.id]


def test_retire_orphaned_disabled_bots_skips_already_archived_bot(tmp_path, monkeypatch):
    from forex.strategies import base as strategies_base
    import forex.strategies.remove as remove_module

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))
    purged = []
    monkeypatch.setattr(remove_module, "purge",
                        lambda bot_id, archive=False: purged.append(bot_id))

    strat = _JpyOnlyBot()
    # Ne PAS appeler ensure_dir() : simule un bot déjà archivé lors d'un run précédent.

    runner._retire_orphaned_disabled_bots([strat], {strat.id}, {})

    assert purged == []  # rien à refaire, aucun dossier recréé


def test_retire_orphaned_disabled_bots_ignores_non_disabled_bots(tmp_path, monkeypatch):
    from forex.strategies import base as strategies_base
    import forex.strategies.remove as remove_module

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))
    purged = []
    monkeypatch.setattr(remove_module, "purge",
                        lambda bot_id, archive=False: purged.append(bot_id))

    strat = _JpyOnlyBot()
    strat.ensure_dir()

    runner._retire_orphaned_disabled_bots([strat], set(), {})  # pas désactivé

    assert purged == []
    assert os.path.isdir(strat.dir)  # dossier intact, jamais touché


def test_retire_orphaned_disabled_bots_closes_open_position_at_current_price_not_entry_price(
    tmp_path, monkeypatch
):
    from forex.strategies import base as strategies_base
    import forex.strategies.remove as remove_module

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))
    monkeypatch.setattr(remove_module, "purge", lambda bot_id, archive=False: None)

    strat = _JpyOnlyBot()
    rt = runner.BotRuntime(strat)
    rt.broker.open_position("USD_JPY", "long", 150.00, 0.10, spread_pips=0.0, slippage_pips=0.0)
    assert rt.broker.has_position("USD_JPY")

    # Le marché a bougé pendant que le processus était arrêté : le prix
    # courant (151.50) est très différent du prix d'entrée (~150.00).
    candles_by_pair = {"USD_JPY": _flat(5, price=151.50)}
    runner._retire_orphaned_disabled_bots([strat], {strat.id}, candles_by_pair)

    # `_retire_orphaned_disabled_bots` clôture via un NOUVEAU BotRuntime (donc
    # un nouveau PaperBroker) : il partage le même fichier de persistance
    # (`strat.portfolio_path`) que `rt.broker`, mais pas le même état en
    # mémoire. On recharge `rt.broker` depuis le disque pour observer la
    # clôture effectivement écrite.
    rt.broker.load()

    assert not rt.broker.has_position("USD_JPY")
    closed_trade = rt.broker.trades[-1]
    assert closed_trade.exit_price == pytest.approx(151.50, abs=0.01)


# ── Réglages de notification (onglet Paramètres) ──────────

class _AlwaysEnterBot(Strategy):
    """Bot factice qui entre toujours, pour tester le filtrage des notifs."""

    id = "always-enter-notif-test-bot"
    label = "Bot de test qui entre toujours"
    min_candles = 1

    def decide(self, pair, now, candles, events, context=None):
        return StrategyDecision(True, "long", 0.9, ["test"], {})


def _moving_candles(n=400):
    """
    Bougies avec un léger mouvement de prix (ATR > 0) : `_flat()` a un ATR nul
    (bougies identiques), ce qui fait échouer toute entrée ("ATR nul") avant
    même d'atteindre `open_position` — cf. le commentaire équivalent dans
    `test_run_bot_threads_strategy_exit_mode_into_opened_position`.
    """
    return [
        [i * 3600_000, 1.10 + (i % 5) * 0.0002, 1.10 + (i % 5) * 0.0002 + 0.0003,
         1.10 + (i % 5) * 0.0002 - 0.0003, 1.10 + (i % 5) * 0.0002, 0.0]
        for i in range(n)
    ]


def test_run_bot_skips_entry_notification_when_disabled(tmp_path, monkeypatch):
    from forex.strategies import base as strategies_base

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))
    notified = []
    monkeypatch.setattr(runner, "_notify", lambda *a, **k: notified.append(a))

    strat = _AlwaysEnterBot()
    rt = runner.BotRuntime(strat)
    candles_by_pair = {"EUR_USD": _moving_candles()}
    now = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)
    settings = {**ns.DEFAULTS, "forex_entries_enabled": False}

    runner._run_bot(rt, candles_by_pair, [], {"candles_by_pair": candles_by_pair, "crossasset": {}},
                    now, 60, verbose=False, settings=settings)

    assert notified == []
    assert rt.broker.has_position("EUR_USD")  # l'entrée a bien eu lieu, juste pas notifiée


def test_run_bot_sends_entry_notification_by_default(tmp_path, monkeypatch):
    from forex.strategies import base as strategies_base

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))
    notified = []
    monkeypatch.setattr(runner, "_notify", lambda *a, **k: notified.append(a))

    strat = _AlwaysEnterBot()
    strat.id = "always-enter-notif-test-bot-2"
    rt = runner.BotRuntime(strat)
    candles_by_pair = {"EUR_USD": _moving_candles()}
    now = datetime(2026, 7, 15, 14, tzinfo=timezone.utc)

    runner._run_bot(rt, candles_by_pair, [], {"candles_by_pair": candles_by_pair, "crossasset": {}},
                    now, 60, verbose=False)  # settings=None → défauts (tout activé)

    assert len(notified) == 1


def test_manage_open_skips_exit_notification_when_disabled(tmp_path, monkeypatch):
    from forex.strategies import base as strategies_base

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))
    notified = []
    monkeypatch.setattr(runner, "_notify", lambda *a, **k: notified.append(a))

    strat = _JpyOnlyBot()
    rt = runner.BotRuntime(strat)
    pos = rt.broker.open_position("USD_JPY", "long", 150.00, 0.10, spread_pips=0.0, slippage_pips=0.0)
    rec = {"pair": "USD_JPY"}
    settings = {**ns.DEFAULTS, "forex_exits_enabled": False}

    closed = runner._manage_open(rt, "USD_JPY", pos, high=pos.tp + 1e-3, low=1.0, close=pos.tp,
                                 ts=pos.entry_ts + 3_600_000,
                                 now=datetime(2026, 7, 15, 15, tzinfo=timezone.utc),
                                 bar_min=60, rec=rec, verbose=False, settings=settings)

    assert closed is True
    assert notified == []


def test_manage_open_sends_exit_notification_by_default(tmp_path, monkeypatch):
    from forex.strategies import base as strategies_base

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))
    notified = []
    monkeypatch.setattr(runner, "_notify", lambda *a, **k: notified.append(a))

    strat = _JpyOnlyBot()
    strat.id = "jpy-only-test-bot-notif-default"
    rt = runner.BotRuntime(strat)
    pos = rt.broker.open_position("USD_JPY", "long", 150.00, 0.10, spread_pips=0.0, slippage_pips=0.0)
    rec = {"pair": "USD_JPY"}

    closed = runner._manage_open(rt, "USD_JPY", pos, high=pos.tp + 1e-3, low=1.0, close=pos.tp,
                                 ts=pos.entry_ts + 3_600_000,
                                 now=datetime(2026, 7, 15, 15, tzinfo=timezone.utc),
                                 bar_min=60, rec=rec, verbose=False)  # settings=None → défauts

    assert closed is True
    assert len(notified) == 1


def test_build_daily_recap_message_aggregates_entries_exits_and_pnl(tmp_path, monkeypatch):
    from forex.strategies import base as strategies_base

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))
    strat = _JpyOnlyBot()
    strat.id = "jpy-only-test-bot-recap"
    rt = runner.BotRuntime(strat)
    since = datetime(2026, 7, 15, 0, tzinfo=timezone.utc)

    entry_ts = int(datetime(2026, 7, 15, 10, tzinfo=timezone.utc).timestamp() * 1000)
    pos = rt.broker.open_position("USD_JPY", "long", 150.00, 0.10, spread_pips=0.0,
                                  slippage_pips=0.0, ts=entry_ts)
    exit_ts = int(datetime(2026, 7, 15, 12, tzinfo=timezone.utc).timestamp() * 1000)
    # low reste au-dessus du stop pour que ce soit bien le TP qui soit touché
    # (on_bar teste le stop en premier : un low trop bas déclencherait un
    # stop-loss même si high dépasse le TP).
    trade = rt.broker.on_bar("USD_JPY", high=pos.tp + 1e-3, low=pos.entry_price, close=pos.tp, ts=exit_ts)
    assert trade is not None and trade.pnl > 0

    until = datetime(2026, 7, 15, 22, tzinfo=timezone.utc)
    title, body = runner._build_daily_recap_message([rt], since, until, datetime(2026, 7, 15, 22, 0))

    assert "Récap" in title
    assert "1 entrée" in body
    assert "1 gain" in body
    assert "0 perte" in body
    assert f"{trade.pnl:+.2f}" in body


def test_build_daily_recap_message_counts_still_open_position_as_an_entry(tmp_path, monkeypatch):
    from forex.strategies import base as strategies_base

    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path))
    strat = _JpyOnlyBot()
    strat.id = "jpy-only-test-bot-recap-open"
    rt = runner.BotRuntime(strat)
    since = datetime(2026, 7, 15, 0, tzinfo=timezone.utc)
    entry_ts = int(datetime(2026, 7, 15, 10, tzinfo=timezone.utc).timestamp() * 1000)
    rt.broker.open_position("USD_JPY", "long", 150.00, 0.10, spread_pips=0.0,
                            slippage_pips=0.0, ts=entry_ts)

    until = datetime(2026, 7, 15, 22, tzinfo=timezone.utc)
    _, body = runner._build_daily_recap_message([rt], since, until, datetime(2026, 7, 15, 22, 0))

    assert "1 entrée" in body
    assert "0 gain" in body and "0 perte" in body  # toujours ouverte, pas encore un gain/une perte


def test_scheduled_notification_slots_use_paris_time_regardless_of_system_tz():
    """Le serveur de prod tourne en UTC (Etc/UTC) — les créneaux 07h30/13h/18h/22h
    doivent rester basés sur l'heure de Paris (avec bascule été/hiver automatique),
    pas sur le fuseau système, sous peine de décalage silencieux de 1h à 2h."""
    now_paris = datetime.now(runner._PARIS_TZ)
    assert now_paris.tzinfo is not None
    assert getattr(now_paris.tzinfo, "key", None) == "Europe/Paris"
    # Vérifie que ce n'est pas juste un alias d'UTC : l'offset doit être +1h (CET)
    # ou +2h (CEST), jamais 0.
    assert now_paris.utcoffset().total_seconds() in (3600, 7200)


# ── _slot_action : créneaux de notification (classement / récap) ──

def test_slot_action_ranking_fires_at_each_of_the_four_slots():
    """Mode détaillé : les 4 créneaux historiques (730/1300/1800/2200) sont
    inchangés — le nouveau code ne doit rien changer à ce comportement."""
    last_slot, started = -1, False  # déjà passé le tout premier lancement
    for slot in (730, 1300, 1800, 2200):
        action, last_slot, started = runner._slot_action(slot, "detailed", True, last_slot, started)
        assert action == "ranking"
        assert last_slot == slot


def test_slot_action_ranking_disabled_produces_no_action():
    action, last_slot, started = runner._slot_action(1300, "detailed", False, 730, False)
    assert action is None
    assert last_slot == 1300  # l'état avance quand même, juste pas de notif


def test_slot_action_daily_recap_fires_at_730_1200_and_2000():
    """Nouveau planning du récap : 3 notifs/jour à 7h30, 12h et 20h."""
    last_slot, started = -1, False
    fired = []
    for slot in (730, 1200, 2000):
        action, last_slot, started = runner._slot_action(slot, "daily_recap", True, last_slot, started)
        fired.append(action)
        assert last_slot == slot
    assert fired == ["daily_recap", "daily_recap", "daily_recap"]


def test_slot_action_daily_recap_does_not_refire_between_its_own_slots():
    """Entre deux créneaux du récap (12h et 20h), rester dans la même
    fenêtre horaire ne doit pas redéclencher — les anciens créneaux
    'classement' de 13h/18h n'ont aucun effet en mode daily_recap."""
    action, last_slot, started = runner._slot_action(1200, "daily_recap", True, -1, False)
    assert action == "daily_recap"
    assert last_slot == 1200

    action, last_slot, started = runner._slot_action(1300, "daily_recap", True, last_slot, started)
    assert action is None
    action, last_slot, started = runner._slot_action(1800, "daily_recap", True, last_slot, started)
    assert action is None

    action, last_slot, started = runner._slot_action(2000, "daily_recap", True, last_slot, started)
    assert action == "daily_recap"


def test_slot_action_suppresses_only_the_very_first_notification_after_startup():
    """Lancement du script en cours de journée (ex. 15h) : le créneau déjà
    passé (1300) ne doit pas déclencher de notif rétroactive, mais l'état
    doit quand même avancer pour que le créneau suivant (1800) notifie."""
    action, last_slot, started = runner._slot_action(1500, "detailed", True, -1, True)
    assert action is None  # rien envoyé au lancement
    assert started is False
    assert last_slot == 1300  # créneau déjà passé enregistré sans notifier

    action, last_slot, started = runner._slot_action(1800, "detailed", True, last_slot, started)
    assert action == "ranking"  # le créneau suivant notifie normalement


def test_slot_action_fixed_bug_first_slot_of_each_new_day_now_notifies():
    """Régression du bug historique : avant le correctif, le reset quotidien
    remettait last_notified_slot à -1 juste avant 7h30, ce qui refaisait
    croire à un 'tout premier lancement' et supprimait silencieusement la
    notif du premier créneau CHAQUE jour (pas seulement au lancement du
    script). Ici, `just_started` est déjà False (script tourne depuis la
    veille) : le 7h30 du nouveau jour doit donc bien notifier."""
    # Fin de journée précédente : dernier créneau (2200) déjà notifié.
    last_slot, started = 2200, False
    # Passage nocturne avant 7h30 : le reset doit ramener last_slot à -1
    # sans jamais mettre started à True.
    action, last_slot, started = runner._slot_action(300, "daily_recap", True, last_slot, started)
    assert action is None
    assert last_slot == -1
    assert started is False

    # 7h30 du nouveau jour : doit notifier (c'est le bug corrigé).
    action, last_slot, started = runner._slot_action(730, "daily_recap", True, last_slot, started)
    assert action == "daily_recap"
    assert last_slot == 730


def test_slot_action_switching_mode_mid_day_does_not_crash_or_double_fire():
    """Changer de mode (dans les réglages) entre deux cycles ne doit pas
    planter ni renvoyer une notif en double pour un créneau déjà traité."""
    action, last_slot, started = runner._slot_action(730, "detailed", True, -1, False)
    assert action == "ranking"
    assert last_slot == 730

    # Bascule vers daily_recap : 730 est un créneau commun aux deux jeux,
    # donc déjà égal à last_notified_slot -> pas de re-déclenchement.
    action, last_slot, started = runner._slot_action(730, "daily_recap", True, last_slot, started)
    assert action is None
    assert last_slot == 730

    # Le créneau récap suivant (1200) déclenche normalement.
    action, last_slot, started = runner._slot_action(1200, "daily_recap", True, last_slot, started)
    assert action == "daily_recap"
