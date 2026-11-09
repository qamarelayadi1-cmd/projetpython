"""Orchestration et adaptateurs pour les modules d'ingestion existants."""

import gzip
import ipaddress
import re
from datetime import datetime
from pathlib import Path
from typing import Iterator

import requests

from logger_config import get_logger
from storage.sqlite_storage import AuthEvent, SQLiteEventStore

logger = get_logger(__name__, "processing.log")
ingestion_logger = get_logger(f"{__name__}.ingestion", "ingestion.log")
UNKNOWN_COUNTRY = "Unknown"
NON_PUBLIC_COUNTRY = "Private / local"
BATCH_SIZE = 500
MAX_GEO_LOOKUPS_PER_RUN = 20

SSH_LINE = re.compile(
    r"^(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})\s+\S+\s+sshd\[\d+\]:\s*(?P<message>.*)$"
)
REPEATED_MESSAGE = re.compile(
    r"^message repeated (?P<count>\d+) times:\s*\[(?P<message>.*)\]$"
)
IP_TOKEN = r"(?P<ip>[0-9A-Fa-f:.]+)"
ACCEPTED = re.compile(
    rf"^Accepted (?:password|publickey) for (?P<username>\S+) from {IP_TOKEN} port \d+"
)
FAILED = re.compile(
    rf"^Failed [\w/-]+ for (?:invalid user )?(?P<username>\S+) "
    rf"from {IP_TOKEN} port \d+"
)
INVALID_USER = re.compile(
    rf"^Invalid user (?P<username>\S*) from {IP_TOKEN} port \d+"
)


def iter_log_files(data_directory: str | Path) -> Iterator[Path]:
    """Énumère tous les fichiers auth.log pris en charge, dans l'ordre."""
    directory = Path(data_directory)
    try:
        files = sorted(
            path
            for path in directory.iterdir()
            if path.is_file()
            and re.fullmatch(r"auth\.log(?:\.\d+)?(?:\.gz)?", path.name)
        )
    except OSError:
        ingestion_logger.exception("Impossible de lire le dossier de données %s", directory)
        raise
    if not files:
        error = FileNotFoundError(f"Aucun fichier auth.log trouvé dans {directory}")
        ingestion_logger.error("%s", error)
        raise error
    return iter(files)


def parse_line(line: str, source: str, year: int | None = None) -> list[AuthEvent]:
    """Parse une ligne SSH sans dépendre du parseur existant, non fonctionnel."""
    line_match = SSH_LINE.match(line.rstrip("\r\n"))
    if line_match is None:
        if "sshd[" in line:
            logger.warning("Ligne SSH non reconnue dans %s: %s", source, line.rstrip())
        return []

    timestamp_text = (
        f"{year or datetime.now().year} {line_match.group('month')} "
        f"{line_match.group('day')} {line_match.group('time')}"
    )
    try:
        timestamp = datetime.strptime(timestamp_text, "%Y %b %d %H:%M:%S").isoformat(
            sep=" "
        )
    except ValueError:
        logger.exception("Date invalide dans %s: %s", source, line.rstrip())
        return []

    message = line_match.group("message")
    repeated = REPEATED_MESSAGE.match(message)
    occurrences = int(repeated.group("count")) if repeated else 1
    if repeated:
        message = repeated.group("message")

    for pattern, status in (
        (ACCEPTED, "Success"),
        (FAILED, "Failed"),
        (INVALID_USER, "Invalid"),
    ):
        match = pattern.match(message)
        if match is None:
            continue
        ip = match.group("ip")
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            logger.error("Adresse IP invalide dans %s: %s", source, ip)
            return []
        if status == "Failed" and "invalid user " in message:
            status = "Invalid"
        username = match.group("username") or "(empty)"
        return [
            AuthEvent(
                timestamp=timestamp,
                ip=ip,
                username=username,
                status=status,
                country=UNKNOWN_COUNTRY,
                source=source,
                occurrences=occurrences,
            )
        ]

    if message.startswith(("Accepted ", "Failed ", "Invalid user", "message repeated ")):
        logger.warning(
            "Ligne SSH sans événement pris en charge dans %s: %s",
            source,
            line.rstrip(),
        )
    return []


def _country_for_ip(ip: str, store: SQLiteEventStore) -> str:
    """Résout le pays en privilégiant le cache persistant."""
    cached_country = store.get_cached_country(ip)
    if cached_country is not None:
        return cached_country

    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        logger.error("Adresse IP invalide ignorée par la géolocalisation: %s", ip)
        country = UNKNOWN_COUNTRY
    else:
        if not address.is_global:
            country = NON_PUBLIC_COUNTRY
        else:
            country = _lookup_country(ip)
    store.cache_country(ip, country)
    return country


def _lookup_country(ip: str) -> str:
    """Interroge ipinfo avec un délai maximal et journalise les erreurs réseau."""
    try:
        response = requests.get(f"https://ipinfo.io/{ip}/json", timeout=(2, 4))
        if response.status_code != 200:
            logger.error(
                "ipinfo a répondu HTTP %s pour %s", response.status_code, ip
            )
            return UNKNOWN_COUNTRY
        payload = response.json()
    except requests.Timeout:
        logger.exception("Délai dépassé lors de la géolocalisation de %s", ip)
        return UNKNOWN_COUNTRY
    except requests.RequestException:
        logger.exception("Erreur réseau lors de la géolocalisation de %s", ip)
        return UNKNOWN_COUNTRY
    except ValueError:
        logger.exception("Réponse JSON invalide de ipinfo pour %s", ip)
        return UNKNOWN_COUNTRY

    if not isinstance(payload, dict):
        logger.error("Format JSON inattendu de ipinfo pour %s", ip)
        return UNKNOWN_COUNTRY
    country = payload.get("country")
    if not isinstance(country, str) or not country:
        logger.error("Pays absent de la réponse ipinfo pour %s", ip)
        return UNKNOWN_COUNTRY
    return country


def run_pipeline(
    data_directory: str | Path,
    store: SQLiteEventStore,
) -> int:
    """Lit tous les journaux, parse et stocke les événements enrichis."""
    total = 0
    batch: list[AuthEvent] = []
    country_cache: dict[str, str] = {}
    geo_lookups = 0
    geo_limit_logged = False

    for path in iter_log_files(data_directory):
        ingestion_logger.info("Lecture du fichier %s", path)
        try:
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rt", encoding="utf-8", errors="strict") as stream:
                for line_number, line in enumerate(stream, start=1):
                    try:
                        events = parse_line(line, path.name)
                    except (ValueError, UnicodeError):
                        logger.exception(
                            "Ligne invalide %s:%d", path.name, line_number
                        )
                        continue
                    for event in events:
                        country = country_cache.get(event.ip)
                        if country is None:
                            cached_country = store.get_cached_country(event.ip)
                            if cached_country is not None:
                                country = cached_country
                            elif (
                                ipaddress.ip_address(event.ip).is_global
                                and geo_lookups >= MAX_GEO_LOOKUPS_PER_RUN
                            ):
                                country = UNKNOWN_COUNTRY
                                if not geo_limit_logged:
                                    logger.warning(
                                        "Limite de %d géolocalisations atteinte; "
                                        "les autres IP seront marquées Unknown",
                                        MAX_GEO_LOOKUPS_PER_RUN,
                                    )
                                    geo_limit_logged = True
                            else:
                                country = _country_for_ip(event.ip, store)
                                if ipaddress.ip_address(event.ip).is_global:
                                    geo_lookups += 1
                            country_cache[event.ip] = country
                        batch.append(
                            AuthEvent(
                                timestamp=event.timestamp,
                                ip=event.ip,
                                username=event.username,
                                status=event.status,
                                country=country,
                                source=event.source,
                                occurrences=event.occurrences,
                            )
                        )
                    if len(batch) >= BATCH_SIZE:
                        total += store.insert_events(batch)
                        batch.clear()
        except (OSError, EOFError, gzip.BadGzipFile, UnicodeError):
            ingestion_logger.exception("Erreur de lecture du fichier %s", path)
            raise

    total += store.insert_events(batch)
    logger.info(
        "Pipeline terminé: %d événements stockés; %d géolocalisations demandées",
        total,
        geo_lookups,
    )
    return total
