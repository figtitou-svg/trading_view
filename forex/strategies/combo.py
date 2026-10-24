"""
forex/strategies/combo.py — Bots de COMBINAISON (diversification).

Un bot de combinaison n'a pas de logique propre : il fait voter plusieurs bots
de base et n'entre que s'ils s'accordent. L'intérêt est double :

  - **sélectivité** : exiger deux avis indépendants filtre les signaux les plus
    fragiles. Moins de trades, mais théoriquement de meilleure qualité ;
  - **diversification** : combiner des bots qui regardent des choses
    DIFFÉRENTES (structure de liquidité vs macro fondamentale) a beaucoup plus
    de valeur que combiner deux variantes techniques, dont les erreurs sont
    corrélées. Un combo `smc+macro` peut avoir un edge là où `trend+chartist`
    ne fait que répéter deux fois la même information.

Comme tout autre bot, un combo a son propre portefeuille, son journal et ses
paramètres appris : il est mis en concurrence avec ses propres membres et sera
coupé par l'apprentissage s'il ne fait pas mieux qu'eux.

⚠️ Coût de calcul : sans précaution, chaque combo réévaluerait ses membres
(détection de swing points, figures…) déjà évalués par ailleurs. Les décisions
de base sont donc **mémoïsées par cycle** dans le contexte partagé, clé
(bot, paire, horodatage de bougie) : un membre n'est jamais calculé deux fois
pour la même bougie, quel que soit le nombre de combos qui l'utilisent.
"""

from __future__ import annotations

from datetime import datetime

from forex.data.calendar import EconEvent
from forex.strategies.base import Strategy, StrategyDecision

# Clé du cache de décisions dans le contexte partagé du cycle.
_CACHE_KEY = "_base_decisions"


class ComboStrategy(Strategy):
    """Combinaison de bots de base. `mode` : 'all' (unanimité) ou 'majority'."""

    def __init__(self, members: list[Strategy], mode: str = "all"):
        if len(members) < 2:
            raise ValueError("un combo exige au moins 2 bots")
        if mode not in {"all", "majority"}:
            raise ValueError(f"mode de combo inconnu : {mode!r}")
        self.members = members
        self.mode = mode
        names = "+".join(m.id for m in members)
        # Préfixe 'maj-' et non 'maj:' : l'id sert de NOM DE DOSSIER de cache,
        # et ':' est un caractère illégal dans un chemin Windows.
        self.id = names if mode == "all" else f"maj-{names}"
        self.label = (f"Combinaison {'unanime' if mode == 'all' else 'majoritaire'} : "
                      + " + ".join(m.label.split(" (")[0] for m in members))
        # Mentionne les IDS des membres (et non leurs labels) : ce sont eux que
        # la page dédiée du bot utilise pour faire le lien vers chaque membre.
        self.description = (
            f"Bot de combinaison ({'unanimité' if mode == 'all' else 'majorité'}) : "
            + " et ".join(m.id for m in members)
            + " doivent s'accorder pour entrer."
        )
        # Stop/TP : moyenne de ceux des membres. Un combo hérite d'horizons
        # hétérogènes (smc serre, macro élargit) ; la moyenne est un compromis
        # neutre, que l'auto-tuner ajustera ensuite par paire s'il le justifie.
        self.atr_stop_mult = sum(m.atr_stop_mult for m in members) / len(members)
        self.atr_tp_mult = sum(m.atr_tp_mult for m in members) / len(members)
        # Il faut de quoi satisfaire le membre le plus exigeant, sinon celui-ci
        # s'abstiendrait systématiquement et le combo serait muet.
        self.min_candles = max(m.min_candles for m in members)

    # ── Évaluation mémoïsée des membres ───────────────────
    def _member_decision(self, member, pair, now, candles, events, context) -> StrategyDecision:
        cache = context.setdefault(_CACHE_KEY, {})
        key = (member.id, pair, candles[-1][0])
        if key not in cache:
            # Le filtre temporel a déjà été appliqué par le combo lui-même :
            # le repasser à chaque membre serait redondant (et fausserait le
            # cache si un membre était évalué avec un réglage différent).
            cache[key] = member.evaluate(pair, now, candles, events,
                                         use_time_filter=False, context=context)
        return cache[key]

    def decide(
        self,
        pair: str,
        now: datetime,
        candles: list[list[float]],
        events: list[EconEvent],
        context: dict | None = None,
    ) -> StrategyDecision:
        context = context if context is not None else {}
        decisions = {m.id: self._member_decision(m, pair, now, candles, events, context)
                     for m in self.members}

        firing = {bot_id: d for bot_id, d in decisions.items() if d.enter and d.direction}
        components = {
            "members": {bot_id: {"enter": d.enter, "direction": d.direction,
                                 "strength": d.strength, "setup": d.components.get("setup")}
                        for bot_id, d in decisions.items()},
        }

        if not firing:
            return StrategyDecision.no("aucun membre ne tire", components)

        longs = [b for b, d in firing.items() if d.direction == "long"]
        shorts = [b for b, d in firing.items() if d.direction == "short"]

        # Un désaccord de direction annule toujours l'entrée, dans les 2 modes :
        # deux bots qui se contredisent ne « diversifient » rien, ils signalent
        # que le marché n'est pas lisible.
        if longs and shorts:
            return StrategyDecision.no(
                f"désaccord : long={longs} vs short={shorts}", components)

        direction = "long" if longs else "short"
        agreeing = longs or shorts
        needed = len(self.members) if self.mode == "all" else (len(self.members) + 1) // 2

        if len(agreeing) < needed:
            return StrategyDecision.no(
                f"{len(agreeing)}/{needed} membre(s) requis — "
                f"seuls {', '.join(agreeing)} tirent", components)

        # Setup = les membres qui ont déclenché, pour que l'apprentissage puisse
        # distinguer « smc+macro d'accord » de « macro seul dans un combo maj: ».
        components["setup"] = "+".join(sorted(agreeing))
        strength = sum(firing[b].strength for b in agreeing) / len(agreeing)
        reasons = [f"{b} {firing[b].direction} ({firing[b].reasons[0][:60]})" for b in agreeing]

        return StrategyDecision(
            True, direction, round(strength, 3),
            [f"combo {self.mode} {direction} : " + " | ".join(reasons)],
            components,
        )
