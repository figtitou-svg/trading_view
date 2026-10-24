"""
Package `forex` — système de trading forex multi-signaux (recherche).

Autonome et découplé du bot crypto (`scanner.py`, `main.py`, dashboard) :
aucun fichier crypto n'est importé ni modifié.

Principe : n'entrer en position qu'en **confluence** de trois familles de
signaux indépendants, plutôt que sur un indicateur isolé —

  1. technique  (momentum / structure de prix)      → forex.signals.technical
  2. fondamental event-driven (surprises macro)      → forex.signals.fundamental
  3. filtre de risque temporel (fenêtres d'annonce)  → forex.signals.time_filter

La règle de confluence est dans forex.signals.confluence.

Rien ici ne peut passer un ordre réel : les prix viennent d'un feed public
sans credentials (forex.data.prices) et l'exécution est 100 % simulée
(forex.paper.broker). Le passage à un broker réel serait une étape séparée
et explicite.
"""

__all__ = ["config"]
