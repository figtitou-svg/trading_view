"""
Tests des identifiants de séries FRED (forex/data/macro.py).

Ces séries sont des chaînes arbitraires côté FRED : une faute de frappe s'y
glisse silencieusement (le code importe et tourne sans erreur), et ne se
révèle qu'au premier appel réseau en prod (log d'avertissement, biais macro
resté à 0.0). CP0000EZ19M086NESA (inflation zone euro) contenait exactement
ce genre de coquille — vérifiée le 21/07/2026 directement contre l'API FRED :
NESA n'existe pas, NEST est la série active (confirmée en retournant des
données à jour). Ce test fige les valeurs correctes pour empêcher une
régression silencieuse.
"""

import pytest

from forex.data.macro import FRED_SERIES


def test_eur_cpi_series_id_is_the_valid_one():
    assert FRED_SERIES["EUR"]["cpi"] == "CP0000EZ19M086NEST"


def test_all_series_ids_are_non_empty_strings():
    for currency, series in FRED_SERIES.items():
        for kind, series_id in series.items():
            assert isinstance(series_id, str) and series_id, (
                f"{currency}.{kind} series id vide ou invalide : {series_id!r}"
            )


def test_get_pair_macro_detail_computes_bias_and_rates(monkeypatch):
    from forex.data import macro as macro_mod

    def fake_get_macro_data(currency):
        return {"USD": {"rate": 5.0}, "EUR": {"rate": 3.0}}.get(currency, {"rate": None})

    monkeypatch.setattr(macro_mod, "get_macro_data", fake_get_macro_data)

    detail = macro_mod.get_pair_macro_detail("EUR_USD")
    assert detail["pair"] == "EUR_USD"
    assert detail["base"] == "EUR"
    assert detail["quote"] == "USD"
    assert detail["base_rate"] == 3.0
    assert detail["quote_rate"] == 5.0
    assert detail["bias"] == pytest.approx(-0.4)  # (3.0 - 5.0) / 5.0


def test_get_pair_macro_detail_missing_rate_returns_none_rates(monkeypatch):
    from forex.data import macro as macro_mod

    monkeypatch.setattr(macro_mod, "get_macro_data", lambda ccy: {"rate": None})

    detail = macro_mod.get_pair_macro_detail("AUD_CAD")
    assert detail["base_rate"] is None
    assert detail["quote_rate"] is None
    assert detail["bias"] == 0.0
