"""
forex/signals/smc.py — Smart Money Concepts (inefficiences de liquidité).

Contrairement aux indicateurs classiques (MA, MACD) qui décrivent le prix
passé, l'approche SMC cherche des **traces laissées par les gros ordres** :
là où le prix s'est déplacé trop vite pour que tous les ordres soient
appariés, il reste une zone d'inefficience que le marché a tendance à revenir
combler avant de repartir.

Quatre briques, toutes calculées sans aucun look-ahead :

1. **Fair Value Gap (FVG)** — déséquilibre sur 3 bougies : le corps de la
   bougie centrale est si impulsif que l'ombre haute de la 1re et l'ombre
   basse de la 3e ne se recouvrent pas. Le « trou » est la zone d'inefficience.

2. **Order Block (OB)** — la dernière bougie de sens opposé juste avant une
   impulsion. C'est là que l'ordre institutionnel a été absorbé ; un retour
   du prix sur cette zone est un point d'entrée avec un stop serré derrière.

3. **Break of Structure (BOS) / Change of Character (CHoCH)** — cassure en
   clôture du dernier swing confirmé. Le BOS confirme la tendance en cours,
   le CHoCH signale son retournement. Sert de **biais directionnel** : on ne
   prend une zone que dans le sens de la structure.

4. **Liquidity sweep (chasse de stops)** — une mèche qui dépasse un ancien
   extrême puis referme de l'autre côté : les stops ont été pris, souvent
   juste avant le vrai mouvement.

Règle d'entrée du bot : biais donné par la structure, déclenchement quand le
prix **mitige** (revient dans) une zone FVG ou Order Block alignée avec ce
biais, pendant une session liquide (Londres / New York).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from forex import config
from forex.signals import indicators
from forex.signals.patterns import SwingPoint, swing_points


@dataclass
class Zone:
    """Zone d'inefficience (FVG ou Order Block) laissée par une impulsion."""

    kind: str          # 'fvg' | 'orderblock'
    direction: str     # 'long' (zone de demande) | 'short' (zone d'offre)
    bottom: float
    top: float
    index: int         # bougie où la zone a été créée

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top

    @property
    def size(self) -> float:
        return self.top - self.bottom


@dataclass
class Structure:
    """État de la structure de marché (biais directionnel)."""

    bias: str | None    # 'long' | 'short' | None
    event: str | None   # 'BOS' | 'CHoCH' | None
    level: float | None  # niveau cassé
    reason: str
    bars_ago: int = 0   # ancienneté de la cassure (0 = bougie courante)


# ── 1. Fair Value Gaps ────────────────────────────────────

def fair_value_gaps(
    candles: list[list[float]],
    atr: float,
    *,
    lookback: int = config.FOREX_SMC_LOOKBACK,
    min_size_atr: float = config.FOREX_SMC_MIN_FVG_ATR,
) -> list[Zone]:
    """
    FVG haussier : le HIGH de la bougie i-2 est sous le LOW de la bougie i
    (le marché a « sauté » cette zone en montant). FVG baissier : symétrique.

    Seuls les gaps d'au moins `min_size_atr` × ATR sont retenus — un gap d'un
    dixième de pip n'est pas une inefficience, c'est du bruit de cotation.
    """
    out: list[Zone] = []
    if atr <= 0 or len(candles) < 3:
        return out
    min_size = min_size_atr * atr
    start = max(2, len(candles) - lookback)
    for i in range(start, len(candles)):
        prev_high, prev_low = candles[i - 2][2], candles[i - 2][3]
        cur_high, cur_low = candles[i][2], candles[i][3]
        if cur_low > prev_high and (cur_low - prev_high) >= min_size:
            out.append(Zone("fvg", "long", prev_high, cur_low, i))
        elif prev_low > cur_high and (prev_low - cur_high) >= min_size:
            out.append(Zone("fvg", "short", cur_high, prev_low, i))
    return out


# ── 2. Order Blocks ───────────────────────────────────────

def order_blocks(
    candles: list[list[float]],
    atr: float,
    *,
    lookback: int = config.FOREX_SMC_LOOKBACK,
    impulse_atr: float = config.FOREX_SMC_IMPULSE_ATR,
) -> list[Zone]:
    """
    Order Block haussier : la dernière bougie BAISSIÈRE précédant immédiatement
    une impulsion haussière d'au moins `impulse_atr` × ATR. La zone est le
    corps complet (low → high) de cette bougie.
    """
    out: list[Zone] = []
    if atr <= 0 or len(candles) < 3:
        return out
    min_move = impulse_atr * atr
    start = max(1, len(candles) - lookback)
    for i in range(start, len(candles)):
        o, c = candles[i][1], candles[i][4]
        move = c - o
        if abs(move) < min_move:
            continue
        prev = candles[i - 1]
        prev_bullish = prev[4] > prev[1]
        # Impulsion haussière → on cherche la bougie baissière juste avant.
        if move > 0 and not prev_bullish:
            out.append(Zone("orderblock", "long", prev[3], prev[2], i - 1))
        elif move < 0 and prev_bullish:
            out.append(Zone("orderblock", "short", prev[3], prev[2], i - 1))
    return out


# ── 3. Structure de marché (BOS / CHoCH) ──────────────────

def _prior_bias(swings: list[SwingPoint]) -> str | None:
    """
    Biais implicite avant la cassure : séquence de sommets/creux croissants
    (higher highs + higher lows) = haussier, décroissants = baissier.
    """
    highs = [s.price for s in swings if s.kind == "high"][-2:]
    lows = [s.price for s in swings if s.kind == "low"][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return None
    if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
        return "long"
    if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
        return "short"
    return None


def market_structure(
    candles: list[list[float]],
    *,
    lookback: int = config.FOREX_SMC_STRUCTURE_LOOKBACK,
) -> Structure:
    """
    Biais directionnel donné par la DERNIÈRE cassure de structure en date.

    On remonte les bougies récentes jusqu'à trouver une clôture qui a cassé un
    swing confirmé *à ce moment-là*, et ce biais reste valable ensuite : c'est
    le principe même du BOS. Exiger que la cassure ait lieu sur la bougie
    courante rendrait le signal quasi impossible à déclencher, puisqu'il
    faudrait qu'elle coïncide avec la mitigation d'une zone — deux événements
    séparés de plusieurs bougies dans le schéma SMC classique (cassure, puis
    repli sur la zone, puis reprise).

    Anti-look-ahead : à la bougie i, seuls les swings déjà CONFIRMÉS à cet
    instant sont utilisables, c'est-à-dire ceux dont l'index + la fenêtre de
    confirmation droite est ≤ i.
    """
    swings = swing_points(candles)
    if not swings:
        return Structure(None, None, None, "pas de swing confirmé")

    right = config.FOREX_SWING_RIGHT
    n = len(candles)
    oldest = max(1, n - lookback)

    for i in range(n - 1, oldest - 1, -1):
        close = candles[i][4]
        usable = [s for s in swings if s.index + right <= i]
        if not usable:
            continue
        last_high = next((s for s in reversed(usable) if s.kind == "high"), None)
        last_low = next((s for s in reversed(usable) if s.kind == "low"), None)
        bars_ago = n - 1 - i

        if last_high is not None and close > last_high.price:
            event = "BOS" if _prior_bias(usable) == "long" else "CHoCH"
            return Structure(
                "long", event, last_high.price,
                f"{event} haussier il y a {bars_ago} bougie(s) : "
                f"clôture {close:.5f} > sommet {last_high.price:.5f}",
                bars_ago)
        if last_low is not None and close < last_low.price:
            event = "BOS" if _prior_bias(usable) == "short" else "CHoCH"
            return Structure(
                "short", event, last_low.price,
                f"{event} baissier il y a {bars_ago} bougie(s) : "
                f"clôture {close:.5f} < creux {last_low.price:.5f}",
                bars_ago)

    return Structure(None, None, None, "aucune cassure de structure récente")


# ── 4. Chasse de liquidité ────────────────────────────────

def liquidity_sweep(candles: list[list[float]], atr: float) -> str | None:
    """
    Chasse de stops sur la DERNIÈRE bougie : sa mèche dépasse un ancien
    extrême de swing, mais la clôture revient du bon côté. Direction retournée
    = sens du mouvement attendu APRÈS la chasse (mèche basse → 'long').
    """
    if atr <= 0 or len(candles) < 3:
        return None
    swings = swing_points(candles[:-1])
    if not swings:
        return None
    last = candles[-1]
    _, _, high, low, close, *_ = last

    last_low = next((s for s in reversed(swings) if s.kind == "low"), None)
    if last_low is not None and low < last_low.price <= close:
        return "long"
    last_high = next((s for s in reversed(swings) if s.kind == "high"), None)
    if last_high is not None and high > last_high.price >= close:
        return "short"
    return None


# ── Sessions de trading ───────────────────────────────────
# Logique déplacée dans forex.signals.sessions (générique, réutilisable par
# n'importe quel bot). Ce module garde un alias `active_sessions` et une
# fonction `in_liquid_session` avec le défaut SPÉCIFIQUE à SMC
# (FOREX_SMC_SESSIONS), pour ne rien changer à son comportement existant.

from forex.signals.sessions import active_sessions  # noqa: F401 (ré-exporté)


def in_liquid_session(dt: datetime, allowed: list[str] | None = None) -> bool:
    """
    Vrai pendant les sessions retenues pour SMC (Londres/New York par défaut).

    C'est le garde-fou le plus important du bot SMC : les inefficiences de
    liquidité se créent quand le volume institutionnel est présent. Appliquer
    la même logique pendant la session asiatique (range étroit, faible volume)
    revient à trader du bruit — c'est le conseil « isolez par session ».
    """
    from forex.signals import sessions as _sessions

    allowed = allowed or config.FOREX_SMC_SESSIONS
    return _sessions.in_liquid_session(dt, allowed)


# ── Signal composite ──────────────────────────────────────

@dataclass
class SMCResult:
    direction: str | None
    strength: float
    reason: str
    components: dict


def smc_signal(
    candles: list[list[float]],
    now: datetime,
    *,
    require_session: bool = True,
) -> SMCResult:
    """
    Assemble les briques : biais de structure → zone mitigée dans ce sens →
    entrée. La chasse de liquidité et le type d'événement (CHoCH vs BOS)
    modulent la force.
    """
    atr = indicators.atr(candles[-(config.ATR_PERIOD + 1) * 3:], config.ATR_PERIOD)
    sessions = active_sessions(now)
    components: dict = {"atr": round(atr, 6), "sessions": sessions}

    if atr <= 0:
        return SMCResult(None, 0.0, "ATR nul", components)

    if require_session and not in_liquid_session(now):
        return SMCResult(None, 0.0,
                         f"hors session liquide (actives : {', '.join(sessions) or 'aucune'})",
                         components)

    structure = market_structure(candles)
    components["structure"] = structure.event
    components["structure_reason"] = structure.reason
    components["bias"] = structure.bias
    if structure.bias is None:
        return SMCResult(None, 0.0, structure.reason, components)

    close = candles[-1][4]
    sweep = liquidity_sweep(candles, atr)
    components["liquidity_sweep"] = sweep

    # Zones alignées avec le biais et que le prix mitige actuellement.
    # Elles doivent avoir été créées AU PLUS TÔT à la cassure de structure :
    # une inefficience antérieure appartient à l'ancien régime de marché et
    # n'a pas de raison d'être défendue par le flux d'ordres actuel.
    break_index = len(candles) - 1 - structure.bars_ago
    zones = [
        z for z in (fair_value_gaps(candles, atr) + order_blocks(candles, atr))
        if z.direction == structure.bias and z.contains(close) and z.index >= break_index
    ]
    components["zones_mitigees"] = len(zones)
    if not zones:
        return SMCResult(None, 0.0,
                         f"biais {structure.bias} ({structure.event}) mais aucune zone mitigée",
                         components)

    zone = max(zones, key=lambda z: z.index)
    components["setup"] = zone.kind
    components["zone"] = {"kind": zone.kind, "bottom": round(zone.bottom, 5),
                          "top": round(zone.top, 5), "index": zone.index}

    # Force : base solide (setup complet), bonifiée par un CHoCH (retournement
    # net, souvent le meilleur rapport risque/rendement), par une chasse de
    # liquidité dans le bon sens, et par la fraîcheur de la zone.
    strength = 0.5
    if structure.event == "CHoCH":
        strength += 0.15
    if sweep == structure.bias:
        strength += 0.2
    if zone.index >= len(candles) - 10:
        strength += 0.1
    strength = min(1.0, strength)

    reason = (f"{structure.event} {structure.bias} + mitigation {zone.kind} "
              f"[{zone.bottom:.5f}–{zone.top:.5f}]")
    if sweep == structure.bias:
        reason += " après chasse de liquidité"
    if sessions:
        reason += f" · session {'/'.join(sessions)}"

    return SMCResult(structure.bias, round(strength, 3), reason, components)
