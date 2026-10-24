"""
forex/data/calendar.py — Calendrier économique (données Forex Factory).

Source : le flux JSON public de faireconomy (mêmes données que le calendrier
Forex Factory), bien plus robuste qu'un scraping HTML :
    https://nfs.faireconomy.media/ff_calendar_thisweek.json

Chaque semaine fournit `forecast`/`previous` et, une fois l'annonce tombée,
`actual`. Le surprise score (forex.signals.fundamental) a besoin d'un
**historique** de surprises passées : on accumule donc les events dans un CSV
local (FOREX_DATA_DIR/economic_calendar.csv) au fil des refresh, et on peut
aussi y importer un CSV historique fourni.

Aucun credential requis. En cas d'échec réseau, on retombe sur le cache CSV.
"""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import httpx

from forex import config

# Seul le flux "cette semaine" est publié de façon fiable sur ce host ; on
# accumule l'historique semaine après semaine dans le CSV local (merge_into_history).
FEED_URLS = {
    "thisweek": "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
}

_HEADERS = {"User-Agent": "Mozilla/5.0 (forex-research-bot; paper-trading)"}

CSV_PATH = os.path.join(config.FOREX_DATA_DIR, "economic_calendar.csv")

_MAJOR_CCYS = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}


@dataclass
class EconEvent:
    """Un événement macro normalisé (horodaté en UTC)."""
    dt: datetime          # date/heure UTC de l'annonce
    currency: str         # 'USD', 'EUR'…
    title: str            # 'CPI y/y', 'Non-Farm Employment Change'…
    impact: str           # 'High' / 'Medium' / 'Low' / 'Holiday'
    actual: float | None
    forecast: float | None
    previous: float | None

    @property
    def has_result(self) -> bool:
        return self.actual is not None and self.forecast is not None

    def event_type(self) -> str:
        """Type générique (sans suffixe m/m, y/y…) pour regrouper les surprises."""
        base = re.sub(r"\b(y/y|m/m|q/q)\b", "", self.title, flags=re.I)
        return base.strip().rstrip(":").strip()


def parse_value(raw) -> float | None:
    """
    Convertit une valeur du calendrier en float.
    Gère '%', 'K'→×1e3, 'M'→×1e6, 'B'→×1e9, '<', '>', virgules, vide.
    '3.2%' → 3.2 · '236K' → 236000 · '-0.1' → -0.1 · '' → None
    """
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace("%", "").replace("<", "").replace(">", "")
    if s == "" or s.upper() in {"N/A", "NA"}:
        return None
    mult = 1.0
    if s and s[-1] in "KkMmBbTt":
        mult = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[s[-1].upper()]
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def _parse_feed_json(items: list[dict]) -> list[EconEvent]:
    events: list[EconEvent] = []
    for it in items:
        try:
            dt = datetime.fromisoformat(it["date"]).astimezone(timezone.utc)
        except (KeyError, ValueError):
            continue
        events.append(EconEvent(
            dt=dt,
            currency=str(it.get("country", "")).upper(),
            title=str(it.get("title", "")).strip(),
            impact=str(it.get("impact", "")).strip().title(),
            actual=parse_value(it.get("actual")),
            forecast=parse_value(it.get("forecast")),
            previous=parse_value(it.get("previous")),
        ))
    return events


def fetch_feed(which: str = "thisweek", timeout: float = 10.0) -> list[EconEvent]:
    """Télécharge un flux hebdomadaire (thisweek/nextweek/lastweek)."""
    url = FEED_URLS[which]
    resp = httpx.get(url, headers=_HEADERS, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return _parse_feed_json(resp.json())


# ── Persistance CSV (historique cumulé) ──────────────────

_CSV_FIELDS = ["dt", "currency", "title", "impact", "actual", "forecast", "previous"]


def _event_key(e: EconEvent) -> tuple:
    return (e.dt.isoformat(), e.currency, e.title)


def load_events(path: str = CSV_PATH) -> list[EconEvent]:
    """Charge l'historique depuis le CSV (vide si absent)."""
    if not os.path.exists(path):
        return []
    out: list[EconEvent] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                dt = datetime.fromisoformat(row["dt"])
            except (KeyError, ValueError):
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            out.append(EconEvent(
                dt=dt.astimezone(timezone.utc),
                currency=row.get("currency", "").upper(),
                title=row.get("title", ""),
                impact=row.get("impact", ""),
                actual=parse_value(row.get("actual")),
                forecast=parse_value(row.get("forecast")),
                previous=parse_value(row.get("previous")),
            ))
    return out


def save_events(events: list[EconEvent], path: str = CSV_PATH) -> None:
    """Écrit la liste d'events dans le CSV (triée par date)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    events = sorted(events, key=lambda e: e.dt)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        w.writeheader()
        for e in events:
            row = asdict(e)
            row["dt"] = e.dt.isoformat()
            w.writerow(row)


def merge_into_history(new_events: list[EconEvent], path: str = CSV_PATH) -> int:
    """
    Fusionne des events dans l'historique CSV. Un event déjà présent est mis à
    jour si le nouveau porte un `actual` que l'ancien n'avait pas (l'annonce est
    tombée depuis). Retourne le nombre d'events ajoutés/mis à jour.
    """
    existing = {_event_key(e): e for e in load_events(path)}
    changed = 0
    for e in new_events:
        k = _event_key(e)
        if k not in existing:
            existing[k] = e
            changed += 1
        elif existing[k].actual is None and e.actual is not None:
            existing[k] = e
            changed += 1
    if changed:
        save_events(list(existing.values()), path)
    return changed


def refresh(path: str = CSV_PATH) -> int:
    """Récupère last/this/next week et fusionne dans l'historique. → nb de changements."""
    total = 0
    collected: list[EconEvent] = []
    for which in FEED_URLS:
        try:
            collected.extend(fetch_feed(which))
        except Exception as exc:  # réseau indisponible : on garde ce qu'on a
            print(f"[calendar] échec {which}: {exc}")
    if collected:
        total = merge_into_history(collected, path)
    return total


def get_events(
    currency: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    impact: str | None = None,
    path: str = CSV_PATH,
) -> list[EconEvent]:
    """Filtre l'historique par devise / fenêtre temporelle / impact."""
    events = load_events(path)
    out = []
    for e in events:
        if currency and e.currency != currency.upper():
            continue
        if impact and e.impact.lower() != impact.lower():
            continue
        if start and e.dt < start:
            continue
        if end and e.dt > end:
            continue
        out.append(e)
    return sorted(out, key=lambda e: e.dt)


# ── Dashboard : score d'importance + explication en langage simple ──

IMPORTANCE_SCORE = {"high": 5, "medium": 3, "low": 1, "holiday": 0}


def importance_score(impact: str | None) -> int:
    """Score 0→5 dérivé du champ `impact` brut (High/Medium/Low/Holiday)."""
    return IMPORTANCE_SCORE.get((impact or "").strip().lower(), 0)


# Glossaire local, volontairement minimal : quelques mots-clés fréquents plutôt
# qu'une couverture exhaustive. Repli sur un texte générique si le titre ne
# matche rien — mieux qu'un plantage ou un champ vide.
_EVENT_GLOSSARY: dict[str, str] = {
    "cpi": ("Indice des prix à la consommation (inflation). Plus haut que prévu → "
            "souvent haussier pour la devise (la banque centrale pourrait monter ses taux)."),
    "non-farm": ("Emplois créés hors secteur agricole aux États-Unis. Un chiffre fort "
                 "renforce généralement le dollar."),
    "nfp": ("Emplois créés hors secteur agricole aux États-Unis. Un chiffre fort "
            "renforce généralement le dollar."),
    "pmi": ("Indice des directeurs d'achat (activité manufacturière/services). "
            "Au-dessus de 50 = expansion, en dessous = contraction."),
    "gdp": ("Produit intérieur brut : mesure de la croissance économique. Une "
            "croissance plus forte que prévu est généralement haussière pour la devise."),
    "retail sales": ("Ventes au détail : indicateur de la consommation des ménages. "
                     "Plus fort que prévu → souvent haussier."),
    "interest rate": ("Décision de taux directeur de la banque centrale. Une hausse "
                      "de taux est généralement haussière pour la devise."),
    "unemployment": ("Taux de chômage. Une baisse est généralement haussière pour la "
                     "devise (économie plus solide)."),
    "trade balance": ("Différence entre exportations et importations. Un excédent "
                      "plus important est généralement haussier."),
}


def explain_event(title: str | None) -> str:
    """
    Explication en langage simple d'une annonce, par mot-clé (repli sur un
    texte générique si le titre n'est reconnu par aucun mot-clé du glossaire).
    """
    key = (title or "").lower()
    for kw, text in _EVENT_GLOSSARY.items():
        if kw in key:
            return text
    return ("Annonce économique — l'impact précis sur le marché dépend de l'écart "
           "entre le chiffre réel et la prévision.")


def _cli() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Calendrier économique forex")
    ap.add_argument("--refresh", action="store_true", help="Rafraîchir depuis le flux et fusionner dans le cache")
    ap.add_argument("--show", metavar="CCY", nargs="?", const="", help="Afficher les events (option: devise)")
    args = ap.parse_args()

    if args.refresh:
        n = refresh()
        print(f"Calendrier rafraîchi : {n} event(s) ajouté(s)/mis à jour → {CSV_PATH}")
    if args.show is not None:
        ccy = args.show or None
        events = get_events(currency=ccy)
        print(f"{len(events)} event(s) dans l'historique" + (f" pour {ccy}" if ccy else ""))
        for e in events[-30:]:
            res = f"a={e.actual} f={e.forecast} p={e.previous}" if e.has_result else "(pas de résultat)"
            print(f"  {e.dt:%Y-%m-%d %H:%M} {e.currency:3} [{e.impact:6}] {e.title} — {res}")


if __name__ == "__main__":
    _cli()
