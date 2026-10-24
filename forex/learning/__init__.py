"""
Package `forex.learning` — module 7 : rétroaction par trade & auto-amélioration.

Le bot relit ses propres trades (journal) et ses opportunités manquées pour :
  - mesurer la performance par COMBINAISON de signaux (analysis) ;
  - ré-optimiser ses paramètres via walk-forward, sous garde-fous (tuner) ;
  - désactiver une combinaison qui se dégrade / réactiver une combinaison qui
    reprend (state) ;
tout changement étant validé sur échantillon, journalisé et réversible.

Rien n'est jamais ajusté « au ressenti » : les paramètres ne bougent qu'après
un cycle walk-forward, et les combinaisons qu'au-delà d'un échantillon minimum.
"""
