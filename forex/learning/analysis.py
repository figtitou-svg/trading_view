"""
forex/learning/analysis.py — Analyse de performance par combinaison de signaux.

Regroupe les trades du journal par `combo` (ex. 'tech:long', 'tech+fund:short')
et calcule, pour chacun : n, win rate, expectancy (moyenne de pnl_pct), profit
factor, et un **test de significativité** (t-test de la moyenne de pnl_pct vs 0).

Le module 7 n'agit (désactive/réactive un combo) que si un combo est
**statistiquement** perdant/gagnant ET avec un échantillon ≥ MIN_SAMPLE — pour
ne jamais réagir au bruit d'une poignée de trades.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from forex import config


@dataclass
class ComboStats:
    combo: str
    n: int
    wins: int
    losses: int
    neutrals: int
    win_rate: float
    expectancy: float          # moyenne de pnl_pct (% du capital par trade)
    profit_factor: float
    t_stat: float
    p_value: float
    n_live: int = 0
    n_backtest: int = 0

    @property
    def enough_sample(self) -> bool:
        return self.n >= config.FOREX_LEARN_MIN_SAMPLE

    @property
    def significant_loser(self) -> bool:
        """Assez de preuve que ce combo perd de l'argent (à désactiver)."""
        return (self.enough_sample and self.expectancy < 0
                and self.p_value < config.FOREX_LEARN_ALPHA)

    @property
    def significant_winner(self) -> bool:
        """Assez de preuve que ce combo gagne (à (ré)activer)."""
        return (self.enough_sample and self.expectancy > 0
                and self.p_value < config.FOREX_LEARN_ALPHA)

    def to_dict(self) -> dict:
        # inf (aucune perte) n'est pas sérialisable en JSON → None côté API.
        pf = round(self.profit_factor, 2) if self.profit_factor != float("inf") else None
        return {
            "combo": self.combo, "n": self.n, "wins": self.wins, "losses": self.losses,
            "neutrals": self.neutrals, "win_rate": round(self.win_rate, 1),
            "expectancy": round(self.expectancy, 4), "profit_factor": pf,
            "p_value": round(self.p_value, 4),
            "enough_sample": self.enough_sample,
            "n_live": self.n_live, "n_backtest": self.n_backtest,
            "verdict": ("perdant significatif" if self.significant_loser
                        else "gagnant significatif" if self.significant_winner
                        else "non concluant"),
        }


def _profit_factor(pnls: list[float]) -> float:
    gains = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def _ttest_vs_zero(values: list[float]) -> tuple[float, float]:
    """t-test unilatéral de la moyenne vs 0. Retourne (t, p_bilatéral)."""
    if len(values) < 2:
        return 0.0, 1.0
    try:
        from scipy import stats
    except ImportError:
        return 0.0, 1.0
    t, p = stats.ttest_1samp(values, 0.0)
    if t != t:  # NaN (variance nulle)
        return 0.0, 1.0
    return float(t), float(p)


def analyze(trades: list[dict]) -> dict[str, ComboStats]:
    """Retourne {combo: ComboStats} à partir des enregistrements du journal."""
    groups: dict[str, list[dict]] = {}
    for t in trades:
        groups.setdefault(t.get("combo", "?"), []).append(t)

    out: dict[str, ComboStats] = {}
    for combo, ts in groups.items():
        pnls = [t.get("pnl_pct", 0.0) for t in ts]
        wins = sum(1 for t in ts if t.get("classification") == "win")
        losses = sum(1 for t in ts if t.get("classification") == "loss")
        neutrals = sum(1 for t in ts if t.get("classification") == "neutral")
        n_live = sum(1 for t in ts if t.get("source", "live") == "live")
        decided = wins + losses
        t_stat, p_value = _ttest_vs_zero(pnls)
        out[combo] = ComboStats(
            combo=combo, n=len(ts), wins=wins, losses=losses, neutrals=neutrals,
            win_rate=(wins / decided * 100) if decided else 0.0,
            expectancy=sum(pnls) / len(pnls) if pnls else 0.0,
            profit_factor=_profit_factor(pnls),
            t_stat=t_stat, p_value=p_value,
            n_live=n_live, n_backtest=len(ts) - n_live,
        )
    return out


def summary(stats: dict[str, ComboStats]) -> str:
    if not stats:
        return "Aucun trade journalisé pour l'instant."
    lines = ["Performance par combinaison de signaux :"]
    for s in sorted(stats.values(), key=lambda x: x.expectancy):
        lines.append(
            f"  {s.combo:16} n={s.n:3} ({s.n_live} live · {s.n_backtest} hist.) · "
            f"win {s.win_rate:4.0f}% · expectancy {s.expectancy:+.3f}% · "
            f"PF {s.profit_factor:.2f} · {s.to_dict()['verdict']}"
        )
    return "\n".join(lines)
