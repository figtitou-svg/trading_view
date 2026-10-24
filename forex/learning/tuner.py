"""
forex/learning/tuner.py — Auto-tuner des paramètres par walk-forward.

Ré-optimise une **petite** grille de paramètres (multiples ATR stop/TP) en
**walk-forward** : chaque jeu candidat est évalué HORS ÉCHANTILLON sur des
fenêtres de test glissantes (paramètre figé), puis comparé au réglage courant.

Garde-fous (anti-overfitting) — un changement n'est proposé QUE si :
  - le nombre de folds ≥ `FOREX_LEARN_MIN_FOLDS` ;
  - la proportion de folds positifs ≥ `FOREX_LEARN_POSITIVE_FOLD_RATIO` ;
  - le gain OOS composé dépasse le courant d'au moins `FOREX_LEARN_OOS_MARGIN_PCT`.
Sinon : `accepted = False`, on ne touche à rien.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from forex import config
from forex.data.calendar import EconEvent
from forex.backtest.engine import run_backtest

# Grille volontairement PETITE et justifiée (pas de brute force).
TUNE_GRID = [
    {"atr_stop_mult": s, "atr_tp_mult": t}
    for s in (1.5, 2.0, 2.5)
    for t in (2.0, 3.0, 4.0)
]


def _compound(pnls: list[float]) -> float:
    eq = 1.0
    for p in pnls:
        eq *= (1 + p / 100)
    return (eq - 1) * 100


def _fixed_param_oos(
    candles: list[list[float]], pair: str, events: list[EconEvent], params: dict,
    *, train_bars: int, test_bars: int, warmup: int, **bt,
) -> list[float]:
    """
    Rendements OOS par fold pour un jeu de paramètres FIGÉ.

    Les paramètres ne changeant pas en cours de route, UN SEUL rejeu causal du
    backtest complet produit les mêmes trades que des rejeux tronqués fold par
    fold — on découpe ensuite par fenêtre de test (via entry_ts).
    """
    res = run_backtest(candles, pair, events, warmup=warmup, **{**bt, **params})
    fold_returns: list[float] = []
    f_start = warmup
    while f_start + train_bars + test_bars <= len(candles):
        train_end = f_start + train_bars
        test_end = min(train_end + test_bars, len(candles))
        lo, hi = candles[train_end][0], candles[test_end - 1][0]
        fold_pnls = [t.pnl_pct for t in res.trades if lo <= t.entry_ts <= hi]
        fold_returns.append(_compound(fold_pnls))
        f_start += test_bars
    return fold_returns


@dataclass
class TuneProposal:
    pair: str
    accepted: bool
    reason: str
    changes: dict = field(default_factory=dict)     # {field: after}
    before: dict = field(default_factory=dict)      # {field: before}
    oos_before: float = 0.0
    oos_after: float = 0.0
    n_folds: int = 0
    positive_folds: int = 0

    def summary(self) -> str:
        if not self.accepted:
            return f"[{self.pair}] pas de changement — {self.reason}"
        ch = ", ".join(f"{k}: {self.before.get(k)}→{v}" for k, v in self.changes.items())
        return (f"[{self.pair}] {ch} · OOS {self.oos_before:+.1f}%→{self.oos_after:+.1f}% "
                f"({self.positive_folds}/{self.n_folds} folds+)")


def propose(
    pair: str,
    candles: list[list[float]],
    events: list[EconEvent] | None = None,
    current: dict | None = None,
    *,
    train_bars: int = 1500,
    test_bars: int = 500,
    grid: list[dict] | None = None,
    defaults: dict | None = None,
    **backtest_kwargs,
) -> TuneProposal:
    """
    Évalue la grille en walk-forward et propose (ou non) un nouveau réglage.

    `defaults` : réglage de référence quand aucun override n'a encore été
    appris. Chaque bot a le sien (le stop de `smc` est serré, celui de `macro`
    large) : partir des constantes globales comparerait le candidat à un
    réglage que le bot n'utilise pas.
    """
    events = events or []
    grid = grid or TUNE_GRID
    warmup = max(config.MA_SLOW, config.MACD_SLOW + config.MACD_SIGNAL) + 5

    # Réglage courant = overrides appris, sinon défauts du bot, sinon config.
    current = current or {}
    defaults = defaults or {}
    base = {
        "atr_stop_mult": current.get("atr_stop_mult",
                                     defaults.get("atr_stop_mult", config.ATR_STOP_MULT)),
        "atr_tp_mult": current.get("atr_tp_mult",
                                   defaults.get("atr_tp_mult", config.ATR_TP_MULT)),
    }

    common = dict(train_bars=train_bars, test_bars=test_bars, warmup=warmup, **backtest_kwargs)
    base_folds = _fixed_param_oos(candles, pair, events, base, **common)
    if len(base_folds) < config.FOREX_LEARN_MIN_FOLDS:
        return TuneProposal(pair, False, f"folds insuffisants ({len(base_folds)})")
    base_oos = _compound(base_folds)

    best_params, best_oos, best_folds = base, base_oos, base_folds
    for params in grid:
        if params == base:
            continue
        folds = _fixed_param_oos(candles, pair, events, params, **common)
        oos = _compound(folds)
        if oos > best_oos:
            best_params, best_oos, best_folds = params, oos, folds

    if best_params == base:
        return TuneProposal(pair, False, "aucun réglage ne bat le courant",
                            oos_before=base_oos, oos_after=base_oos,
                            n_folds=len(base_folds))

    positive = sum(1 for r in best_folds if r > 0)
    ratio = positive / len(best_folds)
    if ratio < config.FOREX_LEARN_POSITIVE_FOLD_RATIO:
        return TuneProposal(pair, False,
                            f"folds positifs insuffisants ({positive}/{len(best_folds)})",
                            oos_before=base_oos, oos_after=best_oos,
                            n_folds=len(best_folds), positive_folds=positive)
    if best_oos - base_oos < config.FOREX_LEARN_OOS_MARGIN_PCT:
        return TuneProposal(pair, False,
                            f"gain OOS insuffisant ({best_oos - base_oos:+.1f}% < "
                            f"{config.FOREX_LEARN_OOS_MARGIN_PCT}%)",
                            oos_before=base_oos, oos_after=best_oos,
                            n_folds=len(best_folds), positive_folds=positive)

    changes = {k: v for k, v in best_params.items() if base.get(k) != v}
    before = {k: base.get(k) for k in changes}
    return TuneProposal(pair, True, "walk-forward validé", changes=changes, before=before,
                        oos_before=base_oos, oos_after=best_oos,
                        n_folds=len(best_folds), positive_folds=positive)
