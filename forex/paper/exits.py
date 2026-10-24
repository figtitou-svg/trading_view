"""
forex/paper/exits.py — Mécanismes de sortie DYNAMIQUE (fonctions pures).

Chaque fonction calcule un candidat stop/tp à partir du meilleur prix atteint
depuis l'entrée (`extreme_price`, mis à jour par le broker à chaque bougie),
PAS du prix courant : c'est ce qui garantit qu'un stop/tp resserré ne peut
jamais reculer, même si le prix retrace ensuite. Aucune de ces fonctions ne
touche à l'état d'une position — c'est `PaperBroker.update_exit_levels()`
(forex/paper/broker.py) qui les appelle et persiste le résultat.
"""

from __future__ import annotations


def trailing_stop(direction: str, extreme_price: float, atr: float,
                  atr_stop_mult: float, current_stop: float) -> float:
    """Stop qui suit `extreme_price` à distance fixe, ne recule jamais."""
    if direction == "long":
        candidate = extreme_price - atr_stop_mult * atr
        return max(current_stop, candidate)
    candidate = extreme_price + atr_stop_mult * atr
    return min(current_stop, candidate)


def breakeven_trailing_stop(direction: str, extreme_price: float, atr: float,
                            atr_stop_mult: float, current_stop: float,
                            entry_price: float, initial_stop: float) -> float:
    """
    Comme `trailing_stop`, mais le stop reste au niveau initial tant que le
    profit non réalisé n'a pas atteint 1R (distance initiale entrée→stop) ;
    à partir de 1R il saute au moins au prix d'entrée (risque nul), puis
    continue de traler normalement.
    """
    initial_risk = abs(entry_price - initial_stop)
    profit = (extreme_price - entry_price) if direction == "long" else (entry_price - extreme_price)
    if profit < initial_risk:
        return current_stop
    breakeven = max(current_stop, entry_price) if direction == "long" else min(current_stop, entry_price)
    return trailing_stop(direction, extreme_price, atr, atr_stop_mult, breakeven)


def chandelier_tp(direction: str, extreme_price: float, atr: float,
                  atr_tp_mult: float, current_tp: float) -> float:
    """TP qui s'étend avec `extreme_price` (laisse courir les gagnants), ne recule jamais."""
    if direction == "long":
        candidate = extreme_price + atr_tp_mult * atr
        return max(current_tp, candidate)
    candidate = extreme_price - atr_tp_mult * atr
    return min(current_tp, candidate)
