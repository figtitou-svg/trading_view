"""
tests/conftest.py — Configuration d'environnement pour les tests.

Chargé par pytest AVANT les modules de test. Depuis l'arrêt du trading
crypto, il ne reste que des réglages neutres pour le module forex.
"""

import os

# Pas de Telegram pendant les tests (les notifications sont ignorées).
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("TELEGRAM_CHAT_ID", "")
