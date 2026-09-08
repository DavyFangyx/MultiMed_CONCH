#!/usr/bin/env python3
"""Collect greedy c-index curves and tables into results_display/."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from collect_common import (
    add_common_collect_args,
    collect_named_files,
    compose_collage,
    print_collect_summary,
    resolve_collect_context,
    write_combined_csv,
)

from common.paths import dataset_greedy_results_dir


CSV_STEM = "cindex_by_n_fields"
SOURCE_COLUMNS = ["step", "n_fields", "added", "c_index_mean", "c_index_std", "c_index_se", "subset"]
GROWTH_MATRIX_STEM = "field_gain_matrix"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect greedy cindex_by_n_fields PNG/CSV files into "
            "results_display/greedy/{encoding}/{landmark_tag}/."
        )
    )
    return add_common_collect_args(parser, experiment="greedy")


def locate_dataset(dataset: str, encoding: str, landmark_tag: str, experiment: str = "") -> dict:
    src_dir = dataset_greedy_results_dir(
        dataset,
        encoding=encoding,
        landmark_tag=landmark_tag,
        experiment=experiment,
    )
    return {"src_dir": src_dir}


def parse_added_fields(raw: str) -> list[str]:
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def growth_events(records: list[dict]) -> list[dict]:
    events: list[dict] = []
    for record in records:
        prev_mean = None
        for idx, row in enumerate(record["rows"]):
            mean = float(row["c_index_mean"])
            if idx == 0:
                prev_mean = mean
                continue
            delta = mean - float(prev_mean)
            prev_mean = mean
            if delta <= 0:
                continue
            for field in parse_added_fields(row["added"]):
                events.append(
                    {
                        "dataset": record["dataset"],
                        "encoding": record["encoding"],
                        "landmark_tag": record["landmark_tag"],
                        "field": field,
                        "step": row["step"],
                        "delta_c": delta,
                        "c_index_mean": mean,
                    }
                )
    return events


def growth_matrix(records: list[dict]) -> tuple[list[dict], list[str], list[str]]:
    events = growth_events(records)
    datasets = [record["dataset"] for record in records]
    counts: dict[str, int] = {}
    for event in events:
        counts[event["field"]] = counts.get(event["field"], 0) + 1
    fields = sorted(counts, key=lambda name: (-counts[name], name))
    return events, fields, datasets


def write_growth_matrix_csv(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["dataset", "encoding", "landmark_tag", "field", "step", "delta_c", "c_index_mean"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(events)


def plot_growth_matrix(
    path: Path,
    events: list[dict],
    *,
    fields: list[str],
    datasets: list[str],
    encoding: str,
    landmark_tag: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import Normalize

    matrix = np.full((len(fields), len(datasets)), np.nan, dtype=float)
    field_index = {name: idx for idx, name in enumerate(fields)}
    dataset_index = {name: idx for idx, name in enumerate(datasets)}
    for event in events:
        row = field_index[event["field"]]
        col = dataset_index[event["dataset"]]
        current = matrix[row, col]
        delta = float(event["delta_c"])
        matrix[row, col] = delta if np.isnan(current) else current + delta

    masked = np.ma.masked_invalid(matrix)
    cmap = plt.get_cmap("YlOrRd").copy()
    cmap.set_bad("white")
    finite = matrix[np.isfinite(matrix)]
    vmax = float(finite.max()) if finite.size else 1.0
    vmin = 0.0

    fig_w = max(12.0, 2.8 + 0.42 * len(datasets))
    fig_h = max(7.0, 2.4 + 0.34 * len(fields))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), layout="constrained")
    im = ax.imshow(masked, aspect="auto", cmap=cmap, norm=Normalize(vmin=vmin, vmax=max(vmax, 1e-6)))
    ax.set_xticks(range(len(datasets)))
    ax.set_xticklabels(datasets, rotation=90, ha="center", va="top", fontsize=9)
    ax.set_yticks(range(len(fields)))
    ax.set_yticklabels(fields, fontsize=9)
    ax.set_xlabel("dataset")
    ax.set_ylabel("added field")
    ax.set_title(f"greedy field gains  |  {encoding} / {landmark_tag}")
    ax.tick_params(length=0)
    ax.set_xticks(np.arange(-0.5, len(datasets), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(fields), 1), minor=True)
    ax.grid(which="minor", color="#dddddd", linewidth=0.6)
    ax.tick_params(which="minor", bottom=False, left=False)
    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01)
    cbar.set_label("Δ c-index")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    encoding, landmark_tag, experiment, names, out_dir = resolve_collect_context(args)

    def _locate(dataset, encoding, landmark_tag):
        return locate_dataset(dataset, encoding, landmark_tag, experiment=getattr(args, "experiment", ""))

    records, missing = collect_named_files(
        names,
        encoding=encoding,
        landmark_tag=landmark_tag,
        locate=_locate,
        required=[f"{CSV_STEM}.csv", f"{CSV_STEM}.png"],
        csv_key=f"{CSV_STEM}.csv",
        csv_columns=SOURCE_COLUMNS,
    )
    for record in records:
        record["png_path"] = record["cindex_by_n_fields_png"]
        record["csv_path"] = record["cindex_by_n_fields_csv"]

    csv_path = out_dir / f"{CSV_STEM}.csv"
    png_path = out_dir / f"{CSV_STEM}.png"
    matrix_csv_path = out_dir / f"{GROWTH_MATRIX_STEM}.csv"
    matrix_png_path = out_dir / f"{GROWTH_MATRIX_STEM}.png"
    stale_missing = out_dir / "missing.csv"
    fields: list[str] = []
    wrote: list[Path] = []
    skipped: list[Path] = []

    if records:
        write_combined_csv(csv_path, records, SOURCE_COLUMNS)
        compose_collage(
            records,
            png_path,
            heading=f"greedy c-index by n_fields  |  {encoding} / {landmark_tag}",
            cols=args.cols,
        )
        matrix_rows, fields, datasets = growth_matrix(records)
        write_growth_matrix_csv(matrix_csv_path, matrix_rows)
        wrote.extend([csv_path, png_path, matrix_csv_path])
        if fields:
            plot_growth_matrix(
                matrix_png_path,
                matrix_rows,
                fields=fields,
                datasets=datasets,
                encoding=encoding,
                landmark_tag=landmark_tag,
            )
            wrote.append(matrix_png_path)
        else:
            print("no later-step c-index gains; skip field gain matrix figure")
            skipped.append(matrix_png_path)
    else:
        print("no matching greedy PNG/CSV files; skip collage and combined CSV")
        skipped.extend([csv_path, png_path, matrix_csv_path, matrix_png_path])

    if stale_missing.exists():
        stale_missing.unlink()

    print_collect_summary(names=names, records=records, missing=missing, wrote=wrote, skipped=skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
