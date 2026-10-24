"""
copytrading/mirror.py — Portefeuille miroir (logique pure, sans réseau).

Chaque trader copié reçoit une « poche » égale du capital virtuel ; chacune de
ses positions est reproduite avec la même fraction de compte que chez lui.
Le levier n'est PAS répliqué : la fraction est plafonnée en amont
(api.parse_positions) — le miroir ne peut pas perdre plus que sa poche.

Tout opère sur un dict sérialisable en JSON — aucune classe, aucun accès
réseau : c'est ce qui rend le module testable et l'état trivialement
persistable par le runner.
"""

from __future__ import annotations

_MAX_TRADES = 200          # trades clôturés conservés
_MAX_EQUITY_POINTS = 720   # 1 point/heure ≈ 30 jours glissants
_MIN_POSITION_EUR = 1.0    # en dessous : poussière, on n'ouvre pas


def new_portfolio(start_equity: float) -> dict:
    return {"start_equity": start_equity, "realized_pnl": 0.0,
            "positions": [], "trades": [], "equity_history": []}


def latent_pnl(pos: dict, price: float | None) -> float:
    """P&L latent d'une position au prix donné (0.0 si prix inconnu)."""
    if price is None or price <= 0 or pos["entry_price"] <= 0:
        return 0.0
    ratio = price / pos["entry_price"] - 1.0
    sign = 1.0 if pos["direction"] == "long" else -1.0
    return pos["size_eur"] * ratio * sign


def equity(pf: dict, mids: dict) -> float:
    return (pf["start_equity"] + pf["realized_pnl"]
            + sum(latent_pnl(p, mids.get(p["coin"])) for p in pf["positions"]))


def _record_trade(pf, pos, size_eur, exit_price, pnl, now_iso, reason) -> dict:
    trade = {
        "trader": pos["trader"], "coin": pos["coin"], "direction": pos["direction"],
        "size_eur": round(size_eur, 2), "entry_price": pos["entry_price"],
        "exit_price": exit_price, "pnl_eur": round(pnl, 2),
        "opened_at": pos["opened_at"], "closed_at": now_iso, "reason": reason,
    }
    pf["trades"].append(trade)
    del pf["trades"][:-_MAX_TRADES]
    return trade


def _close(pf, pos, price, now_iso, reason) -> dict:
    pnl = latent_pnl(pos, price)
    pf["realized_pnl"] += round(pnl, 2)
    pf["positions"].remove(pos)
    return _record_trade(pf, pos, pos["size_eur"], price, pnl, now_iso, reason)


def close_trader(pf: dict, trader: str, mids: dict, now_iso: str,
                 reason: str = "copie désactivée") -> list[dict]:
    """
    Clôture toutes les positions miroir d'un trader. Prix inconnu → clôture au
    prix d'entrée (P&L 0) : mieux vaut solder que garder la position d'un
    trader qu'on ne suit plus. Retourne les trades clôturés (pour notification).
    """
    closed = []
    for pos in [p for p in pf["positions"] if p["trader"] == trader]:
        price = mids.get(pos["coin"]) or pos["entry_price"]
        closed.append(_close(pf, pos, price, now_iso, reason))
    return closed


def sync_trader(pf: dict, trader: str, pocket_eur: float, target: dict,
                mids: dict, now_iso: str, *, tolerance: float = 0.20) -> list[dict]:
    """
    Aligne les positions miroir d'un trader sur `target`
    ({coin: {"direction", "frac"}}, cf. api.parse_positions).
    Retourne les trades clôturés/réduits durant cet appel (pour notification).
    """
    closed: list[dict] = []
    current = {p["coin"]: p for p in pf["positions"] if p["trader"] == trader}

    # 1. Positions que le trader a fermées depuis le dernier poll.
    for coin, pos in list(current.items()):
        if coin not in target:
            price = mids.get(coin) or pos["entry_price"]
            closed.append(_close(pf, pos, price, now_iso, "clôturé par le trader"))
            del current[coin]

    # 2. Ouvertures et ajustements.
    for coin, tgt in target.items():
        price = mids.get(coin)
        if price is None or price <= 0:
            continue                      # pas de prix → prochain poll
        pos = current.get(coin)

        if pos is not None and pos["direction"] != tgt["direction"]:
            closed.append(_close(pf, pos, price, now_iso, "retournement du trader"))
            pos = None

        want_eur = tgt["frac"] * pocket_eur
        if pos is None:
            if want_eur < _MIN_POSITION_EUR:
                continue
            pf["positions"].append({
                "trader": trader, "coin": coin, "direction": tgt["direction"],
                "size_eur": round(want_eur, 2), "entry_price": price,
                "frac": tgt["frac"], "opened_at": now_iso,
            })
            continue

        cur_eur = pos["size_eur"]
        if cur_eur <= 0 or abs(want_eur - cur_eur) / cur_eur <= tolerance:
            pos["frac"] = tgt["frac"]     # écart toléré : pas de transaction
            continue
        if want_eur > cur_eur:
            # Renforcement : prix d'entrée moyen pondéré.
            add = want_eur - cur_eur
            pos["entry_price"] = (pos["entry_price"] * cur_eur + price * add) / want_eur
            pos["size_eur"] = round(want_eur, 2)
        elif want_eur < _MIN_POSITION_EUR:
            # Le reste serait de la poussière : on clôture entièrement plutôt
            # que de laisser une position résiduelle qui ne repasse jamais
            # par le circuit de clôture (le coin reste dans `target`).
            closed.append(_close(pf, pos, price, now_iso, "allègement"))
            continue
        else:
            # Allègement : le P&L de la part fermée est réalisé.
            cut = cur_eur - want_eur
            pnl = latent_pnl(pos, price) * (cut / cur_eur)
            pf["realized_pnl"] += round(pnl, 2)
            closed.append(_record_trade(pf, pos, cut, price, pnl, now_iso, "allègement"))
            pos["size_eur"] = round(want_eur, 2)
        pos["frac"] = tgt["frac"]

    return closed


def record_equity(pf: dict, mids: dict, now) -> None:
    """Un point d'equity par heure au plus, fenêtre glissante de 30 jours."""
    ts = int(now.timestamp() * 1000)
    hist = pf.setdefault("equity_history", [])
    if hist and ts - hist[-1][0] < 3_600_000:
        return
    hist.append([ts, round(equity(pf, mids), 2)])
    del hist[:-_MAX_EQUITY_POINTS]
