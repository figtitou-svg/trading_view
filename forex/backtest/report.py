"""
forex/backtest/report.py — Rapport de validation d'une paire.

Assemble toutes les briques de validation exigées AVANT tout paper trading :
  1. Backtest de la stratégie de **confluence** (tous signaux) — coûts inclus ;
  2. Backtest **technique seule** (signal fondamental désactivé) — benchmark clé :
     la confluence doit le battre pour justifier la brique fondamentale ;
  3. **Buy & hold** — benchmark passif ;
  4. **Event study / CAR** — la brique fondamentale a-t-elle un edge statistique ?
  5. **Walk-forward** — robustesse hors échantillon.

Usage :
    python -m forex.backtest.report --pair EUR_USD --granularity H1
"""

from __future__ import annotations

from dataclasses import dataclass

from forex import config
from forex.data import prices, calendar as cal
from forex.backtest.engine import run_backtest, buy_and_hold_return_pct, BacktestResult
from forex.backtest.event_study import event_study, EventStudyResult
from forex.backtest.walkforward import walk_forward, WalkForwardResult


@dataclass
class ValidationReport:
    pair: str
    n_candles: int
    n_events: int
    confluence: BacktestResult
    technical_only: BacktestResult
    buy_hold_pct: float
    study: EventStudyResult | None
    walk: WalkForwardResult | None

    @property
    def confluence_beats_technical(self) -> bool:
        return self.confluence.total_return_pct > self.technical_only.total_return_pct

    def text(self) -> str:
        lines = [
            "═" * 66,
            f"  RAPPORT DE VALIDATION — {self.pair}",
            "═" * 66,
            f"  Données   : {self.n_candles} bougies · {self.n_events} events macro",
            "",
            "  Stratégies (coûts spread+slippage+swap inclus) :",
            f"    • Confluence      : {self.confluence.summary()}",
            f"    • Technique seule : {self.technical_only.summary()}",
            f"    • Buy & hold      : rendement {self.buy_hold_pct:+.1f}%",
            "",
        ]
        edge = "OUI ✅" if self.confluence_beats_technical else "NON ❌"
        lines.append(f"  → La confluence bat-elle la technique seule ? {edge}")

        sharpe = self.confluence.sharpe_ratio()
        if sharpe > 3:
            sharpe_flag = "⚠️ suspect (>3, probable sur-optimisation)"
        elif sharpe < 0.5:
            sharpe_flag = "⚠️ edge faible ou nul (<0.5)"
        else:
            sharpe_flag = "OK (0.5–2, plage crédible)"
        lines += ["", f"  Sharpe (confluence) : {sharpe:.2f} — {sharpe_flag}"]

        by_session = self.confluence.sharpe_by_session()
        if by_session:
            lines.append("  Sharpe par session  : " + " · ".join(
                f"{name} {value:.2f}" for name, value in sorted(by_session.items())))
        if self.study is not None:
            lines += ["", "  Event study (brique fondamentale) :", "    " + self.study.summary()]
        if self.walk is not None:
            lines += ["", "  Robustesse hors échantillon :", "    " + self.walk.summary()]
        lines += [
            "",
            "  Verdict : passer en paper trading UNIQUEMENT si la confluence bat la",
            "  technique seule ET que l'event study est significatif ET que le",
            "  walk-forward reste positif hors échantillon.",
            "═" * 66,
        ]
        return "\n".join(lines)


def build_report(
    pair: str,
    *,
    granularity: str = config.FOREX_GRANULARITY,
    period: str | None = None,
    do_walkforward: bool = True,
) -> ValidationReport:
    candles = prices.fetch_ohlcv(pair, granularity, period=period)
    base, quote = pair.upper().split("_")
    events = [e for e in cal.load_events() if e.currency in {base, quote}]

    common = dict(granularity=granularity)
    # Le rapport juge la VRAIE confluence → mode strict (tous les signaux requis).
    confluence = run_backtest(candles, pair, events, use_fundamental=True,
                              use_technical=True, use_time_filter=True,
                              confluence_mode="strict", **common)
    technical_only = run_backtest(candles, pair, events, use_fundamental=False,
                                  use_technical=True, use_time_filter=True, **common)
    bh = buy_and_hold_return_pct(candles)

    study = None
    if events:
        try:
            study = event_study(pair, events, candles)
        except Exception as exc:
            print(f"[report] event study indisponible : {exc}")

    walk = None
    if do_walkforward and len(candles) >= 2200:
        walk = walk_forward(candles, pair, events, granularity=granularity)

    return ValidationReport(
        pair=pair, n_candles=len(candles), n_events=len(events),
        confluence=confluence, technical_only=technical_only,
        buy_hold_pct=bh, study=study, walk=walk,
    )


def _cli() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Rapport de validation forex")
    ap.add_argument("--pair", default=config.FOREX_PAIRS[0], help="Paire, ex. EUR_USD")
    ap.add_argument("--granularity", default=config.FOREX_GRANULARITY)
    ap.add_argument("--period", default=None, help="Période yfinance (ex. 730d, 2y)")
    ap.add_argument("--no-walkforward", action="store_true")
    args = ap.parse_args()

    report = build_report(
        args.pair.upper(), granularity=args.granularity,
        period=args.period, do_walkforward=not args.no_walkforward,
    )
    print(report.text())


if __name__ == "__main__":
    _cli()
