"""Tests de forex/data/prices.py — résolution des tickers yfinance."""

from forex.data import prices


def test_yf_ticker_converts_forex_pair_unchanged():
    assert prices.yf_ticker("EUR_USD") == "EURUSD=X"
    assert prices.yf_ticker("USD_JPY") == "USDJPY=X"


def test_yf_ticker_uses_override_for_nasdaq():
    assert prices.yf_ticker("NDX_USD") == "^NDX"


def test_yf_ticker_uses_override_for_gold():
    assert prices.yf_ticker("XAU_USD") == "GC=F"


def test_yf_ticker_uses_override_for_oil():
    assert prices.yf_ticker("WTI_USD") == "CL=F"


def test_yf_ticker_override_is_case_insensitive():
    assert prices.yf_ticker("ndx_usd") == "^NDX"
