"""
forex/data/prices.py — Feed de prix forex **sans credentials** (yfinance).

Fournit des bougies OHLCV au format partagé avec le bot crypto :
    [timestamp_ms, open, high, low, close, volume]
(le volume forex de yfinance est souvent 0, sans conséquence pour la stratégie).

Aucune requête réseau à l'import : tout se fait au premier appel, pour que les
tests puissent importer le module hors-ligne.

Limites yfinance (à connaître) : intervalle 1m ≤ 7 jours, 15m ≤ 60 jours,
1h ≤ 730 jours, 1d illimité. Le module choisit une `period` par défaut adaptée.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Mapping granularité interne → intervalle yfinance.
# yfinance n'a pas de H4 natif : on le reconstruit par resample d'H1.
_INTERVAL_MAP = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "H1": "1h",
    "H4": "1h",   # resamplé en 4h après téléchargement
    "D": "1d",
}

# Période de téléchargement par défaut, choisie sous les limites yfinance.
_DEFAULT_PERIOD = {
    "1m": "7d",
    "5m": "60d",
    "15m": "60d",
    "1h": "730d",
    "1d": "10y",
}


# Instruments cross-asset : ticker yfinance natif, pas de conversion
# BASE_QUOTE=X (ce ne sont pas des paires de devises). Mêmes tickers que
# forex/data/crossasset.py pour l'or et le pétrole (déjà éprouvés).
_TICKER_OVERRIDES = {
    "NDX_USD": "^NDX",
    "XAU_USD": "GC=F",
    "WTI_USD": "CL=F",
}


def yf_ticker(instrument: str) -> str:
    """'EUR_USD' → 'EURUSD=X' (convention yfinance pour le forex) ; les
    instruments de _TICKER_OVERRIDES utilisent leur ticker natif."""
    key = instrument.upper()
    if key in _TICKER_OVERRIDES:
        return _TICKER_OVERRIDES[key]
    base, quote = key.split("_")
    return f"{base}{quote}=X"


def _df_to_ohlcv(df) -> list[list[float]]:
    """Convertit un DataFrame yfinance en liste [ts_ms, o, h, l, c, v]."""
    import pandas as pd  # import local : évite le coût si le module n'est pas utilisé

    if df is None or len(df) == 0:
        return []

    # yfinance peut renvoyer des colonnes MultiIndex (ticker en 2e niveau).
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)

    out: list[list[float]] = []
    for ts, row in df.iterrows():
        # Index tz-aware ou naïf → epoch ms UTC
        if getattr(ts, "tzinfo", None) is None:
            ts = ts.tz_localize("UTC") if hasattr(ts, "tz_localize") else ts
        epoch_ms = int(pd.Timestamp(ts).timestamp() * 1000)
        try:
            o, h, l, c = (float(row["Open"]), float(row["High"]),
                          float(row["Low"]), float(row["Close"]))
        except (KeyError, TypeError, ValueError):
            continue
        v = float(row["Volume"]) if "Volume" in row and not pd.isna(row["Volume"]) else 0.0
        if any(x != x for x in (o, h, l, c)):  # NaN check
            continue
        out.append([epoch_ms, o, h, l, c, v])
    return out


def _resample_h4(candles: list[list[float]]) -> list[list[float]]:
    """Agrège des bougies H1 en H4 (blocs alignés sur 0/4/8/12/16/20 h UTC)."""
    if not candles:
        return []
    import pandas as pd

    df = pd.DataFrame(candles, columns=["ts", "o", "h", "l", "c", "v"])
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("dt")
    agg = df.resample("4h", label="left", closed="left").agg(
        {"ts": "first", "o": "first", "h": "max", "l": "min", "c": "last", "v": "sum"}
    ).dropna()
    return [[int(r.ts), r.o, r.h, r.l, r.c, r.v] for r in agg.itertuples()]


def fetch_ohlcv(
    instrument: str,
    granularity: str = "H1",
    period: str | None = None,
    count: int | None = None,
) -> list[list[float]]:
    """
    Télécharge les bougies OHLCV d'une paire.

    Args:
        instrument: 'EUR_USD', 'GBP_USD', 'USD_JPY'…
        granularity: M1/M5/M15/H1/H4/D.
        period: période yfinance ('60d', '2y'…). Défaut adapté à la granularité.
        count: si fourni, ne garde que les `count` dernières bougies closes.

    Returns:
        Liste [ts_ms, o, h, l, c, v], triée par temps croissant, bougies closes.
    """
    import yfinance as yf

    gran = granularity.upper()
    if gran not in _INTERVAL_MAP:
        raise ValueError(f"Granularité non supportée : {granularity}")
    interval = _INTERVAL_MAP[gran]
    period = period or _DEFAULT_PERIOD[interval]

    df = yf.download(
        yf_ticker(instrument), period=period, interval=interval,
        auto_adjust=False, progress=False, threads=False,
    )
    candles = _df_to_ohlcv(df)
    if gran == "H4":
        candles = _resample_h4(candles)

    # yfinance inclut la bougie en cours (non close) en dernière position : on
    # la retire pour ne raisonner que sur des bougies clôturées.
    if candles:
        candles = candles[:-1]

    if count is not None and len(candles) > count:
        candles = candles[-count:]
    return candles


def get_price(instrument: str) -> float | None:
    """Dernier prix connu (close de la dernière bougie 1m disponible)."""
    candles = fetch_ohlcv(instrument, "M1", period="1d", count=1)
    if candles:
        return candles[-1][4]
    daily = fetch_ohlcv(instrument, "D", period="5d", count=1)
    return daily[-1][4] if daily else None


def candle_dt(candle: list[float]) -> datetime:
    """Horodatage d'une bougie en datetime UTC."""
    return datetime.fromtimestamp(candle[0] / 1000, tz=timezone.utc)
