"""Tests des parseurs purs du client Hyperliquid (aucun accès réseau)."""

from copytrading import api

# Ligne réelle (tronquée) du leaderboard stats-data.hyperliquid.xyz, 23/07/2026.
LEADERBOARD_ROW = {
    "ethAddress": "0x85ECF584F25DB6F146718B86D493E33C5AF72052",
    "accountValue": "62183555.0353940129",
    "displayName": None,
    "windowPerformances": [
        ["day", {"pnl": "30559.044878", "roi": "0.0005648654", "vlm": "1519378068.46"}],
        ["week", {"pnl": "903227.633083", "roi": "0.0168135189", "vlm": "7671235532.60"}],
        ["month", {"pnl": "5804518.71", "roi": "0.1042", "vlm": "31000000000.0"}],
        ["allTime", {"pnl": "42000000.0", "roi": "2.05", "vlm": "900000000000.0"}],
    ],
}

# clearinghouseState réel (structure), avec un long ETH et un short BTC.
CLEARINGHOUSE_STATE = {
    "marginSummary": {"accountValue": "100000.0", "totalNtlPos": "30000.0"},
    "assetPositions": [
        {"type": "oneWay", "position": {
            "coin": "ETH", "szi": "8.9713", "positionValue": "20000.0",
            "entryPx": "2309.1", "leverage": {"type": "cross", "value": 5}}},
        {"type": "oneWay", "position": {
            "coin": "BTC", "szi": "-0.1", "positionValue": "10000.0",
            "entryPx": "117000.0", "leverage": {"type": "cross", "value": 5}}},
    ],
}


def test_parse_leaderboard_row():
    r = api.parse_leaderboard_row(LEADERBOARD_ROW)
    assert r["address"] == "0x85ecf584f25db6f146718b86d493e33c5af72052"
    assert r["account_value"] == 62183555.0353940129
    assert r["roi_week"] == 0.0168135189
    assert r["roi_month"] == 0.1042
    assert r["volume_week"] == 7671235532.60
    assert r["display_name"] is None


def test_parse_leaderboard_row_malformee():
    assert api.parse_leaderboard_row({}) is None
    assert api.parse_leaderboard_row({"ethAddress": "0xabc", "accountValue": "n/a"}) is None


def test_parse_positions():
    account_value, target = api.parse_positions(CLEARINGHOUSE_STATE)
    assert account_value == 100000.0
    assert target["ETH"] == {"direction": "long", "frac": 0.2}
    assert target["BTC"] == {"direction": "short", "frac": 0.1}


def test_parse_positions_frac_plafonnee():
    state = {"marginSummary": {"accountValue": "1000.0"},
             "assetPositions": [{"type": "oneWay", "position": {
                 "coin": "SOL", "szi": "100", "positionValue": "5000.0"}}]}
    _, target = api.parse_positions(state)
    assert target["SOL"]["frac"] == 1.0  # levier non répliqué


def test_parse_positions_compte_vide():
    assert api.parse_positions({"marginSummary": {"accountValue": "0.0"},
                                "assetPositions": []}) == (0.0, {})
    assert api.parse_positions({}) == (0.0, {})
