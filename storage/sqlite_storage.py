"""Stockage SQLite des événements d'authentification SSH."""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from logger_config import get_logger

logger = get_logger(__name__, "storage.log")


@dataclass(frozen=True)
class AuthEvent:
    """Événement extrait d'une ligne de journal SSH."""

    timestamp: str
    ip: str
    username: str | None
    status: str
    country: str
    source: str
    occurrences: int = 1


class SQLiteEventStore:
    """Enregistre les événements et fournit les agrégations du tableau de bord."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.database_path)) as connection:
                with connection:
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS auth_events (
                            id INTEGER PRIMARY KEY,
                            timestamp TEXT NOT NULL,
                            ip TEXT NOT NULL,
                            username TEXT,
                            status TEXT NOT NULL,
                            country TEXT NOT NULL,
                            source TEXT NOT NULL,
                            occurrences INTEGER NOT NULL
                        )
                        """
                    )
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS geo_cache (
                            ip TEXT PRIMARY KEY,
                            country TEXT NOT NULL
                        )
                        """
                    )
        except (OSError, sqlite3.Error):
            logger.exception("Impossible d'initialiser la base %s", self.database_path)
            raise

    def insert_events(self, events: list[AuthEvent]) -> int:
        """Insère un lot d'événements dans une transaction."""
        if not events:
            return 0
        rows = [
            (
                event.timestamp,
                event.ip,
                event.username,
                event.status,
                event.country,
                event.source,
                event.occurrences,
            )
            for event in events
        ]
        try:
            with closing(sqlite3.connect(self.database_path)) as connection:
                with connection:
                    connection.executemany(
                        """
                        INSERT INTO auth_events
                            (timestamp, ip, username, status, country, source, occurrences)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        rows,
                    )
        except sqlite3.Error:
            logger.exception("Échec d'insertion de %d événements", len(events))
            raise
        return len(rows)

    def get_cached_country(self, ip: str) -> str | None:
        """Retourne le pays en cache, ou None si l'adresse n'a jamais été traitée."""
        try:
            with closing(sqlite3.connect(self.database_path)) as connection:
                row = connection.execute(
                    "SELECT country FROM geo_cache WHERE ip = ?", (ip,)
                ).fetchone()
        except sqlite3.Error:
            logger.exception("Impossible de lire le cache géographique pour %s", ip)
            raise
        return None if row is None else str(row[0])

    def cache_country(self, ip: str, country: str) -> None:
        """Ajoute ou actualise le pays associé à une adresse IP."""
        try:
            with closing(sqlite3.connect(self.database_path)) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO geo_cache (ip, country) VALUES (?, ?)
                        ON CONFLICT(ip) DO UPDATE SET country = excluded.country
                        """,
                        (ip, country),
                    )
        except sqlite3.Error:
            logger.exception("Impossible de mettre en cache le pays de %s", ip)
            raise

    def failed_attempts_by_country(self, limit: int = 15) -> list[tuple[str, int]]:
        """Retourne les pays qui cumulent le plus d'échecs."""
        if limit < 1:
            raise ValueError("La limite doit être supérieure à zéro.")
        return self._aggregate(
            """
            SELECT country, SUM(occurrences) AS total
            FROM auth_events
            WHERE status IN ('Failed', 'Invalid')
            GROUP BY country
            ORDER BY total DESC, country
            LIMIT ?
            """,
            (limit,),
        )

    def successful_attempts_by_user(self) -> list[tuple[str, int]]:
        """Agrège les authentifications réussies par utilisateur."""
        return self._aggregate(
            """
            SELECT username, SUM(occurrences) AS total
            FROM auth_events
            WHERE status = 'Success' AND username IS NOT NULL
            GROUP BY username
            ORDER BY total DESC, username
            """
        )

    def invalid_users(self, limit: int = 15) -> list[tuple[str, int]]:
        """Retourne les noms d'utilisateurs invalides les plus fréquents."""
        if limit < 1:
            raise ValueError("La limite doit être supérieure à zéro.")
        return self._aggregate(
            """
            SELECT username, SUM(occurrences) AS total
            FROM auth_events
            WHERE status = 'Invalid' AND username IS NOT NULL
            GROUP BY username
            ORDER BY total DESC, username
            LIMIT ?
            """,
            (limit,),
        )

    def _aggregate(
        self, query: str, parameters: tuple[object, ...] = ()
    ) -> list[tuple[str, int]]:
        try:
            with closing(sqlite3.connect(self.database_path)) as connection:
                rows = connection.execute(query, parameters).fetchall()
        except sqlite3.Error:
            logger.exception("Échec d'une requête d'agrégation")
            raise
        return [(str(name), int(total)) for name, total in rows]
