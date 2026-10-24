"""
Tests des fonctions pures ajoutées à forex/data/calendar.py pour le dashboard :
score d'importance 0→5 (dérivé du champ `impact` brut) et explication en
langage simple d'une annonce (glossaire local avec repli générique).
"""

from forex.data.calendar import importance_score, explain_event


def test_importance_score_mapping():
    assert importance_score("High") == 5
    assert importance_score("Medium") == 3
    assert importance_score("Low") == 1
    assert importance_score("Holiday") == 0


def test_importance_score_unknown_impact_defaults_to_zero():
    assert importance_score("") == 0
    assert importance_score(None) == 0
    assert importance_score("n'importe quoi") == 0


def test_explain_event_known_terms():
    assert "inflation" in explain_event("CPI y/y").lower()
    assert "emplois" in explain_event("Non-Farm Employment Change").lower()


def test_explain_event_unknown_term_has_generic_fallback():
    text = explain_event("Un titre totalement inconnu")
    assert text
    assert "annonce économique" in text.lower()
