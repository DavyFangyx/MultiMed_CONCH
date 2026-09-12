#!/usr/bin/env python3
"""Aligned single-field c-index bar charts and a radial bar disc.

Usage:
conda activate conch
python "results_display/scripts/E1_Fig2_Single-field c-index.py" \
    --dataset all \
    --landmark_time all \
    --disc_top_n 20
"""

from __future__ import annotations

import argparse
import csv
import os
from collections import Counter
from pathlib import Path

import numpy as np

from collect_common import (
    PROJECT_ROOT,
    add_common_collect_args,
    collect_named_files,
    print_collect_summary,
)
from common.datasets import load_dataset_configs, resolve_dataset_names
from common.paths import (
    RESULTS_ROOT,
    dataset_univariate_results_dir,
    parse_landmark_time_list,
    result_experiment_name,
    validate_encoding,
)
from discovery.landmark import iter_landmark_args


CSV_NAME = "field_cindex.csv"
SOURCE_COLUMNS = [
    "field",
    "field_idx",
    "n_fields",
    "c_index_mean",
    "c_index_std",
    "per_fold",
    "status",
]
FIG_DIRNAME = "E1_Fig2_Single-field c-index"
YMAX = 0.90
DPI = 160
BAR_WIDTH = 0.86


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Draw TCGA single-field c-index bar charts and a radial bar disc. "
            "Missing fields are plotted as 0."
        )
    )
    add_common_collect_args(
        parser,
        experiment="univariate",
        extra_help=(
            "Override default results_display/"
            + FIG_DIRNAME
            + "/{encoding}/{landmark_tag}"
        ),
    )
    parser.add_argument(
        "--disc_top_n",
        "--top_n",
        dest="disc_top_n",
        type=int,
        default=15,
        metavar="N",
        help=(
            "number of top fields to include in disc.png, ranked by mean "
            "c_index_mean across datasets (default: 15)"
        ),
    )
    parser.add_argument(
        "--disc_rank_mode",
        "--rank_mode",
        choices=("coverage", "mean"),
        default="coverage",
        help=(
            "ranking mode for disc top fields: coverage ranks by the number "
            "of datasets with a value, then mean c-index; mean preserves the "
            "original mean-first ranking (default: coverage)"
        ),
    )
    return parser


def is_tcga_dataset(name: str) -> bool:
    return str(name).upper().startswith("TCGA")


def display_dataset_name(name: str) -> str:
    return str(name).replace("_", "-")


def fig_out_dir(
    encoding: str,
    landmark_tag: str,
    override: str | None = None,
    *,
    nest_override: bool = False,
) -> Path:
    if override:
        path = Path(override)
        return path / landmark_tag if nest_override else path
    return PROJECT_ROOT / "results_display" / FIG_DIRNAME / encoding / landmark_tag


def locate_dataset(
    dataset: str, encoding: str, landmark_tag: str, experiment: str = ""
) -> dict:
    return {
        "src_dir": dataset_univariate_results_dir(
            dataset,
            encoding=encoding,
            landmark_tag=landmark_tag,
            experiment=experiment,
        )
    }


def configure_matplotlib():
    os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp") / "mplconfig"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def field_leaf(field: str) -> str:
    text = str(field).replace("[]", "")
    return text.split(".")[-1]


def field_parent(field: str) -> str:
    text = str(field).replace("[]", "")
    parts = [part for part in text.split(".") if part]
    if len(parts) >= 2:
        return parts[-2]
    return ""


def short_field_labels(fields: list[str]) -> list[str]:
    leaves = [field_leaf(field) for field in fields]
    counts = Counter(leaves)
    labels = []
    for field, leaf in zip(fields, leaves):
        if counts[leaf] == 1:
            labels.append(leaf)
            continue
        parent = field_parent(field)
        labels.append(parent + "." + leaf if parent else leaf)
    return labels


def parse_float(row: dict[str, str], key: str) -> float | None:
    raw = (row.get(key) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def build_matrix(records: list[dict], fields: list[str], key: str) -> np.ndarray:
    index = {field: idx for idx, field in enumerate(fields)}
    matrix = np.full((len(records), len(fields)), np.nan, dtype=float)
    for row_idx, record in enumerate(records):
        for row in record["rows"]:
            field = str(row.get("field") or "").strip()
            if field not in index:
                continue
            value = parse_float(row, key)
            if value is None:
                continue
            matrix[row_idx, index[field]] = value
    return matrix


def filled_heights(row: np.ndarray) -> np.ndarray:
    return np.nan_to_num(row, nan=0.0)


def top_field_indices(
    matrix: np.ndarray, top_n: int | None, rank_mode: str = "coverage"
) -> list[int]:
    """Return field indexes ranked by the selected cross-dataset strategy."""
    n_fields = matrix.shape[1]
    if top_n is None:
        return list(range(n_fields))
    if top_n <= 0:
        raise ValueError("--disc_top_n/--top_n must be a positive integer")
    if rank_mode not in {"coverage", "mean"}:
        raise ValueError("rank_mode must be 'coverage' or 'mean'")

    counts = np.sum(np.isfinite(matrix), axis=0)
    totals = np.nansum(matrix, axis=0)
    scores = np.divide(
        totals,
        counts,
        out=np.full(n_fields, np.nan, dtype=float),
        where=counts > 0,
    )
    if rank_mode == "coverage":
        # Relax coverage one level at a time; use mean c-index within a tier.
        sort_key = lambda idx: (-counts[idx], -scores[idx], idx)
    else:
        # Original behavior: mean c-index first, coverage as tie-breaker.
        sort_key = lambda idx: (-scores[idx], -counts[idx], idx)
    ranked = sorted(
        (idx for idx in range(n_fields) if counts[idx] > 0), key=sort_key
    )
    return ranked[: min(top_n, len(ranked))]


def write_rows_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_matrix_csv(
    path: Path, datasets: list[str], fields: list[str], matrix: np.ndarray
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["dataset", *fields])
        for dataset, row in zip(datasets, matrix):
            payload = [dataset]
            for value in row:
                payload.append("" if np.isnan(value) else ("%.10g" % value))
            writer.writerow(payload)


def dataset_color_map(datasets: list[str], plt) -> dict[str, tuple]:
    n = len(datasets)
    cmap = plt.get_cmap("nipy_spectral")
    if n == 1:
        return {datasets[0]: cmap(0.15)}
    return {
        name: cmap(0.08 + 0.84 * idx / (n - 1))
        for idx, name in enumerate(datasets)
    }


def style_bar_axis(ax, labels: list[str], *, show_labels: bool) -> None:
    n_cols = len(labels)
    ax.set_xlim(-0.5, n_cols - 0.5)
    ax.set_ylim(0.0, YMAX)
    ax.set_yticks([0.0, 0.25, 0.50, 0.75])
    ax.tick_params(axis="y", labelsize=7, length=2, pad=1)
    ax.tick_params(axis="x", length=0, pad=2)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.axhline(0.5, color="#bbbbbb", lw=0.6, ls="--", zorder=0)
    if show_labels:
        ax.set_xticks(np.arange(n_cols))
        ax.set_xticklabels(labels, rotation=90, fontsize=5.5, ha="center", va="top")
        ax.set_xlabel("fields (dictionary order)")
    else:
        ax.set_xticks([])


def draw_bars(
    ax,
    *,
    heights: np.ndarray,
    stds: np.ndarray | None,
    color,
    with_error: bool,
) -> None:
    n_cols = heights.shape[0]
    x = np.arange(n_cols)
    ax.bar(
        x,
        heights,
        width=BAR_WIDTH,
        color=color,
        edgecolor="none",
        zorder=2,
    )
    if not with_error or stds is None:
        return
    mask = np.isfinite(stds) & (heights > 0)
    if not np.any(mask):
        return
    ax.errorbar(
        x[mask],
        heights[mask],
        yerr=stds[mask],
        fmt="none",
        ecolor="#222222",
        elinewidth=0.45,
        capsize=1.1,
        capthick=0.45,
        zorder=3,
    )


def plot_dataset_bars(
    path: Path,
    *,
    heights: np.ndarray,
    stds: np.ndarray | None,
    labels: list[str],
    dataset: str,
    color,
    title: str,
    plt,
) -> None:
    n_cols = heights.shape[0]
    fig_w = max(18.0, n_cols * 0.11)
    fig, ax = plt.subplots(figsize=(fig_w, 4.6))
    draw_bars(ax, heights=heights, stds=stds, color=color, with_error=True)
    style_bar_axis(ax, labels, show_labels=True)
    ax.set_ylabel("c-index")
    ax.set_title(title, fontsize=13, pad=10)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)


def plot_stacked_bars(
    path: Path,
    *,
    matrix: np.ndarray,
    stds: np.ndarray | None,
    datasets: list[str],
    labels: list[str],
    colors: dict[str, tuple],
    title: str,
    plt,
) -> None:
    n_rows, n_cols = matrix.shape
    fig_w = max(18.0, n_cols * 0.11)
    fig_h = max(8.0, n_rows * 0.72 + 3.4)
    fig, axes = plt.subplots(
        n_rows,
        1,
        figsize=(fig_w, fig_h),
        sharex=True,
        squeeze=False,
    )
    fig.suptitle(title, fontsize=13, y=0.995)
    for row_idx, dataset in enumerate(datasets):
        ax = axes[row_idx, 0]
        heights = filled_heights(matrix[row_idx])
        draw_bars(
            ax,
            heights=heights,
            stds=None,
            color=colors[dataset],
            with_error=False,
        )
        style_bar_axis(ax, labels, show_labels=(row_idx == n_rows - 1))
        ax.set_ylabel(
            display_dataset_name(dataset),
            rotation=0,
            ha="right",
            va="center",
            fontsize=7.5,
            labelpad=18,
        )
        ax.set_yticks([0.0, 0.5])
        ax.tick_params(axis="y", labelsize=6)
    fig.tight_layout(rect=(0.02, 0.0, 1.0, 0.98))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)


def polar_label_style(theta_rad: float) -> tuple[float, str]:
    deg = float(np.degrees(theta_rad) % 360.0)
    rotation = -deg
    if 90.0 < deg < 270.0:
        rotation += 180.0
        ha = "right"
    else:
        ha = "left"
    return rotation, ha


def plot_disc(
    path: Path,
    *,
    matrix: np.ndarray,
    datasets: list[str],
    colors: dict[str, tuple],
    title: str,
    plt,
) -> None:
    """Draw each dataset's bar chart on one curved 1/n circumference sector."""
    n_rows, n_cols = matrix.shape
    if n_rows == 0 or n_cols == 0:
        return

    sector = (2.0 * np.pi) / n_rows
    sector_gap = min(sector * 0.08, 0.018)
    field_step = (sector - 2.0 * sector_gap) / n_cols
    bar_width = field_step * 0.84
    baseline = 1.35
    radial_span = 4.9
    max_r = baseline + radial_span

    fig = plt.figure(figsize=(16.5, 16.5))
    ax = fig.add_subplot(111, projection="polar")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    for row_idx, dataset in enumerate(datasets):
        start = row_idx * sector + sector_gap
        theta = start + (np.arange(n_cols) + 0.5) * field_step
        heights = filled_heights(matrix[row_idx])
        radial_heights = np.clip(heights, 0.0, YMAX) / YMAX * radial_span
        ax.bar(
            theta,
            radial_heights,
            width=bar_width,
            bottom=baseline,
            color=colors[dataset],
            edgecolor="none",
            align="center",
            zorder=2,
        )

        # The ordinary chart's horizontal x-axis becomes this curved baseline.
        baseline_theta = np.linspace(
            start - sector_gap * 0.15,
            start + sector - sector_gap * 0.85,
            32,
        )
        ax.plot(
            baseline_theta,
            np.full(baseline_theta.shape, baseline),
            color="#d0d0d0",
            lw=0.65,
            zorder=1,
        )

        # Dataset names identify the sectors without adding a y-axis/legend.
        middle = row_idx * sector + sector * 0.5
        deg = float(np.degrees(middle) % 360.0)
        rotation = deg - 90.0
        if 90.0 < deg < 270.0:
            rotation += 180.0
            ha = "right"
        else:
            ha = "left"
        ax.text(
            middle,
            max_r + 0.34,
            display_dataset_name(dataset),
            rotation=rotation,
            rotation_mode="anchor",
            ha=ha,
            va="center",
            fontsize=6.0,
            clip_on=False,
        )

    # The circular chart intentionally has no x/y ticks, labels, or grid.
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_ylim(0.0, max_r + 0.72)
    ax.grid(False)
    ax.spines["polar"].set_visible(False)
    ax.set_title(title, fontsize=14, pad=18)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)


def run_one_landmark(
    args,
    encoding: str,
    landmark_tag: str,
    experiment: str,
    names: list[str],
    *,
    nest_override: bool = False,
) -> int:
    out_dir = fig_out_dir(encoding, landmark_tag, args.out, nest_override=nest_override)
    per_dir = out_dir / "per_dataset"
    per_top_dir = out_dir / "per_dataset_top_n"

    def _locate(dataset, encoding, landmark_tag):
        return locate_dataset(
            dataset, encoding, landmark_tag, experiment=getattr(args, "experiment", "")
        )

    records, missing = collect_named_files(
        names,
        encoding=encoding,
        landmark_tag=landmark_tag,
        locate=_locate,
        required=[CSV_NAME],
        csv_key=CSV_NAME,
        csv_columns=SOURCE_COLUMNS,
    )
    wrote = []
    skipped = []
    if not records:
        print_collect_summary(
            names=names, records=records, missing=missing, wrote=wrote, skipped=skipped
        )
        print("  out_dir: %s" % out_dir)
        return 1

    fields = sorted(
        {
            str(row.get("field") or "").strip()
            for record in records
            for row in record["rows"]
            if str(row.get("field") or "").strip()
        }
    )
    labels = short_field_labels(fields)
    datasets = [record["dataset"] for record in records]
    matrix = build_matrix(records, fields, "c_index_mean")
    stds = build_matrix(records, fields, "c_index_std")
    disc_indices = top_field_indices(
        matrix, args.disc_top_n, rank_mode=args.disc_rank_mode
    )
    disc_fields = [fields[idx] for idx in disc_indices]
    disc_labels = [labels[idx] for idx in disc_indices]
    disc_matrix = matrix[:, disc_indices]
    plt = configure_matplotlib()
    colors = dataset_color_map(datasets, plt)

    axis_csv = out_dir / "field_axis.csv"
    matrix_csv = out_dir / "cindex_matrix.csv"
    write_rows_csv(
        axis_csv,
        [
            {"field_idx": idx, "field": field, "label": label}
            for idx, (field, label) in enumerate(zip(fields, labels))
        ],
        ["field_idx", "field", "label"],
    )
    write_matrix_csv(matrix_csv, datasets, fields, matrix)
    wrote.extend([axis_csv, matrix_csv])

    heading = "E1 Fig2 single-field c-index  |  %s / %s" % (encoding, landmark_tag)
    stacked_png = out_dir / "stacked_barcode.png"
    plot_stacked_bars(
        stacked_png,
        matrix=matrix,
        stds=stds,
        datasets=datasets,
        labels=labels,
        colors=colors,
        title=heading,
        plt=plt,
    )
    wrote.append(stacked_png)

    disc_png = out_dir / "disc.png"
    plot_disc(
        disc_png,
        matrix=disc_matrix,
        datasets=datasets,
        colors=colors,
        title="%s  |  top %d fields (%s rank)"
        % (heading, len(disc_fields), args.disc_rank_mode),
        plt=plt,
    )
    wrote.append(disc_png)

    disc_fields_csv = out_dir / "disc_top_fields.csv"
    scores = np.nanmean(disc_matrix, axis=0)
    available = np.sum(np.isfinite(disc_matrix), axis=0)
    write_rows_csv(
        disc_fields_csv,
        [
            {
                "rank": rank,
                "field_idx": idx,
                "field": field,
                "label": label,
                "c_index_mean_across_datasets": "%.10g" % score,
                "datasets_with_value": int(count),
            }
            for rank, (idx, field, label, score, count) in enumerate(
                zip(disc_indices, disc_fields, disc_labels, scores, available),
                start=1,
            )
        ],
        [
            "rank",
            "field_idx",
            "field",
            "label",
            "c_index_mean_across_datasets",
            "datasets_with_value",
        ],
    )
    wrote.append(disc_fields_csv)

    for row_idx, record in enumerate(records):
        dataset = record["dataset"]
        png_path = per_dir / ("%s.png" % dataset)
        plot_dataset_bars(
            png_path,
            heights=filled_heights(matrix[row_idx]),
            stds=stds[row_idx],
            labels=labels,
            dataset=dataset,
            color=colors[dataset],
            title="%s  |  %s / %s" % (
                display_dataset_name(dataset),
                encoding,
                landmark_tag,
            ),
            plt=plt,
        )
        wrote.append(png_path)

        top_png_path = per_top_dir / ("%s.png" % dataset)
        plot_dataset_bars(
            top_png_path,
            heights=filled_heights(disc_matrix[row_idx]),
            stds=stds[row_idx, disc_indices],
            labels=disc_labels,
            dataset=dataset,
            color=colors[dataset],
            title="%s  |  %s / %s  |  top %d fields" % (
                display_dataset_name(dataset),
                encoding,
                landmark_tag,
                len(disc_fields),
            ),
            plt=plt,
        )
        wrote.append(top_png_path)

    missing_csv = out_dir / "missing.csv"
    if missing:
        write_rows_csv(
            missing_csv,
            [
                {
                    "dataset": row["dataset"],
                    "encoding": row["encoding"],
                    "landmark_tag": row["landmark_tag"],
                    "reason": row["reason"],
                }
                for row in missing
            ],
            ["dataset", "encoding", "landmark_tag", "reason"],
        )
        wrote.append(missing_csv)
    elif missing_csv.exists():
        missing_csv.unlink()

    print_collect_summary(
        names=names, records=records, missing=missing, wrote=wrote, skipped=skipped
    )
    print(
        "  fields: %d (disc: %d, rank_mode: %s)"
        % (len(fields), len(disc_fields), args.disc_rank_mode)
    )
    print("  out_dir: %s" % out_dir)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    encoding = validate_encoding(args.encoding)
    experiment = result_experiment_name(
        getattr(args, "collect_kind", "univariate"),
        getattr(args, "experiment", ""),
    )
    names = sorted(
        name
        for name in resolve_dataset_names(
            args.dataset, load_dataset_configs(args.datasets_config)
        )
        if is_tcga_dataset(name)
    )
    if not names:
        raise ValueError("no TCGA datasets resolved from --dataset")
    tokens = parse_landmark_time_list(args.landmark_time)
    nest_override = bool(args.out) and (tokens == ["all"] or len(tokens) > 1)
    scan_root = RESULTS_ROOT / experiment / encoding
    rc = 0
    n_ran = 0
    for bound in iter_landmark_args(args, scan_roots=scan_root, context=str(scan_root)):
        n_ran += 1
        print("== %s / %s ==" % (encoding, bound.landmark_tag))
        rc = max(
            rc,
            run_one_landmark(
                args,
                encoding,
                bound.landmark_tag,
                experiment,
                names,
                nest_override=nest_override,
            ),
        )
    if n_ran == 0:
        raise ValueError("no landmark tags resolved from --landmark_time")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
