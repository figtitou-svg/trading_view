"""
forex/strategies/remove.py — Purge du cache d'un bot désactivé.

Ne touche PAS au code : couper un bot reste l'affaire de `enabled = False`
dans sa classe (cf. forex.strategies.registry). Ce script supprime (ou
archive) son dossier de cache `_cache/bots/<id>/` — portefeuille virtuel,
journal de trades, paramètres appris — une fois qu'on ne veut plus de son
historique.

Usage :
    python -m forex.strategies.remove --bot smc-old
    python -m forex.strategies.remove --bot smc-old --archive
"""

from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime, timezone

from forex.strategies.base import BOTS_DIR


def purge(bot_id: str, *, archive: bool = False) -> str:
    """Supprime (ou archive) _cache/bots/<bot_id>/. Retourne un message de résultat."""
    bot_dir = os.path.join(BOTS_DIR, bot_id)
    if not os.path.isdir(bot_dir):
        return f"aucun dossier de cache pour {bot_id!r} ({bot_dir})"
    if archive:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        dest = f"{bot_dir}.bak-{stamp}"
        shutil.move(bot_dir, dest)
        return f"{bot_id} archivé -> {dest}"
    shutil.rmtree(bot_dir)
    return f"{bot_id} supprimé ({bot_dir})"


def _cli() -> None:
    ap = argparse.ArgumentParser(description="Purge le cache d'un bot forex désactivé")
    ap.add_argument("--bot", required=True, help="Identifiant du bot (ex. smc-old)")
    ap.add_argument("--archive", action="store_true", help="Renommer en .bak au lieu de supprimer")
    args = ap.parse_args()
    print(purge(args.bot, archive=args.archive))


if __name__ == "__main__":
    _cli()
