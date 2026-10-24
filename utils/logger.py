"""
utils/logger.py — Configuration centralisée du logging.

Fournit un logger avec :
  - Sortie console colorée
  - Fichier rotatif (logs/bot.log, 5 MB, 3 backups)
  - Niveau configurable via LOG_LEVEL
"""

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logger(name: str = "tradingview_bot") -> logging.Logger:
    """Crée et configure le logger principal de l'application."""

    # Importer ici pour éviter les imports circulaires
    from config import LOG_LEVEL

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    # Éviter les doublons si le logger est déjà configuré
    if logger.handlers:
        return logger

    # ── Format ────────────────────────────────────────────
    fmt = logging.Formatter(
        fmt="%(asctime)s │ %(levelname)-8s │ %(name)s.%(module)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Console Handler ──────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    # ── File Handler (rotatif) ───────────────────────────
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "bot.log")

    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger


# Logger par défaut, prêt à l'emploi
logger = setup_logger()
