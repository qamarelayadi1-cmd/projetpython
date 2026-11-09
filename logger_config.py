"""Configuration des journaux rotatifs de l'application."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIRECTORY = Path(__file__).resolve().parent / "logs"
LOG_FORMAT = "%(asctime)s|%(levelname)s|%(name)s|%(message)s"


def get_logger(name: str, log_filename: str) -> logging.Logger:
    """Retourne un logger qui écrit dans son propre fichier rotatif."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_DIRECTORY / log_filename,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
