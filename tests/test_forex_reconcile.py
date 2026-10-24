"""Réconciliation portefeuille ↔ journal (source unique de vérité)."""
import json
import os

from forex.paper import reconcile


def _write_portfolio(path, trades, start=10000.0):
    equity = start + sum(t["pnl"] for t in trades)
    payload = {"start_equity": start, "equity": equity, "peak_equity": max(start, equity),
               "positions": {}, "trades": trades, "updated_at": "2026-07-27T00:00:00+00:00"}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def _trade(pair="EUR_USD", entry_ts=1000, pnl=50.0):
    return {"pair": pair, "direction": "long", "entry_ts": entry_ts,
            "exit_ts": entry_ts + 3600_000, "entry_price": 1.1, "exit_price": 1.11,
            "net_pips": 10.0, "pnl": pnl, "pnl_pct": pnl / 100, "exit_reason": "take-profit",
            "event_driven": False, "signals": {}, "adjusted": False}


def test_check_detects_missing_journal_trades(tmp_path):
    pf = str(tmp_path / "paper_portfolio.json")
    jn = str(tmp_path / "trade_journal.jsonl")
    _write_portfolio(pf, [_trade(entry_ts=1000), _trade(entry_ts=2000, pnl=-30.0)])
    # Journal vide : les 2 trades live manquent.
    report = reconcile.check(portfolio_path=pf, journal_path=jn)
    assert report["consistent"] is False
    assert report["missing_in_journal"] == 2
    assert abs(report["equity_gap"] - 20.0) < 0.01   # 50 - 30 non journalisés


def test_fix_restores_invariant(tmp_path):
    pf = str(tmp_path / "paper_portfolio.json")
    jn = str(tmp_path / "trade_journal.jsonl")
    _write_portfolio(pf, [_trade(entry_ts=1000), _trade(entry_ts=2000, pnl=-30.0)])
    fixed = reconcile.fix(portfolio_path=pf, journal_path=jn, strategy_id="testbot")
    assert fixed == 2
    report = reconcile.check(portfolio_path=pf, journal_path=jn)
    assert report["consistent"] is True
    # Idempotent : refaire fix n'ajoute rien.
    assert reconcile.fix(portfolio_path=pf, journal_path=jn, strategy_id="testbot") == 0


def test_check_ok_when_aligned(tmp_path):
    pf = str(tmp_path / "paper_portfolio.json")
    jn = str(tmp_path / "trade_journal.jsonl")
    _write_portfolio(pf, [_trade(entry_ts=1000)])
    reconcile.fix(portfolio_path=pf, journal_path=jn, strategy_id="testbot")
    report = reconcile.check(portfolio_path=pf, journal_path=jn)
    assert report["consistent"] is True
    assert report["missing_in_journal"] == 0


def test_check_corrupted_portfolio_json(tmp_path):
    """Portfolio JSON corrompu (ou pas du JSON) → available=False, consistent=True."""
    pf = str(tmp_path / "paper_portfolio.json")
    jn = str(tmp_path / "trade_journal.jsonl")
    with open(pf, "w", encoding="utf-8") as f:
        f.write("{pas du json valide")
    report = reconcile.check(portfolio_path=pf, journal_path=jn)
    assert report["available"] is False
    assert report["consistent"] is True
    assert report["missing_in_journal"] == 0
    assert report["extra_in_journal"] == 0


def test_check_portfolio_json_is_list_not_dict(tmp_path):
    """Portfolio JSON valide mais qui n'est pas un dict (ex. liste) → available=False."""
    pf = str(tmp_path / "paper_portfolio.json")
    jn = str(tmp_path / "trade_journal.jsonl")
    with open(pf, "w", encoding="utf-8") as f:
        json.dump([1, 2, 3], f)
    report = reconcile.check(portfolio_path=pf, journal_path=jn)
    assert report["available"] is False
    assert report["consistent"] is True


def test_check_detects_extra_in_journal(tmp_path):
    """Après reset du portefeuille, le journal contient des trades que le portefeuille n'a plus.

    Cas : le portefeuille a été réinitialisé (nouveau fichier, trades vides), mais le journal
    n'est jamais nettoyé (append-only). Les trades live du journal deviennent 'extra'.
    """
    pf = str(tmp_path / "paper_portfolio.json")
    jn = str(tmp_path / "trade_journal.jsonl")

    # Premier état : portefeuille avec 2 trades, synchro dans le journal
    _write_portfolio(pf, [_trade(entry_ts=1000), _trade(entry_ts=2000, pnl=-30.0)])
    reconcile.fix(portfolio_path=pf, journal_path=jn, strategy_id="testbot")

    # Reset du portefeuille : nouveau fichier avec trades vides, mais même equity de départ
    _write_portfolio(pf, [], start=10000.0)

    # Vérification : journal a 2 trades live, portefeuille n'en a zéro
    report = reconcile.check(portfolio_path=pf, journal_path=jn)
    assert report["extra_in_journal"] == 2
    assert report["missing_in_journal"] == 0
    assert report["consistent"] is False  # divergence détectée
    # equity_gap sera négatif (portefeuille = start_equity, journal récalcule equity)
    assert report["equity_gap"] < 0


def test_check_extra_and_missing_both_detected(tmp_path):
    """Cas complexe : le journal a des extras ET des trades du portefeuille manquent."""
    pf = str(tmp_path / "paper_portfolio.json")
    jn = str(tmp_path / "trade_journal.jsonl")

    # Initial synchro
    _write_portfolio(pf, [_trade(entry_ts=1000, pnl=50.0)])
    reconcile.fix(portfolio_path=pf, journal_path=jn, strategy_id="testbot")

    # Ajoute manuellement un ancien trade au portfolio
    old_trade = _trade(entry_ts=500, pnl=100.0)
    _write_portfolio(pf, [old_trade, _trade(entry_ts=1000, pnl=50.0)], start=10000.0)

    # Maintenant portefeuille a 2 trades, journal n'a que 1 (le récent)
    report = reconcile.check(portfolio_path=pf, journal_path=jn)
    assert report["missing_in_journal"] == 1  # entry_ts=500 manque
    assert report["extra_in_journal"] == 0    # rien en surplus
    assert report["consistent"] is False


# ── Tests de régression : deux try séparés dans journal_and_learn ──

def test_journal_and_learn_journalizes_even_if_learning_fails(tmp_path, monkeypatch):
    """
    Régression : learning_loop.run_learning qui lève → le trade est quand même
    écrit dans le journal et aucune exception ne se propage.
    """
    from forex.strategies.base import Strategy, StrategyDecision
    from forex.paper.runner import BotRuntime
    from forex import learning

    monkeypatch.setattr("forex.strategies.base.BOTS_DIR", str(tmp_path))

    # Stratégie factice
    class _DummyStrategy(Strategy):
        id = "test-learning-fail"
        label = "Test"
        min_candles = 1

        def decide(self, pair, now, candles, events, context=None):
            return StrategyDecision.no("dummy")

    # BotRuntime minimal
    strat = _DummyStrategy()
    rt = BotRuntime(strat)

    # Mock learning.run_learning pour qu'il lève
    def _boom(*args, **kwargs):
        raise RuntimeError("scipy missing / data corrupted")

    monkeypatch.setattr("forex.paper.runner.learning_loop.run_learning", _boom)

    # Créer un trade et appeler journal_and_learn
    trade = {
        "pair": "EUR_USD", "direction": "long", "entry_ts": 1000, "exit_ts": 2000,
        "entry_price": 1.1, "exit_price": 1.11, "net_pips": 10.0, "pnl": 50.0,
        "pnl_pct": 0.5, "exit_reason": "take-profit", "event_driven": False,
        "signals": {}, "adjusted": False
    }

    # NE DOIT PAS LEVER
    rt.journal_and_learn(trade, combo="test:long")

    # Vérifier que le trade est dans le journal
    trades = learning.journal.read_journal(path=rt.strategy.journal_path)
    assert len(trades) == 1
    assert trades[0]["pair"] == "EUR_USD"
    assert trades[0]["pnl"] == 50.0


def test_journal_and_learn_aborts_if_journalizing_fails(tmp_path, monkeypatch):
    """
    Régression : journal.append_trade qui lève → pas d'exception propagée,
    et learning.run_learning n'est pas déclenché.
    """
    from forex.strategies.base import Strategy, StrategyDecision
    from forex.paper.runner import BotRuntime

    monkeypatch.setattr("forex.strategies.base.BOTS_DIR", str(tmp_path))

    class _DummyStrategy(Strategy):
        id = "test-journal-fail"
        label = "Test"
        min_candles = 1

        def decide(self, pair, now, candles, events, context=None):
            return StrategyDecision.no("dummy")

    strat = _DummyStrategy()
    rt = BotRuntime(strat)

    # Mock journal.append_trade pour qu'il lève
    learning_called = []

    def _boom(*args, **kwargs):
        raise IOError("Permission denied writing journal")

    def _track_learning(*args, **kwargs):
        learning_called.append(True)

    monkeypatch.setattr("forex.paper.runner.journal.append_trade", _boom)
    monkeypatch.setattr("forex.paper.runner.learning_loop.run_learning", _track_learning)

    trade = {
        "pair": "EUR_USD", "direction": "long", "entry_ts": 1000, "exit_ts": 2000,
        "entry_price": 1.1, "exit_price": 1.11, "net_pips": 10.0, "pnl": 50.0,
        "pnl_pct": 0.5, "exit_reason": "take-profit", "event_driven": False,
        "signals": {}, "adjusted": False
    }

    # NE DOIT PAS LEVER
    rt.journal_and_learn(trade, combo="test:long")

    # Vérifier que l'apprentissage n'a pas été déclenché (early return)
    assert learning_called == []
