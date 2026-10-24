"""
forex/data/macro.py — Récupération des données macroéconomiques via FRED API.

Récupère les taux d'intérêt, inflation (CPI), et chômage pour évaluer le biais fondamental.
Les résultats sont mis en cache dans un fichier JSON pour éviter de surcharger l'API,
les données macroéconomiques ne changeant qu'une fois par mois.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import httpx

from forex import config

logger = logging.getLogger("forex.macro")

CACHE_FILE = os.path.join(config.FOREX_DATA_DIR, "macro_cache.json")

# Mapping des séries FRED (Federal Reserve Economic Data)
# FEDFUNDS: Taux directeur USA
# IRLT: Taux d'intérêt long terme (souvent proxy du rendement obligataire)
FRED_SERIES = {
    "USD": {
        "rate": "FEDFUNDS",   # Taux Fed
        "cpi": "CPIAUCSL",    # Inflation
        "unemp": "UNRATE",    # Chômage
    },
    "EUR": {
        "rate": "ECBDFR",     # ECB Deposit Facility Rate pour Euro Area
        "cpi": "CP0000EZ19M086NEST", # HICP Euro area
        "unemp": "LRHUTTTTEZM156S", # Harmonized Unemployment Rate Euro area
    },
    "GBP": {
        "rate": "BOERUKM",    # Bank of England Official Bank Rate
        "cpi": "GBRCPIALLMINMEI",
        "unemp": "LRHUTTTTGBM156S",
    },
    "JPY": {
        "rate": "INTDSRJPM193N", # Interest Rates: Discount Rate for Japan
        "cpi": "JPNCPIALLMINMEI",
        "unemp": "LRHUTTTTJPM156S",
    }
}

class MacroDataCache:
    def __init__(self):
        self.data = {}
        self.last_update = {}
        self._load()

    def _load(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                    self.data = cache.get("data", {})
                    self.last_update = cache.get("last_update", {})
            except Exception as e:
                logger.error(f"Erreur lecture cache macro : {e}")

    def _save(self):
        try:
            os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({"data": self.data, "last_update": self.last_update}, f, indent=2)
        except Exception as e:
            logger.error(f"Erreur écriture cache macro : {e}")

    def get(self, series_id: str) -> float | None:
        """Retourne la valeur en cache si elle a moins de 24h."""
        if series_id not in self.data:
            return None
        last_dt = datetime.fromisoformat(self.last_update[series_id])
        age_hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
        if age_hours > 24: # Refresh every 24h
            return None
        return self.data[series_id]

    def set(self, series_id: str, value: float):
        self.data[series_id] = value
        self.last_update[series_id] = datetime.now(timezone.utc).isoformat()
        self._save()

_cache = MacroDataCache()

def _fetch_fred_series(series_id: str) -> float | None:
    """Récupère la dernière observation valide pour une série FRED."""
    if not config.FRED_API_KEY:
        logger.warning("Clé FRED_API_KEY manquante. Impossible de récupérer les données macro.")
        return None

    val = _cache.get(series_id)
    if val is not None:
        return val

    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": config.FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 1
    }
    try:
        r = httpx.get(url, params=params, timeout=10.0)
        r.raise_for_status()
        data = r.json()
        obs = data.get("observations", [])
        if obs and obs[0].get("value") != ".":
            val = float(obs[0]["value"])
            _cache.set(series_id, val)
            return val
    except Exception as e:
        logger.warning(f"Impossible de fetch la série FRED {series_id}: {e}")
    return None

def get_macro_data(currency: str) -> dict[str, float | None]:
    """Récupère les données macro pour une devise."""
    currency = currency.upper()
    if currency not in FRED_SERIES:
        return {"rate": None, "cpi": None, "unemp": None}
    
    return {
        "rate": _fetch_fred_series(FRED_SERIES[currency]["rate"]),
        "cpi": _fetch_fred_series(FRED_SERIES[currency]["cpi"]),
        "unemp": _fetch_fred_series(FRED_SERIES[currency]["unemp"]),
    }

def get_pair_macro_bias(pair: str) -> float:
    """
    Calcule un score de biais macroéconomique pour une paire de devises.
    Score > 0 : Biais haussier pour la devise de base (ex: long EUR/USD)
    Score < 0 : Biais baissier
    
    Logique ultra-basique (Carry Trade) :
    On compare le différentiel de taux d'intérêt.
    """
    if "_" not in pair:
        return 0.0
    base, quote = pair.split("_")
    
    base_data = get_macro_data(base)
    quote_data = get_macro_data(quote)
    
    base_rate = base_data.get("rate")
    quote_rate = quote_data.get("rate")
    
    if base_rate is None or quote_rate is None:
        return 0.0
        
    diff = base_rate - quote_rate
    
    # Normalisation empirique (un diff de 5% = score maximum)
    bias = diff / 5.0
    
    # Clamp entre -1.0 et 1.0
    return max(-1.0, min(1.0, bias))


def get_pair_macro_detail(pair: str) -> dict:
    """
    Détail du calcul de biais pour une paire : les taux de base/quote et le
    biais qui en résulte. Utilisé par le dashboard pour expliquer le chiffre
    de `get_pair_macro_bias` (dont la signature ne doit pas changer : elle est
    consommée telle quelle par `forex.strategies.macro_trend`).
    """
    if "_" not in pair:
        return {"pair": pair, "bias": 0.0, "base": None, "quote": None,
                "base_rate": None, "quote_rate": None}
    base, quote = pair.split("_")
    base_rate = get_macro_data(base).get("rate")
    quote_rate = get_macro_data(quote).get("rate")
    return {
        "pair": pair,
        "bias": get_pair_macro_bias(pair),
        "base": base,
        "quote": quote,
        "base_rate": base_rate,
        "quote_rate": quote_rate,
    }
