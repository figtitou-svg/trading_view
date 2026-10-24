"""Tests du backfill historique du journal d'apprentissage (module 7)."""

import random
from datetime import datetime, timedelta, timezone

import pytest

from forex.learning import backfill, journal


@pytest.fixture(autouse=True)
def _clear_price_cache():
    """
    Le cache de séries de `backfill` est global au processus (voulu : tous les
    bots d'une même exécution doivent rejouer EXACTEMENT les mêmes données).
    Il doit être vidé entre les tests, sinon un test hérite des prix d'un autre
    et les doublures de `fetch_ohlcv` ne sont jamais appelées.
    """
    backfill.clear_cache()
    yield
    backfill.clear_cache()


def _isolate_state(monkeypatch, tmp_path):
    """Isole state.get_overrides des vrais réglages appris de la machine (hermétique)."""
    monkeypatch.setattr(backfill.state, "get_overrides", lambda pair, path=None: {})


def _synthetic_candles(n=4000, seed=3):
    """Marche aléatoire avec dérive (assez de volatilité pour générer des trades)."""
    random.seed(seed)
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    price = 1.10
    out = []
    for i in range(n):
        price *= (1 + 0.00002 + random.gauss(0, 0.0008))
        o = price
        h = price * (1 + abs(random.gauss(0, 0.0006)))
        l = price * (1 - abs(random.gauss(0, 0.0006)))
        c = price * (1 + random.gauss(0, 0.0004))
        ts = int((base + timedelta(hours=i)).timestamp() * 1000)
        out.append([ts, o, max(o, h, c), min(o, l, c), c, 0.0])
    return out


def test_backfill_pair_adds_trades_tagged_backtest(tmp_path, monkeypatch):
    _isolate_state(monkeypatch, tmp_path)
    p = str(tmp_path / "journal.jsonl")
    candles = _synthetic_candles()
    monkeypatch.setattr(backfill.prices, "fetch_ohlcv", lambda pair, gran: candles)
    monkeypatch.setattr(backfill.cal, "load_events", lambda: [])

    added = backfill.backfill_pair("EUR_USD", path=p)
    assert added > 0
    recs = journal.read_journal(path=p)
    assert len(recs) == added
    assert all(r["source"] == "backtest" for r in recs)
    assert all(r["pair"] == "EUR_USD" for r in recs)


def test_backfill_pair_idempotent(tmp_path, monkeypatch):
    """Relancer le backfill sur les mêmes données n'ajoute AUCUN doublon."""
    _isolate_state(monkeypatch, tmp_path)
    p = str(tmp_path / "journal.jsonl")
    candles = _synthetic_candles()
    monkeypatch.setattr(backfill.prices, "fetch_ohlcv", lambda pair, gran: candles)
    monkeypatch.setattr(backfill.cal, "load_events", lambda: [])

    first = backfill.backfill_pair("EUR_USD", path=p)
    assert first > 0
    second = backfill.backfill_pair("EUR_USD", path=p)
    assert second == 0  # tout déjà présent
    assert journal.count(path=p) == first


def test_backfill_pair_too_little_data_returns_zero(tmp_path, monkeypatch):
    p = str(tmp_path / "journal.jsonl")
    monkeypatch.setattr(backfill.prices, "fetch_ohlcv", lambda pair, gran: [[0, 1.1, 1.1, 1.1, 1.1, 0]] * 5)
    assert backfill.backfill_pair("EUR_USD", path=p) == 0
    assert journal.count(path=p) == 0


def test_backfill_pair_handles_fetch_error(tmp_path, monkeypatch):
    p = str(tmp_path / "journal.jsonl")

    def boom(pair, gran):
        raise RuntimeError("réseau indisponible")

    monkeypatch.setattr(backfill.prices, "fetch_ohlcv", boom)
    assert backfill.backfill_pair("EUR_USD", path=p) == 0


def test_backfill_all_aggregates_per_pair(tmp_path, monkeypatch):
    _isolate_state(monkeypatch, tmp_path)
    p = str(tmp_path / "journal.jsonl")
    candles = _synthetic_candles()
    monkeypatch.setattr(backfill.prices, "fetch_ohlcv", lambda pair, gran: candles)
    monkeypatch.setattr(backfill.cal, "load_events", lambda: [])

    counts = backfill.backfill_all(pairs=["EUR_USD", "GBP_USD"], path=p)
    assert set(counts.keys()) == {"EUR_USD", "GBP_USD"}
    assert all(n > 0 for n in counts.values())
    recs = journal.read_journal(path=p)
    assert {r["pair"] for r in recs} == {"EUR_USD", "GBP_USD"}


def test_backfill_produces_journal_records_analyzable(tmp_path, monkeypatch):
    """Les trades injectés doivent être directement exploitables par analysis.analyze()."""
    from forex.learning import analysis

    _isolate_state(monkeypatch, tmp_path)
    p = str(tmp_path / "journal.jsonl")
    candles = _synthetic_candles()
    monkeypatch.setattr(backfill.prices, "fetch_ohlcv", lambda pair, gran: candles)
    monkeypatch.setattr(backfill.cal, "load_events", lambda: [])
    backfill.backfill_pair("EUR_USD", path=p)

    stats = analysis.analyze(journal.read_journal(path=p))
    assert stats  # au moins un combo présent
    for s in stats.values():
        assert s.n_backtest == s.n and s.n_live == 0


def test_refresh_pair_purges_and_regenerates(tmp_path, monkeypatch):
    """refresh_pair doit repartir de zéro pour la paire (pas d'accumulation de doublons)."""
    _isolate_state(monkeypatch, tmp_path)
    p = str(tmp_path / "journal.jsonl")
    candles = _synthetic_candles()
    monkeypatch.setattr(backfill.prices, "fetch_ohlcv", lambda pair, gran: candles)
    monkeypatch.setattr(backfill.cal, "load_events", lambda: [])

    first = backfill.backfill_pair("EUR_USD", path=p)
    assert first > 0
    refreshed = backfill.refresh_pair("EUR_USD", path=p)
    # Mêmes données (mêmes réglages) → même nombre de trades régénérés, et
    # surtout PAS d'accumulation (pas de doublons issus de l'ancien passage).
    assert refreshed == first
    assert journal.count(path=p) == first


def test_refresh_pair_reflects_changed_params(tmp_path, monkeypatch):
    """Si les paramètres appris changent, refresh_pair doit rejouer AVEC eux."""
    p = str(tmp_path / "journal.jsonl")
    candles = _synthetic_candles()
    monkeypatch.setattr(backfill.prices, "fetch_ohlcv", lambda pair, gran: candles)
    monkeypatch.setattr(backfill.cal, "load_events", lambda: [])

    monkeypatch.setattr(backfill.state, "get_overrides", lambda pair, path=None: {})
    backfill.backfill_pair("EUR_USD", path=p)
    baseline_pnls = sorted(r["pnl_pct"] for r in journal.read_journal(path=p))

    # Change les multiples ATR appris → doit changer les sorties (stop/TP différents)
    monkeypatch.setattr(
        backfill.state, "get_overrides",
        lambda pair, path=None: {"atr_stop_mult": 1.0, "atr_tp_mult": 5.0},
    )
    backfill.refresh_pair("EUR_USD", path=p)
    tuned_pnls = sorted(r["pnl_pct"] for r in journal.read_journal(path=p))
    assert tuned_pnls != baseline_pnls


def test_purge_source_only_removes_matching_pair_and_source(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    journal.append_trade({"pair": "EUR_USD", "direction": "long", "entry_ts": 1,
                          "exit_ts": 2, "pnl_pct": 0.1, "exit_reason": "take-profit",
                          "signals": {}}, path=p, source="backtest")
    journal.append_trade({"pair": "EUR_USD", "direction": "long", "entry_ts": 3,
                          "exit_ts": 4, "pnl_pct": 0.1, "exit_reason": "take-profit",
                          "signals": {}}, path=p, source="live")
    journal.append_trade({"pair": "GBP_USD", "direction": "long", "entry_ts": 5,
                          "exit_ts": 6, "pnl_pct": 0.1, "exit_reason": "take-profit",
                          "signals": {}}, path=p, source="backtest")

    removed = journal.purge_source("EUR_USD", source="backtest", path=p)
    assert removed == 1
    remaining = journal.read_journal(path=p)
    assert len(remaining) == 2
    assert {(r["pair"], r["source"]) for r in remaining} == {("EUR_USD", "live"), ("GBP_USD", "backtest")}
