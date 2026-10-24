"""
forex/signals/technical.py — Signal technique (momentum + structure de prix).

Combine quatre briques en une direction + une force, par VOTE À LA MAJORITÉ :
  - **MA crossover** (50/200) : tendance de fond (haussière/baissière) ;
  - **MACD** : confirmation de momentum (signe de la ligne) ;
  - **Figure chartiste** (forex.signals.patterns) : double top/bottom,
    tête-épaules, triangles, drapeaux — les schémas classiques reconnus par
    n'importe quel trader ;
  - **RSI** : filtre de surachat/survente (invalide une entrée à contre-sens).

Vote à la majorité sur (MA, MACD, figure) : il faut au moins 2 voix sur 3
d'accord, et strictement majoritaires. Quand aucune figure n'est détectée
(cas le plus fréquent), le vote se réduit mathématiquement à l'exigence
« MA ET MACD d'accord » — comportement identique à l'historique du bot.
Une figure chartiste peut donc débloquer une entrée que MA+MACD seuls
n'auraient pas validée (si l'un des deux s'accorde avec elle), ou au
contraire renforcer la force du signal quand tout s'aligne.

Le RSI reste un filtre d'invalidation final, appliqué après le vote.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from forex import config
from forex.signals import indicators, patterns


@dataclass
class TechnicalResult:
    direction: str | None            # 'long' | 'short' | None
    strength: float                  # 0.0 → 1.0
    reason: str
    components: dict = field(default_factory=dict)

    @property
    def is_bullish(self) -> bool:
        return self.direction == "long"

    @property
    def is_bearish(self) -> bool:
        return self.direction == "short"


def technical_signal(
    candles: list[list[float]],
    *,
    rsi_period: int = config.RSI_PERIOD,
    rsi_overbought: float = config.RSI_OVERBOUGHT,
    rsi_oversold: float = config.RSI_OVERSOLD,
    macd_fast: int = config.MACD_FAST,
    macd_slow: int = config.MACD_SLOW,
    macd_signal: int = config.MACD_SIGNAL,
    ma_fast: int = config.MA_FAST,
    ma_slow: int = config.MA_SLOW,
    use_patterns: bool = True,
) -> TechnicalResult:
    """
    Évalue le signal technique sur des bougies OHLCV closes.

    `use_patterns=False` retire la figure chartiste du vote : le signal se
    réduit alors à « MA ET MACD d'accord ». Utilisé par le bot `trend`, qui
    doit rester une stratégie de tendance PURE — les figures sont devenues un
    bot autonome (`forex.strategies.patterns`), et les faire voter ici en plus
    rendrait la contribution de chaque approche impossible à mesurer.
    """
    closes = [c[4] for c in candles]
    if len(closes) < max(ma_slow, macd_slow + macd_signal) + 1:
        return TechnicalResult(None, 0.0, "pas assez de bougies", {})

    rsi_v = indicators.rsi(closes, rsi_period)
    ma_f = indicators.ema(closes, ma_fast)
    ma_s = indicators.ema(closes, ma_slow)
    macd_v = indicators.macd(closes, macd_fast, macd_slow, macd_signal)
    pattern = patterns.detect_patterns(candles) if use_patterns else None

    components = {
        "rsi": rsi_v,
        "ma_fast": round(ma_f, 6) if ma_f else None,
        "ma_slow": round(ma_s, 6) if ma_s else None,
        "macd_line": round(macd_v[0], 8) if macd_v else None,
        "macd_hist": round(macd_v[2], 8) if macd_v else None,
        "pattern": pattern.name if pattern else None,
        "pattern_reason": pattern.reason if pattern else None,
    }

    if ma_f is None or ma_s is None or macd_v is None:
        return TechnicalResult(None, 0.0, "indicateurs indisponibles", components)

    # Momentum via le SIGNE de la ligne MACD (EMA rapide vs lente) : stable, à la
    # différence du signe de l'histogramme (macd vs signal) qui oscille sur une
    # tendance régulière (histogramme ≈ 0). L'histogramme reste loggué.
    macd_line = macd_v[0]
    # Un votant ABSTIEN quand sa mesure est exactement neutre (EMA rapide égale
    # à la lente, ligne MACD nulle). Un simple `>` compterait cette égalité
    # comme un vote baissier : sur un marché parfaitement plat, MA et MACD
    # « voteraient » tous deux short et le bot vendrait un marché sans tendance.
    ma_bull = None if ma_f == ma_s else ma_f > ma_s
    macd_bull = None if macd_line == 0 else macd_line > 0
    pattern_bull = (pattern.direction == "long") if pattern else None

    # Vote à la majorité sur (MA, MACD, figure). Sans figure détectée (cas le
    # plus fréquent), seuls MA et MACD votent : la majorité (2 voix sur 2
    # possibles) exige alors qu'ils soient d'accord — comportement identique
    # à l'ancienne règle stricte « MA ET MACD ».
    votes = [ma_bull, macd_bull, pattern_bull]
    votes_bull = sum(1 for v in votes if v is True)
    votes_bear = sum(1 for v in votes if v is False)
    n_voters = sum(1 for v in votes if v is not None)

    def _label(v) -> str:
        return "neutre" if v is None else ("haussier" if v else "baissier")

    if votes_bull >= 2 and votes_bull > votes_bear:
        direction = "long"
    elif votes_bear >= 2 and votes_bear > votes_bull:
        direction = "short"
    else:
        return TechnicalResult(
            None, 0.0,
            f"MA-trend ({_label(ma_bull)}) et MACD ({_label(macd_bull)})"
            + (f" et figure {pattern.name} ({_label(pattern_bull)})" if pattern else "")
            + " sans majorité",
            components,
        )

    # Filtre RSI : pas d'achat en surachat, pas de vente en survente.
    if direction == "long" and rsi_v >= rsi_overbought:
        return TechnicalResult(None, 0.0, f"RSI {rsi_v} ≥ {rsi_overbought} (surachat)", components)
    if direction == "short" and rsi_v <= rsi_oversold:
        return TechnicalResult(None, 0.0, f"RSI {rsi_v} ≤ {rsi_oversold} (survente)", components)

    # Force : accord des votants (sur 3 si figure présente, sinon sur 2) +
    # bonus RSI bien orienté + bonus si la figure elle-même s'accorde (elle
    # apporte une force propre, mesurée géométriquement par detect_patterns).
    agree = votes_bull if direction == "long" else votes_bear
    vote_ratio = agree / n_voters
    rsi_bias = (rsi_v - 50) / 50  # -1 (survente) → +1 (surachat)
    rsi_boost = max(0.0, rsi_bias if direction == "long" else -rsi_bias)
    pattern_boost = pattern.strength if (pattern and pattern_bull == (direction == "long")) else 0.0
    strength = min(1.0, vote_ratio * 0.6 + rsi_boost * 0.2 + pattern_boost * 0.2)

    reason = f"{'Haussier' if direction == 'long' else 'Baissier'} : MA{ma_fast}/{ma_slow} + MACD"
    if pattern and pattern_bull == (direction == "long"):
        reason += f" + figure {pattern.name}"
    reason += f" alignés, RSI {rsi_v}"

    return TechnicalResult(direction, round(strength, 3), reason, components)
