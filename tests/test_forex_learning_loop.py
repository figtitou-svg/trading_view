"""Tests de l'orchestrateur du module 7 (forex/learning/loop.py), multi-bots."""

from forex.learning import loop, tuner


def _isolate_cache(monkeypatch, tmp_path):
    """
    `run_learning` termine désormais par `verdict.write_all()`, qui lit/écrit
    `forex/_cache/verdicts.json` et `forex/_cache/bots/<id>/...` (journal,
    portefeuille). Sans isolation, ces tests taperaient dans le VRAI cache de
    prod (et pourraient même pousser des bots dans le vrai disabled_bots.json)
    — critique car pytest tourne aussi sur la VM de prod avant restart.

    `config.FOREX_DATA_DIR` est relu à l'appel par verdict.py (via
    `_default_verdicts_path()`), donc un simple monkeypatch suffit. `BOTS_DIR`
    (forex/strategies/base.py) est un global de module relu à chaque accès à
    `Strategy.dir` — même mécanisme que dans tests/test_forex_runner.py.
    """
    from forex import config as fconfig
    from forex.strategies import base as strategies_base

    monkeypatch.setattr(fconfig, "FOREX_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(strategies_base, "BOTS_DIR", str(tmp_path / "bots"))


def test_run_learning_refreshes_only_tuned_pairs_before_combo_review(monkeypatch, tmp_path):
    """
    Ordre critique : si l'auto-tuner change les paramètres d'une paire, son
    historique simulé doit être régénéré (refresh_pair) AVANT que l'analyse
    des setups ne juge sa rentabilité — sinon on jugerait une stratégie qui
    n'est déjà plus celle réellement en vigueur.
    """
    _isolate_cache(monkeypatch, tmp_path)
    call_order = []

    def fake_propose(pair, candles, events, current, **kw):
        accepted = pair == "EUR_USD"
        return tuner.TuneProposal(
            pair, accepted, "ok" if accepted else "gate",
            changes={"atr_tp_mult": 4.0} if accepted else {},
        )

    monkeypatch.setattr(loop.prices, "fetch_ohlcv", lambda pair, gran: [1] * 10)
    monkeypatch.setattr(loop, "_events_for", lambda pair: [])
    monkeypatch.setattr(loop.tuner, "propose", fake_propose)
    monkeypatch.setattr(loop.state, "apply_param_change",
                        lambda *a, **k: call_order.append(("apply_param_change", a[0])))
    monkeypatch.setattr(loop.backfill, "refresh_pair",
                        lambda pair, *a, **k: call_order.append(("refresh_pair", pair)) or 5)
    monkeypatch.setattr(loop.backfill, "backfill_all",
                        lambda *a, **k: call_order.append(("backfill_all",)) or {})
    monkeypatch.setattr(loop, "_review_combos",
                        lambda bot: call_order.append(("review_combos", bot.id)) or [])
    monkeypatch.setattr(loop, "_notify", lambda *a, **k: None)
    monkeypatch.setattr(loop.config, "FOREX_PAIRS", ["EUR_USD", "GBP_USD"])

    loop.run_learning(reason="test", do_tune=True, notify=False, bots=["trend"])

    # EUR_USD (accepté) → refresh_pair appelé ; GBP_USD (refusé) → jamais.
    refreshed = [c[1] for c in call_order if c[0] == "refresh_pair"]
    assert refreshed == ["EUR_USD"]

    # Ordre : tuning (apply_param_change) → refresh → backfill_all → review_combos
    kinds = [c[0] for c in call_order]
    assert kinds.index("apply_param_change") < kinds.index("refresh_pair")
    assert kinds.index("refresh_pair") < kinds.index("review_combos")
    assert kinds.index("backfill_all") < kinds.index("review_combos")


def test_run_learning_without_tune_skips_backfill_and_refresh(monkeypatch, tmp_path):
    _isolate_cache(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(loop.backfill, "backfill_all", lambda *a, **k: calls.append("backfill_all") or {})
    monkeypatch.setattr(loop.backfill, "refresh_pair", lambda pair, *a, **k: calls.append("refresh_pair") or 0)
    monkeypatch.setattr(loop, "_review_combos", lambda bot: calls.append("review_combos") or [])
    monkeypatch.setattr(loop, "_notify", lambda *a, **k: None)

    loop.run_learning(reason="palier", do_tune=False, notify=False, bots=["trend"])

    assert calls == ["review_combos"]  # ni backfill ni refresh sans --tune


def test_run_learning_isolates_bots(monkeypatch, tmp_path):
    """
    Chaque bot doit être analysé dans SON périmètre : `_review_combos` reçoit
    le bot, et les chemins qu'il utilise sont ceux du bot. C'est la garantie
    qu'un setup coupé chez `trend` ne coupe rien chez `smc`.
    """
    _isolate_cache(monkeypatch, tmp_path)
    seen = []
    monkeypatch.setattr(loop, "_review_combos", lambda bot: seen.append(bot) or [])
    monkeypatch.setattr(loop, "_notify", lambda *a, **k: None)

    loop.run_learning(do_tune=False, notify=False, bots=["trend", "smc"])

    assert [b.id for b in seen] == ["trend", "smc"]
    # Journaux et états distincts → aucune contamination possible.
    assert seen[0].journal_path != seen[1].journal_path
    assert seen[0].state_path != seen[1].state_path


def test_run_learning_calls_verdict_write_all_once_with_same_bots(monkeypatch, tmp_path):
    """
    `run_learning` doit terminer par UN SEUL appel à `verdict.write_all`,
    avec la même liste de bots (mêmes ids, même ordre) que celle passée à
    `_review_combos` dans la boucle principale — sinon le portail lu par le
    runner (sizing) et l'API v2 pourrait juger un périmètre de bots différent
    de celui réellement analysé ce cycle.
    """
    _isolate_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(loop, "_review_combos", lambda bot: [])
    monkeypatch.setattr(loop, "_notify", lambda *a, **k: None)

    write_all_calls = []

    def fake_write_all(bots=None, path=None):
        write_all_calls.append(bots)
        return {"verdicts": {}}

    monkeypatch.setattr(loop.verdict, "write_all", fake_write_all)

    loop.run_learning(do_tune=False, notify=False, bots=["trend", "smc"])

    assert len(write_all_calls) == 1
    assert [b.id for b in write_all_calls[0]] == ["trend", "smc"]


def test_run_learning_scopes_kill_announcement_to_this_cycle_bots(monkeypatch, tmp_path):
    """
    `verdict.write_all` fusionne désormais avec `verdicts.json` existant (fix
    c6b531e) : `payload["verdicts"]` contient TOUS les bots jamais enregistrés,
    pas seulement ceux calculés cet appel. L'annonce "💀 verdict kill" ne doit
    porter que sur les bots réellement recalculés ce cycle — sinon un cycle
    mono-bot (palier) republierait sur Telegram le kill d'un bot déjà tué lors
    d'un cycle précédent, à chaque fois.
    """
    _isolate_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(loop, "_review_combos", lambda bot: [])
    monkeypatch.setattr(loop, "_notify", lambda *a, **k: None)

    def fake_write_all(bots=None, path=None):
        # "smc" est un kill PÉRIMÉ (persistant depuis un cycle antérieur, pas
        # recalculé ici) ; "trend" est le seul bot réellement passé ce cycle,
        # et son verdict frais n'est pas un kill.
        return {"verdicts": {
            "smc": {"status": "kill"},
            "trend": {"status": "ok"},
        }}

    monkeypatch.setattr(loop.verdict, "write_all", fake_write_all)

    changes = loop.run_learning(do_tune=False, notify=False, bots=["trend"])

    assert not any("💀 verdict kill" in c for c in changes)
    assert not any("smc" in c for c in changes)


def test_run_learning_swallows_verdict_write_all_errors(monkeypatch, tmp_path):
    """
    Une panne d'écriture des verdicts (disque plein, cache corrompu...) ne
    doit jamais faire planter tout le cycle d'apprentissage — le portail
    verdicts est un plus, pas une dépendance dure des combos/tuning.
    """
    _isolate_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(loop, "_review_combos", lambda bot: [])
    monkeypatch.setattr(loop, "_notify", lambda *a, **k: None)

    def boom(bots=None, path=None):
        raise RuntimeError("disque plein")

    monkeypatch.setattr(loop.verdict, "write_all", boom)

    changes = loop.run_learning(do_tune=False, notify=False, bots=["trend"])

    assert changes == []  # ne propage pas l'exception, ne casse pas le cycle
