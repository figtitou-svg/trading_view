"""Endpoints de réglages de notification — déplacés de main.py à l'identique (spec 2026-07-27)."""
import json as _json
import os as _os

from fastapi import APIRouter, HTTPException, Request

from utils.logger import logger
from services.notification_settings import (
    DEFAULTS as _NOTIF_DEFAULTS,
    SETTINGS_PATH as _NOTIF_SETTINGS_PATH,
    load_notification_settings as _load_notification_settings,
)

router = APIRouter()

_NOTIF_MODES = {"detailed", "daily_recap"}
_NOTIF_MODE_KEYS = ("forex_mode", "copytrading_mode")
_NOTIF_BOOL_KEYS = ("forex_entries_enabled", "forex_exits_enabled", "forex_ranking_enabled")


def _validate_notification_settings(payload) -> dict:
    """Valide la forme du payload de réglages ; lève HTTPException si invalide."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload invalide")
    settings = dict(_NOTIF_DEFAULTS)
    for key in _NOTIF_MODE_KEYS:
        mode = payload.get(key, _NOTIF_DEFAULTS[key])
        if mode not in _NOTIF_MODES:
            raise HTTPException(status_code=400, detail=f"{key} invalide : {mode!r}")
        settings[key] = mode
    for key in _NOTIF_BOOL_KEYS:
        if key in payload:
            if not isinstance(payload[key], bool):
                raise HTTPException(status_code=400, detail=f"{key} doit être un booléen")
            settings[key] = payload[key]
    return settings


@router.get("/api/settings/notifications")
async def get_notification_settings():
    """Réglages de notification actuels (valeurs par défaut si jamais modifiés)."""
    return _load_notification_settings()


@router.post("/api/settings/notifications")
async def set_notification_settings(request: Request):
    """Enregistre les réglages de notification (pris en compte au prochain poll)."""
    payload = await request.json()
    settings = _validate_notification_settings(payload)
    _os.makedirs(_os.path.dirname(_NOTIF_SETTINGS_PATH), exist_ok=True)
    tmp = _NOTIF_SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(settings, f, ensure_ascii=False, indent=2)
    _os.replace(tmp, _NOTIF_SETTINGS_PATH)
    logger.info(f"⚙️ Réglages de notification mis à jour : {settings}")
    return settings
