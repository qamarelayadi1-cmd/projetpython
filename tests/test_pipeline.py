"""Tests ciblés du parsing, du cache et des agrégations."""

import gzip
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from matplotlib import pyplot as plt

from pipeline.runner import _country_for_ip, parse_line, run_pipeline
from serving.dashboard import build_dashboard
from storage.sqlite_storage import SQLiteEventStore


class PipelineTests(unittest.TestCase):
    def test_parse_success_and_invalid_user(self) -> None:
        success = parse_line(
            "May 24 01:02:03 host sshd[12]: Accepted publickey for alice "
            "from 8.8.8.8 port 22 ssh2",
            "auth.log.1",
            year=2025,
        )
        invalid = parse_line(
            "May 24 01:02:04 host sshd[13]: Invalid user guest "
            "from 8.8.4.4 port 23",
            "auth.log.1",
            year=2025,
        )
        self.assertEqual((success[0].username, success[0].status), ("alice", "Success"))
        self.assertEqual((invalid[0].username, invalid[0].status), ("guest", "Invalid"))
        self.assertTrue(success[0].timestamp.startswith("2025-05-24"))

    def test_repeated_message_keeps_occurrence_count(self) -> None:
        events = parse_line(
            "May 24 01:02:03 host sshd[12]: message repeated 7 times: "
            "[Failed password for root from 8.8.8.8 port 22 ssh2]",
            "auth.log.1",
            year=2025,
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].occurrences, 7)
        self.assertEqual(events[0].status, "Failed")

    def test_empty_invalid_username_is_kept_as_an_invalid_event(self) -> None:
        events = parse_line(
            "May 24 01:02:03 host sshd[12]: Invalid user  "
            "from 8.8.8.8 port 22",
            "auth.log.1",
            year=2025,
        )
        self.assertEqual(events[0].username, "(empty)")
        self.assertEqual(events[0].status, "Invalid")

    def test_pipeline_reads_plain_and_gzip_and_caches_ip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data = root / "data"
            data.mkdir()
            (data / "auth.log.1").write_text(
                "May 24 01:02:03 host sshd[12]: Accepted password for alice "
                "from 8.8.8.8 port 22 ssh2\n",
                encoding="utf-8",
            )
            with gzip.open(data / "auth.log.2.gz", "wt", encoding="utf-8") as stream:
                stream.write(
                    "May 24 01:02:04 host sshd[13]: Failed password for bob "
                    "from 8.8.8.8 port 23 ssh2\n"
                )

            store = SQLiteEventStore(root / "events.sqlite3")
            with patch("pipeline.runner._lookup_country", return_value="US") as lookup:
                inserted = run_pipeline(data, store)

            self.assertEqual(inserted, 2)
            lookup.assert_called_once_with("8.8.8.8")
            self.assertEqual(store.failed_attempts_by_country(), [("US", 1)])
            self.assertEqual(store.successful_attempts_by_user(), [("alice", 1)])

    def test_pipeline_limits_public_ip_lookups(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data = root / "data"
            data.mkdir()
            lines = [
                f"May 24 01:02:{index:02d} host sshd[{index}]: "
                f"Failed password for root from 8.8.8.{index} port 22 ssh2"
                for index in range(1, 23)
            ]
            (data / "auth.log.1").write_text("\n".join(lines), encoding="utf-8")
            store = SQLiteEventStore(root / "events.sqlite3")

            with patch("pipeline.runner._lookup_country", return_value="US") as lookup:
                inserted = run_pipeline(data, store)

            self.assertEqual(inserted, 22)
            self.assertEqual(lookup.call_count, 20)
            self.assertEqual(
                dict(store.failed_attempts_by_country()),
                {"US": 20, "Unknown": 2},
            )

    def test_private_ip_is_not_sent_to_geolocation_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = SQLiteEventStore(Path(temporary_directory) / "events.sqlite3")
            with patch("pipeline.runner._lookup_country") as lookup:
                country = _country_for_ip("127.0.0.1", store)
            self.assertEqual(country, "Private / local")
            lookup.assert_not_called()
            self.assertEqual(store.get_cached_country("127.0.0.1"), country)

    def test_dashboard_writes_three_png_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            store = SQLiteEventStore(root / "events.sqlite3")
            paths = build_dashboard(store, root / "charts", show=False)
            self.assertEqual(len(paths), 3)
            self.assertTrue(all(path.is_file() for path in paths))
            self.assertEqual(
                [path.name for path in paths],
                [
                    "01_invalid_user_attempts.png",
                    "02_failed_attempts_by_country.png",
                    "03_successful_attempts_by_user.png",
                ],
            )

    def test_dashboard_displays_the_saved_figures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            store = SQLiteEventStore(root / "events.sqlite3")
            displayed_charts: list[
                list[tuple[str, str, str, float, tuple[float, float]]]
            ] = []

            def inspect_dashboard(**_: object) -> None:
                figure = plt.gcf()
                displayed_charts.append(
                    [
                        (
                            axis.get_title(),
                            axis.get_xlabel(),
                            axis.get_ylabel(),
                            axis.patches[0].get_height(),
                            axis.get_ylim(),
                        )
                        for axis in figure.axes
                    ]
                )

            with patch(
                "serving.dashboard.plt.show",
                side_effect=inspect_dashboard,
            ) as show:
                build_dashboard(store, root / "charts")
            show.assert_called_once_with(block=True)
            self.assertEqual(
                displayed_charts[0][:3],
                [
                    (
                        "1. Tentatives échouées avec 'Invalid user' (top 15)",
                        "Nombre de tentatives",
                        "Nom d'utilisateur invalide",
                        0.12,
                        (-0.5, 0.5),
                    ),
                    (
                        "2. Tentatives échouées par pays (top 15)",
                        "Nombre de tentatives échouées",
                        "Pays (code ISO)",
                        0.12,
                        (-0.5, 0.5),
                    ),
                    (
                        "3. Connexions réussies par utilisateur",
                        "Nombre de connexions réussies",
                        "Utilisateur",
                        0.12,
                        (-0.5, 0.5),
                    ),
                ],
            )


if __name__ == "__main__":
    unittest.main()
