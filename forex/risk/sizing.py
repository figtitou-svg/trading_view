"""
forex/risk/sizing.py — Dimensionnement de position (pip / lot / ATR).

Fonctions pures, testées, indépendantes de tout broker :
  - taille du pip (0.01 pour les paires JPY, 0.0001 sinon) ;
  - valeur du pip dans la devise du compte ;
  - nombre d'`units` pour ne jamais risquer plus de X % du capital si le stop
    est touché (tronqué à l'entier inférieur → le risque n'est jamais dépassé) ;
  - stops/take-profit dynamiques en multiples d'ATR.

Convention : 1 lot standard = 100 000 units. `units` est le nominal en devise
de base (positif = long, négatif = short).
"""

from __future__ import annotations


def parse_instrument(pair: str) -> tuple[str, str]:
    """'EUR_USD' → ('EUR', 'USD')."""
    base, quote = pair.upper().split("_")
    return base, quote


def pip_size(pair: str) -> float:
    """0.01 pour les paires cotées en JPY, 0.0001 sinon."""
    _, quote = parse_instrument(pair)
    return 0.01 if quote == "JPY" else 0.0001


def price_distance_to_pips(pair: str, distance: float) -> float:
    """Convertit un écart de prix en pips."""
    return abs(distance) / pip_size(pair)


def pips_to_price(pair: str, pips: float) -> float:
    """Convertit un nombre de pips en écart de prix."""
    return pips * pip_size(pair)


def pip_value_per_unit(
    pair: str,
    account_ccy: str,
    price: float,
    quote_to_account_rate: float | None = None,
) -> float:
    """
    Valeur d'1 pip pour 1 unit, exprimée dans la devise du compte.

    - Si la quote == devise du compte : pip_value = pip_size.
    - Si la base  == devise du compte : pip_value = pip_size / price.
    - Sinon : il faut le taux quote→compte (`quote_to_account_rate`).
    """
    base, quote = parse_instrument(pair)
    pip = pip_size(pair)
    account_ccy = account_ccy.upper()

    if quote == account_ccy:
        return pip
    if base == account_ccy:
        return pip / price
    if quote_to_account_rate is None:
        raise ValueError(
            f"taux {quote}->{account_ccy} requis pour valoriser le pip de {pair}"
        )
    return pip * quote_to_account_rate


def units_from_risk(
    capital: float,
    risk_pct: float,
    stop_loss_pips: float,
    pair: str,
    account_ccy: str,
    price: float,
    quote_to_account_rate: float | None = None,
) -> int:
    """
    Nombre d'units tel que perdre `stop_loss_pips` ne coûte pas plus de
    `risk_pct` % du capital. Tronqué à l'entier inférieur (risque jamais dépassé).
    Retourne 0 sur entrée dégénérée (capital/stop/pip nuls).
    """
    if capital <= 0 or risk_pct <= 0 or stop_loss_pips <= 0 or price <= 0:
        return 0
    risk_amount = capital * (risk_pct / 100.0)
    pip_val = pip_value_per_unit(pair, account_ccy, price, quote_to_account_rate)
    if pip_val <= 0:
        return 0
    loss_per_unit = stop_loss_pips * pip_val
    if loss_per_unit <= 0:
        return 0
    return int(risk_amount / loss_per_unit)  # troncature vers le bas


def atr_stops(
    price: float,
    atr: float,
    direction: str,
    stop_mult: float,
    tp_mult: float,
) -> tuple[float, float]:
    """
    Stop-loss et take-profit dynamiques en multiples d'ATR.
    direction 'long' → stop en-dessous / tp au-dessus ; 'short' → inversé.
    """
    if direction == "long":
        return price - stop_mult * atr, price + tp_mult * atr
    if direction == "short":
        return price + stop_mult * atr, price - tp_mult * atr
    raise ValueError(f"direction invalide : {direction!r}")
