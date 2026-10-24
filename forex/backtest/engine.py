"""
forex/backtest/engine.py — Moteur de backtest événementiel (pandas/numpy libre).

Rejoue la stratégie de confluence bougie par bougie sur une paire :
  - à chaque bougie CLÔTURÉE et en position flat, on évalue `confluence.evaluate`
    (avec la fenêtre d'historique disponible → aucun look-ahead) ;
  - à l'entrée, on pose stop/TP en multiples d'ATR ; le prix d'entrée subit le
    spread + slippage (coûts réalistes) ;
  - en position, stop/TP sont testés en intrabar (high/low), et un trade
    event-driven sans mouvement utile est coupé après EVENT_TRADE_MAX_MIN ;
  - le swap overnight est déduit par jour de détention.

Comptabilité **broker-agnostique** : la taille est fixée pour que toucher le
stop coûte exactement `risk_pct` % du capital. Donc le P&L d'un trade en % du
capital = (pips nets / pips du stop) × risk_pct — pas besoin de valeur de pip
ni de taux croisé, et les stratégies restent comparables entre elles et au
buy & hold.

Chaque trade journalise le contexte COMPLET des signaux à l'entrée (pas
seulement les déclencheurs) pour un post-mortem quantitatif ET qualitatif.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone

from forex import config
from forex.data.calendar import EconEvent
from forex.risk.sizing import pip_size, price_distance_to_pips
from forex.signals import indicators
from forex.signals.confluence import evaluate, is_event_driven

_GRAN_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D": 1440}


@dataclass
class Trade:
    pair: str
    direction: str
    entry_ts: int
    entry_price: float
    exit_ts: int
    exit_price: float
    stop_pips: float
    net_pips: float
    pnl_pct: float               # % du capital (après coûts)
    bars_held: int
    exit_reason: str
    event_driven: bool
    signals: dict = field(default_factory=dict)   # log complet à l'entrée

    @property
    def won(self) -> bool:
        return self.pnl_pct > 0


@dataclass
class BacktestResult:
    pair: str
    trades: list[Trade]
    equity_curve: list[float]
    start_equity: float

    @property
    def final_equity(self) -> float:
        return self.equity_curve[-1] if self.equity_curve else self.start_equity

    @property
    def total_return_pct(self) -> float:
        return (self.final_equity / self.start_equity - 1) * 100

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.won)

    @property
    def win_rate(self) -> float:
        return (self.wins / self.n * 100) if self.n else 0.0

    def max_drawdown_pct(self) -> float:
        peak, mdd = self.start_equity, 0.0
        for eq in self.equity_curve:
            peak = max(peak, eq)
            mdd = max(mdd, (peak - eq) / peak * 100)
        return mdd

    def profit_factor(self) -> float:
        gains = sum(t.pnl_pct for t in self.trades if t.pnl_pct > 0)
        losses = -sum(t.pnl_pct for t in self.trades if t.pnl_pct < 0)
        if losses == 0:
            return float("inf") if gains > 0 else 0.0
        return gains / losses

    def sharpe_ratio(self) -> float:
        return sharpe_ratio(self.trades)

    def sharpe_by_session(self) -> dict[str, float]:
        return sharpe_by_session(self.trades)

    def summary(self) -> str:
        return (
            f"[{self.pair}] {self.n} trades · win {self.win_rate:.0f}% · "
            f"rendement {self.total_return_pct:+.1f}% · maxDD {self.max_drawdown_pct():.1f}% · "
            f"PF {self.profit_factor():.2f} · Sharpe {self.sharpe_ratio():.2f}"
        )


def _candle_dt(candle) -> datetime:
    return datetime.fromtimestamp(candle[0] / 1000, tz=timezone.utc)


def sharpe_ratio(trades: list[Trade]) -> float:
    """
    Ratio de Sharpe annualisé, calculé sur les rendements PAR TRADE (pnl_pct).

    Annualisé par la fréquence de trades RÉELLEMENT OBSERVÉE (nombre de trades
    sur la durée couverte, ramené à l'année) plutôt qu'une fréquence fixe
    arbitraire : un bot qui trade 10 fois/an et un autre 200 fois/an n'ont pas
    la même échelle de temps entre deux points de leur courbe d'equity, et les
    confondre fausserait la comparaison.

    Repère (conseil anti-overfitting) : un Sharpe hors-échantillon > 3 est le
    symptôme d'une courbe sur-optimisée, pas d'un edge réel — à traiter avec
    méfiance plutôt que comme une victoire. Une plage 0,5-2 est crédible.
    """
    if len(trades) < 2:
        return 0.0
    returns = [t.pnl_pct / 100 for t in trades]
    std = statistics.pstdev(returns)
    if std == 0:
        return 0.0
    span_days = (trades[-1].exit_ts - trades[0].entry_ts) / 1000 / 86400
    if span_days <= 0:
        return 0.0
    trades_per_year = len(trades) / span_days * 365
    return statistics.fmean(returns) / std * (trades_per_year ** 0.5)


def sharpe_by_session(trades: list[Trade]) -> dict[str, float]:
    """
    Sharpe par session de marché active à l'ENTRÉE du trade (Londres/New York/
    Tokyo — cf. forex.signals.sessions). Un trade pendant l'overlap Londres/NY
    compte dans les deux : l'objectif est de VOIR où l'edge existe (conseil
    « isolez par session »), pas de partitionner un total qui doit sommer.
    """
    from forex.signals.sessions import active_sessions  # import local : évite un cycle au chargement

    buckets: dict[str, list[Trade]] = {}
    for t in trades:
        dt = datetime.fromtimestamp(t.entry_ts / 1000, tz=timezone.utc)
        for name in active_sessions(dt):
            buckets.setdefault(name, []).append(t)
    return {name: sharpe_ratio(ts) for name, ts in buckets.items()}


def run_backtest(
    candles: list[list[float]],
    pair: str,
    events: list[EconEvent] | None = None,
    *,
    start_equity: float = 1000.0,
    risk_pct: float = config.FOREX_RISK_PCT,
    granularity: str = config.FOREX_GRANULARITY,
    atr_period: int = config.ATR_PERIOD,
    atr_stop_mult: float = config.ATR_STOP_MULT,
    atr_tp_mult: float = config.ATR_TP_MULT,
    spread_pips: float = config.FOREX_SPREAD_PIPS,
    slippage_pips: float = config.FOREX_SLIPPAGE_PIPS,
    commission_pips: float = config.FOREX_COMMISSION_PIPS,
    swap_pips_per_day: float = config.FOREX_SWAP_PIPS_PER_DAY,
    use_technical: bool = config.USE_TECHNICAL,
    use_fundamental: bool = config.USE_FUNDAMENTAL,
    use_time_filter: bool = config.USE_TIME_FILTER,
    confluence_mode: str = config.FOREX_CONFLUENCE_MODE,
    warmup: int | None = None,
    strategy=None,
    context_provider=None,
) -> BacktestResult:
    """
    Backtest complet d'une paire. Voir le docstring du module pour la méthode.

    `strategy` : bot (`forex.strategies.base.Strategy`) dont on rejoue la
    logique. Si omis, on retombe sur l'ancienne règle de confluence — ce qui
    garde les rapports et tests historiques strictement inchangés.

    `context_provider(index, window) -> dict` : fournit au bot les données
    mutualisées reconstituées À CET INSTANT du passé (matrice des paires pour
    le bot macro, par exemple). Indispensable pour rester sans look-ahead :
    on ne peut pas lui passer le contexte d'aujourd'hui.
    """
    events = events or []
    pip = pip_size(pair)
    bar_min = _GRAN_MINUTES.get(granularity.upper(), 60)
    max_hold_bars = max(1, config.EVENT_TRADE_MAX_MIN // bar_min)
    warmup = warmup or max(config.MA_SLOW, config.MACD_SLOW + config.MACD_SIGNAL, atr_period) + 5

    equity = start_equity
    equity_curve = [equity]
    trades: list[Trade] = []

    # Fenêtre d'évaluation bornée : au-delà de ~3×MA_SLOW bars, la contribution
    # des vieilles bougies à l'EMA est < 0,3 % — les garder rendrait le backtest
    # O(n²) pour un résultat identique au bruit près.
    lookback = max(warmup, config.MA_SLOW * 3)

    pos: dict | None = None

    for i in range(warmup, len(candles)):
        bar = candles[i]
        _, o, high, low, close, _ = bar
        dt = _candle_dt(bar)

        # ── En position : gérer la sortie ─────────────────
        if pos is not None:
            direction = pos["direction"]
            stop, tp = pos["stop"], pos["tp"]
            exit_price = exit_reason = None

            if direction == "long":
                if low <= stop:
                    exit_price, exit_reason = stop, "stop-loss"
                elif high >= tp:
                    exit_price, exit_reason = tp, "take-profit"
            else:  # short
                if high >= stop:
                    exit_price, exit_reason = stop, "stop-loss"
                elif low <= tp:
                    exit_price, exit_reason = tp, "take-profit"

            bars_held = i - pos["entry_index"]
            # Sortie forcée temporelle (uniquement trades event-driven).
            if exit_price is None and pos["event_driven"] and bars_held >= max_hold_bars:
                moved = abs(close - pos["entry_price"]) >= pos["atr"]
                if not moved:
                    exit_price, exit_reason = close, "sortie temporelle (pas de mouvement)"
            # Filet de sécurité : détention absolue maximale (indépendante de la
            # sortie event-driven), pour ne pas couper un trade technique en route.
            if exit_price is None and bars_held >= config.MAX_HOLD_BARS:
                exit_price, exit_reason = close, "détention max"

            if exit_price is not None:
                sign = 1 if direction == "long" else -1
                raw_pips = (exit_price - pos["entry_price"]) / pip * sign
                days_held = bars_held * bar_min / 1440
                cost_pips = spread_pips + slippage_pips + commission_pips + swap_pips_per_day * days_held
                net_pips = raw_pips - cost_pips
                pnl_pct = (net_pips / pos["stop_pips"]) * risk_pct if pos["stop_pips"] else 0.0
                equity *= (1 + pnl_pct / 100)
                equity_curve.append(equity)
                trades.append(Trade(
                    pair=pair, direction=direction,
                    entry_ts=pos["entry_ts"], entry_price=pos["entry_price"],
                    exit_ts=bar[0], exit_price=exit_price,
                    stop_pips=round(pos["stop_pips"], 1), net_pips=round(net_pips, 1),
                    pnl_pct=round(pnl_pct, 4), bars_held=bars_held,
                    exit_reason=exit_reason, event_driven=pos["event_driven"],
                    signals=pos["signals"],
                ))
                pos = None
            continue  # une bougie ne fait pas sortie ET entrée

        # ── Flat : chercher une entrée ────────────────────
        window = candles[max(0, i + 1 - lookback): i + 1]
        if strategy is not None:
            decision = strategy.evaluate(
                pair, dt, window, events, use_time_filter=use_time_filter,
                context=context_provider(i, window) if context_provider else None,
            )
        else:
            decision = evaluate(
                pair, dt, window, events,
                use_technical=use_technical, use_fundamental=use_fundamental,
                use_time_filter=use_time_filter, mode=confluence_mode,
                # Réagir à tout event tombé pendant la bougie qui vient de clôturer.
                fundamental_lookback_minutes=bar_min + config.EXCLUSION_MIN_AFTER + 1,
            )
        if not decision.enter:
            continue

        atr = indicators.atr(window[-(atr_period + 1) * 3:], atr_period)
        if atr <= 0:
            continue

        direction = decision.direction
        entry_mid = close
        # Coût d'entrée : on subit la moitié du spread + le slippage (défavorable).
        entry_cost = (spread_pips / 2 + slippage_pips) * pip
        entry_price = entry_mid + entry_cost if direction == "long" else entry_mid - entry_cost

        if direction == "long":
            stop, tp = entry_price - atr_stop_mult * atr, entry_price + atr_tp_mult * atr
        else:
            stop, tp = entry_price + atr_stop_mult * atr, entry_price - atr_tp_mult * atr
        stop_pips = price_distance_to_pips(pair, entry_price - stop)

        pos = {
            "direction": direction, "entry_index": i, "entry_ts": bar[0],
            "entry_price": entry_price, "stop": stop, "tp": tp,
            "stop_pips": stop_pips, "atr": atr,
            "event_driven": is_event_driven(decision.components),
            "signals": decision.components,
        }

    return BacktestResult(pair, trades, equity_curve, start_equity)


def buy_and_hold_return_pct(candles: list[list[float]], warmup: int = 0) -> float:
    """Rendement d'un simple achat-conservation (benchmark)."""
    seg = candles[warmup:] if warmup else candles
    if len(seg) < 2:
        return 0.0
    return (seg[-1][4] / seg[0][4] - 1) * 100
