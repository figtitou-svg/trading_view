"""Tests des réglages de notification partagés (services/notification_settings.py)."""

import json

from services import notification_settings as ns


def test_load_returns_defaults_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ns, "SETTINGS_PATH", str(tmp_path / "missing.json"))
    assert ns.load_notification_settings() == ns.DEFAULTS


def test_load_merges_saved_values_over_defaults(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(ns, "SETTINGS_PATH", str(path))
    path.write_text(json.dumps({"forex_mode": "daily_recap", "forex_entries_enabled": False}),
                    encoding="utf-8")
    settings = ns.load_notification_settings()
    assert settings["forex_mode"] == "daily_recap"
    assert settings["forex_entries_enabled"] is False
    assert settings["forex_exits_enabled"] is True  # valeur par défaut préservée


def test_load_returns_defaults_on_corrupt_file(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(ns, "SETTINGS_PATH", str(path))
    path.write_text("{not valid json", encoding="utf-8")
    assert ns.load_notification_settings() == ns.DEFAULTS


def test_defaults_are_not_mutated_by_load(tmp_path, monkeypatch):
    """load_notification_settings() ne doit jamais renvoyer l'objet DEFAULTS
    lui-même : un appelant qui muterait le retour ne doit pas corrompre le
    module pour le reste du process."""
    monkeypatch.setattr(ns, "SETTINGS_PATH", str(tmp_path / "missing.json"))
    result = ns.load_notification_settings()
    result["forex_mode"] = "daily_recap"
    assert ns.DEFAULTS["forex_mode"] == "detailed"


def test_load_returns_defaults_when_file_contains_a_non_dict_value(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(ns, "SETTINGS_PATH", str(path))
    path.write_text("[1, 2, 3]", encoding="utf-8")  # JSON valide, mais pas un objet
    assert ns.load_notification_settings() == ns.DEFAULTS
