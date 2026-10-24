"""Tests du journal d'apprentissage (classification + clé de combo + IO)."""

from forex.learning import journal
from forex.signals.confluence import combo_key


def test_combo_key():
    assert combo_key({"technical": {"direction": "long"},
                      "fundamental": {"direction": "long"}}, "long") == "tech+fund:long"
    assert combo_key({"technical": {"direction": "short"}}, "short") == "tech:short"
    assert combo_key({"fundamental": {"direction": "long"}}, "long") == "fund:long"
    assert combo_key({}, None) == "none:?"


def test_classify():
    assert journal.classify(1.5, "take-profit") == "win"
    assert journal.classify(-1.0, "stop-loss") == "loss"
    assert journal.classify(0.05, "sortie temporelle (pas de mouvement)") == "neutral"
    assert journal.classify(-0.2, "sortie temporelle (pas de mouvement)") == "neutral"


def test_record_from_trade_dict():
    rec = journal.record_from_trade({
        "pair": "EUR_USD", "direction": "long", "entry_ts": 1, "exit_ts": 2,
        "entry_price": 1.1, "exit_price": 1.11, "net_pips": 10, "pnl": 5.0,
        "pnl_pct": 0.5, "exit_reason": "take-profit", "event_driven": False,
        "signals": {"technical": {"direction": "long"}},
    })
    assert rec["classification"] == "win"
    assert rec["combo"] == "tech:long"
    assert rec["source"] == "live"  # défaut


def test_record_from_trade_source_backtest():
    rec = journal.record_from_trade(
        {"pair": "EUR_USD", "direction": "long", "entry_ts": 1, "exit_ts": 2,
         "pnl_pct": 0.5, "exit_reason": "take-profit", "signals": {}},
        source="backtest",
    )
    assert rec["source"] == "backtest"


def test_append_read_roundtrip(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    for i in range(3):
        journal.append_trade({
            "pair": "EUR_USD", "direction": "long", "entry_ts": i, "exit_ts": i + 1,
            "entry_price": 1.1, "exit_price": 1.1, "net_pips": 0, "pnl": 1.0,
            "pnl_pct": 0.1, "exit_reason": "take-profit",
            "signals": {"technical": {"direction": "long"}},
        }, path=p)
    assert journal.count(path=p) == 3
    assert all(r["combo"] == "tech:long" for r in journal.read_journal(path=p))
    assert all(r["source"] == "live" for r in journal.read_journal(path=p))


def test_existing_keys_and_source_dedup(tmp_path):
    p = str(tmp_path / "journal.jsonl")
    journal.append_trade({"pair": "EUR_USD", "direction": "long", "entry_ts": 100,
                          "exit_ts": 101, "pnl_pct": 0.1, "exit_reason": "take-profit",
                          "signals": {}}, path=p, source="live")
    journal.append_trade({"pair": "EUR_USD", "direction": "long", "entry_ts": 100,
                          "exit_ts": 101, "pnl_pct": 0.1, "exit_reason": "take-profit",
                          "signals": {}}, path=p, source="backtest")
    keys = journal.existing_keys(path=p)
    # même pair/entry_ts mais sources différentes → deux clés distinctes
    assert ("EUR_USD", 100, "live") in keys
    assert ("EUR_USD", 100, "backtest") in keys
    assert len(keys) == 2


def test_existing_keys_defaults_missing_source_to_live(tmp_path):
    """Rétro-compatibilité : une ancienne entrée sans champ 'source' compte comme 'live'."""
    import json
    p = str(tmp_path / "journal.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"pair": "EUR_USD", "entry_ts": 5}) + "\n")
    assert ("EUR_USD", 5, "live") in journal.existing_keys(path=p)
