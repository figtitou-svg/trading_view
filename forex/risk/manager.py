"""
forex/risk/manager.py — Garde-fous de risque.

  1. **Levier ESMA** (réglementation UE) : rejet de toute position dont le levier
     dépasse le plafond réglementaire (30:1 paires majeures, 20:1 mineures/or).
  2. **Kill-switch de drawdown** : coupe l'ouverture de nouvelles positions si la
     perte du jour / de la semaine dépasse un seuil, ou si le repli depuis le plus
     haut du capital (trailing drawdown) est trop important.

Broker-agnostique : opère sur des chiffres (capital, units, prix). Réutilisé
par le backtest et le broker simulé.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

_MAJOR_CCYS = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}


def is_major_pair(pair: str) -> bool:
    base, quote = pair.upper().split("_")
    return base in _MAJOR_CCYS and quote in _MAJOR_CCYS


def max_leverage(pair: str) -> float:
    """Plafond ESMA : 30:1 majeures, 20:1 mineures ; 20:1 pour l'or (XAU)."""
    base, quote = pair.upper().split("_")
    if base == "XAU" or quote == "XAU":
        return 20.0
    return 30.0 if is_major_pair(pair) else 20.0


def position_leverage(units: float, price: float, capital: float) -> float:
    """Levier effectif = notionnel / capital."""
    if capital <= 0:
        return float("inf")
    notional = abs(units) * price
    return notional / capital


@dataclass
class LeverageCheck:
    allowed: bool
    leverage: float
    cap: float
    message: str


def check_leverage(pair: str, units: float, price: float, capital: float) -> LeverageCheck:
    lev = position_leverage(units, price, capital)
    cap = max_leverage(pair)
    ok = lev <= cap + 1e-9
    msg = (f"levier {lev:.1f}:1 ≤ {cap:.0f}:1 OK" if ok
           else f"levier {lev:.1f}:1 > plafond ESMA {cap:.0f}:1 — refusé")
    return LeverageCheck(ok, round(lev, 2), cap, msg)


@dataclass
class RiskManager:
    """Suivi du capital et interdiction d'ouverture au-delà des seuils de perte."""
    capital: float
    daily_loss_limit_pct: float = 3.0
    weekly_loss_limit_pct: float = 6.0
    trailing_drawdown_pct: float = 10.0

    peak_equity: float = field(default=0.0)
    equity: float = field(default=0.0)
    _day_start_equity: float = field(default=0.0)
    _week_start_equity: float = field(default=0.0)
    _day: date | None = field(default=None)
    _week: int | None = field(default=None)

    def __post_init__(self) -> None:
        self.equity = self.equity or self.capital
        self.peak_equity = self.peak_equity or self.capital
        self._day_start_equity = self._day_start_equity or self.capital
        self._week_start_equity = self._week_start_equity or self.capital

    # ── Mises à jour ──────────────────────────────────────
    def start_day(self, equity: float, when: datetime | None = None) -> None:
        when = when or datetime.now(timezone.utc)
        self._day = when.date()
        self._week = when.isocalendar().week
        self._day_start_equity = equity
        self.equity = equity
        self.peak_equity = max(self.peak_equity, equity)

    def start_week(self, equity: float) -> None:
        self._week_start_equity = equity

    def update_equity(self, equity: float, when: datetime | None = None) -> None:
        """Enregistre l'equity courant (roule le jour/semaine si nécessaire)."""
        when = when or datetime.now(timezone.utc)
        if self._day is None:
            self.start_day(equity, when)
            self.start_week(equity)
            return
        if when.date() != self._day:
            self._day = when.date()
            self._day_start_equity = equity
        wk = when.isocalendar().week
        if wk != self._week:
            self._week = wk
            self._week_start_equity = equity
        self.equity = equity
        self.peak_equity = max(self.peak_equity, equity)

    # ── Mesures ───────────────────────────────────────────
    def daily_loss_pct(self) -> float:
        if self._day_start_equity <= 0:
            return 0.0
        return max(0.0, (self._day_start_equity - self.equity) / self._day_start_equity * 100)

    def weekly_loss_pct(self) -> float:
        if self._week_start_equity <= 0:
            return 0.0
        return max(0.0, (self._week_start_equity - self.equity) / self._week_start_equity * 100)

    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity * 100)

    def can_open_trade(self) -> tuple[bool, str]:
        """Vrai si aucun garde-fou de perte n'est déclenché."""
        if self.daily_loss_pct() >= self.daily_loss_limit_pct:
            return False, (f"perte du jour {self.daily_loss_pct():.1f}% ≥ "
                           f"limite {self.daily_loss_limit_pct}% — trading coupé")
        if self.weekly_loss_pct() >= self.weekly_loss_limit_pct:
            return False, (f"perte de la semaine {self.weekly_loss_pct():.1f}% ≥ "
                           f"limite {self.weekly_loss_limit_pct}% — trading coupé")
        if self.drawdown_pct() >= self.trailing_drawdown_pct:
            return False, (f"drawdown {self.drawdown_pct():.1f}% ≥ "
                           f"limite {self.trailing_drawdown_pct}% — trading coupé")
        return True, "risque OK"
