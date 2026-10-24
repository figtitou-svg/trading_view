"""Tests de l'endpoint de suppression d'un bot forex depuis le dashboard."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
import forex.strategies as strategies
from api.routers import forex_v1

_FAKE_BOTS = [
    SimpleNamespace(id="macro"),
    SimpleNamespace(id="macro__trailing"),
    SimpleNamespace(id="chartist+macro"),
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(forex_v1, "_FOREX_CACHE", str(tmp_path))
    monkeypatch.setattr(strategies, "active", lambda: _FAKE_BOTS)
    return TestClient(main.app)


def test_disable_unknown_bot_returns_404(client, tmp_path):
    r = client.post("/api/forex/bots/does-not-exist/disable")
    assert r.status_code == 404
    assert not (tmp_path / "disabled_bots.json").exists()


def test_disable_known_bot_writes_disabled_list(client, tmp_path):
    r = client.post("/api/forex/bots/macro__trailing/disable")
    assert r.status_code == 200
    assert r.json()["disabled"] == ["macro__trailing"]
    on_disk = json.loads((tmp_path / "disabled_bots.json").read_text(encoding="utf-8"))
    assert on_disk == ["macro__trailing"]


def test_disable_twice_does_not_duplicate(client):
    client.post("/api/forex/bots/macro/disable")
    r = client.post("/api/forex/bots/macro/disable")
    assert r.json()["disabled"] == ["macro"]


def test_disable_combo_bot_id_with_plus_character(client):
    r = client.post("/api/forex/bots/chartist%2Bmacro/disable")
    assert r.status_code == 200
    assert r.json()["disabled"] == ["chartist+macro"]


def test_disable_preserves_previously_disabled_ids(client, tmp_path):
    client.post("/api/forex/bots/macro/disable")
    r = client.post("/api/forex/bots/macro__trailing/disable")
    assert set(r.json()["disabled"]) == {"macro", "macro__trailing"}


@pytest.fixture
def candles_client(tmp_path, monkeypatch):
    candles_path = tmp_path / "forex_candles.json"
    candles_path.write_text(json.dumps({
        "EUR_USD": [[1000, 1.1, 1.2, 1.0, 1.15]],
        "GBP_USD": [[1000, 1.3, 1.4, 1.2, 1.35]],
        "USD_JPY": [[1000, 150.0, 151.0, 149.0, 150.5]],
    }), encoding="utf-8")
    monkeypatch.setattr(forex_v1, "_FOREX_CANDLES", str(candles_path))
    return TestClient(main.app)


def test_candles_unfiltered_returns_every_pair(candles_client):
    r = candles_client.get("/api/forex/candles")
    assert set(r.json().keys()) == {"EUR_USD", "GBP_USD", "USD_JPY"}


def test_candles_single_pair_filters_to_that_pair(candles_client):
    r = candles_client.get("/api/forex/candles?pair=eur_usd")
    assert r.json() == {"EUR_USD": [[1000, 1.1, 1.2, 1.0, 1.15]]}


def test_candles_multiple_pairs_comma_separated(candles_client):
    r = candles_client.get("/api/forex/candles?pair=EUR_USD,USD_JPY")
    assert set(r.json().keys()) == {"EUR_USD", "USD_JPY"}


def test_candles_unknown_pair_returns_empty_list(candles_client):
    r = candles_client.get("/api/forex/candles?pair=XAU_USD")
    assert r.json() == {"XAU_USD": []}
