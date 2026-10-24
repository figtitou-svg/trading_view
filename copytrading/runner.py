"""
copytrading/runner.py — Boucle du miroir copy trading (100 % simulé).

Réplique en continu les positions des traders Hyperliquid activés depuis le
dashboard (follows.json) dans un portefeuille virtuel, et écrit son état dans
copytrading/_cache/ pour l'API. Aucun ordre réel n'est possible : tout fill
est un calcul local.

Lancer :
    python -m copytrading.runner            # boucle continue
    python -m copytrading.runner --once     # une seule itération (test/cron)
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from copytrading import api, config, mirror, selector
from services.notification_settings import load_notification_settings

# Créneau du récap quotidien (18h, heure de Paris) — fuseau explicite : le
# serveur de prod tourne en UTC, `datetime.now()` nu décalerait le créneau
# de 1h à 2h selon la saison (même bug que forex/paper/runner.py, corrigé
# le 25/07/2026).
_PARIS_TZ = ZoneInfo("Europe/Paris")
_RECAP_SLOT = 1800


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path: str, payload) -> None:
    """Écriture atomique (tmp + replace) : l'API peut lire à tout moment."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        print(f"[copy] écriture de {os.path.basename(path)} échouée : {e}")


def _build_close_message(trade: dict) -> tuple[str, str]:
    emoji = "🟢" if trade["pnl_eur"] > 0 else "🔴"
    title = f"{emoji} COPY TRADING — position clôturée"
    body = (f"{trade['trader'][:10]}… · {trade['coin']} {trade['direction']}\n"
            f"{trade['reason']} · P&L {trade['pnl_eur']:+.2f} €")
    return title, body


def _build_copytrading_recap_message(pf: dict, since: datetime, until: datetime,
                                     now_local: datetime) -> tuple[str, str]:
    """Récap quotidien enrichi (mode notification 'daily_recap') : nombre
    d'ouvertures/clôtures (gains/pertes) et P&L cumulé depuis le dernier
    récap — un seul message par jour au lieu d'une notif par clôture."""
    n_opened = 0
    n_wins = 0
    n_losses = 0
    pnl_total = 0.0

    for pos in pf["positions"]:
        try:
            opened_at = datetime.fromisoformat(pos["opened_at"])
        except (KeyError, ValueError):
            continue
        if since < opened_at <= until:
            n_opened += 1

    for trade in pf["trades"]:
        try:
            opened_at = datetime.fromisoformat(trade["opened_at"])
        except (KeyError, ValueError):
            opened_at = None
        if opened_at is not None and since < opened_at <= until:
            n_opened += 1
        try:
            closed_at = datetime.fromisoformat(trade["closed_at"])
        except (KeyError, ValueError):
            continue
        if since < closed_at <= until:
            if trade["pnl_eur"] > 0:
                n_wins += 1
            else:
                n_losses += 1
            pnl_total += trade["pnl_eur"]

    title = f"📅 Récap quotidien Copy Trading ({now_local.strftime('%H:%M')})"
    body = (f"🔵 {n_opened} ouverture(s) · ✅ {n_wins} gain(s) · ❌ {n_losses} perte(s)\n"
            f"P&L cumulé {pnl_total:+.2f} €")
    return title, body


def _notify(title: str, body: str) -> None:
    """Envoie une alerte Telegram (import paresseux, comme forex/paper/runner.py)."""
    try:
        import asyncio
        from services.notifier import notifier  # noqa: PLC0415
        asyncio.run(notifier.send_telegram_text(f"*{title}*\n{body}"))
    except Exception as e:  # pas de Telegram configuré / offline : on continue
        print(f"[copy] notification ignorée : {e}")


def _notify_trade_closed(trade: dict) -> None:
    title, body = _build_close_message(trade)
    _notify(title, body)


def refresh_candidates(now: datetime, *, fetch_leaderboard=None) -> None:
    """Rafraîchit candidates.json si le cache a dépassé sa durée de vie."""
    # Résolu à l'APPEL (pas en défaut de paramètre) pour rester monkeypatchable :
    # un défaut `=api.fetch_leaderboard` serait figé à l'import du module.
    fetch_leaderboard = fetch_leaderboard or api.fetch_leaderboard
    cached = _read_json(config.CANDIDATES_PATH)
    if cached:
        try:
            updated = datetime.fromisoformat(cached["updated_at"])
            age = (now - updated).total_seconds()
            if age < config.COPY_LEADERBOARD_REFRESH_SECONDS:
                return
        except (KeyError, ValueError):
            pass
    rows = [r for r in (api.parse_leaderboard_row(x) for x in fetch_leaderboard()) if r]
    _write_json(config.CANDIDATES_PATH, {
        "updated_at": now.isoformat(),
        "candidates": selector.select_candidates(rows),
    })


def load_follows() -> list[str]:
    data = _read_json(config.FOLLOWS_PATH) or {}
    return [a for a in data.get("follows", []) if isinstance(a, str)]


def iterate(pf: dict, follows: list[str], *,
            fetch_positions=None, fetch_mids=None,
            now: datetime | None = None) -> tuple[dict, list[str]]:
    """Un cycle de synchronisation. Retourne (mids, erreurs)."""
    # Même raison que refresh_candidates : résolution à l'appel.
    fetch_positions = fetch_positions or api.fetch_positions
    fetch_mids = fetch_mids or api.fetch_mids
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    errors: list[str] = []
    closed_trades: list[dict] = []
    mids = fetch_mids()

    # Traders désactivés depuis le dernier cycle : positions soldées.
    for trader in sorted({p["trader"] for p in pf["positions"]} - set(follows)):
        closed_trades += mirror.close_trader(pf, trader, mids, now_iso)

    # Poche égale par trader, basée sur l'equity du moment (spec validée).
    pocket = mirror.equity(pf, mids) / len(follows) if follows else 0.0
    for addr in follows:
        try:
            state = fetch_positions(addr)
            account_value, target = api.parse_positions(state)
            if account_value <= 0:
                continue    # compte illisible/vide : on ne clôture rien sur un doute
            closed_trades += mirror.sync_trader(pf, addr, pocket, target, mids, now_iso,
                                                tolerance=config.COPY_ADJUST_TOLERANCE)
        except Exception as e:
            errors.append(f"{addr}: {e}")
            continue

    mirror.record_equity(pf, mids, now)
    if load_notification_settings()["copytrading_mode"] == "detailed":
        for trade in closed_trades:
            _notify_trade_closed(trade)
    return mids, errors


def _payload(pf: dict, mids: dict, now: datetime) -> dict:
    """État sérialisé pour l'API : positions enrichies du prix et P&L latent."""
    positions = []
    for p in pf["positions"]:
        price = mids.get(p["coin"])
        positions.append({**p, "last_price": price,
                          "pnl_eur": round(mirror.latent_pnl(p, price), 2)})
    return {**pf, "positions": positions,
            "equity": round(mirror.equity(pf, mids), 2),
            "updated_at": now.isoformat()}


def run(once: bool = False) -> None:
    pf = _read_json(config.PORTFOLIO_PATH) or mirror.new_portfolio(config.COPY_START_EQUITY)
    print("=" * 60)
    print("  📋 COPY TRADING — MIROIR HYPERLIQUID (100 % simulé)")
    print("=" * 60)
    print(f"  capital {config.COPY_START_EQUITY:.0f} € · poll {config.COPY_POLL_SECONDS}s "
          f"· tolérance ±{config.COPY_ADJUST_TOLERANCE:.0%}")

    scheduled_slots = [730, 1300, 1800, 2200]
    last_notified_slot = -1
    last_daily_recap_time = datetime.now(timezone.utc)

    while True:
        now = datetime.now(timezone.utc)
        try:
            try:
                refresh_candidates(now)
            except Exception as e:
                print(f"[copy] refresh leaderboard échoué : {e}")
            follows = load_follows()
            mids, errors = iterate(pf, follows, now=now)
            _write_json(config.PORTFOLIO_PATH, _payload(pf, mids, now))
            _write_json(config.STATUS_PATH, {
                "updated_at": now.isoformat(),
                "poll_seconds": config.COPY_POLL_SECONDS,
                "n_follows": len(follows),
                "errors": errors,
            })
            for err in errors:
                print(f"[copy] trader en erreur : {err}")

            # --- Récap quotidien (créneau 18h, mode 'daily_recap' uniquement) ---
            settings = load_notification_settings()
            now_local = datetime.now(_PARIS_TZ)
            current_time_val = now_local.hour * 100 + now_local.minute
            triggered_slot = -1
            for slot in scheduled_slots:
                if current_time_val >= slot:
                    triggered_slot = slot
            if triggered_slot != -1 and triggered_slot != last_notified_slot:
                if last_notified_slot != -1:  # pas de spam au tout premier lancement
                    if (settings["copytrading_mode"] == "daily_recap"
                            and triggered_slot == _RECAP_SLOT):
                        title, body = _build_copytrading_recap_message(
                            pf, last_daily_recap_time, now, now_local)
                        _notify(title, body)
                        last_daily_recap_time = now
                last_notified_slot = triggered_slot
            if current_time_val < scheduled_slots[0] and last_notified_slot != -1:
                last_notified_slot = -1
            # ----------------------------------------------------------------
        except KeyboardInterrupt:
            print("\n👋 Runner copy trading arrêté.")
            break
        except Exception as e:
            # Hyperliquid injoignable (fetch_mids...) : on garde le dernier
            # état écrit et on réessaie au poll suivant.
            print(f"[copy] erreur boucle : {e}")

        if once:
            break
        time.sleep(config.COPY_POLL_SECONDS)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Miroir copy trading Hyperliquid (simulé)")
    ap.add_argument("--once", action="store_true", help="Une seule itération puis sortie")
    args = ap.parse_args()
    run(once=args.once)
