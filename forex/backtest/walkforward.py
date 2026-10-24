"""
forex/backtest/walkforward.py — Walk-forward optimization (validation glissante).

Plutôt qu'un unique split train/test (sur-ajustable), on avance par fenêtres :
sur chaque fenêtre d'entraînement on choisit le meilleur jeu de paramètres
(petite grille, justifiée théoriquement — pas de brute force), puis on l'évalue
sur la fenêtre de test **immédiatement suivante** (hors échantillon). Les
résultats de test concaténés donnent une performance réaliste, sans look-ahead
(le test est toujours postérieur à l'entraînement qui l'a calibré).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from forex import config
from forex.data.calendar import EconEvent
from forex.backtest.engine import run_backtest, Trade


def _compound_return(trades: list[Trade]) -> float:
    """Rendement composé (%) d'une liste de trades via leurs pnl_pct."""
    eq = 1.0
    for t in trades:
        eq *= (1 + t.pnl_pct / 100)
    return (eq - 1) * 100


@dataclass
class Fold:
    train_start_ts: int
    train_end_ts: int
    test_end_ts: int
    best_params: dict
    train_return_pct: float
    test_return_pct: float
    test_trade_count: int
    test_trades: list[Trade] = field(default_factory=list)


@dataclass
class WalkForwardResult:
    pair: str
    folds: list[Fold] = field(default_factory=list)

    @property
    def oos_return_pct(self) -> float:
        eq = 1.0
        for f in self.folds:
            eq *= (1 + f.test_return_pct / 100)
        return (eq - 1) * 100

    @property
    def oos_trades(self) -> int:
        return sum(f.test_trade_count for f in self.folds)

    @property
    def oos_sharpe(self) -> float:
        from forex.backtest.engine import sharpe_ratio

        pooled = [t for f in self.folds for t in f.test_trades]
        return sharpe_ratio(pooled)

    @property
    def positive_folds(self) -> int:
        return sum(1 for f in self.folds if f.test_return_pct > 0)

    def summary(self) -> str:
        return (
            f"[{self.pair}] Walk-forward : {len(self.folds)} folds · "
            f"rendement OOS composé {self.oos_return_pct:+.1f}% · "
            f"Sharpe OOS {self.oos_sharpe:.2f} · "
            f"{self.positive_folds}/{len(self.folds)} folds positifs · "
            f"{self.oos_trades} trades OOS"
        )


DEFAULT_GRID = [{"atr_tp_mult": tp} for tp in (2.0, 3.0, 4.0)]


def walk_forward(
    candles: list[list[float]],
    pair: str,
    events: list[EconEvent] | None = None,
    *,
    train_bars: int = 1500,
    test_bars: int = 500,
    param_grid: list[dict] | None = None,
    warmup: int | None = None,
    **backtest_kwargs,
) -> WalkForwardResult:
    """Exécute la validation walk-forward. `param_grid` = liste de dicts d'overrides."""
    events = events or []
    param_grid = param_grid or DEFAULT_GRID
    warmup = warmup or max(config.MA_SLOW, config.MACD_SLOW + config.MACD_SIGNAL) + 5
    result = WalkForwardResult(pair)

    f_start = warmup
    while f_start + train_bars + test_bars <= len(candles):
        train_end = f_start + train_bars
        test_end = min(train_end + test_bars, len(candles))
        train_start_ts = candles[f_start][0]
        train_end_ts = candles[train_end][0]
        test_end_ts = candles[test_end - 1][0]

        # ── Optimisation sur la fenêtre d'entraînement ────
        best_params, best_score = param_grid[0], float("-inf")
        for params in param_grid:
            res = run_backtest(candles[:train_end], pair, events,
                               warmup=warmup, **{**backtest_kwargs, **params})
            train_trades = [t for t in res.trades if t.entry_ts >= train_start_ts]
            score = _compound_return(train_trades)
            if score > best_score:
                best_score, best_params = score, params

        # ── Évaluation hors échantillon ───────────────────
        res = run_backtest(candles[:test_end], pair, events,
                           warmup=warmup, **{**backtest_kwargs, **best_params})
        test_trades = [t for t in res.trades if train_end_ts <= t.entry_ts <= test_end_ts]

        result.folds.append(Fold(
            train_start_ts=train_start_ts, train_end_ts=train_end_ts, test_end_ts=test_end_ts,
            best_params=best_params, train_return_pct=round(best_score, 2),
            test_return_pct=round(_compound_return(test_trades), 2),
            test_trade_count=len(test_trades), test_trades=test_trades,
        ))
        f_start += test_bars  # avance non chevauchante

    return result
