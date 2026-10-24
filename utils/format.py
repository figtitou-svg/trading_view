"""
utils/format.py — Formatage adaptatif des prix.

BTC vaut ~64 000 $ mais DOGE ~0,12 $ : un arrondi fixe à 2 décimales
rend les petits prix illisibles (stop 0.1180 et TP 0.1245 affichés
tous deux « 0.12 »). On adapte le nombre de décimales à l'ordre de
grandeur du prix.
"""


def fmt_price(price: float | None) -> str:
    """Formate un prix avec une précision adaptée à sa magnitude."""
    if price is None:
        return "?"
    if price >= 100:
        return f"{price:.2f}"
    if price >= 1:
        return f"{price:.4f}"
    return f"{price:.6f}"
