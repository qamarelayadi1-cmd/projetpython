"""Génération des graphiques du tableau de bord."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.container import BarContainer
from matplotlib.figure import Figure

from logger_config import get_logger
from storage.sqlite_storage import SQLiteEventStore

logger = get_logger(__name__, "serving.log")


def _draw_bar_chart(
    axis: Axes,
    labels: list[str],
    values: list[int],
    title: str,
    x_label: str,
    y_label: str,
    color: str = "#2F80D1",
) -> None:
    bars: BarContainer = axis.barh(
        labels,
        values,
        color=color,
        height=0.65 if len(labels) > 1 else 0.12,
        zorder=3,
    )
    axis.bar_label(
        bars,
        labels=[f"{value:,}".replace(",", " ") for value in values],
        padding=4,
        fontsize=8,
    )
    axis.set_title(title, fontsize=10, fontweight="bold")
    axis.set_xlabel(x_label, fontsize=8)
    axis.set_ylabel(y_label, fontsize=8)
    axis.tick_params(axis="both", labelsize=8)
    axis.grid(axis="x", color="#E8E8E8", linewidth=0.8, zorder=0)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.margins(x=0.12)
    if len(labels) == 1:
        axis.set_ylim(-0.5, 0.5)
    elif labels:
        axis.invert_yaxis()


def _save_bar_chart(
    labels: list[str],
    values: list[int],
    title: str,
    x_label: str,
    y_label: str,
    output_path: Path,
    color: str = "#2F80D1",
) -> None:
    figure: Figure | None = None
    try:
        figure, axis = plt.subplots(figsize=(11, 6))
        _draw_bar_chart(axis, labels, values, title, x_label, y_label, color)
        figure.tight_layout()
        figure.savefig(output_path, dpi=150)
    except (OSError, RuntimeError, ValueError, TypeError):
        logger.exception("Impossible d'écrire le graphique %s", output_path)
        if figure is not None:
            plt.close(figure)
        raise
    plt.close(figure)
    logger.info("Graphique enregistré: %s", output_path)


def build_dashboard(
    store: SQLiteEventStore,
    output_directory: str | Path,
    top_n: int = 15,
    show: bool = True,
) -> list[Path]:
    """Construit et enregistre les trois graphiques demandés."""
    output = Path(output_directory)
    try:
        output.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("Impossible de créer le dossier de sortie %s", output)
        raise

    failed_by_country = store.failed_attempts_by_country(top_n)
    successful_by_user = store.successful_attempts_by_user()
    invalid_users = store.invalid_users(top_n)

    charts = [
        (
            [user for user, _ in invalid_users] or ["Aucune donnée"],
            [count for _, count in invalid_users] or [0],
            f"1. Tentatives échouées avec 'Invalid user' (top {top_n})",
            "Nombre de tentatives",
            "Nom d'utilisateur invalide",
            output / "01_invalid_user_attempts.png",
            "#2F80D1",
        ),
        (
            [country for country, _ in failed_by_country] or ["Aucune donnée"],
            [count for _, count in failed_by_country] or [0],
            f"2. Tentatives échouées par pays (top {top_n})",
            "Nombre de tentatives échouées",
            "Pays (code ISO)",
            output / "02_failed_attempts_by_country.png",
            "#A3A39D",
        ),
        (
            [user for user, _ in successful_by_user] or ["Aucune donnée"],
            [count for _, count in successful_by_user] or [0],
            "3. Connexions réussies par utilisateur",
            "Nombre de connexions réussies",
            "Utilisateur",
            output / "03_successful_attempts_by_user.png",
            "#2F80D1",
        ),
    ]

    paths: list[Path] = []
    for labels, values, title, x_label, y_label, path, color in charts:
        _save_bar_chart(labels, values, title, x_label, y_label, path, color)
        paths.append(path)

    if show:
        figure = plt.figure(figsize=(12.5, 7.7))
        layout = figure.add_gridspec(2, 2, hspace=0.3, wspace=0.24)
        axes = (
            figure.add_subplot(layout[0, 0]),
            figure.add_subplot(layout[0, 1]),
            figure.add_subplot(layout[1, :]),
        )
        try:
            for axis, chart in zip(axes, charts):
                labels, values, title, x_label, y_label, _, color = chart
                _draw_bar_chart(axis, labels, values, title, x_label, y_label, color)
            figure.suptitle(
                "Analyse des logs SSH (auth.log)",
                fontsize=14,
                fontweight="bold",
            )
            figure.subplots_adjust(top=0.9, bottom=0.09)
            plt.show(block=True)
        except Exception:
            logger.exception("Impossible d'afficher le tableau de bord")
            raise
        finally:
            plt.close(figure)
    return paths
