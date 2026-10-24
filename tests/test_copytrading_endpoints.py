"""Tests des endpoints copy trading (cache pointé vers un dossier temporaire)."""

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main
from api.routers import copytrading

ADDR = "0x" + "a" * 40


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(copytrading, "_COPY_CACHE", str(tmp_path))
    return TestClient(main.app)


def _write(tmp_path, name, payload):
    (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")


def test_follow_unfollow_roundtrip(client, tmp_path):
    r = client.post(f"/api/copytrading/follow/{ADDR.upper()}")
    assert r.status_code == 200
    assert r.json()["follows"] == [ADDR]          # normalisée en minuscules
    assert json.loads((tmp_path / "follows.json").read_text())["follows"] == [ADDR]
    r = client.post(f"/api/copytrading/unfollow/{ADDR}")
    assert r.json()["follows"] == []


def test_follow_adresse_invalide(client):
    assert client.post("/api/copytrading/follow/abc").status_code == 400
    assert client.post("/api/copytrading/follow/0xZZ").status_code == 400


def test_status(client, tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    _write(tmp_path, "candidates.json", {"updated_at": now, "candidates": [
        {"address": ADDR, "account_value": 100000.0,
         "roi_week": 0.05, "roi_month": 0.2}]})
    _write(tmp_path, "follows.json", {"follows": [ADDR]})
    _write(tmp_path, "portfolio.json", {"updated_at": now, "start_equity": 10000.0,
                                        "equity": 10100.0, "positions": [], "trades": []})
    data = client.get("/api/copytrading/status").json()
    assert data["available"] is True
    assert data["runner_active"] is True
    assert data["candidates"][0]["followed"] is True
    assert data["follows"] == [ADDR]


def test_status_sans_runner(client):
    data = client.get("/api/copytrading/status").json()
    assert data["available"] is False and data["runner_active"] is False


def test_portfolio(client, tmp_path):
    trades = [{"coin": f"C{i}", "pnl_eur": i} for i in range(60)]
    _write(tmp_path, "portfolio.json", {
        "updated_at": "2026-07-23T12:00:00+00:00", "start_equity": 10000.0,
        "equity": 10500.0, "positions": [], "trades": trades,
        "equity_history": [[1, 10000.0]]})
    data = client.get("/api/copytrading/portfolio").json()
    assert data["return_pct"] == 5.0
    assert len(data["trades"]) == 50
    assert data["trades"][0]["coin"] == "C59"     # plus récents d'abord
