"""
forex/signals/macro.py — Modèle macro quotidien (refonte du signal fondamental).

L'ancien signal (`forex.signals.fundamental`) est **event-driven** : il n'a un
avis que dans la petite fenêtre suivant une annonce économique, et seulement si
l'historique du calendrier permet de normaliser la surprise. En pratique il ne
s'exprimait presque jamais.

Ce modèle-ci raisonne en **score de devise**, recalculable à chaque barre à
partir de données disponibles tous les jours. Quatre contributions, chacune
motivée par un mécanisme économique connu (pas de facteur choisi au hasard) :

1. **Force relative** — performance récente de chaque devise, déduite de la
   matrice des paires déjà téléchargées par le runner (coût réseau NUL). Une
   devise qui monte contre toutes les autres est fondamentalement demandée.

2. **Régime de risque** — le VIX et l'or mesurent l'appétit pour le risque.
   En stress (risk-off), les capitaux fuient vers le JPY et le CHF et
   abandonnent les devises à haut bêta (AUD, NZD). C'est l'une des relations
   les plus stables du marché des changes.

3. **Différentiel de taux** — le rendement du 10 ans US pilote le USD :
   des taux qui montent attirent les capitaux vers le dollar (carry).

4. **Lien matières premières** — le CAD suit le pétrole (le Canada est
   exportateur net), l'AUD suit globalement les matières premières.

La **surprise macro événementielle** est conservée, mais rétrogradée en
BONUS ponctuel : quand une vraie surprise est mesurable, elle renforce ou
contredit le score du jour, au lieu d'être la seule condition d'existence du
signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from forex import config
from forex.data.calendar import EconEvent
from forex.signals.fundamental import fundamental_signal

# Devises refuges (montent quand le marché a peur) et devises à haut bêta
# (sensibles au cycle, chutent en stress).
_SAFE_HAVENS = {"JPY": 1.0, "CHF": 1.0, "USD": 0.5}
_RISK_CURRENCIES = {"AUD": 1.0, "NZD": 1.0, "CAD": 0.6}
# Sensibilité au pétrole (exportateurs nets).
_OIL_SENSITIVITY = {"CAD": 1.0, "NOK": 1.0}


@dataclass
class MacroResult:
    direction: str | None
    strength: float
    reason: str
    score: float = 0.0
    components: dict = field(default_factory=dict)


def currency_strength(
    candles_by_pair: dict[str, list[list[float]]],
    *,
    bars: int = config.FOREX_MACRO_STRENGTH_BARS,
) -> dict[str, float]:
    """
    Score de force par devise : moyenne de ses variations en % sur `bars`
    barres, à travers TOUTES les paires où elle apparaît.

    Pour une paire BASE_QUOTE qui monte de x %, la base gagne +x et la quote
    perd -x. Moyenner sur plusieurs paires isole la devise du bruit propre à
    une paire donnée — c'est la construction classique d'un indice de force.
    """
    totals: dict[str, list[float]] = {}
    for pair, candles in (candles_by_pair or {}).items():
        if not candles or len(candles) <= bars:
            continue
        try:
            base, quote = pair.upper().split("_")
        except ValueError:
            continue
        now_price, past_price = candles[-1][4], candles[-1 - bars][4]
        if not past_price:
            continue
        chg = (now_price / past_price - 1) * 100
        totals.setdefault(base, []).append(chg)
        totals.setdefault(quote, []).append(-chg)
    return {ccy: round(sum(v) / len(v), 4) for ccy, v in totals.items() if v}


def risk_regime(cross: dict) -> tuple[str | None, float]:
    """
    Régime de risque déduit du VIX (et confirmé par l'or).
    Retourne ('risk-off' | 'risk-on' | None, intensité 0→1).
    """
    vix = (cross or {}).get("vix") or {}
    gold = (cross or {}).get("gold") or {}
    vix_chg = vix.get("change_pct")
    if vix_chg is None:
        return None, 0.0

    gold_chg = gold.get("change_pct", 0.0) or 0.0
    threshold = config.FOREX_MACRO_VIX_THRESHOLD_PCT
    if vix_chg >= threshold:
        # L'or qui monte en même temps confirme la fuite vers la qualité.
        intensity = min(1.0, vix_chg / (threshold * 3)) + (0.15 if gold_chg > 0 else 0.0)
        return "risk-off", round(min(1.0, intensity), 3)
    if vix_chg <= -threshold:
        intensity = min(1.0, -vix_chg / (threshold * 3)) + (0.15 if gold_chg < 0 else 0.0)
        return "risk-on", round(min(1.0, intensity), 3)
    return None, 0.0


def currency_scores(
    candles_by_pair: dict[str, list[list[float]]],
    cross: dict,
) -> tuple[dict[str, float], dict]:
    """
    Score macro composite par devise (positif = devise soutenue), et détail
    des contributions pour la traçabilité.
    """
    strength = currency_strength(candles_by_pair)
    regime, intensity = risk_regime(cross)
    oil_chg = ((cross or {}).get("oil") or {}).get("change_pct", 0.0) or 0.0
    us10y_chg = ((cross or {}).get("us10y") or {}).get("change_pct", 0.0) or 0.0

    w = config.FOREX_MACRO_WEIGHTS
    scores: dict[str, float] = {}
    for ccy in set(strength) | _SAFE_HAVENS.keys() | _RISK_CURRENCIES.keys():
        score = w["strength"] * strength.get(ccy, 0.0)

        if regime == "risk-off":
            score += w["risk"] * intensity * _SAFE_HAVENS.get(ccy, 0.0)
            score -= w["risk"] * intensity * _RISK_CURRENCIES.get(ccy, 0.0)
        elif regime == "risk-on":
            score -= w["risk"] * intensity * _SAFE_HAVENS.get(ccy, 0.0)
            score += w["risk"] * intensity * _RISK_CURRENCIES.get(ccy, 0.0)

        score += w["oil"] * oil_chg / 100 * _OIL_SENSITIVITY.get(ccy, 0.0)
        if ccy == "USD":
            score += w["yield"] * us10y_chg / 100

        scores[ccy] = round(score, 5)

    detail = {
        "strength": strength,
        "regime": regime,
        "regime_intensity": intensity,
        "oil_change_pct": oil_chg,
        "us10y_change_pct": us10y_chg,
    }
    return scores, detail


def macro_signal(
    pair: str,
    now: datetime,
    candles_by_pair: dict[str, list[list[float]]],
    cross: dict,
    events: list[EconEvent] | None = None,
    *,
    threshold: float = config.FOREX_MACRO_THRESHOLD,
) -> MacroResult:
    """
    Avis macro sur une paire : différence des scores de ses deux devises,
    éventuellement amplifiée par une surprise économique récente.
    """
    base, quote = pair.upper().split("_")
    scores, detail = currency_scores(candles_by_pair, cross)

    if base not in scores or quote not in scores:
        return MacroResult(None, 0.0, "scores de devises indisponibles",
                           components=detail)

    spread = scores[base] - scores[quote]
    components = {**detail, "score_base": scores[base], "score_quote": scores[quote],
                  "spread": round(spread, 5), "setup": "macro"}

    # Bonus événementiel : une vraie surprise macro dans le bon sens renforce
    # la conviction ; dans le mauvais sens, elle annule le signal du jour (une
    # publication fraîche prime sur une tendance de fond de quelques jours).
    event_dir = None
    if events:
        fund = fundamental_signal(pair, now, events)
        event_dir = fund.direction
        components["event"] = {"direction": fund.direction, "score": fund.score,
                               "reason": fund.reason}
        if event_dir is not None:
            expected = "long" if spread > 0 else "short"
            if event_dir == expected:
                spread *= config.FOREX_MACRO_EVENT_BOOST
                components["setup"] = "macro+event"
            else:
                return MacroResult(
                    None, 0.0,
                    f"surprise macro {event_dir} contredit le biais du jour — on s'abstient",
                    round(spread, 5), components)

    if abs(spread) < threshold:
        return MacroResult(None, 0.0,
                           f"écart macro {spread:+.4f} sous le seuil {threshold}",
                           round(spread, 5), components)

    direction = "long" if spread > 0 else "short"
    strength = min(1.0, abs(spread) / (threshold * 3))

    bits = [f"{base} {scores[base]:+.4f} vs {quote} {scores[quote]:+.4f}"]
    if detail["regime"]:
        bits.append(f"régime {detail['regime']}")
    if components["setup"] == "macro+event":
        bits.append("confirmé par une surprise macro")

    return MacroResult(direction, round(strength, 3),
                       f"macro {direction} : " + " · ".join(bits),
                       round(spread, 5), components)
