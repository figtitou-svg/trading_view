"""
copytrading/config.py — Configuration du module copy trading, pilotée par
variables d'environnement (`.env`). Aucun secret requis : les API Hyperliquid
utilisées sont publiques et l'exécution est 100 % simulée.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# Répertoire d'état (candidats, follows, portefeuille, statut).
COPY_DATA_DIR = os.getenv(
    "COPY_DATA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cache"),
)
CANDIDATES_PATH = os.path.join(COPY_DATA_DIR, "candidates.json")
FOLLOWS_PATH = os.path.join(COPY_DATA_DIR, "follows.json")
PORTFOLIO_PATH = os.path.join(COPY_DATA_DIR, "portfolio.json")
STATUS_PATH = os.path.join(COPY_DATA_DIR, "status.json")

# ── Portefeuille miroir ──────────────────────────────────
COPY_START_EQUITY = float(os.getenv("COPY_START_EQUITY", "10000"))
COPY_POLL_SECONDS = int(os.getenv("COPY_POLL_SECONDS", "180"))
# Écart relatif de taille au-delà duquel une position miroir est ajustée.
COPY_ADJUST_TOLERANCE = float(os.getenv("COPY_ADJUST_TOLERANCE", "0.20"))

# ── Présélection des candidats ───────────────────────────
COPY_LEADERBOARD_REFRESH_SECONDS = int(
    os.getenv("COPY_LEADERBOARD_REFRESH_SECONDS", str(24 * 3600)))
COPY_N_CANDIDATES = int(os.getenv("COPY_N_CANDIDATES", "10"))
# Bornes de taille de compte : trop petit = bruit statistique, trop gros =
# positions incopiables à notre échelle.
COPY_MIN_ACCOUNT_USD = float(os.getenv("COPY_MIN_ACCOUNT_USD", "50000"))
COPY_MAX_ACCOUNT_USD = float(os.getenv("COPY_MAX_ACCOUNT_USD", "10000000"))
