"""
forex/signals/patterns.py — Figures chartistes classiques (analyse technique
« au sens propre » : ce que n'importe quel trader reconnaîtrait sur un graphique).

Détection sur POINTS DE SWING (fractals), sans dépendance externe :
  - Double Top / Double Bottom
  - Tête-épaules (et sa version inversée)
  - Triangles (ascendant / descendant / symétrique)
  - Drapeau / Fanion (impulsion + consolidation + cassure)

Principes communs :
  - Un point de swing n'est retenu que lorsqu'il est CONFIRMÉ (les bougies
    suivantes nécessaires à sa détection existent déjà dans la liste passée),
    donc jamais de biais anticipatif (look-ahead).
  - Une figure n'émet un signal que lorsqu'elle est CASSÉE (cassure de ligne
    de cou / de trendline déjà franchie sur la dernière bougie close), jamais
    sur une figure encore « en formation ».
  - Les seuils de tolérance / cassure sont exprimés en MULTIPLES D'ATR (pas de
    pourcentages arbitraires) pour rester cohérents entre paires et limiter
    le risque de sur-ajustement.

Simplification assumée : les « lignes de cou » du double top/bottom et de la
tête-épaules sont des NIVEAUX (moyenne des points concernés), pas des
trendlines obliques — suffisant pour un signal de trading, pas un outil de
tracé graphique.
"""

from __future__ import annotations

from dataclasses import dataclass

from forex import config
from forex.signals import indicators

# Fenêtre du drapeau/fanion : nombre de bougies de l'impulsion ("pole") et de
# la consolidation qui suit. Valeurs internes (non exposées en config) pour
# limiter le nombre de paramètres réglables (anti-overfitting).
_FLAG_POLE_BARS = 10
_FLAG_CONSOL_BARS = 6
_FLAG_POLE_ATR_MULT = 3.0       # l'impulsion doit valoir au moins 3×ATR
_FLAG_CONSOL_ATR_MULT = 1.5     # la consolidation doit être plus étroite que 1.5×ATR


@dataclass
class SwingPoint:
    index: int
    price: float
    kind: str   # 'high' | 'low'


@dataclass
class PatternMatch:
    name: str
    direction: str      # 'long' | 'short'
    strength: float     # 0.0 → 1.0
    reason: str


def swing_points(
    candles: list[list[float]],
    left: int = config.FOREX_SWING_LEFT,
    right: int = config.FOREX_SWING_RIGHT,
) -> list[SwingPoint]:
    """
    Points de swing confirmés : une bougie i est un sommet/creux si son
    high/low est extrême sur la fenêtre [i-left, i+right]. Comme il faut
    `right` bougies APRÈS i pour le confirmer, seuls des points déjà
    confirmables dans `candles` sont retournés (pas de look-ahead).
    """
    points: list[SwingPoint] = []
    n = len(candles)
    for i in range(left, n - right):
        highs = [candles[j][2] for j in range(i - left, i + right + 1)]
        lows = [candles[j][3] for j in range(i - left, i + right + 1)]
        h, l = candles[i][2], candles[i][3]
        if h == max(highs):
            points.append(SwingPoint(i, h, "high"))
        if l == min(lows):
            points.append(SwingPoint(i, l, "low"))
    return points


def _tol(atr: float) -> float:
    return config.FOREX_PATTERN_TOLERANCE_ATR * atr


def detect_double_top(
    candles: list[list[float]], swings: list[SwingPoint], atr: float
) -> PatternMatch | None:
    """Deux sommets similaires séparés par un creux (ligne de cou) → baissier à la cassure."""
    highs = [s for s in swings if s.kind == "high"]
    if len(highs) < 2 or atr <= 0:
        return None
    h1, h2 = highs[-2], highs[-1]
    if abs(h1.price - h2.price) > _tol(atr):
        return None
    lows_between = [s for s in swings if s.kind == "low" and h1.index < s.index < h2.index]
    if not lows_between:
        return None
    neckline = min(s.price for s in lows_between)
    close = candles[-1][4]
    if close >= neckline - _tol(atr) * 0.2:
        return None  # pas encore cassé
    clarity = 1.0 - min(1.0, abs(h1.price - h2.price) / _tol(atr))
    break_strength = min(1.0, (neckline - close) / _tol(atr))
    return PatternMatch(
        "Double Top", "short", round(min(1.0, 0.5 * clarity + 0.5 * break_strength), 3),
        f"deux sommets ≈{h1.price:.5f}/{h2.price:.5f}, cassure de la ligne de cou {neckline:.5f}",
    )


def detect_double_bottom(
    candles: list[list[float]], swings: list[SwingPoint], atr: float
) -> PatternMatch | None:
    """Miroir du double top : deux creux similaires → haussier à la cassure."""
    lows = [s for s in swings if s.kind == "low"]
    if len(lows) < 2 or atr <= 0:
        return None
    l1, l2 = lows[-2], lows[-1]
    if abs(l1.price - l2.price) > _tol(atr):
        return None
    highs_between = [s for s in swings if s.kind == "high" and l1.index < s.index < l2.index]
    if not highs_between:
        return None
    neckline = max(s.price for s in highs_between)
    close = candles[-1][4]
    if close <= neckline + _tol(atr) * 0.2:
        return None
    clarity = 1.0 - min(1.0, abs(l1.price - l2.price) / _tol(atr))
    break_strength = min(1.0, (close - neckline) / _tol(atr))
    return PatternMatch(
        "Double Bottom", "long", round(min(1.0, 0.5 * clarity + 0.5 * break_strength), 3),
        f"deux creux ≈{l1.price:.5f}/{l2.price:.5f}, cassure de la ligne de cou {neckline:.5f}",
    )


def detect_head_shoulders(
    candles: list[list[float]], swings: list[SwingPoint], atr: float
) -> PatternMatch | None:
    """Tête-épaules (baissier) sur 3 sommets, ou sa version inversée (haussier) sur 3 creux."""
    if atr <= 0:
        return None

    highs = [s for s in swings if s.kind == "high"]
    if len(highs) >= 3:
        l, m, r = highs[-3], highs[-2], highs[-1]
        if (m.price - l.price > _tol(atr) and m.price - r.price > _tol(atr)
                and abs(l.price - r.price) <= _tol(atr)):
            lows_between = [s for s in swings if s.kind == "low" and l.index < s.index < r.index]
            if len(lows_between) >= 2:
                neckline = sum(s.price for s in lows_between[:2]) / 2
                close = candles[-1][4]
                if close < neckline - _tol(atr) * 0.2:
                    clarity = 1.0 - min(1.0, abs(l.price - r.price) / _tol(atr))
                    break_strength = min(1.0, (neckline - close) / _tol(atr))
                    return PatternMatch(
                        "Tête-épaules", "short",
                        round(min(1.0, 0.5 * clarity + 0.5 * break_strength), 3),
                        f"tête {m.price:.5f} > épaules {l.price:.5f}/{r.price:.5f}, "
                        f"cassure ligne de cou {neckline:.5f}",
                    )

    lows = [s for s in swings if s.kind == "low"]
    if len(lows) >= 3:
        l, m, r = lows[-3], lows[-2], lows[-1]
        if (l.price - m.price > _tol(atr) and r.price - m.price > _tol(atr)
                and abs(l.price - r.price) <= _tol(atr)):
            highs_between = [s for s in swings if s.kind == "high" and l.index < s.index < r.index]
            if len(highs_between) >= 2:
                neckline = sum(s.price for s in highs_between[:2]) / 2
                close = candles[-1][4]
                if close > neckline + _tol(atr) * 0.2:
                    clarity = 1.0 - min(1.0, abs(l.price - r.price) / _tol(atr))
                    break_strength = min(1.0, (close - neckline) / _tol(atr))
                    return PatternMatch(
                        "Tête-épaules inversée", "long",
                        round(min(1.0, 0.5 * clarity + 0.5 * break_strength), 3),
                        f"tête {m.price:.5f} < épaules {l.price:.5f}/{r.price:.5f}, "
                        f"cassure ligne de cou {neckline:.5f}",
                    )
    return None


def _linreg(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Régression linéaire simple (moindres carrés). Retourne (pente, intercept)."""
    n = len(points)
    if n < 2:
        return 0.0, (points[0][1] if points else 0.0)
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] ** 2 for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, sy / n
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


def detect_triangle(
    candles: list[list[float]], swings: list[SwingPoint], atr: float,
    lookback: int = config.FOREX_PATTERN_LOOKBACK,
) -> PatternMatch | None:
    """Triangle ascendant/descendant/symétrique via régression sur les swings récents."""
    if atr <= 0 or len(candles) < 10:
        return None
    cutoff = len(candles) - lookback
    recent_highs = [s for s in swings if s.kind == "high" and s.index >= cutoff]
    recent_lows = [s for s in swings if s.kind == "low" and s.index >= cutoff]
    if len(recent_highs) < 2 or len(recent_lows) < 2:
        return None

    top_slope, top_intercept = _linreg([(s.index, s.price) for s in recent_highs])
    bot_slope, bot_intercept = _linreg([(s.index, s.price) for s in recent_lows])

    flat_threshold = 0.5 * atr / max(lookback, 1)  # pente quasi nulle sur la fenêtre
    top_kind = "flat" if abs(top_slope) < flat_threshold else ("rising" if top_slope > 0 else "falling")
    bot_kind = "flat" if abs(bot_slope) < flat_threshold else ("rising" if bot_slope > 0 else "falling")

    last_i = len(candles) - 1
    top_line = top_slope * last_i + top_intercept
    bot_line = bot_slope * last_i + bot_intercept
    close = candles[-1][4]
    margin = _tol(atr) * 0.2

    if top_kind == "flat" and bot_kind == "rising":
        if close > top_line + margin:
            strength = round(min(1.0, (close - top_line) / _tol(atr)), 3)
            return PatternMatch("Triangle ascendant", "long", strength,
                               f"résistance plate {top_line:.5f} cassée par le haut")
        return None
    if bot_kind == "flat" and top_kind == "falling":
        if close < bot_line - margin:
            strength = round(min(1.0, (bot_line - close) / _tol(atr)), 3)
            return PatternMatch("Triangle descendant", "short", strength,
                               f"support plat {bot_line:.5f} cassé par le bas")
        return None
    if top_kind == "falling" and bot_kind == "rising":
        if close > top_line + margin:
            strength = round(min(1.0, (close - top_line) / _tol(atr)), 3)
            return PatternMatch("Triangle symétrique", "long", strength,
                               f"cassure haussière du triangle symétrique ({top_line:.5f})")
        if close < bot_line - margin:
            strength = round(min(1.0, (bot_line - close) / _tol(atr)), 3)
            return PatternMatch("Triangle symétrique", "short", strength,
                               f"cassure baissière du triangle symétrique ({bot_line:.5f})")
    return None


def detect_flag(candles: list[list[float]], atr: float) -> PatternMatch | None:
    """Impulsion forte + consolidation étroite + cassure dans le sens de l'impulsion."""
    total_needed = _FLAG_POLE_BARS + _FLAG_CONSOL_BARS + 1
    if atr <= 0 or len(candles) < total_needed:
        return None

    consol = candles[-(_FLAG_CONSOL_BARS + 1):-1]   # consolidation (hors bougie de cassure)
    pole = candles[-(_FLAG_POLE_BARS + _FLAG_CONSOL_BARS + 1): -(_FLAG_CONSOL_BARS + 1)]
    breakout = candles[-1]

    pole_move = pole[-1][4] - pole[0][4]
    if abs(pole_move) < _FLAG_POLE_ATR_MULT * atr:
        return None  # pas d'impulsion nette

    consol_high = max(c[2] for c in consol)
    consol_low = min(c[3] for c in consol)
    if (consol_high - consol_low) > _FLAG_CONSOL_ATR_MULT * atr:
        return None  # consolidation pas assez étroite

    close = breakout[4]
    margin = _tol(atr) * 0.2
    if pole_move > 0 and close > consol_high + margin:
        strength = round(min(1.0, (close - consol_high) / _tol(atr)), 3)
        return PatternMatch("Drapeau haussier", "long", strength,
                           f"impulsion +{pole_move:.5f}, cassure de consolidation {consol_high:.5f}")
    if pole_move < 0 and close < consol_low - margin:
        strength = round(min(1.0, (consol_low - close) / _tol(atr)), 3)
        return PatternMatch("Drapeau baissier", "short", strength,
                           f"impulsion {pole_move:.5f}, cassure de consolidation {consol_low:.5f}")
    return None


def detect_patterns(candles: list[list[float]]) -> PatternMatch | None:
    """Exécute tous les détecteurs et retourne la figure CONFIRMÉE la plus nette (ou None)."""
    if len(candles) < 30:
        return None
    atr = indicators.atr(candles, config.ATR_PERIOD)
    if atr <= 0:
        return None
    swings = swing_points(candles)

    candidates = [
        detect_double_top(candles, swings, atr),
        detect_double_bottom(candles, swings, atr),
        detect_head_shoulders(candles, swings, atr),
        detect_triangle(candles, swings, atr),
        detect_flag(candles, atr),
    ]
    matches = [m for m in candidates if m is not None]
    if not matches:
        return None
    return max(matches, key=lambda m: m.strength)
