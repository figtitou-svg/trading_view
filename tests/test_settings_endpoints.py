"""Tests des endpoints de réglages de notification (main.py)."""

import json

import pytest
from fastapi.testclient import TestClient

import main
from api.routers import settings as settings_router
from services.notification_settings import DEFAULTS


@pytest.fixture
def client(tmp_path, monkeypatch):
    import services.notification_settings as notification_settings_module

    path = str(tmp_path / "notification_settings.json")
    monkeypatch.setattr(settings_router, "_NOTIF_SETTINGS_PATH", path)
    monkeypatch.setattr(notification_settings_module, "SETTINGS_PATH", path)
    return TestClient(main.app), path


def test_get_returns_defaults_when_nothing_saved(client):
    c, _ = client
    assert c.get("/api/settings/notifications").json() == DEFAULTS


def test_post_then_get_roundtrip(client):
    c, path = client
    payload = {"forex_mode": "daily_recap", "forex_entries_enabled": False}
    r = c.post("/api/settings/notifications", json=payload)
    assert r.status_code == 200
    assert r.json()["forex_mode"] == "daily_recap"
    assert r.json()["forex_entries_enabled"] is False
    assert r.json()["forex_exits_enabled"] is True  # défaut préservé

    with open(path, encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["forex_mode"] == "daily_recap"

    assert c.get("/api/settings/notifications").json() == r.json()


def test_post_rejects_invalid_mode(client):
    c, _ = client
    r = c.post("/api/settings/notifications", json={"forex_mode": "bogus"})
    assert r.status_code == 400


def test_post_rejects_non_boolean_toggle(client):
    c, _ = client
    r = c.post("/api/settings/notifications", json={"forex_entries_enabled": "yes"})
    assert r.status_code == 400


def test_post_rejects_non_dict_payload(client):
    c, _ = client
    r = c.post("/api/settings/notifications", content=b"null",
              headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_get_returns_defaults_when_file_contains_non_dict_json(client):
    c, path = client
    with open(path, "w", encoding="utf-8") as f:
        f.write('"oops-not-a-dict"')
    assert c.get("/api/settings/notifications").json() == DEFAULTS


def test_second_post_resets_unspecified_keys_to_defaults_not_prior_values(client):
    """La sémantique est un remplacement complet à chaque POST, pas une fusion
    avec la précédente sauvegarde : une clé omise dans un second POST doit
    revenir à sa valeur par défaut, pas conserver la valeur du premier POST."""
    c, _ = client
    c.post("/api/settings/notifications", json={
        "forex_entries_enabled": False,
        "forex_exits_enabled": False,
        "forex_ranking_enabled": False,
    })
    r = c.post("/api/settings/notifications", json={"forex_mode": "daily_recap"})
    assert r.status_code == 200
    assert r.json()["forex_entries_enabled"] is True   # revenu au défaut, pas resté False
    assert r.json()["forex_exits_enabled"] is True
    assert r.json()["forex_ranking_enabled"] is True
    assert r.json()["forex_mode"] == "daily_recap"


def test_post_rejects_invalid_copytrading_mode(client):
    c, _ = client
    r = c.post("/api/settings/notifications", json={"copytrading_mode": "bogus"})
    assert r.status_code == 400


def test_post_then_get_roundtrip_copytrading_mode(client):
    c, _ = client
    r = c.post("/api/settings/notifications", json={"copytrading_mode": "daily_recap"})
    assert r.status_code == 200
    assert r.json()["copytrading_mode"] == "daily_recap"
    assert c.get("/api/settings/notifications").json()["copytrading_mode"] == "daily_recap"


def test_second_post_resets_copytrading_mode_to_default(client):
    c, _ = client
    c.post("/api/settings/notifications", json={"copytrading_mode": "daily_recap"})
    r = c.post("/api/settings/notifications", json={"forex_mode": "daily_recap"})
    assert r.status_code == 200
    assert r.json()["copytrading_mode"] == "detailed"


def test_post_sets_forex_and_copytrading_mode_independently(client):
    c, _ = client
    r = c.post("/api/settings/notifications", json={
        "forex_mode": "daily_recap",
        "copytrading_mode": "detailed",
    })
    assert r.status_code == 200
    assert r.json()["forex_mode"] == "daily_recap"
    assert r.json()["copytrading_mode"] == "detailed"
