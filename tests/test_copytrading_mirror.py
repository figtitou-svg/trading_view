"""Tests du portefeuille miroir (logique pure, aucun réseau)."""

from datetime import datetime, timezone

from copytrading import mirror

NOW = "2026-07-23T12:00:00+00:00"


def _pf():
    return mirror.new_portfolio(10000.0)


def test_ouverture_proportionnelle():
    pf = _pf()
    mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "long", "frac": 0.05}},
                       {"BTC": 100000.0}, NOW)
    assert len(pf["positions"]) == 1
    p = pf["positions"][0]
    assert p["size_eur"] == 250.0 and p["entry_price"] == 100000.0
    assert p["direction"] == "long" and p["trader"] == "0xa"


def test_pas_d_ouverture_poussiere():
    pf = _pf()
    mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "long", "frac": 0.0001}},
                       {"BTC": 100000.0}, NOW)
    assert pf["positions"] == []


def test_cloture_quand_le_trader_sort():
    pf = _pf()
    mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "long", "frac": 0.05}},
                       {"BTC": 100000.0}, NOW)
    mirror.sync_trader(pf, "0xa", 5000.0, {}, {"BTC": 110000.0}, NOW)
    assert pf["positions"] == []
    assert len(pf["trades"]) == 1
    t = pf["trades"][0]
    assert t["pnl_eur"] == 25.0        # 250 € × +10 %
    assert pf["realized_pnl"] == 25.0


def test_short_pnl_inverse():
    pf = _pf()
    mirror.sync_trader(pf, "0xa", 5000.0, {"ETH": {"direction": "short", "frac": 0.10}},
                       {"ETH": 2000.0}, NOW)
    mirror.sync_trader(pf, "0xa", 5000.0, {}, {"ETH": 1800.0}, NOW)  # -10 %
    assert pf["trades"][0]["pnl_eur"] == 50.0   # short gagnant : 500 € × +10 %


def test_retournement():
    pf = _pf()
    mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "long", "frac": 0.05}},
                       {"BTC": 100000.0}, NOW)
    closed = mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "short", "frac": 0.05}},
                                {"BTC": 100000.0}, NOW)
    assert len(pf["trades"]) == 1 and pf["trades"][0]["reason"] == "retournement du trader"
    assert pf["positions"][0]["direction"] == "short"
    assert closed == [pf["trades"][0]]


def test_tolerance_pas_d_ajustement():
    pf = _pf()
    mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "long", "frac": 0.05}},
                       {"BTC": 100000.0}, NOW)
    # 0.055 → écart relatif 10 % < 20 % : aucune modification de taille.
    mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "long", "frac": 0.055}},
                       {"BTC": 100000.0}, NOW)
    assert pf["positions"][0]["size_eur"] == 250.0


def test_renforcement_prix_moyen_pondere():
    pf = _pf()
    mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "long", "frac": 0.05}},
                       {"BTC": 100000.0}, NOW)
    mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "long", "frac": 0.10}},
                       {"BTC": 120000.0}, NOW)
    p = pf["positions"][0]
    assert p["size_eur"] == 500.0
    # (100000×250 + 120000×250) / 500 = 110000
    assert p["entry_price"] == 110000.0
    assert pf["trades"] == []


def test_allegement_realise_le_pnl_partiel():
    pf = _pf()
    mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "long", "frac": 0.10}},
                       {"BTC": 100000.0}, NOW)          # 500 €
    closed = mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "long", "frac": 0.05}},
                                {"BTC": 110000.0}, NOW)  # coupe 250 € à +10 %
    assert pf["positions"][0]["size_eur"] == 250.0
    assert pf["realized_pnl"] == 25.0
    assert pf["trades"][0]["reason"] == "allègement"
    assert closed == [pf["trades"][0]]


def test_allegement_sous_le_seuil_cloture_tout():
    pf = _pf()
    mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "long", "frac": 0.10}},
                       {"BTC": 100000.0}, NOW)             # 500 €
    # Le trader réduit sa fraction à quasi zéro sans sortir totalement :
    # want_eur = 0.0001 × 5000 = 0.5 € < seuil de poussière (1 €).
    closed = mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "long", "frac": 0.0001}},
                                {"BTC": 100000.0}, NOW)
    assert pf["positions"] == []               # pas de position résiduelle
    assert len(pf["trades"]) == 1
    assert pf["trades"][0]["reason"] == "allègement"
    assert pf["trades"][0]["size_eur"] == 500.0
    assert closed == [pf["trades"][0]]


def test_isolation_entre_traders():
    pf = _pf()
    mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "long", "frac": 0.05}},
                       {"BTC": 100000.0}, NOW)
    mirror.sync_trader(pf, "0xb", 5000.0, {"BTC": {"direction": "short", "frac": 0.10}},
                       {"BTC": 100000.0}, NOW)
    assert len(pf["positions"]) == 2
    pos_a = next(p for p in pf["positions"] if p["trader"] == "0xa")
    pos_b = next(p for p in pf["positions"] if p["trader"] == "0xb")
    assert pos_a["size_eur"] == 250.0 and pos_a["direction"] == "long"
    assert pos_b["size_eur"] == 500.0 and pos_b["direction"] == "short"
    pos_b_snapshot = dict(pos_b)

    # Le sync du trader A (renforcement) ne doit pas toucher la position de B.
    mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "long", "frac": 0.10}},
                       {"BTC": 120000.0}, NOW)
    pos_b_after = next(p for p in pf["positions"] if p["trader"] == "0xb")
    assert pos_b_after == pos_b_snapshot

    # La clôture de A ne doit pas affecter la position de B.
    mirror.close_trader(pf, "0xa", {"BTC": 120000.0}, NOW)
    assert len(pf["positions"]) == 1
    assert pf["positions"][0]["trader"] == "0xb"
    assert pf["positions"][0] == pos_b_snapshot


def test_close_trader_tout_et_prix_inconnu():
    pf = _pf()
    mirror.sync_trader(pf, "0xa", 5000.0,
                       {"BTC": {"direction": "long", "frac": 0.05},
                        "ETH": {"direction": "short", "frac": 0.05}},
                       {"BTC": 100000.0, "ETH": 2000.0}, NOW)
    mirror.close_trader(pf, "0xa", {"BTC": 110000.0}, NOW)  # pas de mid ETH
    assert pf["positions"] == []
    pnls = {t["coin"]: t["pnl_eur"] for t in pf["trades"]}
    assert pnls["BTC"] == 25.0
    assert pnls["ETH"] == 0.0          # clôturé au prix d'entrée faute de mid


def test_equity_et_historique():
    pf = _pf()
    mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "long", "frac": 0.05}},
                       {"BTC": 100000.0}, NOW)
    mids = {"BTC": 110000.0}
    assert mirror.equity(pf, mids) == 10025.0
    t0 = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 7, 23, 12, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 7, 23, 13, 5, tzinfo=timezone.utc)
    mirror.record_equity(pf, mids, t0)
    mirror.record_equity(pf, mids, t1)   # < 1 h : ignoré
    mirror.record_equity(pf, mids, t2)
    assert len(pf["equity_history"]) == 2


def test_sync_trader_returns_the_closed_trade_when_trader_exits():
    pf = _pf()
    mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "long", "frac": 0.05}},
                       {"BTC": 100000.0}, NOW)
    closed = mirror.sync_trader(pf, "0xa", 5000.0, {}, {"BTC": 110000.0}, NOW)
    assert len(closed) == 1
    assert closed[0]["pnl_eur"] == 25.0
    assert closed[0] == pf["trades"][0]


def test_sync_trader_returns_empty_list_when_nothing_closes():
    pf = _pf()
    closed = mirror.sync_trader(pf, "0xa", 5000.0, {"BTC": {"direction": "long", "frac": 0.05}},
                                {"BTC": 100000.0}, NOW)
    assert closed == []


def test_close_trader_returns_all_closed_trades():
    pf = _pf()
    mirror.sync_trader(pf, "0xa", 5000.0,
                       {"BTC": {"direction": "long", "frac": 0.05},
                        "ETH": {"direction": "short", "frac": 0.05}},
                       {"BTC": 100000.0, "ETH": 2000.0}, NOW)
    closed = mirror.close_trader(pf, "0xa", {"BTC": 110000.0, "ETH": 2000.0}, NOW)
    assert len(closed) == 2
