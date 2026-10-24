"""
forex/strategies/base.py — Socle commun des BOTS forex indépendants.

Chaque bot est une stratégie **autonome et isolée** :
  - sa propre logique d'entrée (`decide()`) ;
  - son propre portefeuille virtuel, son journal de trades et ses paramètres
    appris (fichiers séparés sous `_cache/bots/<id>/`) ;
  - donc sa propre courbe d'equity, ses propres statistiques et sa propre
    boucle d'apprentissage.

Un bot désactivé (ou dont l'apprentissage coupe un combo) n'a **aucun effet**
sur les autres : c'est tout l'intérêt du découpage. À l'inverse d'un vote à la
majorité mélangeant tous les signaux, on peut ici mesurer l'edge de chaque
approche séparément et ne garder que celles qui en ont un.

Ce qui reste MUTUALISÉ (volontairement) :
  - les bougies, récupérées une seule fois par paire et par cycle par le runner
    puis passées à tous les bots (sinon N bots × M paires requêtes réseau) ;
  - le filtre temporel (marché ouvert, fenêtre d'exclusion autour des annonces)
    et les garde-fous de risque : ce sont des règles de sécurité, pas des
    stratégies — les appliquer uniformément garde les bots comparables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime

from forex import config
from forex.data.calendar import EconEvent
from forex.signals import time_filter


BOTS_DIR = os.path.join(config.FOREX_DATA_DIR, "bots")


@dataclass
class StrategyDecision:
    """Décision d'un bot pour une paire à un instant donné (traçable)."""

    enter: bool
    direction: str | None = None          # 'long' | 'short' | None
    strength: float = 0.0                 # 0.0 → 1.0
    reasons: list[str] = field(default_factory=list)
    components: dict = field(default_factory=dict)   # contexte complet (journalisé)

    def summary(self) -> str:
        head = "ENTRÉE" if self.enter else "pas d'entrée"
        if self.direction:
            head += f" {self.direction} (force {self.strength:.2f})"
        return head + " · " + " ; ".join(self.reasons)

    @classmethod
    def no(cls, reason: str, components: dict | None = None) -> "StrategyDecision":
        """Raccourci : pas d'entrée, avec la raison (toujours renseignée)."""
        return cls(False, None, 0.0, [reason], components or {})


class Strategy:
    """
    Classe de base d'un bot. Une sous-classe implémente `decide()` ; le reste
    (filtre temporel, chemins de cache, clé de combo) est fourni ici pour que
    tous les bots restent comparables entre eux.
    """

    id: str = "base"
    label: str = "Bot générique"
    # Résumé court (1-2 phrases) affiché sur la page dédiée du bot dans le
    # dashboard. Vide par défaut : chaque sous-classe concrète le renseigne.
    description: str = ""
    # Multiples ATR par défaut du bot. Une stratégie de cassure (SMC) n'a pas
    # les mêmes objectifs qu'un suivi de tendance : chaque bot porte les siens,
    # et l'auto-tuner les ajuste ensuite indépendamment par bot et par paire.
    atr_stop_mult: float = config.ATR_STOP_MULT
    atr_tp_mult: float = config.ATR_TP_MULT
    # Nombre minimum de bougies nécessaires pour que la logique ait du sens.
    min_candles: int = config.MA_SLOW + 5

    # Gestion de sortie dynamique (cf. forex/paper/exits.py) : "static" (défaut,
    # comportement historique — stop/tp figés à l'entrée), "trailing",
    # "trailing_breakeven" ou "chandelier". Fixé par les variantes générées
    # dans forex/strategies/__init__.py::active(), jamais par un bot lui-même.
    exit_mode: str = "static"

    # Auto-découverte (forex.strategies.registry) : un bot avec enabled=False
    # n'est jamais instancié par active(), sans toucher à aucun autre fichier.
    # Son historique (_cache/bots/<id>/) reste intact tant qu'on ne le purge
    # pas explicitement (cf. forex.strategies.remove).
    enabled: bool = True
    # Univers de paires restreint pour ce bot (ex. une stratégie de carry qui
    # n'a de sens que sur des paires JPY). None = tout FOREX_PAIRS, comme les
    # autres bots — c'est le défaut, pour ne rien changer aux bots existants.
    pairs: list[str] | None = None

    # ── Chemins de cache isolés ───────────────────────────
    @property
    def dir(self) -> str:
        return os.path.join(BOTS_DIR, self.id)

    @property
    def portfolio_path(self) -> str:
        return os.path.join(self.dir, "paper_portfolio.json")

    @property
    def journal_path(self) -> str:
        return os.path.join(self.dir, "trade_journal.jsonl")

    @property
    def state_path(self) -> str:
        return os.path.join(self.dir, "learned_params.json")

    @property
    def status_path(self) -> str:
        return os.path.join(self.dir, "status.json")

    def ensure_dir(self) -> None:
        os.makedirs(self.dir, exist_ok=True)

    # ── Décision ──────────────────────────────────────────
    def decide(
        self,
        pair: str,
        now: datetime,
        candles: list[list[float]],
        events: list[EconEvent],
        context: dict | None = None,
    ) -> StrategyDecision:
        """
        Logique propre au bot. À implémenter par chaque sous-classe.

        `context` transporte les données MUTUALISÉES du cycle, calculées une
        seule fois par le runner pour tous les bots et toutes les paires :
        bougies de toutes les paires (`candles_by_pair`), agrégats cross-asset
        (VIX, or, pétrole, taux). Un bot qui n'en a pas besoin l'ignore.
        """
        raise NotImplementedError

    def evaluate(
        self,
        pair: str,
        now: datetime,
        candles: list[list[float]],
        events: list[EconEvent] | None = None,
        *,
        use_time_filter: bool = config.USE_TIME_FILTER,
        context: dict | None = None,
    ) -> StrategyDecision:
        """
        Point d'entrée utilisé par le runner et le backtest : applique les
        garde-fous communs PUIS la logique du bot.

        Le filtre temporel est appliqué en amont (et non dans chaque bot) pour
        deux raisons : il n'a rien de stratégique (marché fermé = pas d'ordre
        possible, point), et le sortir de la logique évite qu'un bot l'oublie
        et devienne incomparable aux autres.
        """
        events = events or []
        if len(candles) < self.min_candles:
            return StrategyDecision.no(f"pas assez de bougies ({len(candles)})")

        if use_time_filter:
            gate = time_filter.can_trade(pair, now, events)
            if not gate.can_open:
                return StrategyDecision.no(f"bloqué : {gate.reason}",
                                           {"time_gate": gate.reason})

        # `context if ... is not None` et NON `context or {}` : un dict vide est
        # falsy, donc `{} or {}` renverrait un NOUVEAU dict et les écritures du
        # bot (notamment le cache de décisions des combos) seraient perdues.
        decision = self.decide(pair, now, candles, events,
                               context if context is not None else {})
        decision.components.setdefault("strategy", self.id)
        return decision

    # ── Identité des trades (apprentissage) ───────────────
    def combo_key(self, components: dict, direction: str | None) -> str:
        """
        Clé identifiant ce qui a produit une entrée, pour l'analyse de
        performance par le module d'apprentissage.

        Le journal étant désormais séparé par bot, la clé n'a plus besoin de
        nommer les familles de signaux : elle qualifie la VARIANTE interne au
        bot (ex. `fvg:long` vs `orderblock:long` pour SMC), ce qui permet à
        l'apprentissage de désactiver un setup précis sans tuer tout le bot.
        Par défaut : la direction seule.
        """
        setup = (components or {}).get("setup")
        prefix = f"{setup}:" if setup else ""
        return f"{prefix}{direction or '?'}"

    def __repr__(self) -> str:  # pragma: no cover - confort de débogage
        return f"<Strategy {self.id}>"
