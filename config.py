"""
config.py — Configuration du serveur dashboard (forex).

Il ne reste ici que ce dont le dashboard et le module forex ont besoin :
Telegram et logging.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Notifications Telegram (réutilisées par le module forex) ──
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Logging ──────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
