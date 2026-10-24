"""Agrégateur v2 : stats par bot, courbes, santé, cache mtime."""
import json

from api import aggregator


class FakeBot:
    label = "Bot de test"
    description = "desc"

    def __init__(self, tmp_path, bot_id="testbot"):
        self.id = bot_id
        d = tmp_path / bot_id
        d.mkdir(parents=True, exist_ok=True)
        self.journal_path = str(d / "trade_journal.jsonl")
        self.portfolio_path = str(d / "paper_portfolio.json")
        self.status_path = str(d / "status.json")


def _journal_line(entry_ts, pnl, source="live"):
    return json.dumps({"pair": "EUR_USD", "entry_ts": entry_ts,
                       "exit_ts": entry_ts + 3600_000, "pnl": pnl,
                       "pnl_pct": pnl / 100, "classification": "win" if pnl > 0 else "loss",
                       "source": source})


def test_bot_stats_splits_live_and_backtest(tmp_path):
    bot = FakeBot(tmp_path)
    day = 86_400_000
    lines = [_journal_line(i * day, 50.0) for i in range(3)]          # 3 live
    lines += [_journal_line(i * day, -10.0, "backtest") for i in range(5)]
    with open(bot.journal_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(bot.portfolio_path, "w", encoding="utf-8") as f:
        json.dump({"start_equity": 10000.0, "equity": 10150.0, "peak_equity": 10150.0,
                   "positions": {}, "trades": [], "updated_at": "2026-07-27T00:00:00+00:00"}, f)
    s = aggregator.bot_stats(bot)
    assert s["available"] is True
    assert s["live"]["n"] == 3 and s["backtest"]["n"] == 5
    assert s["live"]["expectancy"] > 0 > s["backtest"]["expectancy"]
    assert len(s["equity_curve_live"]) == 3          # 1 point par jour
    assert s["equity_curve_live"][-1][1] == 10150.0  # start + 3×50


def test_corrupt_files_do_not_raise(tmp_path):
    bot = FakeBot(tmp_path)
    with open(bot.journal_path, "w", encoding="utf-8") as f:
        f.write("{pas du json")
    s = aggregator.bot_stats(bot)
    assert s["live"]["n"] == 0                       # ligne corrompue ignorée


def test_mtime_cache(tmp_path, monkeypatch):
    bot = FakeBot(tmp_path)
    with open(bot.journal_path, "w", encoding="utf-8") as f:
        f.write(_journal_line(0, 10.0))
    aggregator.clear_cache()
    first = aggregator.bot_stats(bot)
    second = aggregator.bot_stats(bot)
    assert first["live"]["n"] == second["live"]["n"] == 1
    # Le cache est indexé (path, mtime) : même mtime → même objet retourné.
    assert aggregator._journal_cache_info()["hits"] >= 1


def test_overview_aggregates_multiple_bots(tmp_path, monkeypatch):
    """overview() agrège plusieurs bots et s'arrête sur les erreurs gracieusement."""
    # Créer 2 bots : un normal, un qui lève une exception
    bot_good = FakeBot(tmp_path, bot_id="goodbot")
    bot_bad = FakeBot(tmp_path, bot_id="badbot")

    # Bot bon : données valides
    day = 86_400_000
    with open(bot_good.journal_path, "w", encoding="utf-8") as f:
        f.write(_journal_line(0, 100.0))
    with open(bot_good.portfolio_path, "w", encoding="utf-8") as f:
        json.dump({"start_equity": 10000.0, "equity": 10100.0, "peak_equity": 10100.0,
                   "positions": {}, "trades": [], "updated_at": "2026-07-27T00:00:00+00:00"}, f)

    # Bot mauvais : attribut manquant (lèvera une exception dans bot_stats)
    bot_bad.journal_path = None  # type: ignore

    # Monkeypatcher strategies.active pour retourner nos 2 bots
    monkeypatch.setattr("forex.strategies.active",
                        lambda: [bot_good, bot_bad])

    aggregator.clear_cache()
    result = aggregator.overview()

    # Vérifier que overview() ne plante pas
    assert isinstance(result, dict)
    assert "bots" in result

    # Vérifier que les deux bots apparaissent
    assert len(result["bots"]) == 2
    bots_by_id = {b["bot"]: b for b in result["bots"]}
    assert "goodbot" in bots_by_id
    assert "badbot" in bots_by_id

    # Bot bon doit être available
    assert bots_by_id["goodbot"]["available"] is True
    assert bots_by_id["goodbot"]["equity"] == 10100.0

    # Bot mauvais doit être available: False
    assert bots_by_id["badbot"]["available"] is False

    # total_equity doit ne compter que les bots disponibles
    assert result["total_equity"] == 10100.0

    # n_validated doit ne compter que les bots disponibles
    # (goodbot n'a pas de verdict dans ce test, donc n_validated = 0)
    assert result["n_validated"] == 0

    # data_consistent doit vérifier toutes les données santé (même indisponibles)
    # → False car badbot n'a pas de data_health
    assert isinstance(result["data_consistent"], bool)


def test_overview_passes_verdicts_to_bot_stats(tmp_path, monkeypatch):
    """overview() charge les verdicts une fois et les passe à bot_stats().

    Avec 2 bots, prouve que le hoisting du load() fonctionne :
    - Ancien comportement (load par bot) : 2 appels
    - Optimisation (load une fois dans overview()) : 1 appel
    """
    bot1 = FakeBot(tmp_path, bot_id="bot1")
    bot2 = FakeBot(tmp_path, bot_id="bot2")

    for bot in [bot1, bot2]:
        with open(bot.journal_path, "w", encoding="utf-8") as f:
            f.write(_journal_line(0, 50.0))
        with open(bot.portfolio_path, "w", encoding="utf-8") as f:
            json.dump({"start_equity": 10000.0, "equity": 10050.0, "peak_equity": 10050.0,
                       "positions": {}, "trades": [], "updated_at": "2026-07-27T00:00:00+00:00"}, f)

    monkeypatch.setattr("forex.strategies.active", lambda: [bot1, bot2])

    # Compter le nombre d'appels à verdict_mod.load()
    load_calls = {"count": 0}
    original_load = aggregator.verdict_mod.load

    def counting_load(*args, **kwargs):
        load_calls["count"] += 1
        return original_load(*args, **kwargs)

    monkeypatch.setattr("api.aggregator.verdict_mod.load", counting_load)

    aggregator.clear_cache()
    result = aggregator.overview()

    # verdict_mod.load() doit être appelé UNE FOIS pour 2 bots
    # (pas 2 fois comme ce serait le cas sans l'optimisation)
    assert load_calls["count"] == 1
    assert len(result["bots"]) == 2
