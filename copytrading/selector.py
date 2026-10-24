"""
copytrading/selector.py — Présélection automatique des traders à proposer.

Critères (validés en design) :
  - taille de compte entre COPY_MIN_ACCOUNT_USD et COPY_MAX_ACCOUNT_USD ;
  - ROI 7 j strictement positif (régularité : exclut le coup de chance) ;
  - volume 7 j strictement positif (le trader est actif) ;
  - tri par ROI 30 j décroissant, limité à COPY_N_CANDIDATES.

L'utilisateur garde la main : ces candidats ne sont que des PROPOSITIONS,
rien n'est copié sans activation manuelle depuis le dashboard.
"""

from __future__ import annotations

from copytrading import config


def select_candidates(rows: list[dict]) -> list[dict]:
    """`rows` = lignes déjà parsées par api.parse_leaderboard_row."""
    eligible = [
        r for r in rows
        if config.COPY_MIN_ACCOUNT_USD <= r["account_value"] <= config.COPY_MAX_ACCOUNT_USD
        and r["roi_week"] > 0
        and r["volume_week"] > 0
    ]
    eligible.sort(key=lambda r: r["roi_month"], reverse=True)
    return eligible[:config.COPY_N_CANDIDATES]
