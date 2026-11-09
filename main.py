#!/usr/bin/env python3
from pathlib import Path

from logger_config import get_logger
from pipeline.runner import run_pipeline
from serving.dashboard import build_dashboard
from storage.sqlite_storage import SQLiteEventStore

logger = get_logger(__name__, "main.log")
PROJECT_DIRECTORY = Path(__file__).resolve().parent


def main() -> None:
    """Exécute le pipeline puis génère le tableau de bord."""
    try:
        store = SQLiteEventStore(PROJECT_DIRECTORY / "output" / "auth_events.sqlite3")
        run_pipeline(PROJECT_DIRECTORY / "data", store)
        paths = build_dashboard(store, PROJECT_DIRECTORY / "output")
        logger.info("Tableau de bord créé: %s", ", ".join(map(str, paths)))
    except Exception:
        logger.exception("Échec du pipeline")
        raise


if __name__ == "__main__":
    main()
    