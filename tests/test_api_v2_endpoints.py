"""Endpoints /api/v2 (TestClient sur l'app réelle)."""
from fastapi.testclient import TestClient

from main import app

client = TestClient(app, raise_server_exceptions=False)


def test_overview_shape():
    r = client.get("/api/v2/overview")
    assert r.status_code == 200
    body = r.json()
    for key in ("runner_active", "total_equity", "equity_curve", "bots",
                "data_consistent", "n_validated"):
        assert key in body


def test_bot_detail_404_for_unknown():
    assert client.get("/api/v2/bots/nexistepas").status_code == 404


def test_bot_trades_pagination_shape():
    r = client.get("/api/v2/bots/nexistepas/trades")
    assert r.status_code == 404


def test_candles_filters_pairs():
    r = client.get("/api/v2/candles?pair=EUR_USD")
    assert r.status_code == 200
    assert set(r.json().keys()) <= {"EUR_USD"}


def test_calendar_and_macro():
    assert client.get("/api/v2/calendar").status_code == 200
    assert client.get("/api/v2/macro").status_code == 200


def test_bot_trades_source_invalid_returns_422():
    """source=invalid doit retourner 422 (validation Literal)."""
    r = client.get("/api/v2/bots/macro/trades?source=invalid")
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"


def test_bot_trades_source_case_sensitive_returns_422():
    """source=Live (casse différente) doit retourner 422."""
    r = client.get("/api/v2/bots/macro/trades?source=Live")
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"


def test_bot_trades_page_size_boundary_returns_422():
    """page_size=201 (> max 200) doit retourner 422."""
    r = client.get("/api/v2/bots/macro/trades?page_size=201")
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"


def test_candles_with_from_ts_handles_malformed_gracefully(tmp_path, monkeypatch):
    """Malformed candles (empty lists, missing fields) ne doivent pas faire crasher."""
    import json
    candles_file = tmp_path / "forex_candles.json"
    # Crée des bougies malformées : [], [1000], [1000, 1.1, 1.2, "invalid"], etc.
    bad_candles = {
        "EUR_USD": [
            [],                              # liste vide
            [1000, 1.1],                     # incomplet mais valide
            [2000, 1.2, 1.3, 1.4, 1.5],      # valide
        ],
        "GBP_USD": [
            [3000, 1.5, 1.6, 1.7, 1.8],      # valide
        ],
    }
    candles_file.write_text(json.dumps(bad_candles), encoding="utf-8")

    # Monkeypath le chemin des bougies
    from api.routers import forex_v2
    monkeypatch.setattr(forex_v2, "_CANDLES_PATH", str(candles_file))

    # L'endpoint ne doit pas crasher
    r = client.get("/api/v2/candles?pair=EUR_USD,GBP_USD&from_ts=1500")
    assert r.status_code == 200
    body = r.json()
    # Les bougies vides et incomplètes sont filtrées, seules les valides >= from_ts restent
    assert "EUR_USD" in body
    assert "GBP_USD" in body
    # EUR_USD : [2000, ...] est >= 1500
    assert len(body["EUR_USD"]) == 1
    # GBP_USD : [3000, ...] est >= 1500
    assert len(body["GBP_USD"]) == 1
