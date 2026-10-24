"""Portail de verdict : incubation / watch / validated / kill."""
import json

from forex.learning import verdict


def _trades(n, pnl_pct, source="live"):
    return [{"pair": "EUR_USD", "entry_ts": i, "exit_ts": i + 1, "pnl_pct": pnl_pct,
             "pnl": pnl_pct * 100, "classification": "win" if pnl_pct > 0 else "loss",
             "source": source} for i in range(n)]


def test_incubation_below_min_live():
    v = verdict.compute("bot", _trades(8, 0.5), portfolio=None)
    assert v["status"] == "incubation"
    assert v["progress"] == {"live_trades": 8, "needed": 30}


def test_backtest_alone_never_kills():
    v = verdict.compute("bot", _trades(500, -0.5, source="backtest"), portfolio=None)
    assert v["status"] == "incubation"          # 0 trade live


def test_validated():
    trades = _trades(20, 1.0) + _trades(12, -0.5)   # 32 live, PF (20*1)/(12*0.5)=3.33
    v = verdict.compute("bot", trades, portfolio=None)
    assert v["status"] == "validated"


def test_watch_when_pf_low():
    trades = _trades(16, 0.5) + _trades(16, -0.5)   # PF = 1.0 < 1.15
    v = verdict.compute("bot", trades, portfolio=None)
    assert v["status"] == "watch"


def test_kill_needs_backtest_and_live():
    live = _trades(25, -0.4)                        # 25 live négatifs
    bt = _trades(300, -0.1, source="backtest")      # PF backtest < 0.95
    v = verdict.compute("bot", live + bt, portfolio=None)
    assert v["status"] == "kill"


def test_kill_on_live_drawdown():
    pf = {"start_equity": 10000.0, "equity": 8000.0, "peak_equity": 10000.0}
    v = verdict.compute("bot", _trades(5, -1.0), portfolio=pf)   # DD 20 % > 15 %
    assert v["status"] == "kill"


def test_write_all(tmp_path, monkeypatch):
    out = tmp_path / "verdicts.json"
    data = verdict.write_all(bots=[], path=str(out))
    assert data["verdicts"] == {}
    assert json.loads(out.read_text(encoding="utf-8"))["updated_at"]


# ── Tests supplémentaires (contrôle qualité) ─────────────────────────
def test_regression_backtest_all_winners_no_kill():
    """25 live trades négatifs + 300 backtest TOUS gagnants (PF None) → PAS kill."""
    live = _trades(25, -0.4)  # 25 live négatifs, espérance -40%
    bt = _trades(300, 0.1, source="backtest")  # 300 backtest positifs → PF infini (None)
    v = verdict.compute("bot", live + bt, portfolio=None)
    # Pas de kill car PF backtest est None (tous les trades positifs).
    # 25 trades = insuffisant pour watch/incubation (< 30)
    assert v["status"] == "incubation"
    assert v["backtest"]["profit_factor"] is None  # Aucune perte en backtest


def test_boundary_exactly_30_live_trades():
    """Exactement 30 trades live (seuil d'éligibilité)."""
    trades = _trades(20, 1.0) + _trades(10, -0.5)  # 30 live total, PF 2.0
    v = verdict.compute("bot", trades, portfolio=None)
    assert v["status"] == "validated"
    assert v["progress"]["live_trades"] == 30


def test_boundary_pf_exactly_1_15():
    """PF exactement 1.15 (seuil validated)."""
    # Besoin de 30 trades min + PF = 1.15
    # PF = gains / losses : 30 trades split, ratio donne PF 1.15
    # 20 gagnants de 1.0% chacun = 20% gains
    # 10 perdants de -1.74% chacun = 17.4% losses → PF ≈ 20/17.4 ≈ 1.149 ≈ 1.15
    trades = _trades(20, 1.0) + _trades(10, -1.74)  # PF proche 1.15, espérance > 0
    v = verdict.compute("bot", trades, portfolio=None)
    assert v["status"] == "validated"
    assert v["live"]["profit_factor"] >= 1.15


def test_boundary_drawdown_exactly_15_pct_not_kill():
    """Drawdown exactement 15.0% (seuil strict >, donc PAS kill)."""
    pf = {"start_equity": 10000.0, "equity": 8500.0, "peak_equity": 10000.0}
    # DD = (10000 - 8500) / 10000 = 0.15 = 15.0%
    v = verdict.compute("bot", _trades(5, -0.5), portfolio=pf)
    # Condition kill est dd > 15.0, donc DD 15.0 exactement n'est pas kill
    assert v["status"] != "kill"


def test_boundary_exactly_20_live_trades_for_kill():
    """Exactement 20 trades live pour la condition kill (≥)."""
    live = _trades(20, -0.4)  # Exactement 20, tous négatifs
    bt = _trades(300, -0.1, source="backtest")  # PF backtest < 0.95
    v = verdict.compute("bot", live + bt, portfolio=None)
    assert v["status"] == "kill"


def test_risk_multiplier_none_returns_incubation():
    """risk_multiplier(None) retourne le multiplicateur incubation."""
    from forex import config
    result = verdict.risk_multiplier(None)
    assert result == config.FOREX_VERDICT_RISK_MULT["incubation"]


def test_write_all_json_list_portfolio_does_not_crash(tmp_path):
    """write_all avec portfolio JSON-liste (pas un dict) → ne crash pas, traite comme None."""
    from forex import config

    class FakeBot:
        id = "badbot"
        journal_path = str(tmp_path / "j.jsonl")
        portfolio_path = str(tmp_path / "p.json")

    # Écrire un JSON-liste au lieu d'un dict
    (tmp_path / "p.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    # Écrire un journal minimal
    (tmp_path / "j.jsonl").write_text(json.dumps({
        "pair": "EUR_USD", "entry_ts": 0, "exit_ts": 1,
        "pnl": 50, "pnl_pct": 0.5, "classification": "win"
    }), encoding="utf-8")

    out = tmp_path / "verdicts.json"
    data = verdict.write_all(bots=[FakeBot()], path=str(out))
    # Le JSON-liste est converti en None (pas un dict) → bot reçoit un verdict (incubation)
    assert "badbot" in data["verdicts"]
    assert data["verdicts"]["badbot"]["status"] == "incubation"
    assert json.loads(out.read_text(encoding="utf-8"))["updated_at"]


def test_write_all_appends_kill_to_disabled(tmp_path, monkeypatch):
    """Un bot kill est poussé dans disabled_bots.json (le runner l'archivera)."""
    from forex import config as fconfig

    class FakeBot:
        id = "deadbot"
        journal_path = str(tmp_path / "j.jsonl")
        portfolio_path = str(tmp_path / "p.json")

    (tmp_path / "p.json").write_text(json.dumps(
        {"start_equity": 10000, "equity": 8000, "peak_equity": 10000,
         "positions": {}, "trades": []}), encoding="utf-8")
    monkeypatch.setattr(fconfig, "FOREX_DATA_DIR", str(tmp_path))
    data = verdict.write_all(bots=[FakeBot()], path=str(tmp_path / "verdicts.json"))
    assert data["verdicts"]["deadbot"]["status"] == "kill"
    disabled = json.loads((tmp_path / "disabled_bots.json").read_text(encoding="utf-8"))
    assert "deadbot" in disabled


# ── Régression : write_all() doit FUSIONNER, jamais écraser (bug critique 2026-07-29) ──

def test_write_all_merges_does_not_wipe_other_bots(tmp_path):
    """Bug critique : un appel single-bot (palier-trigger) ne doit PAS effacer les
    verdicts des autres bots déjà présents dans le fichier — seul le bot recalculé
    cet appel voit son entrée remplacée, les autres gardent leur entrée EXACTE."""
    out = tmp_path / "verdicts.json"
    stale_bot_a = {
        "bot": "bot_a", "status": "validated", "reason": "stale entry for bot_a",
        "risk_mult": 1.0, "live": {"n": 40}, "backtest": {"n": 0},
        "drawdown_pct": 0.0, "progress": {"live_trades": 40, "needed": 30},
    }
    stale_bot_b = {
        "bot": "bot_b", "status": "watch", "reason": "stale entry for bot_b",
        "risk_mult": 0.5, "live": {"n": 12}, "backtest": {"n": 0},
        "drawdown_pct": 0.0, "progress": {"live_trades": 12, "needed": 30},
    }
    stale_bot_c = {
        "bot": "bot_c", "status": "incubation", "reason": "stale entry for bot_c",
        "risk_mult": 0.25, "live": {"n": 3}, "backtest": {"n": 0},
        "drawdown_pct": 0.0, "progress": {"live_trades": 3, "needed": 30},
    }
    out.write_text(json.dumps({
        "updated_at": "2026-07-01T00:00:00+00:00",
        "verdicts": {"bot_a": stale_bot_a, "bot_b": stale_bot_b, "bot_c": stale_bot_c},
    }), encoding="utf-8")

    class FakeBotC:
        id = "bot_c"
        journal_path = str(tmp_path / "c_journal.jsonl")
        portfolio_path = str(tmp_path / "c_portfolio.json")

    # bot_c a maintenant assez de trades live pour passer en "validated".
    (tmp_path / "c_journal.jsonl").write_text("\n".join(
        json.dumps(t) for t in _trades(20, 1.0) + _trades(10, -0.5)
    ), encoding="utf-8")

    data = verdict.write_all(bots=[FakeBotC()], path=str(out))

    # bot_a et bot_b : PAS recalculés cet appel → entrée strictement inchangée.
    assert data["verdicts"]["bot_a"] == stale_bot_a
    assert data["verdicts"]["bot_b"] == stale_bot_b
    # bot_c : recalculé cet appel → verdict frais, différent de l'ancien stale.
    assert data["verdicts"]["bot_c"] != stale_bot_c
    assert data["verdicts"]["bot_c"]["status"] == "validated"

    on_disk = json.loads(out.read_text(encoding="utf-8"))
    assert set(on_disk["verdicts"]) == {"bot_a", "bot_b", "bot_c"}
    assert on_disk["verdicts"]["bot_a"] == stale_bot_a
    assert on_disk["verdicts"]["bot_b"] == stale_bot_b


def test_write_all_merge_with_no_pre_existing_file(tmp_path):
    """write_all avec un path inexistant : fallback sur dict vide, fonctionne normalement
    (pas de crash à l'absence de fichier lors de la fusion)."""
    out = tmp_path / "does_not_exist" / "verdicts.json"
    data = verdict.write_all(bots=[], path=str(out))
    assert data["verdicts"] == {}
    assert json.loads(out.read_text(encoding="utf-8"))["updated_at"]


def test_write_all_kill_push_scoped_to_bots_computed_this_call(tmp_path, monkeypatch):
    """Le kill-push vers disabled_bots.json ne doit agir QUE sur les bots calculés cet
    appel — un bot_b au statut "kill" resté dans le fichier fusionné (mais pas passé
    dans `bots` cette fois) ne doit PAS être repoussé dans disabled_bots.json."""
    from forex import config as fconfig

    out = tmp_path / "verdicts.json"
    stale_bot_b_kill = {
        "bot": "bot_b", "status": "kill", "reason": "stale kill entry for bot_b",
        "risk_mult": 0.0, "live": {"n": 25}, "backtest": {"n": 300},
        "drawdown_pct": 0.0, "progress": {"live_trades": 25, "needed": 30},
    }
    out.write_text(json.dumps({
        "updated_at": "2026-07-01T00:00:00+00:00",
        "verdicts": {"bot_b": stale_bot_b_kill},
    }), encoding="utf-8")

    class FakeBotA:
        id = "bot_a"
        journal_path = str(tmp_path / "a_journal.jsonl")
        portfolio_path = str(tmp_path / "a_portfolio.json")

    (tmp_path / "a_portfolio.json").write_text(json.dumps(
        {"start_equity": 10000, "equity": 8000, "peak_equity": 10000,
         "positions": {}, "trades": []}), encoding="utf-8")
    # journal absent → read_journal renvoie [] ; le kill vient du drawdown.

    monkeypatch.setattr(fconfig, "FOREX_DATA_DIR", str(tmp_path))

    data = verdict.write_all(bots=[FakeBotA()], path=str(out))
    assert data["verdicts"]["bot_a"]["status"] == "kill"
    # bot_b reste "kill" dans le fichier fusionné (stale) mais ne doit pas être re-évalué.
    assert data["verdicts"]["bot_b"] == stale_bot_b_kill

    disabled = json.loads((tmp_path / "disabled_bots.json").read_text(encoding="utf-8"))
    assert "bot_a" in disabled
    assert "bot_b" not in disabled
