"""
forex/paper/broker.py — Broker **100 % simulé** (aucun compte, aucun ordre réel).

Portefeuille virtuel persistant (JSON) qui rejoue la même comptabilité que le
backtest :
  - dimensionnement par le risque : toucher le stop coûte `risk_pct` % de
    l'equity au moment de l'entrée ;
  - coûts réalistes appliqués (spread + slippage à l'entrée, spread à la sortie,
    swap par jour de détention) ;
  - stop-loss / take-profit vérifiés en intrabar (high/low) à chaque tick.

Rien ici ne peut passer un ordre : le « fill » est un simple calcul local.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone

from forex import config
from forex.risk.sizing import pip_size, price_distance_to_pips
from forex.paper import exits


@dataclass
class PaperPosition:
    pair: str
    direction: str            # 'long' | 'short'
    entry_ts: int
    entry_price: float
    stop: float
    tp: float
    stop_pips: float
    risk_pct: float
    entry_equity: float
    event_driven: bool = False
    signals: dict = field(default_factory=dict)
    # ── Gestion de sortie dynamique (forex/paper/exits.py) ──
    atr: float = 0.0
    atr_stop_mult: float = 0.0
    atr_tp_mult: float = 0.0
    extreme_price: float = 0.0
    initial_stop: float = 0.0
    initial_tp: float = 0.0
    exit_mode: str = "static"
    adjusted: bool = False


@dataclass
class PaperTrade:
    pair: str
    direction: str
    entry_ts: int
    exit_ts: int
    entry_price: float
    exit_price: float
    net_pips: float
    pnl: float                # en devise de compte (abstraite)
    pnl_pct: float            # % de l'equity à l'entrée
    exit_reason: str
    event_driven: bool
    signals: dict = field(default_factory=dict)
    adjusted: bool = False    # stop/tp ont bougé dynamiquement avant la clôture


class PaperBroker:
    """État du portefeuille virtuel forex, persisté sur disque."""

    def __init__(self, path: str | None = None, start_equity: float | None = None):
        self.path = path or os.path.join(config.FOREX_DATA_DIR, "paper_portfolio.json")
        self.start_equity = start_equity if start_equity is not None else config.FOREX_START_EQUITY
        self.equity = self.start_equity
        self.peak_equity = self.start_equity
        self.positions: dict[str, PaperPosition] = {}
        self.trades: list[PaperTrade] = []
        self.load()

    # ── Persistance ───────────────────────────────────────
    def load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        self.start_equity = data.get("start_equity", self.start_equity)
        self.equity = data.get("equity", self.start_equity)
        self.peak_equity = data.get("peak_equity", self.equity)
        self.positions = {p: PaperPosition(**d) for p, d in data.get("positions", {}).items()}
        self.trades = [PaperTrade(**t) for t in data.get("trades", [])]

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        data = {
            "start_equity": self.start_equity,
            "equity": self.equity,
            "peak_equity": self.peak_equity,
            "positions": {p: asdict(pos) for p, pos in self.positions.items()},
            "trades": [asdict(t) for t in self.trades],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── Consultation ──────────────────────────────────────
    def balance(self) -> float:
        return self.equity

    def position(self, pair: str) -> PaperPosition | None:
        return self.positions.get(pair)

    def has_position(self, pair: str) -> bool:
        return pair in self.positions

    # ── Ouverture ─────────────────────────────────────────
    def open_position(
        self,
        pair: str,
        direction: str,
        mid_price: float,
        atr: float,
        *,
        risk_pct: float = config.FOREX_RISK_PCT,
        atr_stop_mult: float = config.ATR_STOP_MULT,
        atr_tp_mult: float = config.ATR_TP_MULT,
        spread_pips: float = config.FOREX_SPREAD_PIPS,
        slippage_pips: float = config.FOREX_SLIPPAGE_PIPS,
        ts: int | None = None,
        event_driven: bool = False,
        signals: dict | None = None,
        exit_mode: str = "static",
    ) -> PaperPosition:
        """Ouvre une position simulée (prix d'entrée pénalisé par spread+slippage)."""
        if pair in self.positions:
            raise ValueError(f"position déjà ouverte sur {pair}")
        pip = pip_size(pair)
        entry_cost = (spread_pips / 2 + slippage_pips) * pip
        entry_price = mid_price + entry_cost if direction == "long" else mid_price - entry_cost
        if direction == "long":
            stop, tp = entry_price - atr_stop_mult * atr, entry_price + atr_tp_mult * atr
        else:
            stop, tp = entry_price + atr_stop_mult * atr, entry_price - atr_tp_mult * atr
        stop_pips = price_distance_to_pips(pair, entry_price - stop)

        pos = PaperPosition(
            pair=pair, direction=direction, entry_ts=ts or _now_ms(),
            entry_price=entry_price, stop=stop, tp=tp, stop_pips=stop_pips,
            risk_pct=risk_pct, entry_equity=self.equity,
            event_driven=event_driven, signals=signals or {},
            atr=atr, atr_stop_mult=atr_stop_mult, atr_tp_mult=atr_tp_mult,
            extreme_price=entry_price, initial_stop=stop, initial_tp=tp,
            exit_mode=exit_mode,
        )
        self.positions[pair] = pos
        self.save()
        return pos

    # ── Gestion / clôture ─────────────────────────────────
    def _close(
        self, pair: str, exit_price: float, reason: str, ts: int,
        spread_pips: float, slippage_pips: float, swap_pips_per_day: float,
        commission_pips: float = config.FOREX_COMMISSION_PIPS,
    ) -> PaperTrade:
        pos = self.positions.pop(pair)
        pip = pip_size(pair)
        sign = 1 if pos.direction == "long" else -1
        raw_pips = (exit_price - pos.entry_price) / pip * sign
        days_held = max(0.0, (ts - pos.entry_ts) / 1000 / 86400)
        exit_cost_pips = spread_pips / 2 + commission_pips + swap_pips_per_day * days_held
        net_pips = raw_pips - exit_cost_pips
        pnl_pct = (net_pips / pos.stop_pips) * pos.risk_pct if pos.stop_pips else 0.0
        pnl = pos.entry_equity * pnl_pct / 100
        self.equity += pnl
        self.peak_equity = max(self.peak_equity, self.equity)

        trade = PaperTrade(
            pair=pair, direction=pos.direction, entry_ts=pos.entry_ts, exit_ts=ts,
            entry_price=pos.entry_price, exit_price=exit_price,
            net_pips=round(net_pips, 1), pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 4),
            exit_reason=reason, event_driven=pos.event_driven, signals=pos.signals,
            adjusted=pos.adjusted,
        )
        self.trades.append(trade)
        self.save()
        return trade

    def update_exit_levels(self, pair: str, high: float, low: float) -> None:
        """
        Met à jour extreme_price puis, selon exit_mode, stop et/ou tp. Appelée
        AVANT on_bar() à chaque cycle pour que le stop/tp du jour reflète déjà
        l'ajustement dynamique quand on teste s'il a été touché.
        """
        pos = self.positions.get(pair)
        if pos is None or pos.exit_mode == "static":
            return

        pos.extreme_price = (max(pos.extreme_price, high) if pos.direction == "long"
                             else min(pos.extreme_price, low))

        if pos.exit_mode in ("trailing", "chandelier"):
            pos.stop = exits.trailing_stop(pos.direction, pos.extreme_price, pos.atr,
                                           pos.atr_stop_mult, pos.stop)
        elif pos.exit_mode == "trailing_breakeven":
            pos.stop = exits.breakeven_trailing_stop(
                pos.direction, pos.extreme_price, pos.atr, pos.atr_stop_mult,
                pos.stop, pos.entry_price, pos.initial_stop)

        if pos.exit_mode == "chandelier":
            pos.tp = exits.chandelier_tp(pos.direction, pos.extreme_price, pos.atr,
                                         pos.atr_tp_mult, pos.tp)

        if pos.stop != pos.initial_stop or pos.tp != pos.initial_tp:
            pos.adjusted = True
        self.save()

    def on_bar(
        self,
        pair: str,
        high: float,
        low: float,
        close: float,
        ts: int,
        *,
        spread_pips: float = config.FOREX_SPREAD_PIPS,
        slippage_pips: float = config.FOREX_SLIPPAGE_PIPS,
        swap_pips_per_day: float = config.FOREX_SWAP_PIPS_PER_DAY,
        commission_pips: float = config.FOREX_COMMISSION_PIPS,
    ) -> PaperTrade | None:
        """Teste stop/TP en intrabar. Retourne le trade clôturé le cas échéant."""
        pos = self.positions.get(pair)
        if pos is None:
            return None
        exit_price = reason = None
        if pos.direction == "long":
            if low <= pos.stop:
                exit_price, reason = pos.stop, "stop-loss"
            elif high >= pos.tp:
                exit_price, reason = pos.tp, "take-profit"
        else:
            if high >= pos.stop:
                exit_price, reason = pos.stop, "stop-loss"
            elif low <= pos.tp:
                exit_price, reason = pos.tp, "take-profit"
        if exit_price is None:
            return None
        return self._close(pair, exit_price, reason, ts, spread_pips, slippage_pips,
                           swap_pips_per_day, commission_pips)

    def force_close(
        self, pair: str, price: float, reason: str, ts: int | None = None,
        *, spread_pips: float = config.FOREX_SPREAD_PIPS,
        slippage_pips: float = config.FOREX_SLIPPAGE_PIPS,
        swap_pips_per_day: float = config.FOREX_SWAP_PIPS_PER_DAY,
        commission_pips: float = config.FOREX_COMMISSION_PIPS,
    ) -> PaperTrade | None:
        if pair not in self.positions:
            return None
        return self._close(pair, price, reason, ts or _now_ms(),
                           spread_pips, slippage_pips, swap_pips_per_day, commission_pips)

    # ── Stats ─────────────────────────────────────────────
    def stats(self) -> dict:
        n = len(self.trades)
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return {
            "equity": round(self.equity, 2),
            "return_pct": round((self.equity / self.start_equity - 1) * 100, 2),
            "open_positions": list(self.positions.keys()),
            "trades": n,
            "win_rate": round(wins / n * 100, 1) if n else 0.0,
            "peak_equity": round(self.peak_equity, 2),
        }


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)
