"""
services/notifier.py — Envoi de notifications Telegram.

Seul le canal Telegram texte est géré (c'est ce qu'utilise le module forex).

Les envois sont "fire-and-forget" : une erreur est loggée mais ne bloque
jamais le flux principal.
"""

import httpx

import config
from utils.logger import logger


class Notifier:
    """Envoie des messages texte sur Telegram (Markdown)."""

    def __init__(self) -> None:
        self.telegram_token: str = config.TELEGRAM_BOT_TOKEN
        self.telegram_chat_id: str = config.TELEGRAM_CHAT_ID

    async def send_telegram_text(self, message: str) -> bool:
        """Envoie un message Telegram libre. Retourne True si envoyé."""
        if not self.telegram_token or not self.telegram_chat_id:
            logger.debug("Telegram non configuré — message ignoré")
            return False

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        data = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": "Markdown",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=data)
                response.raise_for_status()
            logger.info("📱 Message Telegram envoyé avec succès")
            return True
        except Exception as e:
            logger.error(f"📱 Erreur envoi Telegram: {e}")
            return False


# Instance globale réutilisable
notifier = Notifier()
