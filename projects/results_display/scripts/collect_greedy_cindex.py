#!/usr/bin/env python3
"""Collect greedy c-index curves and tables into results_display/."""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parent
SRC = PROJECT_ROOT / "src"

for path in (REPO_ROOT, SRC):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from common.datasets import load_dataset_configs, resolve_dataset_names
from common.paths import (
    DEFAULT_DATASETS_CONFIG,
    VALID_ENCODINGS,
    dataset_greedy_dir,
    landmark_tag_from_args,
    validate_encoding,
)


DISPLAY_ROOT = PROJECT_ROOT / "results_display"
GRID_COLS = 6
TITLE_HEIGHT = 56
PAD = 12
BACKGROUND = (255, 255, 255)
TITLE_COLOR = (32, 32, 32)
CELL_TITLE_COLOR = (40, 40, 40)
BORDER_COLOR = (220, 220, 220)
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
    parser.add_argument(
        "--dataset",
        default="all",
        help="数据集名；支持 all 或逗号分隔列表。默认 all。",
    )
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument(
        "--encoding",
        default="prompt",
        choices=list(VALID_ENCODINGS),
    )
    parser.add_argument(
        "--landmark_time",
        required=True,
        help="全局 landmark 起点：天数（非负整数）或 none。",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="覆盖默认 results_display/greedy/{encoding}/{landmark_tag}",
    )
    parser.add_argument(
        "--cols",
        type=int,
        default=GRID_COLS,
        help="拼图列数，默认 6。",
    )
    return parser


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = [
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf",
    ]
    search_dirs = [
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/truetype/liberation"),
        Path("/usr/share/fonts/truetype/freefont"),
    ]
    for name in names:
        for root in search_dirs:
            path = root / name
            if path.exists():
                return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def read_curve_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"empty CSV header: {csv_path}")
        missing = [col for col in SOURCE_COLUMNS if col not in reader.fieldnames]
        if missing:
            raise ValueError(f"{csv_path} missing columns: {missing}")
        return [{col: (row.get(col) or "") for col in SOURCE_COLUMNS} for row in reader]


def collect_dataset(
    dataset: str,
    encoding: str,
    landmark_tag: str,
) -> tuple[dict | None, dict | None]:
    greedy_dir = dataset_greedy_dir(dataset, encoding=encoding, landmark_tag=landmark_tag)
    png_path = greedy_dir / f"{CSV_STEM}.png"
    csv_path = greedy_dir / f"{CSV_STEM}.csv"
    reasons = []
    if not png_path.exists():
        reasons.append(f"missing {png_path.name}")
    if not csv_path.exists():
        reasons.append(f"missing {csv_path.name}")
    if reasons:
        return None, {
            "dataset": dataset,
            "encoding": encoding,
            "landmark_tag": landmark_tag,
            "greedy_dir": str(greedy_dir),
            "reason": "; ".join(reasons),
        }
    return {
        "dataset": dataset,
        "encoding": encoding,
        "landmark_tag": landmark_tag,
        "png_path": png_path,
        "csv_path": csv_path,
        "rows": read_curve_rows(csv_path),
    }, None


def write_combined_csv(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["dataset", "encoding", "landmark_tag", *SOURCE_COLUMNS]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            for row in record["rows"]:
                writer.writerow(
                    {
                        "dataset": record["dataset"],
                        "encoding": record["encoding"],
                        "landmark_tag": record["landmark_tag"],
                        **row,
                    }
                )


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def compose_collage(
    records: list[dict],
    out_path: Path,
    *,
    encoding: str,
    landmark_tag: str,
    cols: int,
) -> None:
    if not records:
        raise ValueError("no greedy PNG/CSV records to collage")
    if cols < 1:
        raise ValueError("--cols must be >= 1")

    images = [Image.open(record["png_path"]).convert("RGB") for record in records]
    cell_w = max(im.width for im in images)
    cell_h = max(im.height for im in images)
    n = len(images)
    cols = min(cols, n)
    rows = math.ceil(n / cols)
    title_font = load_font(36, bold=True)
    cell_font = load_font(28, bold=True)

    canvas_w = cols * cell_w + (cols + 1) * PAD
    canvas_h = TITLE_HEIGHT + rows * (TITLE_HEIGHT + cell_h) + (rows + 1) * PAD
    canvas = Image.new("RGB", (canvas_w, canvas_h), BACKGROUND)
    draw = ImageDraw.Draw(canvas)

    heading = f"greedy c-index by n_fields  |  {encoding} / {landmark_tag}"
    tw, th = _text_size(draw, heading, title_font)
    draw.text(((canvas_w - tw) / 2, (TITLE_HEIGHT - th) / 2), heading, fill=TITLE_COLOR, font=title_font)

    for idx, (record, image) in enumerate(zip(records, images)):
        row, col = divmod(idx, cols)
        x0 = PAD + col * (cell_w + PAD)
        y0 = TITLE_HEIGHT + PAD + row * (TITLE_HEIGHT + cell_h + PAD)
        label = record["dataset"]
        lw, lh = _text_size(draw, label, cell_font)
        draw.text((x0 + (cell_w - lw) / 2, y0 + (TITLE_HEIGHT - lh) / 2), label, fill=CELL_TITLE_COLOR, font=cell_font)

        img_x = x0 + (cell_w - image.width) // 2
        img_y = y0 + TITLE_HEIGHT + (cell_h - image.height) // 2
        canvas.paste(image, (img_x, img_y))
        draw.rectangle(
            [x0, y0, x0 + cell_w - 1, y0 + TITLE_HEIGHT + cell_h - 1],
            outline=BORDER_COLOR,
            width=1,
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    for image in images:
        image.close()


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
    encoding = validate_encoding(args.encoding)
    landmark_tag = landmark_tag_from_args(args)
    datasets = load_dataset_configs(args.datasets_config)
    names = resolve_dataset_names(args.dataset, datasets)
    if not names:
        raise ValueError("--dataset did not resolve to any datasets")

    out_dir = Path(args.out) if args.out else DISPLAY_ROOT / "greedy" / encoding / landmark_tag
    records: list[dict] = []
    missing: list[dict] = []
    for name in names:
        record, miss = collect_dataset(name, encoding, landmark_tag)
        if miss is not None:
            missing.append(miss)
            print(f"  skip {name}: {miss['reason']}")
            continue
        records.append(record)

    csv_path = out_dir / f"{CSV_STEM}.csv"
    png_path = out_dir / f"{CSV_STEM}.png"
    matrix_csv_path = out_dir / f"{GROWTH_MATRIX_STEM}.csv"
    matrix_png_path = out_dir / f"{GROWTH_MATRIX_STEM}.png"
    stale_missing = out_dir / "missing.csv"
    fields: list[str] = []

    if records:
        write_combined_csv(csv_path, records)
        compose_collage(
            records,
            png_path,
            encoding=encoding,
            landmark_tag=landmark_tag,
            cols=args.cols,
        )
        matrix_rows, fields, datasets = growth_matrix(records)
        write_growth_matrix_csv(matrix_csv_path, matrix_rows)
        if fields:
            plot_growth_matrix(
                matrix_png_path,
                matrix_rows,
                fields=fields,
                datasets=datasets,
                encoding=encoding,
                landmark_tag=landmark_tag,
            )
        else:
            print("no later-step c-index gains; skip field gain matrix figure")
    else:
        print("no matching greedy PNG/CSV files; skip collage and combined CSV")

    if stale_missing.exists():
        stale_missing.unlink()

    print(f"  datasets requested: {len(names)}")
    print(f"  kept: {len(records)}")
    print(f"  missing: {len(missing)}")
    if records:
        print(f"  wrote {csv_path}")
        print(f"  wrote {png_path}")
        print(f"  wrote {matrix_csv_path}")
        if fields:
            print(f"  wrote {matrix_png_path}")
    else:
        print(f"  skip {png_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
