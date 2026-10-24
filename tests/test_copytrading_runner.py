"""Tests du cycle du runner copy trading (fetchers injectés, aucun réseau)."""

import json
from datetime import datetime, timedelta, timezone

from copytrading import config, mirror, runner

NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


def _state(account, positions):
    return {"marginSummary": {"accountValue": str(account)},
            "assetPositions": [
                {"type": "oneWay", "position": {
                    "coin": c, "szi": str(szi), "positionValue": str(val)}}
                for c, szi, val in positions]}


def test_iterate_ouvre_les_positions_suivies():
    pf = mirror.new_portfolio(10000.0)
    states = {"0xa": _state(100000, [("BTC", 1, 5000)]),      # 5 % long BTC
              "0xb": _state(200000, [("ETH", -10, 20000)])}   # 10 % short ETH
    mids, errors = runner.iterate(
        pf, ["0xa", "0xb"],
        fetch_positions=lambda a: states[a],
        fetch_mids=lambda: {"BTC": 100000.0, "ETH": 2000.0}, now=NOW)
    assert errors == []
    by = {(p["trader"], p["coin"]): p for p in pf["positions"]}
    assert by[("0xa", "BTC")]["size_eur"] == 250.0   # 5 % de 5000 €
    assert by[("0xb", "ETH")]["direction"] == "short"
    assert pf["equity_history"]                      # point d'equity enregistré


def test_iterate_erreur_isolee():
    pf = mirror.new_portfolio(10000.0)
    def fetch(addr):
        if addr == "0xbad":
            raise RuntimeError("timeout")
        return _state(100000, [("BTC", 1, 5000)])
    mids, errors = runner.iterate(pf, ["0xbad", "0xa"], fetch_positions=fetch,
                                  fetch_mids=lambda: {"BTC": 100000.0}, now=NOW)
    assert len(errors) == 1 and "0xbad" in errors[0]
    assert len(pf["positions"]) == 1                 # 0xa copié malgré l'erreur


def test_iterate_erreur_isolee_state_malforme():
    """Un state qui fait planter parse_positions/sync_trader (pas juste le
    fetch réseau) ne doit isoler que le trader fautif, pas tout le cycle."""
    pf = mirror.new_portfolio(10000.0)
    def fetch(addr):
        if addr == "0xbad":
            return None                     # provoque un AttributeError en aval
        return _state(100000, [("BTC", 1, 5000)])
    mids, errors = runner.iterate(pf, ["0xbad", "0xa"], fetch_positions=fetch,
                                  fetch_mids=lambda: {"BTC": 100000.0}, now=NOW)
    assert len(errors) == 1 and "0xbad" in errors[0]
    assert len(pf["positions"]) == 1                 # 0xa copié malgré l'erreur
    assert pf["positions"][0]["trader"] == "0xa"


def test_iterate_does_not_notify_per_trade_in_daily_recap_mode(monkeypatch):
    from services.notification_settings import DEFAULTS
    monkeypatch.setattr(runner, "load_notification_settings",
                        lambda: {**DEFAULTS, "copytrading_mode": "daily_recap"})
    notified = []
    monkeypatch.setattr(runner, "_notify_trade_closed", lambda trade: notified.append(trade))
    pf = mirror.new_portfolio(10000.0)
    runner.iterate(pf, ["0xa"],
                  fetch_positions=lambda a: _state(100000, [("BTC", 1, 5000)]),
                  fetch_mids=lambda: {"BTC": 100000.0}, now=NOW)
    runner.iterate(pf, [], fetch_positions=lambda a: {},
                  fetch_mids=lambda: {"BTC": 110000.0}, now=NOW)
    assert notified == []


def test_iterate_still_notifies_by_default(monkeypatch):
    notified = []
    monkeypatch.setattr(runner, "_notify_trade_closed", lambda trade: notified.append(trade))
    pf = mirror.new_portfolio(10000.0)
    runner.iterate(pf, ["0xa"],
                  fetch_positions=lambda a: _state(100000, [("BTC", 1, 5000)]),
                  fetch_mids=lambda: {"BTC": 100000.0}, now=NOW)
    runner.iterate(pf, [], fetch_positions=lambda a: {},
                  fetch_mids=lambda: {"BTC": 110000.0}, now=NOW)
    assert len(notified) == 1


def test_iterate_cloture_les_desuivis():
    pf = mirror.new_portfolio(10000.0)
    runner.iterate(pf, ["0xa"],
                   fetch_positions=lambda a: _state(100000, [("BTC", 1, 5000)]),
                   fetch_mids=lambda: {"BTC": 100000.0}, now=NOW)
    # 0xa retiré de follows : ses positions doivent être soldées.
    runner.iterate(pf, [], fetch_positions=lambda a: {},
                   fetch_mids=lambda: {"BTC": 110000.0}, now=NOW)
    assert pf["positions"] == []
    assert pf["trades"][0]["reason"] == "copie désactivée"
    assert pf["trades"][0]["pnl_eur"] == 50.0


def _leaderboard_row(address="0xa", roi_week=0.1, roi_month=0.2, vlm_week=500.0):
    return {"ethAddress": address, "displayName": "Test",
            "accountValue": "100000",
            "windowPerformances": [
                ["week", {"roi": roi_week, "pnl": 100.0, "vlm": vlm_week}],
                ["month", {"roi": roi_month, "pnl": 200.0, "vlm": vlm_week}],
            ]}


def test_refresh_candidates_cache_frais_ne_rafraichit_pas(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CANDIDATES_PATH", str(tmp_path / "candidates.json"))
    cached = {"updated_at": NOW.isoformat(), "candidates": [{"address": "0xold"}]}
    (tmp_path / "candidates.json").write_text(json.dumps(cached), encoding="utf-8")

    def fetch_leaderboard():
        raise AssertionError("fetch_leaderboard ne doit pas être appelé : cache frais")

    runner.refresh_candidates(NOW, fetch_leaderboard=fetch_leaderboard)

    on_disk = json.loads((tmp_path / "candidates.json").read_text(encoding="utf-8"))
    assert on_disk == cached                          # inchangé : pas de rafraîchissement


def test_refresh_candidates_cache_perime_rafraichit(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CANDIDATES_PATH", str(tmp_path / "candidates.json"))
    stale_at = NOW - timedelta(seconds=config.COPY_LEADERBOARD_REFRESH_SECONDS + 10)
    cached = {"updated_at": stale_at.isoformat(), "candidates": [{"address": "0xold"}]}
    (tmp_path / "candidates.json").write_text(json.dumps(cached), encoding="utf-8")

    calls = []
    def fetch_leaderboard():
        calls.append(1)
        return [_leaderboard_row()]

    runner.refresh_candidates(NOW, fetch_leaderboard=fetch_leaderboard)

    assert calls == [1]                                # bien rafraîchi
    on_disk = json.loads((tmp_path / "candidates.json").read_text(encoding="utf-8"))
    assert on_disk["updated_at"] == NOW.isoformat()
    assert on_disk["candidates"][0]["address"] == "0xa"


def test_once_ecrit_les_fichiers(tmp_path, monkeypatch):
    from copytrading import config
    monkeypatch.setattr(config, "PORTFOLIO_PATH", str(tmp_path / "portfolio.json"))
    monkeypatch.setattr(config, "STATUS_PATH", str(tmp_path / "status.json"))
    monkeypatch.setattr(config, "CANDIDATES_PATH", str(tmp_path / "candidates.json"))
    monkeypatch.setattr(config, "FOLLOWS_PATH", str(tmp_path / "follows.json"))
    monkeypatch.setattr(runner.api, "fetch_mids", lambda: {"BTC": 100000.0})
    monkeypatch.setattr(runner.api, "fetch_leaderboard", lambda: [])
    runner.run(once=True)
    assert (tmp_path / "portfolio.json").exists()
    assert (tmp_path / "status.json").exists()


def test_iterate_notifies_once_per_closed_position(monkeypatch):
    notified = []
    monkeypatch.setattr(runner, "_notify_trade_closed", lambda trade: notified.append(trade))
    pf = mirror.new_portfolio(10000.0)
    runner.iterate(pf, ["0xa"],
                  fetch_positions=lambda a: _state(100000, [("BTC", 1, 5000)]),
                  fetch_mids=lambda: {"BTC": 100000.0}, now=NOW)
    # 0xa retiré de follows : sa position doit être soldée ET notifiée.
    runner.iterate(pf, [], fetch_positions=lambda a: {},
                  fetch_mids=lambda: {"BTC": 110000.0}, now=NOW)
    assert len(notified) == 1
    assert notified[0]["reason"] == "copie désactivée"


def test_iterate_does_not_notify_on_open_or_no_op_cycle(monkeypatch):
    notified = []
    monkeypatch.setattr(runner, "_notify_trade_closed", lambda trade: notified.append(trade))
    pf = mirror.new_portfolio(10000.0)
    runner.iterate(pf, ["0xa"],
                  fetch_positions=lambda a: _state(100000, [("BTC", 1, 5000)]),
                  fetch_mids=lambda: {"BTC": 100000.0}, now=NOW)
    assert notified == []


def test_build_close_message_format():
    from copytrading.runner import _build_close_message
    trade = {"trader": "0xabcdefabcdefabcdef", "coin": "BTC", "direction": "long",
             "reason": "clôturé par le trader", "pnl_eur": 42.5}
    title, body = _build_close_message(trade)
    assert title == "🟢 COPY TRADING — position clôturée"
    assert "BTC long" in body and "+42.50" in body


def test_build_close_message_red_on_loss():
    from copytrading.runner import _build_close_message
    trade = {"trader": "0xabc", "coin": "ETH", "direction": "short",
             "reason": "retournement du trader", "pnl_eur": -10.0}
    title, _ = _build_close_message(trade)
    assert title.startswith("🔴")


def test_build_copytrading_recap_message_aggregates_opens_closes_and_pnl():
    from copytrading.runner import _build_copytrading_recap_message
    pf = mirror.new_portfolio(10000.0)
    since = datetime(2026, 7, 25, 0, tzinfo=timezone.utc)
    until = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc)

    # Un trade gagnant clôturé dans la fenêtre, ouvert dans la fenêtre.
    pf["trades"].append({
        "trader": "0xa", "coin": "BTC", "direction": "long", "size_eur": 250.0,
        "entry_price": 100000.0, "exit_price": 105000.0, "pnl_eur": 12.5,
        "opened_at": datetime(2026, 7, 25, 8, tzinfo=timezone.utc).isoformat(),
        "closed_at": datetime(2026, 7, 25, 10, tzinfo=timezone.utc).isoformat(),
        "reason": "clôturé par le trader",
    })
    # Un trade perdant clôturé dans la fenêtre.
    pf["trades"].append({
        "trader": "0xb", "coin": "ETH", "direction": "short", "size_eur": 100.0,
        "entry_price": 2000.0, "exit_price": 2100.0, "pnl_eur": -5.0,
        "opened_at": datetime(2026, 7, 25, 9, tzinfo=timezone.utc).isoformat(),
        "closed_at": datetime(2026, 7, 25, 11, tzinfo=timezone.utc).isoformat(),
        "reason": "retournement du trader",
    })
    # Une position encore ouverte, ouverte dans la fenêtre : compte comme une
    # ouverture, pas comme un gain/une perte.
    pf["positions"].append({
        "trader": "0xc", "coin": "SOL", "direction": "long", "size_eur": 50.0,
        "entry_price": 150.0, "frac": 0.1,
        "opened_at": datetime(2026, 7, 25, 12, tzinfo=timezone.utc).isoformat(),
    })

    title, body = _build_copytrading_recap_message(pf, since, until, datetime(2026, 7, 25, 18, 0))

    assert "18:00" in title
    assert "3 ouverture" in body
    assert "1 gain" in body
    assert "1 perte" in body
    assert "+7.50" in body   # 12.5 + (-5.0)


def test_build_copytrading_recap_message_excludes_trades_outside_window():
    from copytrading.runner import _build_copytrading_recap_message
    pf = mirror.new_portfolio(10000.0)
    since = datetime(2026, 7, 25, 0, tzinfo=timezone.utc)
    until = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc)

    # Clôturé la veille : hors fenêtre, ne doit pas compter.
    pf["trades"].append({
        "trader": "0xa", "coin": "BTC", "direction": "long", "size_eur": 250.0,
        "entry_price": 100000.0, "exit_price": 105000.0, "pnl_eur": 999.0,
        "opened_at": datetime(2026, 7, 24, 8, tzinfo=timezone.utc).isoformat(),
        "closed_at": datetime(2026, 7, 24, 10, tzinfo=timezone.utc).isoformat(),
        "reason": "clôturé par le trader",
    })

    title, body = _build_copytrading_recap_message(pf, since, until, datetime(2026, 7, 25, 18, 0))
    assert "0 ouverture" in body
    assert "0 gain" in body and "0 perte" in body
    assert "+0.00" in body


def test_build_copytrading_recap_message_skips_malformed_timestamps_without_crashing():
    from copytrading.runner import _build_copytrading_recap_message
    pf = mirror.new_portfolio(10000.0)
    since = datetime(2026, 7, 25, 0, tzinfo=timezone.utc)
    until = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc)

    # Trade valide, gagnant, dans la fenêtre.
    pf["trades"].append({
        "trader": "0xa", "coin": "BTC", "direction": "long", "size_eur": 250.0,
        "entry_price": 100000.0, "exit_price": 105000.0, "pnl_eur": 12.5,
        "opened_at": datetime(2026, 7, 25, 8, tzinfo=timezone.utc).isoformat(),
        "closed_at": datetime(2026, 7, 25, 10, tzinfo=timezone.utc).isoformat(),
        "reason": "clôturé par le trader",
    })
    # Trade corrompu : ne doit pas planter la fonction ni fausser l'agrégat du trade valide.
    pf["trades"].append({
        "trader": "0xb", "coin": "ETH", "direction": "short", "size_eur": 100.0,
        "entry_price": 2000.0, "exit_price": 2100.0, "pnl_eur": -5.0,
        "opened_at": "not-a-timestamp",
        "closed_at": "also-not-a-timestamp",
        "reason": "retournement du trader",
    })

    title, body = _build_copytrading_recap_message(pf, since, until, datetime(2026, 7, 25, 18, 0))
    assert "1 gain" in body
    assert "0 perte" in body
    assert "+12.50" in body


def test_scheduled_recap_slot_uses_paris_time_regardless_of_system_tz():
    """Le serveur de prod tourne en UTC (Etc/UTC) — le créneau 18h du récap
    quotidien doit rester basé sur l'heure de Paris (avec bascule été/hiver
    automatique), pas sur le fuseau système, sous peine de décalage silencieux
    de 1h à 2h (même bug corrigé le 25/07/2026 dans forex/paper/runner.py)."""
    now_paris = datetime.now(runner._PARIS_TZ)
    assert now_paris.tzinfo is not None
    assert getattr(now_paris.tzinfo, "key", None) == "Europe/Paris"
    assert now_paris.utcoffset().total_seconds() in (3600, 7200)
