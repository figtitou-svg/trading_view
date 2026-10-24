"""
forex/backtest/event_study.py — Event study & Cumulative Abnormal Return (CAR).

Valide **statistiquement** que le signal fondamental a un edge AVANT de le
trader : pour chaque type d'annonce, on mesure le rendement cumulé de la paire
dans la fenêtre qui suit l'annonce, exprimé « en faveur de la devise » (signe
ajusté selon que la devise est base ou quote), puis on teste si les surprises
POSITIVES et NÉGATIVES produisent des CAR significativement différents
(t-test de Welch + bootstrap). Sans cet écart significatif, la brique
fondamentale n'a pas d'edge et ne doit pas être tradée.

Le surprise score est calculé sans look-ahead (cf. forex.signals.fundamental).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from forex import config
from forex.data.calendar import EconEvent
from forex.signals.fundamental import event_polarity, surprise_score


@dataclass
class EventStudyResult:
    pair: str
    window_bars: int
    n_positive: int
    n_negative: int
    mean_car_positive: float          # CAR moyen (en faveur devise), surprises +
    mean_car_negative: float          # CAR moyen, surprises -
    t_stat: float
    p_value: float
    bootstrap_p: float
    per_event: dict = field(default_factory=dict)

    @property
    def significant(self) -> bool:
        return self.p_value < 0.05 and (self.mean_car_positive > self.mean_car_negative)

    def summary(self) -> str:
        verdict = "SIGNIFICATIF ✅" if self.significant else "non significatif ❌"
        return (
            f"[{self.pair}] Event study ({self.n_positive}+/{self.n_negative}- surprises, "
            f"fenêtre {self.window_bars} barres) : CAR+ {self.mean_car_positive*100:+.3f}% vs "
            f"CAR- {self.mean_car_negative*100:+.3f}% · t={self.t_stat:.2f} p={self.p_value:.4f} "
            f"(bootstrap p={self.bootstrap_p:.4f}) → {verdict}"
        )


def _car_in_currency(pair: str, currency: str, entry_close: float, exit_close: float) -> float | None:
    """Rendement cumulé exprimé « en faveur de la devise » de l'annonce."""
    base, quote = pair.upper().split("_")
    pair_ret = exit_close / entry_close - 1
    if currency == base:
        return pair_ret
    if currency == quote:
        return -pair_ret
    return None


def collect_car_samples(
    pair: str,
    events: list[EconEvent],
    candles: list[list[float]],
    *,
    window_bars: int = 6,
    min_history: int = config.FOREX_MIN_SURPRISE_HISTORY,
) -> tuple[list[float], list[float], dict]:
    """
    Retourne (car_surprises_positives, car_surprises_negatives, détail_par_type).
    Un échantillon = CAR (en faveur devise) sur `window_bars` après une annonce
    dont le surprise score signé (× polarité) est calculable.
    """
    base, quote = pair.upper().split("_")
    ccys = {base, quote}
    ts_list = [c[0] for c in candles]

    pos_car: list[float] = []
    neg_car: list[float] = []
    per_event: dict = {}

    for e in events:
        if e.currency not in ccys or not e.has_result:
            continue
        score = surprise_score(e, events, min_history)
        if score is None or score == 0:
            continue
        signed = score * event_polarity(e)   # >0 = surprise favorable à la devise

        idx = bisect.bisect_left(ts_list, int(e.dt.timestamp() * 1000))
        if idx >= len(candles) or idx + window_bars >= len(candles):
            continue
        car = _car_in_currency(pair, e.currency, candles[idx][4], candles[idx + window_bars][4])
        if car is None:
            continue

        (pos_car if signed > 0 else neg_car).append(car)
        et = e.event_type()
        per_event.setdefault(et, {"pos": [], "neg": []})
        per_event[et]["pos" if signed > 0 else "neg"].append(car)

    return pos_car, neg_car, per_event


def _bootstrap_diff_p(pos: list[float], neg: list[float], n_iter: int = 5000) -> float:
    """p-value bootstrap (unilatéral) que mean(pos) > mean(neg) par permutation."""
    import numpy as np

    if not pos or not neg:
        return 1.0
    rng = np.random.default_rng(42)
    observed = float(np.mean(pos) - np.mean(neg))
    pool = np.array(pos + neg)
    n_pos = len(pos)
    count = 0
    for _ in range(n_iter):
        rng.shuffle(pool)
        diff = pool[:n_pos].mean() - pool[n_pos:].mean()
        if diff >= observed:
            count += 1
    return count / n_iter


def event_study(
    pair: str,
    events: list[EconEvent],
    candles: list[list[float]],
    *,
    window_bars: int = 6,
    min_history: int = config.FOREX_MIN_SURPRISE_HISTORY,
) -> EventStudyResult:
    """Réalise l'event study complète pour une paire."""
    import numpy as np
    from scipy import stats

    pos, neg, per_event = collect_car_samples(
        pair, events, candles, window_bars=window_bars, min_history=min_history
    )

    if len(pos) >= 2 and len(neg) >= 2:
        t_stat, p_two = stats.ttest_ind(pos, neg, equal_var=False)
        # Hypothèse unilatérale : CAR+ > CAR-
        p_value = p_two / 2 if t_stat > 0 else 1 - p_two / 2
        boot_p = _bootstrap_diff_p(pos, neg)
    else:
        t_stat, p_value, boot_p = 0.0, 1.0, 1.0

    per_summary = {
        et: {
            "n_pos": len(d["pos"]), "n_neg": len(d["neg"]),
            "mean_pos": float(np.mean(d["pos"])) if d["pos"] else 0.0,
            "mean_neg": float(np.mean(d["neg"])) if d["neg"] else 0.0,
        }
        for et, d in per_event.items()
    }

    return EventStudyResult(
        pair=pair, window_bars=window_bars,
        n_positive=len(pos), n_negative=len(neg),
        mean_car_positive=float(np.mean(pos)) if pos else 0.0,
        mean_car_negative=float(np.mean(neg)) if neg else 0.0,
        t_stat=float(t_stat), p_value=float(p_value), bootstrap_p=float(boot_p),
        per_event=per_summary,
    )
